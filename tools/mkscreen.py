#!/usr/bin/env python3
"""Vytáhne statické pozadí herní obrazovky z originálního screenshotu do data/screen.json.

M1 nemá ROM grafiku (M0 čeká na ROM set), takže statická obrazovka pro milník M1 se
bere přímo z pixelů originálního snímku `sources/media/cheekyms_screenshot.png`
(192x256, MAME, 1. kolo). Z něj se vyřízne pás y=16..247, tj. všechno mezi horní a
dolní HUD lištou: rám, doupě, otvory, podlaha a sklep.

Co se ze snímku odstraní:
  - myši čekající v doupěti a myš v otvoru c. 2 (otvor se nahradi kopií otvoru c. 1),
  - muž a myši na hrací ploše (celý obdélník x=8..183, y=64..191 se vyčerní),
  - prokousaná díra v podlaze (zelená se doplní na celou šířku),
  - dva zbylé kusy sýra (uloží se zvlášť jako sprite, kreslí se z konstant).

Výstup je RLE po řádcích nad 8 barvami originální palety (PROM dává 1 bit na složku).
Až M5 přinese dlaždice z ROM, tenhle soubor i `app/screenRender.js` skončí.

Použití: python3 tools/mkscreen.py
"""
import json, os, struct, sys, zlib

SRC = 'sources/media/cheekyms_screenshot.png'
DST = 'data/screen.json'

# --- geometrie, viz sources/docs/screen_layout.md ---------------------------
BAND_Y0, BAND_Y1 = 16, 247          # vyříznutý pás (včetně)
PLAY = (8, 64, 184, 192)            # hrací plocha x0,y0,x1,y1 (x1,y1 nevčetně)
FLOOR_X0, FLOOR_X1 = 8, 184
FLOOR_ROWS = [192, 194, 195]        # zelené řádky podlahy
HOLE_SRC_X, HOLE_DST_X, HOLE_W = 25, 65, 14   # otvor 1 -> otvor 2 (bez myši)
HOLE_Y0, HOLE_Y1 = 52, 64
CHEESE = (128, 218, 8, 8)           # x, y, w, h prvního zbylého kusu sýra
# 8 kusů sýra = 4 sloupce x 2 řady. Odměřen je jen sloupec x=128 (na snímku už je
# 6 kusů odneseno), rozestup 32 px je odhad — ověřit z videa/ROM (ZADANI kap. 7).
CHEESE_COLS = [32, 64, 96, 128]
CHEESE_ROWS = [218, 226]

PALETTE = ['#000000', '#0000FF', '#00FFFF', '#00FF00', '#FFFF00', '#FF0000', '#FFFFFF', '#FF00FF']
RGB = [tuple(int(c[i:i+2], 16) for i in (1, 3, 5)) for c in PALETTE]


def read_png(path):
    """Minimalistický dekodér PNG (8 bitů, truecolor, bez prokládání)."""
    data = open(path, 'rb').read()
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        sys.exit(path + ': není PNG')
    pos, idat, ihdr = 8, b'', None
    while pos < len(data):
        length, tag = struct.unpack('>I4s', data[pos:pos+8])
        chunk = data[pos+8:pos+8+length]
        if tag == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', chunk)
        elif tag == b'IDAT':
            idat += chunk
        pos += 12 + length
    w, h, depth, color, _, _, interlace = ihdr
    if (depth, color, interlace) != (8, 2, 0):
        sys.exit('podporován je jen 8bitový truecolor bez prokládání')
    raw = zlib.decompress(idat)
    bpp, stride = 3, w * 3
    out, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y*(stride+1)]
        line = bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        for i in range(stride):
            a = line[i-bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i-bpp] if i >= bpp else 0
            if f == 1:   line[i] = (line[i] + a) & 0xff
            elif f == 2: line[i] = (line[i] + b) & 0xff
            elif f == 3: line[i] = (line[i] + (a + b) // 2) & 0xff
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p-a), abs(p-b), abs(p-c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xff
            elif f != 0:
                sys.exit('neznámý filtr ' + str(f))
        out.append([tuple(line[x*3:x*3+3]) for x in range(w)])
        prev = line
    return w, h, out


def index_of(px):
    if px not in RGB:
        sys.exit('barva mimo paletu: ' + str(px))
    return RGB.index(px)


def rle(row):
    out, run, prev = [], 0, row[0]
    for value in row:
        if value == prev:
            run += 1
        else:
            out.append([run, prev])
            prev, run = value, 1
    out.append([run, prev])
    return out


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(root)
    w, h, px = read_png(SRC)
    img = [[index_of(px[y][x]) for x in range(w)] for y in range(h)]

    # sýr si odložíme dřív, než ho z pozadí smažeme
    cx, cy, cw, ch = CHEESE
    cheese = [[img[cy+y][cx+x] for x in range(cw)] for y in range(ch)]

    # otvor c. 2 přepíšeme kopií otvoru c. 1 (v originálu z něj leze myš)
    for y in range(HOLE_Y0, HOLE_Y1):
        for x in range(HOLE_W):
            img[y][HOLE_DST_X+x] = img[y][HOLE_SRC_X+x]

    # doupě: pryč s čekajícími myšmi (červená/bílá) i s osamělým žlutým pixelem
    for y in range(23, 40):
        for x in range(w):
            if img[y][x] in (4, 5, 6):
                img[y][x] = 0

    # hrací plocha a sklep: pryč s mužem, myšmi a sýrem
    for y in range(PLAY[1], PLAY[3]):
        for x in range(PLAY[0], PLAY[2]):
            img[y][x] = 0
    for y in range(196, 246):
        for x in range(PLAY[0], PLAY[2]):
            img[y][x] = 0

    # podlaha: zacelit prokousanou díru
    for y in FLOOR_ROWS:
        for x in range(FLOOR_X0, FLOOR_X1):
            img[y][x] = 3

    band = [rle(img[y]) for y in range(BAND_Y0, BAND_Y1+1)]
    result = {
        'note': 'M1: statické pozadí vyříznuté z sources/media/cheekyms_screenshot.png '
                'nástrojem tools/mkscreen.py; v M5 nahradí dlaždice z ROM',
        'width': w,
        'y': BAND_Y0,
        'height': BAND_Y1-BAND_Y0+1,
        'palette': PALETTE,
        'rows': band,
        'cheese': {'width': cw, 'height': ch, 'rows': [rle(r) for r in cheese],
                   'cols': CHEESE_COLS, 'y': CHEESE_ROWS,
                   'count': len(CHEESE_COLS)*len(CHEESE_ROWS)},
        'floor': {'rows': FLOOR_ROWS, 'x': FLOOR_X0,
                  'width': FLOOR_X1-FLOOR_X0, 'tile': 8},
        # Hrací plocha mezi bočními rámy. Originál pruh s mužem ořezává stejně
        # (`in_man_area` v screen_update, sources/mame/cheekyms.cpp), takže se
        # kladivo u zdi utne místo aby přeteklo do rámu.
        'play': {'x': PLAY[0], 'y': PLAY[1], 'width': PLAY[2]-PLAY[0], 'height': PLAY[3]-PLAY[1]}
    }
    os.makedirs('data', exist_ok=True)
    with open(DST, 'w') as f:
        json.dump(result, f, separators=(',', ':'))
    print('%s: %d řádků, %d B' % (DST, len(band), os.path.getsize(DST)))


if __name__ == '__main__':
    main()
