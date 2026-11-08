# Protokol mezi `mainModel.js` a `gameWorker.js`

Worker drží celý herní stav a tiká na **58,64 Hz** – snímkové frekvenci originálu
(5,408 MHz / 352 / 262, herní logika visí na VBLANK IRQ, viz `sources/docs/hw_notes.md`).
Model do něj jen posílá vstupy a kreslí to, co dostane zpátky.

Stav M3: worker vede muže, kladivo i myši, a řídí se tabulkami rychlostí, počtů a časů
přepsanými z disassembly ROM. Pesti, druhý hráč a kredity přijdou v M4.

## Model → worker

| zpráva | pole | význam |
|---|---|---|
| `init` | `initData: {headless, dip, hiScore, attract, geometry}` | start nové hry. `dip` = ekvivalenty DIP přepínačů z `gameApp.dip` (`lives`, `bonus`, `gameOverSound`, `cabinet`). `headless: true` tiká jen na vyžádání zprávou `tick` (pro testy). `geometry` viz níže. |
| `controls` | `left`, `right`, `hammer` (boolean) | úplný stav ovládání; posílá se při každé změně. Stisk kladiva se **latchuje při doručení zprávy**, ne až v tiku – jinak by se ztratil dotek kratší než jeden 17ms snímek (originál latchuje tlačítko na přerušení stejně). |
| `pause` | – | zastaví tikání. |
| `continue` | – | pokračuje. |
| `tick` | – | jeden krok v režimu `headless`. |
| `reset` | – | zahodí stav (volá se při opuštění herní obrazovky). |

## Worker → model

| zpráva | pole | význam |
|---|---|---|
| `frame` | `frame`, `score`, `hiScore`, `lives`, `screen`, `cheese`, `floor`, `man`, `mice`, `miceLeft`, `swing`, `hit`, `state`, `sounds`, `soundBoard` | jeden odtikaný snímek. `cheese` = pole 8 příznaků (leží ještě ve sklepě?), `floor` = stav 22 dlaždic podlahy (0 celá, 1 nakousnutá, 2 díra), `screen` = číslo kola, `man` = `{x, dir, walk, frame}` (`frame` je jméno pózy z `data/sprites.json`), `mice` = pole `{x, y, frame}` (y je **spodní** hrana, jako u hardwaru; `frame` je jméno spritu z `data/mice.json`, u zabité myši `dead_neg` nebo `dead_pos` podle směru – jedna dlaždice 16×16 o 2 px výš, 30 snímků bez pohybu a bez animace), `miceLeft` = kolik myší kolo ještě vypustí, `swing`/`hit` jako v M2. |
| `roundComplete` | `screen` | kolo dohráno, začíná další. |
| `gameOver` | `score`, `hiScore` | došli muži; model přepne na `GameOverModel`. |

`soundBoard` nese devět spouštěcích linek originální zvukové desky
(`cheese`, `music`, `mouse`, `hammer`, `pest`, `mouseDies`, `pestDies`, `coinExtra`, `mute`,
port 40h a 80h – viz `sources/docs/hw_notes.md`). V M1 je vždy nulový; v M5 ho
`audioManager.playFrame()` promění na syntézu ve Web Audio.

## `geometry` v `init`

Rozměry vlastní model (`ScreenLayout` + `data/sprites.json`), worker si je nedrží podruhé:

| klíč | obsah |
|---|---|
| `man` | `{width, minX, maxX, y, speed, walkTicks}` – kam až smí muž dojít (meze počítají s přesahem kladiva, aby se u zdi neuťalo), rychlost v px na tik a počet tiků na fázi chůze |
| `floor` | `{x, y, tile, tiles}` – podlaha a její dlaždice po 8 px |
| `hammer` | `{head}` – obdélník kladiva ve spritu muže, který slouží jako zásahová plocha |
| `mice` | `{speed, holesX, holeY, cheeseX, cheeseY, width, deathTicks, deathOffsetY, speedByRound, speedLater, concurrentByRound, concurrentLater, turnPeriods, chewByRound, chewMinGap, spawnDelay}` – otvory, sýr a posmrtná animace naměřené z běhu originálu; tabulky podle kola jsou přepsané z ROM (`sources/docs/disasm_notes.md`) |

Švih **řídí tlačítko**: po stisku 2 snímky první póza, pak druhá dokud je tlačítko dole,
a muž se přitom nehýbe (naměřeno z originálu). **Jeden švih zasáhne nejvýš jednu myš**
(`hitUsed`) – odpovídá pravidlu z manuálu, že na podlaze jdou trefovat jen jedna po druhé.
Nový stisk během švihu se ignoruje.

## Co přibude v dalších milnících

- **M4**: pesti, druhý hráč, kredity, bonusový muž, okna (0–3 dle kola).
- **M5**: obraz se přesune do workeru celý (dlaždice + sprity z ROM) a `frame`
  ponese videopaměť místo dnešních `cheese`/`holes`.
