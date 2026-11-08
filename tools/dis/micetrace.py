#!/usr/bin/env python3
"""micetrace.py — sleduje v běžícím originálu myši: kde se rodí, kudy jdou, co dělají.

Spustí ROM v trasovacím emulátoru, odehraje partii a každý snímek zapíše stav všech
osmi spritů (poloha, kód, barva) i podlahu z videopaměti. Z toho se dá odečíst
všechno, co M3 potřebuje: otvory, ze kterých myši lezou, jejich rychlost, kde
prokousávají podlahu, jak dlouho co trvá a kolik jich je najednou.

Formát spritu (sources/mame/cheekyms.cpp, `draw_sprites`):
    b0: bit7 = jeden 16x16 (jinak dvojice), bit1 = dvojice vedle sebe, bity 0-3 kód
    b1: y,  b2: x jako 256-x,  b3: bit3 = zapnuto, bity 0-2 barva (negováno)
Na obrazovku: dx = y-32, dy = 255-(256-b2)

Použití: tools/dis/micetrace.py [--frames 2400] [--out soubor.tsv]
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from z80emu import Z80                                                   # noqa: E402
from trace_cheekyms_mod import CheekyMsBus, load_region_program           # noqa: E402
from manframes import KEYS                                               # noqa: E402


def sprites_of(bus):
    """Zapnuté sprity jako seznam (slot, kód, barva, x, y na obrazovce)."""
    out = []
    for offs in range(0, 0x20, 4):
        b0, b1, b2, b3 = bus.spr[offs], bus.spr[offs+1], bus.spr[offs+2], bus.spr[offs+3]
        if not (b3 & 0x08):
            continue
        sx = 256-b2
        code = (~b0 & 0x0f) << 1
        pair = None if (b0 & 0x80) else ('side' if (b0 & 0x02) else 'stack')
        out.append({'slot': offs//4, 'code': code, 'pair': pair,
                    'color': (~b3 & 0x07), 'x': b1-32, 'y': 255-sx, 'raw': (b0, b1, b2, b3)})
    return out


def floor_holes(bus):
    """Indexy dlaždic podlahy, které nejsou celé (podlaha je neotočeně sloupec tx=7)."""
    # podlaha: obrazovka y 192..195 -> sx 60..63 -> tx 7; dlaždice po ty
    row = [bus.vram[(ty << 5) | 7] for ty in range(32)]
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rom', default=os.path.join(ROOT, 'sources/rom/cheekyms'))
    ap.add_argument('--frames', type=int, default=2400)
    ap.add_argument('--out', default='/tmp/mice.tsv')
    ap.add_argument('--ipf', type=int, default=4300)
    ap.add_argument('--script', default='')
    args = ap.parse_args()

    bus = CheekyMsBus(load_region_program(args.rom))
    cpu = Z80(bus)
    cpu.pc = 0
    script = {100: 'c', 102: '', 140: '1', 142: ''}
    if args.script:
        for part in args.script.split(','):
            f, _, k = part.partition('=')
            script[int(f)] = k
    coin = -1
    with open(args.out, 'w') as f:
        f.write('snimek\tslot\tkod\tbarva\tx\ty\tpar\n')
        for frame in range(args.frames):
            bus.frame = frame
            if frame in script:
                k = script[frame]
                bus.inputs = 0xFF & ~sum(KEYS.get(c, 0) for c in k)
                if 'c' in k:
                    coin = frame
            if frame == coin:
                cpu.nmi_pending = True
            elif bus.irq_mask:
                cpu.int_pending = True
            for _ in range(args.ipf):
                cpu.step()
            for s in sprites_of(bus):
                f.write('%d\t%d\t%d\t%d\t%d\t%d\t%s\n'
                        % (frame, s['slot'], s['code'], s['color'], s['x'], s['y'], s['pair']))
    print('zapsáno -> %s' % args.out)


if __name__ == '__main__':
    main()
