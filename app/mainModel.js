const { AbstractModel } = await import('./svision/js/abstractModel.js?ver='+window.srcVersion);
const { BorderEntity } = await import('./borderEntity.js?ver='+window.srcVersion);
const { TextEntity } = await import('./svision/js/platform/canvas2D/textEntity.js?ver='+window.srcVersion);
const { PauseGameEntity } = await import('./pauseGameEntity.js?ver='+window.srcVersion);
const { ZXColor } = await import('./svision/js/platform/canvas2D/zx/zxColor.js?ver='+window.srcVersion);
const { ScreenLayout } = await import('./screenLayout.js?ver='+window.srcVersion);
const { ScreenRender } = await import('./screenRender.js?ver='+window.srcVersion);
const { GameAreaEntity } = await import('./gameAreaEntity.js?ver='+window.srcVersion);
// begin code

/**
 * The game screen. The worker (gameWorker.js, WORKER-PROTOCOL.md) ticks at the
 * 58.64 Hz of the original machine and sends a 'frame' after every tick; this
 * model routes the controls (keyboard, mouse, gamepad, touch) to the worker as
 * a full {left, right, hammer} state and reacts to gameOver.
 *
 * M2: the picture is the static playfield — the frame, the lair with its four
 * holes, the floor and the cellar — drawn by GameAreaEntity from
 * data/screen.json, plus the man in one of his eight poses from
 * data/sprites.json and the mice, the cheese and the state of the floor from
 * data/mice.json. The pests arrive in M4.
 *
 * The model owns the geometry (ScreenLayout + the sprite measurements) and
 * hands it to the worker on init, so the worker keeps no duplicate of it.
 *
 * The HUD is drawn with the svision fonts on top of the picture; in the
 * original it is part of the video RAM, so M5 moves it into the renderer.
 */
export class MainModel extends AbstractModel {

  constructor(app, attract) {
    super(app);
    this.id = 'MainModel';

    this.attract = attract;
    this.gameOver = false;
    this.frame = null;
    this.controlsState = {left: false, right: false, hammer: false};
    this.worker = null;
    this.render = null;
    this.spritesData = null;
    this.miceData = null;
    this.gameAreaEntity = null;
    this.hud = {};
    this.fpsEntity = null;
    this.fps = {frames: 0, workerFrames: 0, ticks: 0, since: false, lastFrame: false};
  } // constructor

  newBorderEntity() {
    return new BorderEntity(true, this.app.controls.touchscreen.supported);
  } // newBorderEntity

  init() {
    super.init();

    this.borderEntity.bkColor = ZXColor.black;
    this.desktopEntity.bkColor = ZXColor.black;

    // the data files: at once from localStorage, or from the server when they
    // are missing there (R-062)
    this.loadDataFiles(['screen', 'sprites', 'mice'], (files, error) => this.initData(files, error));
  } // init

  /**
   * The part of init() that needs the data files. Runs inside init() when
   * they are in localStorage, later when they had to come from the server.
   * @param {Object|null} files - The data files, or null.
   * @param {Error} [error] - Why they are missing.
   */
  initData(files, error) {
    if (this.app.model !== this) {
      return;
    }
    if (!files) {
      this.app.showErrorMessage(error ? error.message : 'Game data could not be loaded.', 'restart');
    }
    if (this.initScreen()) {
      this.initHud();
    } else {
      this.desktopEntity.addEntity(new TextEntity(this.desktopEntity, this.app.fonts.zxFonts8x8, 0, 8*8, this.desktopWidth, 8, 'CHEEKY MOUSE', ZXColor.brightWhite, false, {align: 'center'}));
      this.desktopEntity.addEntity(new TextEntity(this.desktopEntity, this.app.fonts.fonts5x5, 8, 8*8+16, this.desktopWidth-16, 40,
        'SCREEN DATA MISSING (data/screen.json). RUN tools/mkscreen.py.', ZXColor.brightGreen, false, {align: 'center', textWrap: true}));
    }

    if (this.app.devModeName !== false) {
      // over the 2ND score, which stays empty until two players arrive in M4 —
      // the bottom of the screen is taken by the CREDIT line
      this.fpsEntity = new TextEntity(this.desktopEntity, this.app.fonts.fonts3x3, this.desktopWidth-48, ScreenLayout.HUD_TOP_ROW2_Y+2, 40, 4, '', ZXColor.brightGreen, false, {align: 'right'});
      this.desktopEntity.addEntity(this.fpsEntity);
    }

    // the menu keeps the audio closed; the game opens its buses here (MM pattern)
    this.sendEvent(0, {id: 'openAudioBus', bus: 'sounds', options: {muted: this.app.muted.sounds}});
    this.sendEvent(0, {id: 'openAudioBus', bus: 'music', options: {muted: this.app.muted.music}});

    this.worker = this.app.worker;
    this.app.inputEventsManager.sendEventsActiveKeys('Press');
    this.sendWorkerMessage({
      id: 'init',
      initData: {
        headless: false,
        dip: this.app.dip,
        hiScore: this.app.hiScore || 0,
        attract: this.attract,
        geometry: this.workerGeometry()
      }
    });
    this.updateHud();
  } // initData

  shutdown() {
    super.shutdown();
    this.sendWorkerMessage({id: 'reset'});
    this.sendEvent(0, {id: 'stopAllAudioBuses'});
  } // shutdown


  /**
   * Builds the renderer and adds the picture entity, centered in the desktop.
   * @returns {boolean} True when the picture was created.
   */
  initScreen() {
    var screen = this.loadDataFile('screen');
    if (!screen) {
      return false;
    }
    this.spritesData = this.loadDataFile('sprites');
    this.miceData = this.loadDataFile('mice');
    try {
      this.render = new ScreenRender(screen, this.spritesData, this.miceData);
    } catch (error) {
      console.error(error.message);
      return false;
    }
    this.gameAreaEntity = new GameAreaEntity(this.desktopEntity, ScreenLayout.OFFSET_X, 0, this.render);
    this.desktopEntity.addEntity(this.gameAreaEntity);
    return true;
  } // initScreen

  /**
   * The measurements the worker needs: where the man may walk, how fast, where
   * the floor is and what the hammer's swing looks like. They live in
   * ScreenLayout and data/sprites.json; the worker gets a copy on init.
   * @returns {Object} The geometry block of the init message.
   */
  workerGeometry() {
    var floor = {
      x: ScreenLayout.PLAY_X,
      y: ScreenLayout.FLOOR_Y,
      tile: ScreenLayout.FLOOR_TILE,
      tiles: ScreenLayout.FLOOR_TILES
    };
    if (this.miceData) {
      floor = {
        x: this.miceData.floor.x,
        y: this.miceData.floor.y,
        tile: this.miceData.floor.tile,
        tiles: this.miceData.floor.tiles
      };
    }
    if (!this.spritesData) {
      return {floor: floor};
    }
    var sprites = this.spritesData;
    var timing = sprites.timing;
    var walk = sprites.man.frames.walkR0;
    // Everything about the man is measured off the running original, so it all
    // comes straight out of data/sprites.json — nothing is chosen here.
    var man = {
      width: walk.width,
      minX: sprites.man.minX,
      maxX: sprites.man.maxX,
      y: sprites.man.y,
      speed: timing.speed,           // in 1/256 px per tick
      walkTicks: timing.walkTicks,
      hit0Ticks: timing.hit0Ticks
    };
    // The hit rectangle is the hammer of the striking pose: the part of it that
    // reaches past his body. M3 checks it against the mice.
    var hit = sprites.man.frames.hitR1;
    var geometry = {
      man: man,
      floor: floor,
      hammer: {head: [man.width, 16, hit.width-man.width, 8]}
    };
    if (this.miceData) {
      // the holes, the speed and where the cheese lies are all measured
      geometry.mice = {
        speed: this.miceData.mouse.speed,
        holesX: this.miceData.mouse.holesX,
        holeY: this.miceData.mouse.holeY,
        cheeseX: this.miceData.cheese.x,
        cheeseY: this.miceData.cheese.rows.map((row) => row.y),
        width: 16,
        deathTicks: this.miceData.mouse.deathTicks,
        deathOffsetY: this.miceData.mouse.deathOffsetY,
        // pravidla odečtená z disassembly (sources/docs/disasm_notes.md)
        speedByRound: this.miceData.mouse.speedByRound,
        speedLater: this.miceData.mouse.speedLater,
        concurrentByRound: this.miceData.mouse.concurrentByRound,
        concurrentLater: this.miceData.mouse.concurrentLater,
        turnPeriods: this.miceData.mouse.turnPeriods,
        chewByRound: this.miceData.mouse.chewByRound,
        chewMinGap: this.miceData.mouse.chewMinGap,
        spawnDelay: this.miceData.mouse.spawnDelay
      };
    }
    return geometry;
  } // workerGeometry

  /**
   * The HUD of the original: the three scores on top, the remaining men and the
   * credit at the bottom. The entities are children of the picture, so their
   * coordinates are the raster ones from sources/docs/screen_layout.md.
   */
  initHud() {
    var mono = this.app.fonts.zxFonts8x8Mono;
    var pal = ScreenLayout.PALETTE;
    var add = (name, x, y, width, text, color, align) => {
      this.hud[name] = new TextEntity(this.gameAreaEntity, mono, x, y, width, 8, text, color, false, {align: align});
      this.gameAreaEntity.addEntity(this.hud[name]);
    };
    // The HUD colors are the machine's own, not the ZX palette. The original
    // derives them from the tile position (get_tile_info in the MAME driver):
    // the top bar is one tile column split into three zones, which after the
    // ROT270 become raster x < 64, x < 128 and the rest — exactly where 1ST,
    // HI SCORE and 2ND sit. Yellow and magenta are read off the screenshot;
    // the third zone is never visible in a one-player game, so white is a
    // placeholder until the PROM is dumped (M0).
    add('label1', 24, ScreenLayout.HUD_TOP_ROW1_Y, 24, '1ST', pal[ScreenLayout.YELLOW], 'left');
    add('labelHi', 64, ScreenLayout.HUD_TOP_ROW1_Y, 64, 'HI SCORE', pal[ScreenLayout.MAGENTA], 'left');
    add('label2', 136, ScreenLayout.HUD_TOP_ROW1_Y, 24, '2ND', pal[ScreenLayout.WHITE], 'left');
    add('score1', 8, ScreenLayout.HUD_TOP_ROW2_Y, 56, '', pal[ScreenLayout.YELLOW], 'right');
    add('scoreHi', 64, ScreenLayout.HUD_TOP_ROW2_Y, 56, '', pal[ScreenLayout.MAGENTA], 'right');
    add('score2', 128, ScreenLayout.HUD_TOP_ROW2_Y, 48, '', pal[ScreenLayout.WHITE], 'right');
    add('lives', 8, ScreenLayout.HUD_BOTTOM_Y, 24, '', pal[ScreenLayout.CYAN], 'right');
    add('credit', 88, ScreenLayout.HUD_BOTTOM_Y, 88, '', pal[ScreenLayout.WHITE], 'right');
    // two players are only wired up in M4; until then the second score is blank
    this.hud.label2.hide = true;
    this.hud.score2.hide = true;
  } // initHud

  updateHud() {
    if (!this.hud.score1) {
      return;
    }
    // the original prints the scores unpadded (the screenshot shows "320" and "0")
    this.hud.score1.setText(String(this.app.score || 0));
    this.hud.scoreHi.setText(String(this.app.hiScore || 0));
    this.hud.lives.setText(String(Math.max(0, this.app.lives || 0)));
    this.hud.credit.setText('CREDIT 0');
  } // updateHud

  sendWorkerMessage(event) {
    if (this.worker) {
      this.worker.postMessage(event);
    }
  } // sendWorkerMessage

  /**
   * Sets one control and sends the whole state to the worker when it changed
   * (protocol: {id:'controls', left, right, hammer}).
   */
  setControl(action, value) {
    if (!(action in this.controlsState) || this.controlsState[action] === value) {
      return;
    }
    this.controlsState[action] = value;
    this.sendWorkerMessage(Object.assign({id: 'controls'}, this.controlsState));
  } // setControl

  handleWorkerMessage(event) {
    var data = event.data;
    switch (data.id) {
      case 'frame':
        this.frame = data;
        this.fps.workerFrames++;
        // ★ R-045: a tiky světa zvlášť, odečtené z čítače ve zprávě
        if (this.fps.lastFrame !== false) { this.fps.ticks += data.frame-this.fps.lastFrame; }
        this.fps.lastFrame = data.frame;
        if (this.gameAreaEntity) {
          this.gameAreaEntity.setFrame({
            cheese: data.cheese,
            floor: data.floor,
            man: data.man,
            mice: data.mice
          });
        }
        if (typeof data.score == 'number') {
          this.app.score = data.score;
        }
        if (typeof data.hiScore == 'number' && data.hiScore > (this.app.hiScore || 0)) {
          this.app.hiScore = data.hiScore;
        }
        if (typeof data.lives == 'number') {
          this.app.lives = data.lives;
        }
        if (data.soundBoard && this.app.audioManager && typeof this.app.audioManager.playFrame == 'function') {
          this.app.audioManager.playFrame(data);   // M5: the sound board
        }
        this.updateHud();
        break;
      case 'gameOver':
        if (!this.gameOver) {
          this.gameOver = true;
          if (typeof data.score == 'number') {
            this.app.score = data.score;
          }
          this.app.setModel('GameOverModel');
        }
        break;
    }
  } // handleWorkerMessage

  /** maps a key/gamepad/mouse event to a control action, or false */
  controlAction(key) {
    var kb = this.app.controls.keyboard, mouse = this.app.controls.mouse;
    var mouseOk = (k) => mouse.enable && this.app.inputEventsManager.keysMap[k] === false;
    switch (key) {
      case kb.left: case 'GamepadLeft': return 'left';
      case kb.right: case 'GamepadRight': return 'right';
      case kb.hammer: case 'GamepadJump': return 'hammer';
      case mouse.left: return mouseOk(mouse.left) ? 'left' : false;
      case mouse.right: return mouseOk(mouse.right) ? 'right' : false;
      case mouse.hammer: return mouseOk(mouse.hammer) ? 'hammer' : false;
    }
    return false;
  } // controlAction

  handleEvent(event) {
    if (super.handleEvent(event)) {
      return true;
    }

    switch (event.id) {

      case 'exitGame':
        this.app.setModel('MenuModel');
        return true;

      case 'blurWindow':
        this.pauseGame();
        return true;

      case 'continueGame':
        this.sendWorkerMessage({id: 'continue'});
        this.sendEvent(0, {id: 'continueAllAudioBuses'});
        return true;

      case 'keyPress':
        var key = event.key;
        if (key.length == 1) {
          key = key.toUpperCase();
        }
        switch (key) {
          case 'Escape':
          case 'P':
          case 'GamepadExit':
            this.pauseGame();
            return true;
          case 'Touch':
            if (this.borderEntity.leftControlEntity && this.borderEntity.leftControlEntity.pointOnEntity(event)) {
              this.app.inputEventsManager.touchesMap[event.identifier] = this.borderEntity.leftControlEntity;
              this.touchStart(event, 'left');
              return true;
            }
            if (this.borderEntity.rightControlEntity && this.borderEntity.rightControlEntity.pointOnEntity(event)) {
              this.app.inputEventsManager.touchesMap[event.identifier] = this.borderEntity.rightControlEntity;
              this.touchStart(event, 'right');
              return true;
            }
            break;
          case 'RetryTouch':
            this.setControl(event.action, true);
            return true;
          case this.app.controls.keyboard.sounds:
            this.app.muted.sounds = !this.app.muted.sounds;
            this.sendEvent(0, {id: 'muteAudioBus', bus: 'sounds', muted: this.app.muted.sounds});
            return true;
          case this.app.controls.keyboard.music:
            this.app.muted.music = !this.app.muted.music;
            this.sendEvent(0, {id: 'muteAudioBus', bus: 'music', muted: this.app.muted.music});
            return true;
        }
        var action = this.controlAction(key);
        if (action !== false) {
          this.setControl(action, true);
          return true;
        }
        break;

      case 'keyRelease':
        var rkey = event.key;
        if (rkey.length == 1) {
          rkey = rkey.toUpperCase();
        }
        if (rkey == 'Touch') {
          this.touchEnd(event);
          return true;
        }
        var raction = this.controlAction(rkey);
        if (raction !== false) {
          this.setControl(raction, false);
          return true;
        }
        break;

      case 'keyMove':
        if (event.key == 'Touch') {
          this.touchMove(event);
          return true;
        }
        break;

      case 'errorAudioBus':
        this.app.showErrorMessage(event.error, 'reopen');
        return true;
    }

    return false;
  } // handleEvent

  // pause the worker and open the pause menu (RESUME / SOUNDS / MUSIC / EXIT GAME)
  pauseGame() {
    if (this.desktopEntity.modalEntity || this.gameOver) {
      return;
    }
    this.sendWorkerMessage({id: 'pause'});
    this.sendEvent(0, {id: 'pauseAllAudioBuses'});
    this.desktopEntity.addModalEntity(new PauseGameEntity(this.desktopEntity, 28, 86, 153, 85, 'PAUSE GAME', 'MenuModel'));
  } // pauseGame

  // touch controls (SI/MM pattern): the border's left/right control areas carry a
  // button or a horizontal joystick according to controlsOptions.touchscreen.types
  touchStart(event, side) {
    var ts = this.app.controlsOptions.touchscreen.types[this.app.controls.touchscreen.type][side];
    if (ts.type == 'button') {
      this.setControl(ts.action, true);
    }
    this.app.inputEventsManager.touchesGameControls[event.identifier] = {center: {x: event.x, y: event.y}, type: ts.type, control: ts.control, action: ts.action, actions: ts.actions};
  } // touchStart

  touchEnd(event) {
    var tgc = this.app.inputEventsManager.touchesGameControls;
    if (event.identifier in tgc) {
      if (tgc[event.identifier].action !== false) {
        this.setControl(tgc[event.identifier].action, false);
      }
      delete tgc[event.identifier];
    }
  } // touchEnd

  touchMove(event) {
    var tgc = this.app.inputEventsManager.touchesGameControls;
    if (!(event.identifier in tgc)) {
      return;
    }
    var control = tgc[event.identifier];
    var action = control.action;
    if (control.type == 'joystick' && control.control == 'horizontal') {
      if (event.x-control.center.x < -10) {
        action = control.actions[0];
        control.center.x = event.x;
      }
      if (event.x-control.center.x > 10) {
        action = control.actions[1];
        control.center.x = event.x;
      }
      if (control.action !== action) {
        if (control.action !== false) {
          this.setControl(control.action, false);
        }
        control.action = action;
        this.setControl(control.action, true);
      }
    }
  } // touchMove

  updateFps(timestamp) {
    if (!this.fpsEntity) {
      return;
    }
    this.fps.frames++;
    if (this.fps.since === false) {
      this.fps.since = timestamp;
      return;
    }
    var elapsed = timestamp-this.fps.since;
    if (elapsed >= 1000) {
      var draw = Math.round(this.fps.frames*1000/elapsed);
      var worker = Math.round(this.fps.workerFrames*1000/elapsed);
      var ticks = Math.round(this.fps.ticks*1000/elapsed);
      this.fpsEntity.setText(draw+'/'+worker+'/'+ticks+' FPS');
      this.fps.frames = 0;
      this.fps.workerFrames = 0;
      this.fps.ticks = 0;
      this.fps.since = timestamp;
    }
  } // updateFps

  loopModel(timestamp) {
    super.loopModel(timestamp);

    if (this.desktopEntity.modalEntity) {
      this.desktopEntity.modalEntity.loopEntity(timestamp);
    }

    this.updateFps(timestamp);
    this.drawModel();
  } // loopModel

} // MainModel
