#!/usr/bin/env python3
"""Vyrobí sprity muže do data/sprites.json — **z běhu originálního programu**.

Muž není sprit: je v tilemapě jako blok dlaždic v pruhu tx 8..11, který hardware posouvá
o 0..7 px (port 80h d3-d5). Které dlaždice tvoří kterou pózu, rozhoduje program, takže
se to nedá vyčíst ze samotné grafiky — tenhle nástroj proto pustí ROM v trasovacím
emulátoru (`tools/dis/trace-cheekyms.py`), vhodí minci, spustí hru, chodí a mlátí
kladivem, a čte pózy přímo z videopaměti.

Výstup je osm skutečných póz: chůze a úder, každé zvlášť doprava i doleva (originál
postavu **nezrcadlí**, má pro každý směr vlastní dlaždice). Součástí je i časování
odečtené ze stejného běhu — rychlost chůze, délka fáze a průběh švihu.

Použití: tools/mksprites.py [--frames 1200]
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, 'dis'))
sys.path.insert(0, HERE)
from z80emu import Z80                                                    # noqa: E402
from trace_cheekyms_mod import CheekyMsBus, Renderer, load_region_program  # noqa: E402
from manframes import man_tiles, normalize, KEYS                          # noqa: E402
from mkscreen import rle, PALETTE, RGB                                    # noqa: E402

ROM = 'sources/rom/cheekyms'
DST = 'data/sprites.json'
MAN_Y = 160          # nohy končí na 191, podlaha začíná na 192
MAN_MIN_X = 16       # naměřeno z běhu: levý okraj bloku muže
MAN_MAX_X = 152


def render_pose(renderer, pose, palette_bit=0):
    """Pózu vykreslí do indexů osmibarevné palety; kotva je nejlevější sloupec."""
    cols = max(ty for _, ty, _ in pose)+1
    img = [[0]*(cols*8) for _ in range(32)]
    for tx, ty, code in pose:
        color = renderer.tile_color(tx, 14+ty, palette_bit)
        i = 11-tx
        for row in range(8):
            for col in range(8):
                pen = renderer.tiles[code][row][col]
                if pen:
                    img[i*8+(7-col)][ty*8+row] = RGB.index(renderer.pens[4*color+pen])
    return img


def run(frames, ipf=4300):
    """Odehraje partii a vrátí (pózy v pořadí objevení, časová osa)."""
    bus = CheekyMsBus(load_region_program(os.path.join(ROOT, ROM)))
    cpu = Z80(bus)
    cpu.pc = 0
    script = {100: 'c', 102: '', 140: '1', 142: ''}
    for f in range(300, frames, 200):
        script[f] = 'r'
        script[f+50] = ''
        script[f+60] = 'h'
        script[f+66] = ''
        script[f+80] = 'l'
        script[f+130] = ''
        script[f+140] = 'h'
        script[f+146] = ''
    poses, timeline, coin, keys = [], [], -1, ''
    for frame in range(frames):
        bus.frame = frame
        if frame in script:
            keys = script[frame]
            bus.inputs = 0xFF & ~sum(KEYS.get(c, 0) for c in keys)
            if 'c' in keys:
                coin = frame
        if frame == coin:
            cpu.nmi_pending = True
        elif bus.irq_mask:
            cpu.int_pending = True
        for _ in range(ipf):
            cpu.step()
        tiles = man_tiles(bus.vram)
        pose = normalize(tiles)
        if not pose:
            continue
        if pose not in poses:
            poses.append(pose)
        ty0 = min(ty for _, ty in tiles)
        timeline.append({'frame': frame, 'pose': poses.index(pose),
                         'x': 8*ty0-32-bus.scroll, 'scroll': bus.scroll, 'keys': keys,
                         'pos': bus.ram[0x45]*256+bus.ram[0x46]})
    return poses, timeline


def classify(poses, timeline):
    """Přiřadí pózám jména podle toho, co se v tu chvíli dělo."""
    facing, names = {}, {}
    last_dir = 'R'
    for row in timeline:
        if 'r' in row['keys']:
            last_dir = 'R'
        elif 'l' in row['keys']:
            last_dir = 'L'
        kind = 'hit' if 'h' in row['keys'] else 'walk'
        facing.setdefault(row['pose'], (kind, last_dir))
    order = {}
    for index in range(len(poses)):
        kind, direction = facing.get(index, ('walk', 'R'))
        key = kind+direction
        order.setdefault(key, [])
        order[key].append(index)
    for key, indexes in order.items():
        for n, index in enumerate(indexes):
            names[index] = '%s%s%d' % (key[:-1], key[-1], n)
    return names


def measure_speed(timeline):
    """Přesná rychlost z 16bitové pozice muže v RAM (3045 celá část, 3046 zlomek)."""
    from collections import Counter
    steps = Counter()
    for a, b in zip(timeline, timeline[1:]):
        if b['frame'] == a['frame']+1 and 'r' in a['keys'] and 'h' not in a['keys']:
            steps[(b['pos']-a['pos']) % 65536] += 1
    return steps.most_common(1)[0][0] if steps else 0


def measure_hit0(timeline, names):
    """Kolik snímků drží první póza úderu, než se přepne na druhou."""
    runs, prev, count = [], None, 0
    for row in timeline:
        name = names.get(row['pose'], '')
        if name == prev:
            count += 1
            continue
        if prev and prev.startswith('hit') and prev.endswith('0'):
            runs.append(count)
        prev, count = name, 1
    if prev and prev.startswith('hit') and prev.endswith('0'):
        runs.append(count)
    return max(set(runs), key=runs.count) if runs else 0


def measure_offsets(timeline, names):
    """Posun kotvy bloku pro každou pózu vůči chůzi téhož směru.

    Póza s kladivem může být širší a program blok zapisuje o dlaždici jinam
    (u úderu doleva o 8 px vlevo), takže se to musí kreslit s posunem.
    """
    diffs = {}
    for a, b in zip(timeline, timeline[1:]):
        if b['frame'] != a['frame']+1:
            continue
        na, nb = names.get(a['pose'], ''), names.get(b['pose'], '')
        if not na or not nb or na == nb:
            continue
        if na.startswith('walk') and nb.startswith('hit') and na[4] == nb[3]:
            diffs.setdefault(nb, []).append(b['x']-a['x'])
        elif na.startswith('hit') and nb.startswith('walk') and na[3] == nb[4]:
            diffs.setdefault(na, []).append(a['x']-b['x'])
    offsets = {name: 0 for name in names.values()}
    for name, values in diffs.items():
        offsets[name] = max(set(values), key=values.count)
    # obě fáze úderu mají stejnou kotvu
    for name in list(offsets):
        if name.startswith('hit') and name.endswith('1'):
            offsets[name] = offsets.get(name[:-1]+'0', 0)
    return offsets


def walk_ticks(timeline, names):
    """Kolik snímků drží jedna fáze chůze."""
    runs, last, count = [], None, 0
    for row in timeline:
        name = names.get(row['pose'], '')
        if not name.startswith('walk') or 'r' not in row['keys'] and 'l' not in row['keys']:
            last, count = None, 0
            continue
        if name == last:
            count += 1
        else:
            if last is not None and count:
                runs.append(count)
            last, count = name, 1
    runs = [r for r in runs if r > 0]
    return max(set(runs), key=runs.count) if runs else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--frames', type=int, default=1200)
    args = ap.parse_args()
    os.chdir(ROOT)
    if not os.path.isdir(ROM):
        sys.exit('%s: ROM set chybí, viz sources/rom/README.md' % ROM)

    poses, timeline = run(args.frames)
    names = classify(poses, timeline)
    renderer = Renderer(ROM)
    offsets = measure_offsets(timeline, names)
    frames = {}
    tiles_out = {}
    for index, pose in enumerate(poses):
        name = names.get(index)
        if not name:
            continue
        img = render_pose(renderer, pose)
        frames[name] = {'width': len(img[0]), 'height': 32,
                        'offsetX': offsets.get(name, 0),
                        'rows': [rle(r) for r in img]}
        tiles_out[name] = [list(t) for t in pose]

    speed = measure_speed(timeline)
    result = {
        'note': 'Pózy muže přečtené z videopaměti běžícího originálu (tools/mksprites.py '
                'nad tools/dis/trace-cheekyms.py). Originál postavu nezrcadlí – pro každý '
                'směr má vlastní dlaždice. Nic tu není dokreslené.',
        'palette': PALETTE,
        'man': {'y': MAN_Y, 'minX': MAN_MIN_X, 'maxX': MAN_MAX_X,
                'frames': frames, 'tiles': tiles_out},
        'timing': {
            # rychlost je 16bitová: pozice muže v RAM 3045/3046 roste o tuhle
            # hodnotu za snímek, tedy speed/256 pixelu
            'speed': speed,
            'walkTicks': walk_ticks(timeline, names),
            # švih není pevná animace: po stisku drží první póza `hit0Ticks`
            # snímků, pak druhá dokud je tlačítko dole. Muž se přitom nehýbe.
            'hit0Ticks': measure_hit0(timeline, names),
            'freezeWhileSwinging': True
        }
    }
    os.makedirs('data', exist_ok=True)
    with open(DST, 'w') as f:
        json.dump(result, f, separators=(',', ':'))
    print('%s: %d póz, %d B' % (DST, len(frames), os.path.getsize(DST)))
    for name in sorted(frames):
        print('    %-7s %2dx%d, posun kotvy %+d'
              % (name, frames[name]['width'], frames[name]['height'], frames[name]['offsetX']))
    t = result['timing']
    print('  rychlost %d/256 = %.4f px na snímek, fáze chůze %d snímky'
          % (t['speed'], t['speed']/256, t['walkTicks']))
    print('  švih: první póza %d snímky, druhá dokud je tlačítko dole; muž stojí'
          % t['hit0Ticks'])


if __name__ == '__main__':
    main()
