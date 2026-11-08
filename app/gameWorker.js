// begin code

/**
 * Cheeky Mouse game worker — M2. The mice, the pests and the real scoring are
 * still to come (M3/M4); see WORKER-PROTOCOL.md.
 *
 * The tick is the frame rate of the original machine, not 60 Hz: the video is
 * 5.408 MHz / 352 / 262 = 58.64 Hz and the game logic runs on the VBLANK IRQ
 * (sources/docs/hw_notes.md), so every speed in the game is tied to this rate.
 *
 * The man behaves exactly as the original, all of it measured off the running
 * ROM (tools/mksprites.py over tools/dis/trace-cheekyms.py):
 *   - he moves 464/256 = 1.8125 px per frame, so his position is 16-bit fixed
 *     point exactly like the original keeps it in RAM 3045/3046,
 *   - a walking frame lasts 3 ticks,
 *   - the hammer is NOT a fixed animation: pressing it shows the first pose for
 *     2 ticks and then the second one for as long as the button is held,
 *   - and he does not move at all while the button is down.
 * One swing still only connects once (hitUsed) - the manual says the mice can
 * only be hit one after another.
 *
 * M3 adds the mice. What is measured off the original (tools/dis/micetrace.py,
 * sources/docs/gfx_map.md) and therefore exact: they come out of four holes at
 * x 24/64/112/152, move 2 px per frame both ways, their animation flips every 5
 * frames, the floor is chewed through in a pair of tiles that goes whole ->
 * chewed -> open, the eight pieces of cheese sit at x 80/96/112/128 in rows
 * y 216 and 224, and a mouse that took one carries it home in its mouth. A mouse
 * killed by the hammer turns into one flattened 16x16 sprite two pixels above
 * where she stood and stays there for exactly 30 frames without moving or
 * animating, whether or not she was carrying cheese (tools/dis/deathtrace.py).
 * Which of the two corpse sprites is used depends on the direction she was
 * heading (1D96h in the ROM).
 *
 * Since M3.5 the program itself has been disassembled (sources/asm/cheekyms.asm,
 * findings in sources/docs/disasm_notes.md), so these are now ROM facts rather
 * than guesses: the mouse speed per screen (table 1C28h), how many may be out at
 * once (table 1156h: 3,4,5,5,6,6,7,7 then 8), how long chewing takes (table
 * 1574h, doubled once a hole already exists, in three parts), the 15-frame delay
 * between the hole opening and the mouse coming out, the 27-pixel minimum
 * spacing between chewing sites, and the random periods after which a mouse
 * changes direction (table 1D0Ah: 21, 15, 43, 30 frames). The original has NO
 * hammer evasion at all - the wandering is a plain random walk plus mice pushing
 * each other around (S_1AEF), which is why it looks evasive.
 *
 * What is still our own reading rather than the program's (manual chap. III):
 * which piece of cheese a mouse goes for, and the fact that the remake steers a
 * mouse towards a chosen tile while the original just wanders until it finds a
 * spot far enough from every hole.
 */
var TICK_MS = 1000*352*262/5408000;   // 58.64 Hz, the original VBLANK rate
var CHEESE_COUNT = 8;
var MICE_PER_SCREEN = 32;             // manual chap. III rule 1
var ANIM_TICKS = 5;                   // (IX+1) counts down from 4 in S_1CA9
var CELLAR_Y = 214;                   // measured: the level the mice run at below the floor
var FLOOR_STAND_Y = 190;              // bottom edge of a mouse standing on the floor
var CHEESE_REACH = 14;                // how far below a piece a mouse must get to take it

// manual p. 3: score per screen, and double for a mouse already carrying cheese
var SCORE_TABLE = [20, 20, 30, 30, 40, 40, 50, 50, 60, 60, 70, 70, 80, 80, 90, 90];

var state = null;
var timer = 0;
var lastTime = false;
var accumulator = 0;

// geometry handed over by the model on init (it owns ScreenLayout / sprites)
var SUBPIXEL = 256;
var geometry = {
  man: {width: 24, minX: 16, maxX: 152, y: 160, speed: 464, walkTicks: 3, hit0Ticks: 2},
  floor: {x: 8, y: 192, tile: 8, tiles: 22},
  hammer: {head: [24, 16, 8, 8]},
  mice: {speed: 2, holesX: [24, 64, 112, 152], holeY: 62,
         cheeseX: [80, 96, 112, 128], cheeseY: [216, 224], width: 16,
         deathTicks: 30, deathOffsetY: 2,
         speedByRound: [2, 2.21875, 2.375, 2.53125, 2.6875, 2.84375],
         speedLater: 3, concurrentByRound: [3, 4, 5, 5, 6, 6, 7, 7],
         concurrentLater: 8, turnPeriods: [21, 15, 43, 30],
         chewByRound: [30, 28, 26, 24, 22, 20, 18], chewMinGap: 27, spawnDelay: 15}
};

function reset() {
  clearTimeout(timer);
  timer = 0;
  lastTime = false;
  accumulator = 0;
  state = {
    running: false,
    paused: false,
    headless: false,
    frame: 0,
    score: 0,
    hiScore: 0,
    lives: 3,
    screen: 1,
    cheese: [],                 // true = kus sýra ještě leží ve sklepě
    floor: [],                  // 0 celá dlaždice, 1 nakousnutá, 2 díra
    mice: [],
    miceLeft: MICE_PER_SCREEN,  // kolik jich v kole ještě zbývá vypustit
    miceKilled: 0,
    spawnTimer: 0,
    man: {
      x16: Math.floor((geometry.man.minX+geometry.man.maxX)/2)*SUBPIXEL,
      dir: 1,
      walk: 0,
      walkTimer: 0
    },
    swingFrame: -1,
    hitUsed: false,
    target: null,
    controls: {left: false, right: false, hammer: false},
    hammerLatch: false,
    hammerPressed: false,
    sounds: [],
    gameOverPosted: false
  };
  restock();
} // reset

/** doplní sýr na 8 kusů a zacelí podlahu (manuál, pravidlo 5) */
function restock() {
  state.cheese = [];
  for (var i = 0; i < CHEESE_COUNT; i++) {
    state.cheese.push(true);
  }
  state.floor = [];
  for (var t = 0; t < geometry.floor.tiles; t++) {
    state.floor.push(0);
  }
  state.mice = [];
  state.spawnTimer = 0;
} // restock

/** index kola do tabulek z ROM; kolo 1 je v ROM index 0 */
function roundIndex() {
  return state.screen-1;
} // roundIndex

/** rychlost myši v tomhle kole - tabulka 1C28h, od kola 7 pevně 3 px/snímek */
function mouseSpeed() {
  var mice = geometry.mice;
  var i = roundIndex();
  return (i < mice.speedByRound.length) ? mice.speedByRound[i] : mice.speedLater;
} // mouseSpeed

/**
 * Kolik myší smí být venku najednou - tabulka 1156h z ROM; od kola 9 je to 8,
 * což je zároveň počet spritů, které hardware umí.
 */
function concurrentMice() {
  var mice = geometry.mice;
  var i = roundIndex();
  return (i < mice.concurrentByRound.length) ? mice.concurrentByRound[i] : mice.concurrentLater;
} // concurrentMice

/**
 * Jak dlouho myš kouše - tabulka 1574h podle kola. Když v podlaze nějaká díra
 * už je, doba se zdvojnásobí (originál kontroluje RAM 3022h). Kousání má tři
 * úseky: celou dobu, pak polovinu, pak ještě polovinu.
 */
function chewTicks() {
  var table = geometry.mice.chewByRound;
  var base = table[Math.min(roundIndex(), table.length-1)];
  return state.floor.some(function(stage) { return stage > 0; }) ? 2*base : base;
} // chewTicks

/** S_1CCD: náhodná doba do další změny směru, z tabulky 1D0Ah */
function turnPeriod() {
  var periods = geometry.mice.turnPeriods;
  return periods[Math.floor(Math.random()*periods.length)];
} // turnPeriod

/** bodová hodnota myši v tomhle kole (manuál str. 3) */
function mouseScore(carrying) {
  var index = Math.min(state.screen-1, SCORE_TABLE.length-1);
  return SCORE_TABLE[index]*(carrying ? 2 : 1);
} // mouseScore

/**
 * Vypustí myš z náhodného otvoru. Kde se zakousne do podlahy a pro který kus
 * sýra si jde, si nese s sebou - originál to řeší jinak (viz hlavička).
 */
function spawnMouse() {
  var mice = geometry.mice;
  var hole = Math.floor(Math.random()*mice.holesX.length);
  var tile = chewTile();
  state.mice.push({
    x: mice.holesX[hole],
    y: mice.holeY,
    dir: 'down',
    phase: 0,
    animTimer: 0,
    carrying: false,
    hole: hole,
    tile: tile,
    mode: 'descend',
    timer: 0,
    chew: 0,
    turnTimer: 1,
    stepping: 'along'
  });
} // spawnMouse

/**
 * Kde se myš zakousne. Originál (stav 14BEh) chodí po podlaze a zakousne se
 * všude, kde je dál než chewMinGap od každé existující díry; teprve když žádné
 * takové místo není, spokojí se s čímkoli.
 */
function chewTile() {
  var floor = geometry.floor;
  var gap = geometry.mice.chewMinGap;
  var holes = [];
  for (var t = 0; t+1 < floor.tiles; t++) {
    if (state.floor[t]) {
      holes.push(tileX(t)+floor.tile);
    }
  }
  var good = [], any = [];
  for (t = 0; t+1 < floor.tiles; t++) {
    any.push(t);
    var center = tileX(t)+floor.tile;
    if (holes.every(function(h) { return Math.abs(h-center) >= gap; })) {
      good.push(t);
    }
  }
  var pick = good.length ? good : any;
  return pick[Math.floor(Math.random()*pick.length)];
} // chewTile

/** vodorovný cíl myši: levý okraj dlaždice, kterou prokousává */
function tileX(tile) {
  return geometry.floor.x+tile*geometry.floor.tile;
} // tileX

/** posune myš o krok k cíli; vrátí true, když už tam je */
function stepTo(mouse, targetX, targetY) {
  var speed = mouseSpeed();
  // Originál se hýbe vždy jen po jedné ose (bit 1 v (IX+2)) a osu si přehazuje,
  // když doběhne náhodná doba z tabulky 1D0Ah (S_1CCD). Odtud ta schodovitá
  // chůze. Cíl si tady na rozdíl od originálu neseme s sebou - viz hlavička.
  if (--mouse.turnTimer <= 0) {
    mouse.turnTimer = turnPeriod();
    mouse.stepping = (mouse.stepping === 'across') ? 'along' : 'across';
  }
  var dy = targetY-mouse.y;
  var dx = targetX-mouse.x;
  if (mouse.stepping !== 'across' && dy !== 0) {
    mouse.y += (Math.abs(dy) < speed) ? dy : (dy > 0 ? speed : -speed);
    mouse.dir = (dy > 0) ? 'down' : 'up';
    return false;
  }
  if (dx !== 0) {
    mouse.x += (Math.abs(dx) < speed) ? dx : (dx > 0 ? speed : -speed);
    mouse.dir = (dx > 0) ? 'right' : 'left';
    return false;
  }
  if (dy !== 0) {
    mouse.stepping = 'along';
    return false;
  }
  return true;
} // stepTo

/** nejbližší zbylý kus sýra, nebo -1 */
function nearestCheese(mouse) {
  var mice = geometry.mice;
  var best = -1, bestDistance = 1e9;
  for (var i = 0; i < state.cheese.length; i++) {
    if (!state.cheese[i]) {
      continue;
    }
    var distance = Math.abs(mice.cheeseX[i % mice.cheeseX.length]-mouse.x);
    if (distance < bestDistance) {
      bestDistance = distance;
      best = i;
    }
  }
  return best;
} // nearestCheese

function updateMouse(mouse) {
  var mice = geometry.mice;
  switch (mouse.mode) {

    case 'descend':
      if (stepTo(mouse, tileX(mouse.tile), FLOOR_STAND_Y)) {
        mouse.mode = 'chew';
        mouse.timer = 0;
        mouse.chew = chewTicks();
      }
      break;

    case 'chew':
      // stavy 157Bh / 159Eh / 15C4h: úsek plné délky, pak dva poloviční
      mouse.dir = 'down';
      mouse.timer++;
      if (mouse.timer === mouse.chew) {
        setFloor(mouse.tile, 1);
      } else if (mouse.timer === mouse.chew+Math.floor(mouse.chew/2)) {
        setFloor(mouse.tile, 2);
        state.sounds.push('mouse');
      } else if (mouse.timer >= 2*mouse.chew) {
        mouse.mode = 'cellar';
        mouse.target = nearestCheese(mouse);
        mouse.stepping = 'along';
      }
      break;

    case 'cellar':
      if (mouse.target < 0 || !state.cheese[mouse.target]) {
        mouse.target = nearestCheese(mouse);
      }
      if (mouse.target < 0) {                 // sýr došel, myš se vrací naprázdno
        mouse.mode = 'carry';
        mouse.stepping = 'across';
        break;
      }
      var row = Math.floor(mouse.target/mice.cheeseX.length);
      if (stepTo(mouse, mice.cheeseX[mouse.target % mice.cheeseX.length],
                 mice.cheeseY[row]+CHEESE_REACH)) {
        state.cheese[mouse.target] = false;
        mouse.carrying = true;
        mouse.mode = 'carry';
        mouse.stepping = 'across';
        state.sounds.push('cheese');
        if (state.cheese.indexOf(true) < 0) {
          loseLife();                          // manuál pravidlo 3: odnesen poslední kus
          return;
        }
      }
      break;

    case 'carry':
      if (stepTo(mouse, tileX(mouse.tile), CELLAR_Y)) {
        mouse.mode = 'climb';
        mouse.stepping = 'along';
      }
      break;

    case 'climb':
      if (stepTo(mouse, mice.holesX[mouse.hole], mice.holeY)) {
        mouse.mode = 'gone';
      }
      break;

    case 'dying':
      mouse.timer++;
      if (mouse.timer >= geometry.mice.deathTicks) {
        mouse.mode = 'gone';
      }
      break;
  }
  if (++mouse.animTimer >= ANIM_TICKS) {
    mouse.animTimer = 0;
    mouse.phase = mouse.phase ? 0 : 1;
  }
} // updateMouse

/** stav dlaždice podlahy se nastavuje po dvojicích - díra je 16 px široká */
function setFloor(tile, stage) {
  state.floor[tile] = stage;
  if (tile+1 < state.floor.length) {
    state.floor[tile+1] = stage;
  }
} // setFloor

function loseLife() {
  state.lives--;
  state.sounds.push('mouseDies');
  // manuál pravidlo 5: po ztrátě života se sýr doplní na 8 a plocha se uklidí
  restock();
} // loseLife

/**
 * The hammer's box in raster coordinates while the swing is in its hit window.
 * The stored box belongs to the right-facing sprite, so facing left mirrors it
 * around the man's own box — exactly the way the renderer mirrors the picture.
 * @returns {number[]|null} [x, y, width, height], or null when not striking.
 */
function hitRect() {
  // zásah platí, jakmile je kladivo dole - tedy od druhé fáze švihu dál
  if (state.swingFrame < geometry.man.hit0Ticks) {
    return null;
  }
  var head = geometry.hammer.head;
  var x = manX();
  x = (state.man.dir < 0) ? x+geometry.man.width-head[0]-head[2] : x+head[0];
  return [x, geometry.man.y+head[1], head[2], head[3]];
} // hitRect

/** celopixelová poloha muže (levý okraj jeho bloku) */
function manX() {
  return Math.floor(state.man.x16/SUBPIXEL);
} // manX

/** jméno pózy, kterou má renderer nakreslit */
function manFrame() {
  var dir = state.man.dir < 0 ? 'L' : 'R';
  if (state.swingFrame >= 0) {
    return 'hit'+dir+(state.swingFrame < geometry.man.hit0Ticks ? 0 : 1);
  }
  return 'walk'+dir+state.man.walk;
} // manFrame

/** obdélník myši v rastru; y je spodní hrana, jako u hardwaru */
function mouseRect(mouse) {
  var vertical = (mouse.dir === 'down' || mouse.dir === 'up');
  var w = vertical ? 16 : 32;
  var h = vertical ? 32 : 16;
  return [mouse.x, mouse.y-h+1, w, h];
} // mouseRect

function overlap(a, b) {
  return a[0] < b[0]+b[2] && b[0] < a[0]+a[2] && a[1] < b[1]+b[3] && b[1] < a[1]+a[3];
} // overlap

function moveMan() {
  var man = state.man;
  // while the hammer is down the original freezes him, direction key or not
  if (state.swingFrame >= 0) {
    return;
  }
  var move = 0;
  if (state.controls.left) {
    move--;
  }
  if (state.controls.right) {
    move++;
  }
  if (move === 0) {
    man.walk = 0;
    man.walkTimer = 0;
    return;
  }
  man.dir = move;
  man.x16 += move*geometry.man.speed;
  if (man.x16 < geometry.man.minX*SUBPIXEL) {
    man.x16 = geometry.man.minX*SUBPIXEL;
  }
  if (man.x16 > geometry.man.maxX*SUBPIXEL) {
    man.x16 = geometry.man.maxX*SUBPIXEL;
  }
  if (++man.walkTimer >= geometry.man.walkTicks) {
    man.walkTimer = 0;
    man.walk = man.walk ? 0 : 1;
  }
} // moveMan

function swingHammer() {
  var s = state;
  // The swing follows the button, it is not a fixed animation: the press is
  // latched when the message arrives (a tap shorter than one 17 ms frame would
  // otherwise be lost - the original latches the button on the interrupt the
  // same way), the first pose holds hit0Ticks frames and the second one runs
  // until the button is released.
  if (s.hammerPressed) {
    s.hammerPressed = false;
    if (s.swingFrame < 0) {
      s.swingFrame = 0;
      s.hitUsed = false;
      s.sounds.push('hammer');
    }
  } else if (s.swingFrame >= 0) {
    if (s.controls.hammer || s.swingFrame+1 < geometry.man.hit0Ticks) {
      s.swingFrame++;
    } else {
      s.swingFrame = -1;
    }
  }
  if (s.swingFrame < 0) {
    return;
  }
  var rect = hitRect();
  if (rect === null || s.hitUsed) {
    return;
  }
  // jeden zásah na švih, i kdyby jich bylo v dosahu víc - manuál pravidlo 4
  // říká, že na podlaze jdou myši trefovat jen jedna po druhé
  for (var i = 0; i < s.mice.length; i++) {
    var mouse = s.mice[i];
    if (mouse.mode === 'dying' || mouse.mode === 'gone') {
      continue;
    }
    if (overlap(rect, mouseRect(mouse))) {
      s.hitUsed = true;
      s.score += mouseScore(mouse.carrying);
      if (s.score > s.hiScore) {
        s.hiScore = s.score;
      }
      s.miceKilled++;
      s.sounds.push('mouseDies');
      if (mouse.carrying) {
        // kus sýra, který nesla, spadne zpátky
        var free = s.cheese.indexOf(false);
        if (free >= 0) {
          s.cheese[free] = true;
        }
      }
      mouse.mode = 'dying';
      mouse.timer = 0;
      break;
    }
  }
} // swingHammer

function tick() {
  var s = state;
  s.frame++;
  if (s.lives <= 0) {
    return;
  }

  moveMan();
  swingHammer();

  // vypouštění myší z doupěte
  if (s.miceLeft > 0 && s.mice.length < concurrentMice()) {
    if (--s.spawnTimer <= 0) {
      s.spawnTimer = geometry.mice.spawnDelay;
      s.miceLeft--;
      spawnMouse();
    }
  }
  for (var i = 0; i < s.mice.length; i++) {
    updateMouse(s.mice[i]);
  }
  s.mice = s.mice.filter(function(mouse) { return mouse.mode !== 'gone'; });

  // kolo končí, když je všech 32 myší pryč (manuál pravidlo 7)
  if (s.miceLeft <= 0 && s.mice.length === 0) {
    s.screen++;
    s.miceLeft = MICE_PER_SCREEN;
    s.miceKilled = 0;
    postMessage({id: 'roundComplete', screen: s.screen});
  }
} // tick

function postFrame() {
  var s = state;
  postMessage({
    id: 'frame',
    frame: s.frame,
    score: s.score,
    hiScore: s.hiScore,
    lives: s.lives,
    screen: s.screen,
    cheese: s.cheese,
    floor: s.floor,
    mice: s.mice.map(function(mouse) {
      // A killed mouse is one flattened 16x16 sprite two pixels above where she
      // stood. The ROM (1D96h) picks the sprite by bit 0 of the direction byte,
      // which is set for down and left - so there are two corpses, not one.
      if (mouse.mode === 'dying') {
        var down = (mouse.dir === 'down' || mouse.dir === 'left');
        return {x: mouse.x, y: mouse.y-geometry.mice.deathOffsetY,
                frame: down ? 'dead_neg' : 'dead_pos'};
      }
      return {x: mouse.x, y: mouse.y,
              frame: mouse.dir+'_'+(mouse.carrying ? 'cheese' : 'plain')+mouse.phase};
    }),
    miceLeft: s.miceLeft,
    man: {x: manX(), dir: s.man.dir, walk: s.man.walk, frame: manFrame()},
    swing: s.swingFrame < 0 ? null : s.swingFrame,
    hit: hitRect(),
    state: s.lives > 0 ? 'game' : 'gameOver',
    sounds: s.sounds,
    soundBoard: {cheese: 0, music: 0, mouse: 0, hammer: 0, pest: 0, mouseDies: 0, pestDies: 0, coinExtra: 0, mute: 0}
  });
  s.sounds = [];
  if (s.lives <= 0 && !s.gameOverPosted) {
    s.gameOverPosted = true;
    postMessage({id: 'gameOver', score: s.score, hiScore: s.hiScore});
    s.running = false;
    clearTimeout(timer);
  }
} // postFrame

function loop() {
  var now = performance.now();
  if (lastTime === false) {
    lastTime = now;
  }
  accumulator = Math.min(250, accumulator+now-lastTime);
  lastTime = now;
  var ticked = false;
  while (accumulator >= TICK_MS) {
    tick();
    accumulator -= TICK_MS;
    ticked = true;
  }
  if (ticked) {
    postFrame();
  }
  if (state.running && !state.paused) {
    timer = setTimeout(loop, Math.max(1, TICK_MS-accumulator));
  }
} // loop

reset();

onmessage = function(event) {
  var msg = event.data;
  switch (msg.id) {
    case 'init':
      var initData = msg.initData || {};
      if (initData.geometry) {
        // the model owns ScreenLayout and data/sprites.json and hands the
        // measurements over, so the worker keeps no duplicate of them
        Object.keys(initData.geometry).forEach(function(k) {
          geometry[k] = initData.geometry[k];
        });
      }
      reset();
      state.headless = !!initData.headless;
      state.hiScore = initData.hiScore || 0;
      state.lives = (initData.dip && initData.dip.lives) || 3;
      state.running = true;
      if (!state.headless) {
        loop();
      }
      break;
    case 'controls':
      Object.keys(state.controls).forEach(function(k) {
        state.controls[k] = !!msg[k];
      });
      if (state.controls.hammer && !state.hammerLatch) {
        state.hammerPressed = true;
      }
      state.hammerLatch = state.controls.hammer;
      break;
    case 'pause':
      state.paused = true;
      clearTimeout(timer);
      break;
    case 'continue':
      if (state.running) {
        state.paused = false;
        lastTime = false;
        clearTimeout(timer);
        if (!state.headless) {
          loop();
        }
      }
      break;
    case 'tick':
      if (state.running) {
        tick();
        postFrame();
      }
      break;
    case 'reset':
      reset();
      break;
  }
};
