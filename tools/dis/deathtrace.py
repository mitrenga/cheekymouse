#!/usr/bin/env python3
"""deathtrace.py — co originál udělá s myší, když ji trefí kladivo.

Spustí ROM, postaví muže pod otvor a mlátí kladivem. Každý snímek zapíše syrové
bajty všech osmi spritů, takže se dá odečíst, jaká je posmrtná animace: které
kódy spritu se použijí, jak dlouho a jestli se přitom myš hýbe.

Použití: tools/dis/deathtrace.py [--frames 3000] [--out /tmp/death.tsv]
"""
import argparse, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from z80emu import Z80                                                    # noqa: E402
from trace_cheekyms_mod import CheekyMsBus, load_region_program           # noqa: E402
from manframes import KEYS                                               # noqa: E402


def sprites_of(bus):
    out = []
    for offs in range(0, 0x20, 4):
        b0, b1, b2, b3 = bus.spr[offs], bus.spr[offs+1], bus.spr[offs+2], bus.spr[offs+3]
        if not (b3 & 0x08):
            continue
        out.append({'slot': offs//4, 'code': (~b0 & 0x0f) << 1,
                    'pair': 'single' if (b0 & 0x80) else ('side' if (b0 & 0x02) else 'stack'),
                    'color': (~b3 & 0x07), 'x': b1-32, 'y': 255-(256-b2),
                    'raw': '%02x%02x%02x%02x' % (b0, b1, b2, b3)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rom', default=os.path.join(ROOT, 'sources/rom/cheekyms'))
    ap.add_argument('--frames', type=int, default=3000)
    ap.add_argument('--out', default='/tmp/death.tsv')
    ap.add_argument('--ipf', type=int, default=4300)
    args = ap.parse_args()

    bus = CheekyMsBus(load_region_program(args.rom))
    cpu = Z80(bus)
    cpu.pc = 0
    script = {100: 'c', 102: '', 140: '1', 142: ''}
    coin = -1
    with open(args.out, 'w') as f:
        f.write('snimek\tslot\tkod\tpar\tbarva\tx\ty\tsyrove\n')
        for frame in range(args.frames):
            bus.frame = frame
            keys = ''
            if frame in script:
                keys = script[frame]
                if 'c' in keys:
                    coin = frame
            elif frame > 200:
                # mlátit kladivem obden a přitom se pomalu posouvat po ploše
                keys = 'h' if (frame % 4) < 2 else ''
                if (frame // 200) % 2 == 0:
                    keys += 'r'
                else:
                    keys += 'l'
            if frame > 140 or frame in script:
                bus.inputs = 0xFF & ~sum(KEYS.get(c, 0) for c in keys)
            if frame == coin:
                cpu.nmi_pending = True
            elif bus.irq_mask:
                cpu.int_pending = True
            for _ in range(args.ipf):
                cpu.step()
            for s in sprites_of(bus):
                f.write('%d\t%d\t%d\t%s\t%d\t%d\t%d\t%s\n'
                        % (frame, s['slot'], s['code'], s['pair'], s['color'],
                           s['x'], s['y'], s['raw']))
    print('zapsáno -> %s' % args.out)


if __name__ == '__main__':
    main()
