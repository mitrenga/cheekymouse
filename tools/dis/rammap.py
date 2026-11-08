#!/usr/bin/env python3
"""rammap.py — kdo zapisuje a čte kterou buňku RAM.

Spustí ROM v trasovacím emulátoru a u každého přístupu do RAM (3000h-33FFh) si
poznamená adresu instrukce, která ho způsobila. Výsledkem je mapa proměnných:
pro každou buňku seznam míst v programu, která s ní pracují. To je nejrychlejší
cesta, jak v disassembly najít, kde se drží stav myší, čítač zabitých, RNG a tak.

Použití: tools/dis/rammap.py [--frames 6000] [--input skript.txt] [--out /tmp/ram.txt]
         [--only 0x3045] [--hints sources/asm/ram-hints.txt]
"""
import argparse, os, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from z80emu import Z80                                                    # noqa: E402
from trace_cheekyms_mod import CheekyMsBus, load_region_program, KEYS      # noqa: E402


class WatchBus(CheekyMsBus):
    """Bus, který si u každého přístupu do RAM pamatuje PC volající instrukce."""

    def __init__(self, rom):
        super().__init__(rom)
        self.cpu = None
        self.writers = defaultdict(lambda: defaultdict(int))
        self.readers = defaultdict(lambda: defaultdict(int))
        self.values = defaultdict(set)

    def read(self, a):
        if 0x3000 <= a < 0x3400 and self.cpu is not None:
            self.readers[a][self.pc_of_access()] += 1
        return super().read(a)

    def write(self, a, v):
        if 0x3000 <= a < 0x3400 and self.cpu is not None:
            self.writers[a][self.pc_of_access()] += 1
            if len(self.values[a]) < 40:
                self.values[a].add(v)
        super().write(a, v)

    def pc_of_access(self):
        """PC ukazuje za rozpracovanou instrukci; pro mapu proměnných to stačí."""
        return self.cpu.pc


def read_script(path):
    script = {}
    if not path:
        return {100: 'c', 102: '', 140: '1', 142: ''}
    for ln in open(path):
        ln = ln.split(';', 1)[0].strip()
        if not ln:
            continue
        parts = ln.split(None, 1)
        script[int(parts[0])] = parts[1].strip() if len(parts) > 1 else ''
    return script


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rom', default=os.path.join(ROOT, 'sources/rom/cheekyms'))
    ap.add_argument('--frames', type=int, default=6000)
    ap.add_argument('--input')
    ap.add_argument('--out', default='/tmp/ram.txt')
    ap.add_argument('--ipf', type=int, default=4300)
    ap.add_argument('--only', help='vypsat jen tuhle adresu (hex)')
    args = ap.parse_args()

    bus = WatchBus(load_region_program(args.rom))
    cpu = Z80(bus)
    bus.cpu = cpu
    cpu.pc = 0
    script = read_script(args.input)
    coin = -1
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

    only = int(args.only, 0) if args.only else None
    with open(args.out, 'w') as f:
        f.write('; mapa RAM z běhu %d snímků; W = kdo zapisuje, R = kdo čte (PC za instrukcí)\n' % args.frames)
        for a in sorted(set(bus.writers) | set(bus.readers)):
            if only is not None and a != only:
                continue
            w = bus.writers.get(a, {})
            r = bus.readers.get(a, {})
            vals = sorted(bus.values.get(a, ()))
            f.write('%04X  zápisů %-7d čtení %-7d hodnot %s\n'
                    % (a, sum(w.values()), sum(r.values()),
                       ('%d' % len(vals)) if len(vals) >= 40 else ','.join('%02X' % v for v in vals)))
            f.write('        W: %s\n' % ' '.join('%04X(%d)' % (p, n) for p, n in sorted(w.items(), key=lambda x: -x[1])[:12]))
            f.write('        R: %s\n' % ' '.join('%04X(%d)' % (p, n) for p, n in sorted(r.items(), key=lambda x: -x[1])[:12]))
    print('zapsáno -> %s (%d buněk)' % (args.out, len(set(bus.writers) | set(bus.readers))))


if __name__ == '__main__':
    main()
