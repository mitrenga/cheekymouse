#!/usr/bin/env python3
"""Rozluští originální screenshot proti ROM: která dlaždice a který sprit kde leží.

Tohle je zdroj pravdy pro grafiku. Vezme `sources/media/cheekyms_screenshot.png`, ROM set
a pravidla z MAME driveru a najde kód dlaždice pro každou pozici v tilemapě a pak sprity,
které vysvětlí zbytek. Když se z nalezeného obrázek vykreslí zpátky a je pixelově shodný
s předlohou, je jisté, že dekódování ROM, palety i mapování otočení sedí – a víme přesně,
ze kterých dlaždic je doupě, podlaha, sýr i **muž** a které sprity jsou myši.

Mapování (přesně podle `screen_update` v sources/mame/cheekyms.cpp):
  - ROT270: obrazovka (dx, dy) <-> neotočeně (sx, sy):  sx = 255-dy,  sy = dx+32
  - dlaždice je (sx//8, sy//8), pixel v ní [sy%8][sx%8]
  - barva dlaždice se nebere z paměti, počítá se z pozice (`get_tile_info`)
  - **pruh s mužem**: `in_man_area` = neotočeně x 64..95 a y 41..215, tedy na obrazovce
    y 160..191 a x 9..183 (boční rám do něj nepatří). Uvnitř se tilemapa čte posunutá
    o `scrolly` (port 80h d3-d5, 0..7 px) – po otočení je to jemný vodorovný posun muže.
  - sprity se kreslí **pod** tilemapu, průhledné pero je 0

Použití: python3 tools/matchscreen.py [--rom sources/rom/cheekyms] [--out assets/raw]
"""
import argparse, json, os, struct, sys, zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dumpgfx import make_source, load_region, prom_colors, decode_chars, decode_sprites, \
                    CHAR_FILES, SPRITE_FILES, PROM_FILES
from mkscreen import read_png

SHOT = 'sources/media/cheekyms_screenshot.png'
BLACK = (0, 0, 0)


def in_man_area(sx, sy):
    """`in_man_area` z MAME driveru, v neotočených souřadnicích."""
    return 64 <= sx < 96 and 40 < sy < 216


def tile_color(tx, ty, palette_bit):
    """`get_tile_info`: barva dlaždice plyne z její pozice, ne z paměti."""
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


def screen_map(scroll):
    """Pro každý pixel obrazovky vrátí dlaždici a pixel v ní.

    Vrací slovník (tx, ty) -> seznam (dx, dy, row, col), tedy přesně to, co hardware
    na daném místě z tilemapy přečte – včetně posunutého pruhu s mužem.
    """
    cells = {}
    for dy in range(256):
        sx = 255-dy
        for dx in range(192):
            sy = dx+32
            if in_man_area(sx, sy):
                sy += scroll
                if sy >= 27*8:
                    continue            # driver tenhle pixel nekreslí
            tx, ty = sx >> 3, sy >> 3
            cells.setdefault((tx, ty), []).append((dx, dy, sy & 7, sx & 7))
    return cells


def match_tiles(shot, tiles, pens, cells, palette_bit):
    """Pro každou pozici vrátí (kandidáti, barva); kandidát musí sedět na všech
    svých neprůhledných pixelech. Průhledné se neporovnávají – prosvítá pod nimi sprit."""
    grid = {}
    for (tx, ty), pixels in cells.items():
        color = tile_color(tx, ty, palette_bit)
        found = []
        for code in range(256):
            tile = tiles[code]
            ok = True
            for dx, dy, row, col in pixels:
                pen = tile[row][col]
                if pen and shot[dy][dx] != pens[4*color+pen]:
                    ok = False
                    break
            if ok:
                found.append(code)
        grid[(tx, ty)] = (found, color)
    return grid


def solid_pixels(tile):
    return sum(1 for row in tile for pen in row if pen)


def render_tiles(tiles, pens, cells, chosen):
    """Vykreslí vrstvu tilemapy; None = průhledno (prosvítá sprit nebo černá)."""
    layer = [[None]*192 for _ in range(256)]
    for (tx, ty), pixels in cells.items():
        code, color = chosen[(tx, ty)]
        for dx, dy, row, col in pixels:
            pen = tiles[code][row][col]
            if pen:
                layer[dy][dx] = pens[4*color+pen]
    return layer


def find_sprites(shot, sprites, pens, layer):
    """Hladově vysvětlí zbylé pixely sprity 16x16 (kód, barva, neotočená pozice)."""
    rest = set()
    for dy in range(256):
        for dx in range(192):
            if layer[dy][dx] is None and shot[dy][dx] != BLACK:
                rest.add((255-dy, dx+32))
    def place(code, color, sx0, sy0):
        covered = set()
        for r in range(16):
            for c in range(16):
                pen = sprites[code][r][c]
                if not pen:
                    continue
                sx, sy = sx0+c, sy0+r
                dx, dy = sy-32, 255-sx
                if not (0 <= dx < 192 and 0 <= dy < 256):
                    return None
                if layer[dy][dx] is not None:
                    continue            # dlaždice sprit překrývá
                if shot[dy][dx] != pens[0x80+4*color+pen]:
                    return None
                covered.add((sx, sy))
        return covered
    found, work = [], set(rest)
    while work:
        target = min(work)
        best = None
        for code in range(64):
            for r in range(16):
                for c in range(16):
                    if not sprites[code][r][c]:
                        continue
                    sx0, sy0 = target[0]-c, target[1]-r
                    for color in range(8):
                        covered = place(code, color, sx0, sy0)
                        if covered:
                            gain = len(covered & work)
                            if gain and (best is None or gain > best[0]):
                                best = (gain, code, color, sx0, sy0, covered)
        if best is None:
            return found, work, len(rest)
        found.append({'code': best[1], 'color': best[2], 'x': best[3], 'y': best[4],
                      'screenX': best[4]-32, 'screenY': 255-best[3]-15, 'pixels': best[0]})
        work -= best[5]
    return found, work, len(rest)


def write_png(path, rows_rgb):
    h, w = len(rows_rgb), len(rows_rgb[0])
    raw = bytearray()
    for row in rows_rgb:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rom', default='sources/rom/cheekyms')
    ap.add_argument('--out', default='assets/raw')
    args = ap.parse_args()
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    src = make_source(args.rom)
    tiles = decode_chars(load_region(src, CHAR_FILES, 0x1000))
    sprites = decode_sprites(load_region(src, SPRITE_FILES, 0x1000))
    pens = prom_colors(load_region(src, PROM_FILES, 0x60))
    w, h, shot = read_png(SHOT)
    if (w, h) != (192, 256):
        sys.exit('screenshot má být 192x256')

    # Posun pruhu s mužem: bere se ten, který v pruhu vysvětlí nejvíc pixelů.
    # Počítají se jen dlaždice ležící celé v pruhu, aby výsledek neředily
    # okolní prázdné bloky.
    def band_pixels(scroll, palette_bit):
        cells = screen_map(scroll)
        total = 0
        for (tx, ty), pixels in cells.items():
            if not (8 <= tx < 12):
                continue
            if not all(in_man_area(255-dy, dx+32) for dx, dy, _, _ in pixels):
                continue
            color = tile_color(tx, ty, palette_bit)
            best = 0
            for code in range(256):
                ok = True
                for dx, dy, row, col in pixels:
                    pen = tiles[code][row][col]
                    if pen and shot[dy][dx] != pens[4*color+pen]:
                        ok = False
                        break
                if ok:
                    best = max(best, solid_pixels(tiles[code]))
            total += best
        return total

    scores = [(band_pixels(s, 0), s) for s in range(8)]
    best_score, scroll = max(scores)
    print('jemny posun pruhu s muzem (port 80h d3-d5): %d px' % scroll)
    print('  vysvetlene pixely podle posunu: %s'
          % ', '.join('%d->%d' % (s, px) for px, s in sorted(scores, key=lambda t: t[1])))

    cells = screen_map(scroll)
    for palette_bit in (0, 1):
        grid = match_tiles(shot, tiles, pens, cells, palette_bit)
        unresolved = [k for k, v in grid.items() if not v[0]]
        print('paleta %d: %d/%d dlazdic ma kandidata, %d bez shody'
              % (palette_bit, len(grid)-len(unresolved), len(grid), len(unresolved)))
        if not unresolved:
            break

    chosen = {k: (max(v[0], key=lambda c: (solid_pixels(tiles[c]), -c)), v[1])
              for k, v in grid.items()}
    layer = render_tiles(tiles, pens, cells, chosen)
    diff = sum(1 for dy in range(256) for dx in range(192)
               if layer[dy][dx] is not None and layer[dy][dx] != shot[dy][dx])
    found, left, rest_total = find_sprites(shot, sprites, pens, layer)
    print()
    print('tilemapa: %d pixelu se lisi od predlohy, %d pixelu zbylo na sprity'
          % (diff, rest_total))
    print('sprity (kod, barva, pozice na obrazovce, vysvetlene pixely):')
    for spr in found:
        print('  kod %2d barva %d -> x %3d..%3d y %3d..%3d  (%d px)'
              % (spr['code'], spr['color'], spr['screenX'], spr['screenX']+15,
                 spr['screenY'], spr['screenY']+15, spr['pixels']))
    print('  nevysvetleno: %d pixelu' % len(left))

    os.makedirs(args.out, exist_ok=True)
    write_png(os.path.join(args.out, 'match_tilemap.png'),
              [[layer[y][x] or BLACK for x in range(192)] for y in range(256)])
    write_png(os.path.join(args.out, 'match_rest.png'),
              [[shot[y][x] if layer[y][x] is None else BLACK for x in range(192)] for y in range(256)])
    report = {'paletteBit': palette_bit, 'scroll': scroll,
              'tiles': {'%d,%d' % k: {'code': v[0], 'color': v[1],
                                      'candidates': len(grid[k][0])} for k, v in chosen.items()},
              'sprites': found, 'tilemapDiff': diff, 'spritePixels': rest_total,
              'unexplained': len(left)}
    with open(os.path.join(args.out, 'screen_match.json'), 'w') as f:
        json.dump(report, f, separators=(',', ':'))
    print()
    print('report -> %s/screen_match.json, obrazky match_tilemap.png a match_rest.png' % args.out)


if __name__ == '__main__':
    main()
