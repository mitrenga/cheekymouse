#!/usr/bin/env python3
"""Vytažení grafiky z ROM setu `cheekyms` do PNG sprite sheetů.

ROM v repozitáři NENÍ (copyright) – viz sources/rom/README.md.
Použití:
    python3 tools/dumpgfx.py --roms cesta/k/cheekyms  [--out assets/raw] [--scale 4]

Očekává v adresáři soubory cm01.c1 cm02.c2 cm07.n5 cm08.n6 cm.m8 cm.m9 cm.p3
(nebo přímo cheekyms.zip zadaný jako --roms).

Výstup:
    chars_palNN.png    – 256 dlaždic 8x8 (mřížka 16x16) pro každou z 32 barev sady A i B
    chars_all.png      – všech 256 dlaždic v barvě 1 (rychlý přehled)
    sprites_all.png    – 64 spritů 16x16 (mřížka 8x8), barvy 0-7
    palette.json       – obě znakové PROM a spritová PROM rozbalené na RGB

Formát (dle sources/mame/cheekyms.cpp):
    chars   : gfx_8x8x2_planar, region 0x1000 = 2x 0x800; bitplane 0 = cm02.c2, plane 1 = cm01.c1
    sprites : 16x16, 2bpp, planes { RGN_FRAC(1,2), 0 }, xoffs STEP16(0,1), yoffs STEP16(0,16), 32*8 bitů
    barvy   : PROM 32 B; bity 0-2 = RGB pro sudý pen, bity 4-6 = RGB pro lichý pen (0xff * bit)
"""
import argparse, json, os, struct, sys, zipfile

CHAR_FILES   = [("cm02.c2", 0x000), ("cm01.c1", 0x800)]   # region "chars"   (0x1000)
SPRITE_FILES = [("cm07.n5", 0x000), ("cm08.n6", 0x800)]   # region "sprites" (0x1000)
PROM_FILES   = [("cm.m9", 0x00), ("cm.m8", 0x20), ("cm.p3", 0x40)]  # region "proms" (0x60)


def load_region(src, files, size):
    buf = bytearray(size)
    for name, off in files:
        data = src(name)
        buf[off:off + len(data)] = data
    return bytes(buf)


def make_source(path):
    if os.path.isdir(path):
        def get(name):
            with open(os.path.join(path, name), "rb") as f:
                return f.read()
    elif zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        lower = {n.lower(): n for n in z.namelist()}
        def get(name):
            return z.read(lower[name.lower()])
    else:
        sys.exit(f"{path}: není adresář ani zip")
    return get


def prom_colors(proms):
    """MAME cheekyms_state::palette – 6 skupin po 32 pen, 1 bit na složku."""
    pens = []
    for i in range(6):
        for j in range(0x20):
            byte = proms[0x20 * (i // 2) + j]
            shift = 4 * (i & 1)
            r = 0xff * ((byte >> (shift + 0)) & 1)
            g = 0xff * ((byte >> (shift + 1)) & 1)
            b = 0xff * ((byte >> (shift + 2)) & 1)
            pens.append((r, g, b))
    return pens  # 192 pen; chars 0x00-0x7f, sprites 0x80-0xbf


def decode_chars(rom):
    """256 dlaždic 8x8, 2 bitplány (plane0 = 0x000, plane1 = 0x800)."""
    tiles = []
    for t in range(256):
        px = []
        for y in range(8):
            b0 = rom[0x000 + t * 8 + y]
            b1 = rom[0x800 + t * 8 + y]
            row = []
            for x in range(8):
                bit = 7 - x
                row.append(((b1 >> bit) & 1) << 1 | ((b0 >> bit) & 1))
            px.append(row)
        tiles.append(px)
    return tiles


def decode_sprites(rom):
    """64 spritů 16x16, 2bpp; plane1 = +0x800, řádek = 2 bajty (STEP16(0,16))."""
    sprites = []
    for s in range(64):
        base = s * 32
        px = []
        for y in range(16):
            hi0, lo0 = rom[base + y * 2], rom[base + y * 2 + 1]
            hi1, lo1 = rom[0x800 + base + y * 2], rom[0x800 + base + y * 2 + 1]
            w0 = (hi0 << 8) | lo0
            w1 = (hi1 << 8) | lo1
            row = []
            for x in range(16):
                bit = 15 - x
                row.append(((w1 >> bit) & 1) << 1 | ((w0 >> bit) & 1))
            px.append(row)
        sprites.append(px)
    return sprites


def write_png(path, rgb_rows, scale=1):
    """Minimalistický PNG zapisovač (bez závislostí)."""
    import zlib
    h = len(rgb_rows)
    w = len(rgb_rows[0])
    raw = bytearray()
    for row in rgb_rows:
        for _ in range(scale):
            raw.append(0)
            for (r, g, b) in row:
                raw += bytes((r, g, b)) * scale
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff)
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w * scale, h * scale, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def sheet(cells, cell_w, cell_h, cols, pens, color_base, color, transparent=(255, 0, 255)):
    rows_n = (len(cells) + cols - 1) // cols
    out = [[transparent] * (cols * cell_w) for _ in range(rows_n * cell_h)]
    for i, cell in enumerate(cells):
        cx, cy = (i % cols) * cell_w, (i // cols) * cell_h
        for y in range(cell_h):
            for x in range(cell_w):
                pen = cell[y][x]
                if pen == 0:
                    continue  # pen 0 je průhledný
                out[cy + y][cx + x] = pens[color_base + color * 4 + pen]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--roms", required=True, help="adresář nebo cheekyms.zip")
    ap.add_argument("--out", default="assets/raw")
    ap.add_argument("--scale", type=int, default=4)
    args = ap.parse_args()

    src = make_source(args.roms)
    chars   = load_region(src, CHAR_FILES,   0x1000)
    sprites = load_region(src, SPRITE_FILES, 0x1000)
    proms   = load_region(src, PROM_FILES,   0x60)

    pens = prom_colors(proms)
    os.makedirs(args.out, exist_ok=True)

    tiles = decode_chars(chars)
    spr   = decode_sprites(sprites)

    write_png(os.path.join(args.out, "chars_all.png"),
              sheet(tiles, 8, 8, 16, pens, 0x00, 1), args.scale)
    write_png(os.path.join(args.out, "sprites_all.png"),
              sheet(spr, 16, 16, 8, pens, 0x80, 0), args.scale)

    # každá barevná sada zvlášť: chars mají 32 barev (0x00-0x1f sada A, 0x10-0x1f = paleta B)
    for c in range(32):
        write_png(os.path.join(args.out, f"chars_pal{c:02d}.png"),
                  sheet(tiles, 8, 8, 16, pens, 0x00, c), args.scale)
    for c in range(8):
        write_png(os.path.join(args.out, f"sprites_pal{c}.png"),
                  sheet(spr, 16, 16, 8, pens, 0x80, c), args.scale)

    with open(os.path.join(args.out, "palette.json"), "w") as f:
        json.dump({"pens": pens,
                   "chars_base": 0, "sprites_base": 0x80,
                   "note": "6 skupin po 32 pen; chars sada A = PROM cm.m9, sada B = cm.m8 (bit 6 portu 0x80)"},
                  f, indent=1)

    print(f"hotovo → {args.out}")


if __name__ == "__main__":
    main()
