#!/usr/bin/env python3
"""Vyrobí data myší a měnících se dlaždic do data/mice.json — všechno z ROM.

Sprity myší i kódy dlaždic podlahy a sýra jsou odečtené z běžícího originálu
(`tools/dis/micetrace.py`), obrázky se pak vykreslí přímo z ROM.

Myš je sprit složený ze dvou dlaždic 16x16 (`draw_sprites` v MAME): buď nad sebou
(svislý pohyb, na obrazovce 16x32), nebo vedle sebe (vodorovný, 32x16). Kód spritu
určuje směr i fázi animace a **kódy 0..14 znamenají myš se sýrem v tlamě**, 16..30
myš bez sýra:

    směr    bez sýra   se sýrem
    dolů      24, 16      8, 0
    nahoru    26, 18     10, 2
    doleva    28, 20     12, 4
    doprava   30, 22     14, 6

Podlaha má tři stavy po dvojicích dlaždic (celá / nakousnutá / díra) a sýr je jedna
dlaždice ve dvou řadách s různou barvou.

Použití: python3 tools/mkmice.py
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from dumpgfx import make_source, load_region, prom_colors, decode_chars, decode_sprites, \
                    CHAR_FILES, SPRITE_FILES, PROM_FILES                      # noqa: E402
from mkscreen import rle, PALETTE, RGB                                        # noqa: E402

ROM = 'sources/rom/cheekyms'
DST = 'data/mice.json'
MOUSE_COLOR = 6

# kódy spritů podle směru; první je fáze 0, druhá fáze 1
MOUSE_CODES = {
    'down':  {'plain': [24, 16], 'cheese': [8, 0],  'shape': 'vertical'},
    'up':    {'plain': [26, 18], 'cheese': [10, 2], 'shape': 'vertical'},
    'left':  {'plain': [28, 20], 'cheese': [12, 4], 'shape': 'horizontal'},
    'right': {'plain': [30, 22], 'cheese': [14, 6], 'shape': 'horizontal'},
}

# Zabitá myš: jediná dlaždice 16x16 (b0 bit7). Rutina 1D96h v ROM nastaví bit 3
# v (IX+2), takže `S_1B89` zapíše b0 = 89h nebo 8Ah podle bitu 0 (znaménka směru)
# -> kód 12 nebo 10, a `draw_sprites` udělá code++ -> **sprit 13 nebo 11**.
# Bit 0 je 1 pro dolů a doleva, 0 pro nahoru a doprava.
# Tamtéž: (IX+4) -= 2 (leží o 2 px výš), (IX+1) = 1Eh, tedy 30 snímků. Sedí to
# na měření v `tools/dis/deathtrace.py` (to zachytilo jen variantu 13).
DEATH_SPRITES = {'neg': 13, 'pos': 11}   # neg = bit 0 nastaven (dolů, doleva)
DEATH_TICKS = 30
DEATH_OFFSET_Y = 2

# ---- pravidla z disassembly (sources/asm/cheekyms.asm, sources/docs/disasm_notes.md)
# rychlost myši podle kola: tabulka 1C28h, 16bit (celé px, zlomek/256); kolo >= 6 pevně 0300h
SPEED_BY_ROUND = [0x0200, 0x0238, 0x0260, 0x0288, 0x02B0, 0x02D8]
SPEED_LATER = 0x0300
# kolik myší smí být venku najednou: tabulka 1156h; od kola 8 je to 8 (= i strop spritů)
CONCURRENT_BY_ROUND = [3, 4, 5, 5, 6, 6, 7, 7]
CONCURRENT_LATER = 8
# S_1CCD: po náhodné době z tabulky 1D0Ah si myš vylosuje nový směr (2 bity z RAM 3014h)
TURN_PERIODS = [0x15, 0x0F, 0x2B, 0x1E]
# doba kousání podle kola: tabulka 1574h; když v podlaze díra už je, zdvojnásobí se.
# Fáze: celá doba, pak polovina, pak ještě polovina (stavy 157Bh / 159Eh / 15C4h).
CHEW_BY_ROUND = [0x1E, 0x1C, 0x1A, 0x18, 0x16, 0x14, 0x12]
# 14BEh: myš se nezakousne blíž než 27 px (souřadnice středu) k existující díře
CHEW_MIN_GAP = 0x1B
# 0FEDh: mezi otevřením otvoru a vylezením myši je 15 snímků
SPAWN_DELAY = 0x0F

# naměřeno z běhu hry
HOLES_X = [24, 64, 112, 152]     # levý okraj spritu myši, když vyleze z doupěte
HOLE_Y = 62                      # spodní hrana spritu v otvoru
MOUSE_SPEED = 2                  # px za snímek, svisle i vodorovně

# podlaha: sloupec tilemapy tx=7, barva podle pozice = 7>>1 = 3
FLOOR_TX = 7
# Díra je vždy dvojice dlaždic. V ROM jsou dvě varianty (podle toho, jak myš
# stojí vůči dlaždici); remake používá první a druhou má připravenou.
FLOOR_STAGES = {'whole': [118, 118], 'chewing': [158, 166], 'hole': [173, 181]}
FLOOR_STAGES_ALT = {'chewing': [160, 168], 'hole': [175, 183]}
# sýr: dlaždice 114 ve sloupcích tx=3 (dolní řada) a tx=4 (horní řada)
CHEESE_CODE = 114
CHEESE_TX = [4, 3]               # horní řada, dolní řada
CHEESE_TY = [14, 16, 18, 20]


def tile_color(tx, ty, palette_bit=0):
    palette = 0x10 if palette_bit else 0x00
    if tx >= 0x1e:
        return 0x15 if ty < 0x0c else (0x16 if ty < 0x14 else 0x14)
    if ty == 0x04 or ty == 0x1b:
        return palette | 0x0c
    return palette | (tx >> 1)


def tile_image(tiles, pens, code, color):
    """Dlaždice 8x8 v orientaci obrazovky: screen[y][x] = tile[x][7-y]."""
    img = [[0]*8 for _ in range(8)]
    for y in range(8):
        for x in range(8):
            pen = tiles[code][x][7-y]
            if pen:
                img[y][x] = RGB.index(pens[4*color+pen])
    return img


def sprite_image(sprites, pens, code, shape):
    """Dvojice spritů v orientaci obrazovky."""
    a, b = sprites[(code | 0x20) & 0x3f], sprites[(code | 0x21) & 0x3f]
    if shape == 'vertical':      # neotočeně x+16 -> na obrazovce o 16 výš
        img = [[0]*16 for _ in range(32)]
        for tile, off in ((a, 16), (b, 0)):
            for r in range(16):
                for c in range(16):
                    pen = tile[r][c]
                    if pen:
                        img[off+15-c][r] = RGB.index(pens[0x80+4*MOUSE_COLOR+pen])
    else:                        # neotočeně y+16 -> na obrazovce o 16 doprava
        img = [[0]*32 for _ in range(16)]
        for tile, off in ((a, 0), (b, 16)):
            for r in range(16):
                for c in range(16):
                    pen = tile[r][c]
                    if pen:
                        img[15-c][off+r] = RGB.index(pens[0x80+4*MOUSE_COLOR+pen])
    return img


def single_image(sprites, pens, index):
    """Jeden sprit 16x16 v orientaci obrazovky."""
    tile = sprites[index]
    img = [[0]*16 for _ in range(16)]
    for r in range(16):
        for c in range(16):
            pen = tile[r][c]
            if pen:
                img[15-c][r] = RGB.index(pens[0x80+4*MOUSE_COLOR+pen])
    return img


def pack(img):
    return {'width': len(img[0]), 'height': len(img), 'rows': [rle(r) for r in img]}


def main():
    os.chdir(ROOT)
    if not os.path.isdir(ROM):
        sys.exit('%s: ROM set chybí, viz sources/rom/README.md' % ROM)
    src = make_source(ROM)
    tiles = decode_chars(load_region(src, CHAR_FILES, 0x1000))
    sprites = decode_sprites(load_region(src, SPRITE_FILES, 0x1000))
    pens = prom_colors(load_region(src, PROM_FILES, 0x60))

    mouse = {}
    for direction, spec in MOUSE_CODES.items():
        for kind in ('plain', 'cheese'):
            for phase, code in enumerate(spec[kind]):
                name = '%s_%s%d' % (direction, kind, phase)
                mouse[name] = pack(sprite_image(sprites, pens, code, spec['shape']))
    for name, index in DEATH_SPRITES.items():
        mouse['dead_'+name] = pack(single_image(sprites, pens, index))

    floor = {}
    color = tile_color(FLOOR_TX, 10)
    for stage, codes in FLOOR_STAGES.items():
        floor[stage] = [pack(tile_image(tiles, pens, code, color)) for code in codes]
    floor_alt = {stage: [pack(tile_image(tiles, pens, code, color)) for code in codes]
                 for stage, codes in FLOOR_STAGES_ALT.items()}

    cheese = []
    for tx in CHEESE_TX:
        cheese.append({'y': 255-8*tx-7,
                       'tile': pack(tile_image(tiles, pens, CHEESE_CODE, tile_color(tx, 14)))})

    result = {
        'note': 'Myši, podlaha a sýr z ROM. Kódy spritů a dlaždic i rozměry odečtené '
                'z běhu originálu (tools/dis/micetrace.py); obrázky vykreslené z ROM. '
                'Nic tu není dokreslené.',
        'palette': PALETTE,
        'mouse': {'frames': mouse, 'speed': MOUSE_SPEED,
                  'holesX': HOLES_X, 'holeY': HOLE_Y,
                  'deathTicks': DEATH_TICKS, 'deathOffsetY': DEATH_OFFSET_Y,
                  'speedByRound': [v/256.0 for v in SPEED_BY_ROUND],
                  'speedLater': SPEED_LATER/256.0,
                  'concurrentByRound': CONCURRENT_BY_ROUND,
                  'concurrentLater': CONCURRENT_LATER,
                  'turnPeriods': TURN_PERIODS,
                  'chewByRound': CHEW_BY_ROUND,
                  'chewMinGap': CHEW_MIN_GAP,
                  'spawnDelay': SPAWN_DELAY},
        'floor': {'y': 192, 'x': 8, 'tile': 8, 'tiles': 22,
                  'stages': floor, 'stagesAlt': floor_alt},
        'cheese': {'x': [8*ty-32 for ty in CHEESE_TY], 'rows': cheese}
    }
    os.makedirs('data', exist_ok=True)
    with open(DST, 'w') as f:
        json.dump(result, f, separators=(',', ':'))
    print('%s: %d spritů myši, podlaha %d stavů, sýr %d řady, %d B'
          % (DST, len(mouse), len(floor), len(cheese), os.path.getsize(DST)))
    print('  mrtvá myš: sprity %s, %d snímků, o %d px výš'
          % (DEATH_SPRITES, DEATH_TICKS, DEATH_OFFSET_Y))
    print('  rychlost podle kola: %s, dál %.4f px/snímek'
          % (['%.4f' % (v/256.0) for v in SPEED_BY_ROUND], SPEED_LATER/256.0))
    print('  současně myší: %s, dál %d' % (CONCURRENT_BY_ROUND, CONCURRENT_LATER))
    print('  kousání podle kola: %s (dvojnásobek, když už díra je)' % CHEW_BY_ROUND)
    print('  otvory x %s, y %d, rychlost %d px/snímek'
          % (HOLES_X, HOLE_Y, MOUSE_SPEED))
    print('  sýr x %s, řady y %s' % (result['cheese']['x'], [r['y'] for r in cheese]))


if __name__ == '__main__':
    main()
