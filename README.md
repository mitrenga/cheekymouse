![](/images/app-icon-256x256.png)

CHEEKY MOUSE
=====================
Faithful browser remake of the 1980 Universal arcade game Cheeky Mouse — work in progress.

## About
Released by Universal in 1980 for upright and cocktail cabinets: a vertically oriented screen
with a mouse lair at the top, a floor across the middle and eight pieces of cheese in the cellar
below. The mice come out one by one, chew through the floor and carry the cheese away; you swing
a hammer at them and keep clear of the pests. The original game logic is being rewritten in
JavaScript from the manual, the MAME hardware driver and the program ROM (not emulated) — see
`ZADANI.md` for the design and `MILNIKY.md` for the plan. Sibling projects: Stinger, Space
Invaders, Pleiads (arcade platform), Manic Miner, Jet Set Willy (same svision kernel).

Status: **M3** — a whole round plays: the man walks and swings, the mice come out, chew the floor
and steal the cheese. On top of the M1 skeleton (menu, hall of fame, settings, about, the static
playfield) and a worker that ticks at the machine's own 58.64 Hz. Nothing here is guesswork: the
man's eight poses, the mouse sprites, the floor and the cheese are all read out of the running
original by the tracing emulator in `tools/dis/`, and since the program itself has been
disassembled (`sources/asm/cheekyms.asm`, findings in `sources/docs/disasm_notes.md`) the speeds,
counts and timings per screen come straight from the ROM's own tables. Next: M4 (pests, two
players, the DIP options). The app icons, poster and cover in `images/` are placeholders copied
from Stinger and will be replaced in M6.

## Play now
not deployed yet

## Requirements
- PHP 8.1+
- nginx
- MySQL / MariaDB
- Node.js + terser, for building the bundle (`npm i -g terser`)
- es-check, for the ES2018 compatibility gate in `svtool verify` (`npm i -g es-check`)
- Python 3 for the tools in `tools/`, including the tracing emulator and disassembler in
  `tools/dis/` (no third-party packages)

## Install
(`~/` below refers to the project root, not your home directory.)
- clone this repository
- clone library repository https://github.com/mitrenga/svision
- check symlink ~/app/svision
- configure nginx (example: ~/config/nginx.conf)
- create path ~/js with permissions 0777
- create database (script: ~/config/createDB.sql)
- create configuration file ~/config/config.php (example: ~/config/config.php.sample)
- build the production bundle: ~/app/svision/tools/svtool build bundle

## Build & tooling
The `svtool` CLI (`~/app/svision/tools/svtool`) builds and checks the deploy. Run it from the
project root:
- `svtool build bundle` — minified production bundle `js/bundle.<version>.min.js` (requires terser)
- `svtool build debug-bundle` — the same concatenation left unminified, `js/bundle.<version>.js`, for debugging on a device whose console cannot be opened
- `svtool verify` — check the `js/` deploy is complete, matches the current sources, and stays within ES2018
- `svtool info` — show the app version, deploy state and the most recent database records
- `svtool clean` — remove everything generated from `js/`

Project tools (`tools/`, Python 3):
- `mkscreen.py` — cuts the static playfield out of the original MAME screenshot into
  `data/screen.json`. Rerun it after changing the geometry.
- `mksprites.py` — runs the original in the tracing emulator and reads the man's eight real
  poses and their timing out of its video RAM into `data/sprites.json`. Nothing is drawn by hand.
- `mkmice.py` — the mice, the three floor states and the cheese tiles, rendered from the ROM
  with the codes read out of the running game, into `data/mice.json`.
- `dis/trace-cheekyms.py` — the tracing emulator itself: Z80 plus the hardware from the MAME
  driver. Boots the ROM, takes scripted input and dumps real frames.
- `dis/micetrace.py` — logs every sprite and the floor of a played session, which is where the
  mouse constants come from.
- `matchscreen.py` — takes the reference screenshot apart against the ROM and reports which tile
  and which sprite sits where. The reconstruction is pixel-exact, which is what verifies the ROM
  decode, the palettes and the rotation mapping; the findings are in `sources/docs/gfx_map.md`.
- `dumpgfx.py` — dumps the tiles, sprites and PROM palettes out of the ROM set into PNG sheets
  and `palette.json`. Needs the ROM, which is not in this repository.

## Sources
Reference material (MAME driver and sound netlist, the scanned manual and its transcript, the
schematic, both flyers, the original screenshot, the measured screen geometry and the derived
hardware notes) lives in `sources/` — see `sources/README.md`. The ROM set (`sources/rom/`) is
outside git; the rest of `sources/` is tracked.

## License
See the [LICENSE](LICENSE) file.
