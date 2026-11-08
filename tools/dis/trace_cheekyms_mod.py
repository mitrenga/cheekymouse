#!/usr/bin/env python3
"""trace-cheekyms.py — trasovací emulátor Cheeky Mouse (M0: podklad pro disassemblaci).

Spustí originální program z ROM a vysype, co je opravdu ve videopaměti. Tím se dá zjistit
všechno, co ze samotné grafiky vyčíst nejde: které dlaždice tvoří které pózy muže, jak se
hýbou myši, kdy co program dělá.

Emuluje Z80 + hardware podle `sources/mame/cheekyms.cpp`:
    0000-1FFF  ROM (cm03..cm06)          IN  00  DIP
    3000-33FF  RAM                       IN  01  vstupy (aktivní v nule)
    3800-3BFF  videopaměť 32x32          OUT 20-3F  spriteram (8 spritů po 4 B)
                                         OUT 40  zvukové spouštěče
                                         OUT 80  mute/mince/IRQ enable/scroll/paleta/flip
IRQ na začátku snímku (VBLANK) když je povolené bitem d2 portu 80h; vhozená mince = NMI.
Snímková frekvence 58,64 Hz (5,408 MHz / 352 / 262).

Obraz se kreslí přesně jako `screen_update` v MAME – včetně posunu pruhu s mužem
(`in_man_area`) a spritů pod tilemapou. Renderer je společný s `tools/matchscreen.py`,
takže co ověřil pixelově přesný rozklad referenčního snímku, platí i tady.

Použití:
    tools/dis/trace-cheekyms.py --frames 900 [--input skript.txt] [--shot N=out.png ...]
                                [--man N=out.png ...] [--cov coverage.txt] [--vram N=out.bin]

Skript vstupů: řádky "snímek klávesy", platí od daného snímku dál.
    klávesy: c=mince, 1=start1, 2=start2, l=vlevo, r=vpravo, h=kladivo
"""
import argparse, json, os, struct, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from z80emu import Z80                                                    # noqa: E402
from dumpgfx import make_source, load_region, prom_colors, decode_chars, \
                    decode_sprites, CHAR_FILES, SPRITE_FILES, PROM_FILES  # noqa: E402

PROGRAM_FILES = [('cm03.c5', 0x0000), ('cm04.c6', 0x0800),
                 ('cm05.c7', 0x1000), ('cm06.c8', 0x1800)]

# DIP tovární nastavení (PORT_DIPSETTING defaults v MAME): 3 muži, 1 mince 1 kredit,
# upright, demo zvuky zapnuté, bonus 3000
DSW = 0x01 | 0x04 | 0x10 | 0x20 | 0x40

# vstupy jsou aktivní v nule
KEYS = {'1': 0x01, '2': 0x02, 'r': 0x20, 'l': 0x40, 'h': 0x80}

# hodin CPU na snímek: 2,5 MHz / 58,64 Hz; průměr ~10 T na instrukci
INSTR_PER_FRAME = 4300


class CheekyMsBus:
    def __init__(self, rom):
        self.rom = rom
        self.ram = bytearray(0x400)
        self.vram = bytearray(0x400)
        self.spr = bytearray(0x20)
        self.port80 = 0
        self.irq_mask = 0
        self.inputs = 0xFF
        self.frame = 0
        self.sound_log = []          # (snímek, port, hodnota)
        self.ram_writes = {}
        self.trace_ram = False

    # ---- paměť
    def fetch(self, a):
        return self.read(a)

    def read(self, a):
        if a < 0x2000:
            return self.rom[a]
        if 0x3000 <= a < 0x3400:
            return self.ram[a-0x3000]
        if 0x3800 <= a < 0x3C00:
            return self.vram[a-0x3800]
        return 0xFF

    def write(self, a, v):
        if 0x3000 <= a < 0x3400:
            self.ram[a-0x3000] = v
            if self.trace_ram:
                self.ram_writes[a] = self.ram_writes.get(a, 0)+1
            return
        if 0x3800 <= a < 0x3C00:
            self.vram[a-0x3800] = v
            return

    # ---- I/O
    def in_(self, port):
        port &= 0xFF
        if port == 0x00:
            return DSW
        if port == 0x01:
            return self.inputs
        return 0xFF

    def out(self, port, v):
        port &= 0xFF
        if 0x20 <= port < 0x40:
            self.spr[port-0x20] = v
            return
        if port == 0x40:
            self.sound_log.append((self.frame, 0x40, v))
            return
        if port == 0x80:
            self.port80 = v
            self.irq_mask = (v >> 2) & 1
            self.sound_log.append((self.frame, 0x80, v))
            return

    # ---- pohodlné pohledy na stav
    @property
    def scroll(self):
        return (self.port80 >> 3) & 0x07

    @property
    def palette_bit(self):
        return (self.port80 >> 6) & 1

    @property
    def flip(self):
        return (self.port80 >> 7) & 1


class Renderer:
    """`screen_update` z MAME: sprity pod tilemapou, pruh s mužem posunutý o scrolly."""

    def __init__(self, romdir):
        src = make_source(romdir)
        self.tiles = decode_chars(load_region(src, CHAR_FILES, 0x1000))
        self.sprites = decode_sprites(load_region(src, SPRITE_FILES, 0x1000))
        self.pens = prom_colors(load_region(src, PROM_FILES, 0x60))

    @staticmethod
    def in_man_area(sx, sy):
        return 64 <= sx < 96 and 40 < sy < 216

    @staticmethod
    def tile_color(tx, ty, palette_bit):
        palette = 0x10 if palette_bit else 0x00
        if tx >= 0x1e:
            if ty < 0x0c:
                return 0x15
            if ty < 0x14:
                return 0x16
            return 0x14
        if ty == 0x04 or ty == 0x1b:
            return palette | 0x0c
        return palette | (tx >> 1)

    def frame_rgb(self, bus):
        """Vrátí obraz 192x256 jako seznam řádků RGB trojic."""
        black = (0, 0, 0)
        img = [[black]*192 for _ in range(256)]
        # 1) sprity (kreslí se pod tilemapu)
        for offs in range(0, 0x20, 4):
            if (bus.spr[offs+3] & 0x08) == 0:
                continue
            x = 256 - bus.spr[offs+2]
            y = bus.spr[offs+1]
            code = (~bus.spr[offs+0] & 0x0f) << 1
            color = (~bus.spr[offs+3] & 0x07)
            if bus.spr[offs+0] & 0x80:
                if not bus.flip:
                    code += 1
                self.blit_sprite(img, code, color, x, y)
            elif bus.spr[offs+0] & 0x02:
                self.blit_sprite(img, code | 0x20, color, x, y)
                self.blit_sprite(img, code | 0x21, color, x+0x10, y)
            else:
                self.blit_sprite(img, code | 0x20, color, x, y)
                self.blit_sprite(img, code | 0x21, color, x, y+0x10)
        # 2) tilemapa přes ně
        scroll = bus.scroll
        pbit = bus.palette_bit
        for dy in range(256):
            sx = 255-dy
            for dx in range(192):
                sy = dx+32
                if self.in_man_area(sx, sy):
                    sy += scroll
                    if sy >= 27*8:
                        continue
                tx, ty = sx >> 3, sy >> 3
                pen = self.tiles[bus.vram[(ty << 5) | tx]][sy & 7][sx & 7]
                if pen:
                    img[dy][dx] = self.pens[4*self.tile_color(tx, ty, pbit)+pen]
        return img

    def blit_sprite(self, img, code, color, x, y):
        for r in range(16):
            for c in range(16):
                pen = self.sprites[code & 0x3f][r][c]
                if not pen:
                    continue
                sx, sy = x+c, y+r
                dx, dy = sy-32, 255-sx
                if 0 <= dx < 192 and 0 <= dy < 256:
                    img[dy][dx] = self.pens[0x80+4*color+pen]


def write_png(path, rows):
    h, w = len(rows), len(rows[0])
    raw = bytearray()
    for row in rows:
        raw.append(0)
        for r, g, b in row:
            raw += bytes((r, g, b))
    def chunk(tag, data):
        return struct.pack('>I', len(data))+tag+data+struct.pack('>I', zlib.crc32(tag+data) & 0xffffffff)
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
                + chunk(b'IEND', b''))


def load_input(path):
    if not path:
        return []
    events = []
    for line in open(path):
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        events.append((int(parts[0]), parts[1] if len(parts) > 1 else ''))
    return sorted(events)


def load_region_program(romdir):
    src = make_source(romdir)
    return load_region(src, PROGRAM_FILES, 0x2000)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--rom', default=os.path.join(ROOT, 'sources/rom/cheekyms'))
    ap.add_argument('--frames', type=int, default=900)
    ap.add_argument('--input')
    ap.add_argument('--shot', action='append', default=[], help='N=soubor.png')
    ap.add_argument('--vram', action='append', default=[], help='N=soubor.bin')
    ap.add_argument('--cov')
    ap.add_argument('--trace-ram', action='store_true')
    ap.add_argument('--ipf', type=int, default=INSTR_PER_FRAME)
    ap.add_argument('--quiet', action='store_true')
    args = ap.parse_args()

    src = make_source(args.rom)
    rom = load_region(src, PROGRAM_FILES, 0x2000)
    bus = CheekyMsBus(rom)
    bus.trace_ram = args.trace_ram
    cpu = Z80(bus)
    cpu.pc = 0
    events = load_input(args.input)
    shots = {int(s.split('=')[0]): s.split('=')[1] for s in args.shot}
    vrams = {int(s.split('=')[0]): s.split('=')[1] for s in args.vram}
    renderer = Renderer(args.rom) if shots else None
    cov = set() if args.cov else None

    ei = 0
    coin_frame = -1
    for frame in range(args.frames):
        bus.frame = frame
        while ei < len(events) and events[ei][0] <= frame:
            keys = events[ei][1]
            bus.inputs = 0xFF & ~sum(KEYS.get(k, 0) for k in keys)
            if 'c' in keys:
                coin_frame = frame
            ei += 1
        if frame == coin_frame:
            cpu.nmi_pending = True       # mince spouští 556 one-shot -> NMI
        elif bus.irq_mask:
            cpu.int_pending = True
        for _ in range(args.ipf):
            if cov is not None:
                cov.add(cpu.pc)
            cpu.step()
        if frame in shots:
            write_png(shots[frame], renderer.frame_rgb(bus))
            if not args.quiet:
                print('snímek %d -> %s' % (frame, shots[frame]))
        if frame in vrams:
            with open(vrams[frame], 'wb') as f:
                f.write(bus.vram)
                f.write(bus.spr)
                f.write(bytes([bus.port80]))

    if cov is not None:
        with open(args.cov, 'w') as f:
            for a in sorted(cov):
                if a < 0x2000:
                    f.write('%04X\n' % a)
        print('pokrytí: %d adres -> %s' % (sum(1 for a in cov if a < 0x2000), args.cov))
    if args.trace_ram:
        print('zápisy do RAM: %d různých adres' % len(bus.ram_writes))
    if not args.quiet:
        print('PC=%04X SP=%04X halted=%s IM=%d iff1=%d irq_mask=%d port80=%02X scroll=%d'
              % (cpu.pc, cpu.sp, cpu.halted, cpu.im, cpu.iff1, bus.irq_mask, bus.port80, bus.scroll))
        print('zápisů do videopaměti: %d nenulových bajtů'
              % sum(1 for b in bus.vram if b))
        print('zvukové zápisy: %d' % len(bus.sound_log))



