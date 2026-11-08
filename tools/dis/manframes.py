#!/usr/bin/env python3
"""manframes.py — vytáhne z běžící hry skutečné pózy muže a jejich kódy dlaždic.

Spustí emulátor z `trace-cheekyms.py`, vhodí minci, spustí hru a pak mačká klávesy.
Každý snímek přečte, jaké dlaždice jsou v pruhu muže (tx 8..11), pózy odduplikuje
a vysype je jako PNG přehled + JSON s kódy.

Použití: tools/dis/manframes.py [--frames 1200] [--out assets/raw]
"""
import argparse, json, os, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from z80emu import Z80                                                     # noqa: E402
from trace_cheekyms_mod import CheekyMsBus, Renderer, load_region_program   # noqa: E402

KEYS = {'1': 0x01, '2': 0x02, 'r': 0x20, 'l': 0x40, 'h': 0x80}


# Sloupce ty=4 a ty=27 jsou boční rám obrazovky, ne muž.
FRAME_TY = (4, 27)


def man_tiles(vram):
    out = {}
    for tx in range(8, 12):
        for ty in range(32):
            if ty in FRAME_TY:
                continue
            code = vram[(ty << 5) | tx]
            if code:
                out[(tx, ty)] = code
    return out


def normalize(tiles):
    """Póza nezávisle na poloze: kódy vůči nejlevějšímu sloupci ty."""
    if not tiles:
        return None
    ty0 = min(ty for _, ty in tiles)
    return tuple(sorted((tx, ty-ty0, code) for (tx, ty), code in tiles.items()))


def render_pose(renderer, pose, palette_bit=0):
    cols = max(ty for _, ty, _ in pose)+1
    img = [[(0, 0, 0)]*(cols*8) for _ in range(32)]
    for tx, ty, code in pose:
        color = renderer.tile_color(tx, 14+ty, palette_bit)
        i = 11-tx
        for row in range(8):
            for col in range(8):
                pen = renderer.tiles[code][row][col]
                if pen:
                    img[i*8+(7-col)][ty*8+row] = renderer.pens[4*color+pen]
    return img


def crop(img):
    """Ořízne pózu na její skutečný rozsah."""
    W = len(img[0])
    xs = [x for y in range(32) for x in range(W) if img[y][x] != (0, 0, 0)]
    if not xs:
        return img
    x0, x1 = min(xs), max(xs)
    return [row[x0:x1+1] for row in img]


def write_sheet(path, imgs, cols=8, scale=5, gap=3):
    cw = max(len(i[0]) for i in imgs)+gap
    rows = (len(imgs)+cols-1)//cols
    W, H = cols*cw, rows*(32+gap)
    buf = [[(25, 25, 25)]*W for _ in range(H)]
    for n, img in enumerate(imgs):
        gx, gy = (n % cols)*cw, (n//cols)*(32+gap)
        for y in range(32):
            for x in range(len(img[0])):
                buf[gy+y][gx+x] = img[y][x]
    raw = bytearray()
    for y in range(H):
        for _ in range(scale):
            raw.append(0)
            for p in buf[y]:
                raw += bytes(p)*scale
    def chunk(tag, data):
        return struct.pack('>I', len(data))+tag+data+struct.pack('>I', zlib.crc32(tag+data) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', W*scale, H*scale, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
                + chunk(b'IEND', b''))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rom', default=os.path.join(ROOT, 'sources/rom/cheekyms'))
    ap.add_argument('--frames', type=int, default=1200)
    ap.add_argument('--out', default=os.path.join(ROOT, 'assets/raw'))
    ap.add_argument('--ipf', type=int, default=4300)
    ap.add_argument('--timeline', help='soubor: pro každý snímek póza, pozice muže a scroll')
    args = ap.parse_args()

    bus = CheekyMsBus(load_region_program(args.rom))
    cpu = Z80(bus)
    cpu.pc = 0
    renderer = Renderer(args.rom)

    script = {100: 'c', 102: '', 140: '1', 142: ''}
    for f in range(300, args.frames, 200):
        script[f] = 'r'
        script[f+50] = ''
        script[f+60] = 'h'
        script[f+66] = ''
        script[f+80] = 'l'
        script[f+130] = ''
        script[f+140] = 'h'
        script[f+146] = ''

    poses, coin_frame, timeline = {}, -1, []
    for frame in range(args.frames):
        bus.frame = frame
        if frame in script:
            k = script[frame]
            bus.inputs = 0xFF & ~sum(KEYS.get(c, 0) for c in k)
            if 'c' in k:
                coin_frame = frame
        if frame == coin_frame:
            cpu.nmi_pending = True
        elif bus.irq_mask:
            cpu.int_pending = True
        for _ in range(args.ipf):
            cpu.step()
        tiles = man_tiles(bus.vram)
        pose = normalize(tiles)
        if pose and pose not in poses:
            poses[pose] = frame
        if pose:
            ty0 = min(ty for _, ty in tiles)
            # levý okraj bloku muže na obrazovce: dx = 8*ty - 32 - scroll
            timeline.append((frame, pose, 8*ty0-32-bus.scroll, bus.scroll))

    order = sorted(poses.items(), key=lambda kv: kv[1])
    print('nalezeno %d ruznych poz muze' % len(order))
    os.makedirs(args.out, exist_ok=True)
    if order:
        write_sheet(os.path.join(args.out, 'man_poses.png'),
                    [crop(render_pose(renderer, p)) for p, _ in order], cols=10, scale=6)
        print('prehled -> %s/man_poses.png' % args.out)
    with open(os.path.join(args.out, 'man_poses.json'), 'w') as f:
        json.dump([{'frame': fr, 'tiles': [list(t) for t in pose]} for pose, fr in order],
                  f, separators=(',', ':'))
    index = {p: i for i, (p, _) in enumerate(order)}
    for i, (pose, fr) in enumerate(order):
        print('  poza %d (poprve snimek %4d): kody %s'
              % (i, fr, ','.join(str(c) for _, _, c in pose)))
    if args.timeline:
        with open(args.timeline, 'w') as f:
            f.write('snimek\tpoza\tx\tscroll\n')
            for fr, pose, x, sc in timeline:
                f.write('%d\t%d\t%d\t%d\n' % (fr, index[pose], x, sc))
        print('casova osa -> %s' % args.timeline)


if __name__ == '__main__':
    main()
