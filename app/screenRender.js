// begin code

/**
 * Renders the Cheeky Mouse picture into a raw RGBA buffer.
 *
 * M1/M2 have no ROM graphics yet (M0 is waiting for the ROM set), so the
 * picture is assembled from two generated data files:
 *
 *   data/screen.json  — the static part (the frame, the lair with its four
 *     holes, the floor and the cellar): the original MAME screenshot with the
 *     sprites and the chewed floor removed, run-length coded over the eight
 *     PROM colors by tools/mkscreen.py. The cheese is stored separately and
 *     drawn from the geometry in the same file, so pieces can be taken away.
 *   data/sprites.json — the man's eight poses (tools/mksprites.py), read out of
 *     the video RAM of the running original: walking and striking, each with
 *     its own tiles for facing left and facing right. The original does not
 *     mirror him, so neither do we.
 *   data/mice.json — the mice (four directions, two animation frames, with and
 *     without cheese in the mouth), the three floor states and the cheese
 *     tiles, all rendered from the ROM (tools/mkmice.py).
 *
 * Deliberately free of DOM and Node dependencies (the Stinger
 * tileMapRender.js pattern), so the very same code can render in the browser
 * and in an offline tool. M5 replaces it with the tile/sprite renderer fed
 * from the ROM dump (tools/dumpgfx.py); renderInto() stays as it is.
 */
export class ScreenRender {

  static get WIDTH() { return 192; }
  static get HEIGHT() { return 256; }
  static get BLACK() { return 0; }

  /**
   * @param {Object} screen - The parsed data/screen.json.
   * @param {Object} [sprites] - The parsed data/sprites.json; without it the
   *        man and the hammer are simply not drawn.
   */
  constructor(screen, sprites, mice) {
    if (!screen || !screen.rows || !screen.cheese || !screen.floor) {
      throw new Error('screen data missing or incomplete');
    }
    this.screen = screen;
    this.sprites = sprites || null;
    this.mice = mice || null;
    this.palette = screen.palette.map((color) => [
      parseInt(color.substr(1, 2), 16),
      parseInt(color.substr(3, 2), 16),
      parseInt(color.substr(5, 2), 16)
    ]);
    this.width = screen.width;
    this.height = ScreenRender.HEIGHT;
    this.bandY = screen.y;
    // expand the run-length rows once: the per-frame work is then a plain copy
    this.band = screen.rows.map((row) => this.expandRow(row, this.width));
    this.cheese = screen.cheese.rows.map((row) => this.expandRow(row, screen.cheese.width));
    this.mouse = null;
    this.floorStage = null;
    this.cheeseTile = null;
    if (this.mice) {
      this.mouse = {};
      Object.keys(this.mice.mouse.frames).forEach((key) => {
        var frame = this.mice.mouse.frames[key];
        this.mouse[key] = this.expandSprite(frame.rows, frame.width);
      });
      this.floorStage = {};
      Object.keys(this.mice.floor.stages).forEach((stage) => {
        this.floorStage[stage] = this.mice.floor.stages[stage].map(
          (tile) => this.expandSprite(tile.rows, tile.width));
      });
      this.cheeseTile = this.mice.cheese.rows.map(
        (row) => this.expandSprite(row.tile.rows, row.tile.width));
    }
    this.man = null;
    if (this.sprites) {
      this.man = {};
      Object.keys(this.sprites.man.frames).forEach((key) => {
        var frame = this.sprites.man.frames[key];
        this.man[key] = this.expandSprite(frame.rows, frame.width);
      });
    }
  } // constructor

  /**
   * Expands the run-length rows of one sprite.
   * @param {Array} rows - Run-length coded rows.
   * @param {number} width - Sprite width.
   * @returns {Uint8Array[]} The expanded rows.
   */
  expandSprite(rows, width) {
    return rows.map((row) => this.expandRow(row, width));
  } // expandSprite

  /**
   * Expands one run-length coded row into a flat array of palette indexes.
   * @param {Array} row - Pairs of [runLength, colorIndex].
   * @param {number} width - Expected row width.
   * @returns {Uint8Array} The expanded row.
   */
  expandRow(row, width) {
    var out = new Uint8Array(width);
    var x = 0;
    row.forEach((run) => {
      for (var i = 0; i < run[0] && x < width; i++, x++) {
        out[x] = run[1];
      }
    });
    return out;
  } // expandRow

  /**
   * Paints one pixel of a palette color into the RGBA buffer.
   */
  setPixel(rgba, x, y, index) {
    if (x < 0 || y < 0 || x >= this.width || y >= this.height) {
      return;
    }
    var offset = (y*this.width+x)*4;
    var color = this.palette[index];
    rgba[offset] = color[0];
    rgba[offset+1] = color[1];
    rgba[offset+2] = color[2];
    rgba[offset+3] = 255;
  } // setPixel

  /**
   * Renders a whole frame.
   * @param {Uint8ClampedArray} rgba - Target buffer, WIDTH*HEIGHT*4 bytes.
   * @param {Object} [state] - The video state of one frame:
   *        {cheese, holes, man: {x, frame}}. Everything is optional; the
   *        default is a fresh screen with nobody on it.
   */
  renderInto(rgba, state) {
    for (var i = 0; i < rgba.length; i += 4) {
      rgba[i] = 0;
      rgba[i+1] = 0;
      rgba[i+2] = 0;
      rgba[i+3] = 255;
    }
    for (var row = 0; row < this.band.length; row++) {
      var y = this.bandY+row;
      var line = this.band[row];
      for (var x = 0; x < this.width; x++) {
        if (line[x] !== ScreenRender.BLACK) {
          this.setPixel(rgba, x, y, line[x]);
        }
      }
    }
    if (this.mice) {
      this.drawFloor(rgba, (state && state.floor) || []);
      this.drawCheeseGrid(rgba, (state && state.cheese) || []);
    } else {
      var cheese = this.screen.cheese;
      this.drawCheese(rgba, (state && typeof state.cheese == 'number') ? state.cheese : cheese.count);
      if (state && state.holes) {
        this.drawHoles(rgba, state.holes);
      }
    }
    if (state && state.man && this.man) {
      this.drawMan(rgba, state.man);
    }
    if (state && state.mice && this.mouse) {
      state.mice.forEach((mouse) => this.drawMouse(rgba, mouse));
    }
  } // renderInto

  /**
   * Repaints the floor where the mice have been at work. The background already
   * carries the whole floor, so a chewed or open tile is cleared first and the
   * matching tile drawn over it.
   * @param {Uint8ClampedArray} rgba - Target buffer.
   * @param {number[]} floor - Stage per floor tile: 0 whole, 1 chewing, 2 open.
   */
  drawFloor(rgba, floor) {
    var spec = this.mice.floor;
    var stages = ['whole', 'chewing', 'hole'];
    for (var tile = 0; tile < floor.length; tile++) {
      if (!floor[tile]) {
        continue;
      }
      var x = spec.x+tile*spec.tile;
      for (var y = spec.y; y < spec.y+spec.tile; y++) {
        for (var dx = 0; dx < spec.tile; dx++) {
          this.setPixel(rgba, x+dx, y, ScreenRender.BLACK);
        }
      }
      // a hole is two tiles wide; each tile knows which half it is
      var half = this.floorStage[stages[floor[tile]]][tile & 1];
      this.drawSprite(rgba, half, x, spec.y, false, true);
    }
  } // drawFloor

  /**
   * Draws the pieces of cheese that are still in the cellar.
   * @param {Uint8ClampedArray} rgba - Target buffer.
   * @param {boolean[]} cheese - One flag per piece, rows of four.
   */
  drawCheeseGrid(rgba, cheese) {
    var spec = this.mice.cheese;
    var piece = 0;
    for (var row = 0; row < spec.rows.length; row++) {
      for (var col = 0; col < spec.x.length; col++, piece++) {
        if (cheese[piece]) {
          this.drawSprite(rgba, this.cheeseTile[row], spec.x[col], spec.rows[row].y, false, true);
        }
      }
    }
  } // drawCheeseGrid

  /**
   * Draws one mouse. Its y is the bottom edge, the way the hardware addresses
   * sprites after the rotation.
   * @param {Uint8ClampedArray} rgba - Target buffer.
   * @param {Object} mouse - {x, y, frame} from the worker.
   */
  drawMouse(rgba, mouse) {
    var frame = this.mouse[mouse.frame];
    if (frame) {
      this.drawSprite(rgba, frame, mouse.x, mouse.y-frame.length+1, false, true);
    }
  } // drawMouse

  /**
   * Blits one sprite, optionally mirrored around its own vertical axis and
   * clipped to the playfield. Color index 0 (black) is the transparent pen,
   * exactly as on the original.
   * @param {Uint8ClampedArray} rgba - Target buffer.
   * @param {Uint8Array[]} sprite - The expanded sprite rows.
   * @param {number} x - Left edge in raster coordinates.
   * @param {number} y - Top edge in raster coordinates.
   * @param {boolean} flip - Mirror horizontally.
   * @param {boolean} [clip] - Clip to the playfield between the side frames;
   *        the original clips the man's band the same way (in_man_area in the
   *        MAME driver), so a hammer swung at the wall is cut off instead of
   *        spilling over the frame.
   */
  drawSprite(rgba, sprite, x, y, flip, clip) {
    var play = this.screen.play;
    var left = (clip && play) ? play.x : 0;
    var right = (clip && play) ? play.x+play.width : this.width;
    var width = sprite[0].length;
    for (var sy = 0; sy < sprite.length; sy++) {
      for (var sx = 0; sx < width; sx++) {
        var index = sprite[sy][flip ? width-1-sx : sx];
        if (index !== ScreenRender.BLACK && x+sx >= left && x+sx < right) {
          this.setPixel(rgba, x+sx, y+sy, index);
        }
      }
    }
  } // drawSprite

  /**
   * Draws the man in the pose the worker asks for. Poses have different widths
   * (the hammer reaches further than his body) and the original writes the
   * wider ones a tile to the side, which is what offsetX carries.
   * @param {Uint8ClampedArray} rgba - Target buffer.
   * @param {Object} man - {x, frame} from the worker.
   */
  drawMan(rgba, man) {
    var spec = this.sprites.man;
    var frame = this.man[man.frame];
    if (frame) {
      this.drawSprite(rgba, frame, man.x+(spec.frames[man.frame].offsetX || 0), spec.y, false, true);
    }
  } // drawMan

  /**
   * Draws the remaining pieces of cheese. The mice take them one by one, so the
   * count simply maps onto the grid row by row.
   * @param {Uint8ClampedArray} rgba - Target buffer.
   * @param {number} count - Pieces left, 0..8.
   */
  drawCheese(rgba, count) {
    var cheese = this.screen.cheese;
    var piece = 0;
    cheese.y.forEach((cy) => {
      cheese.cols.forEach((cx) => {
        if (piece++ >= count) {
          return;
        }
        for (var y = 0; y < cheese.height; y++) {
          for (var x = 0; x < cheese.width; x++) {
            var index = this.cheese[y][x];
            if (index !== ScreenRender.BLACK) {
              this.setPixel(rgba, cx+x, cy+y, index);
            }
          }
        }
      });
    });
  } // drawCheese

  /**
   * Clears the floor tiles the mice have chewed through.
   * @param {Uint8ClampedArray} rgba - Target buffer.
   * @param {number[]} holes - Indexes of chewed 8 px floor tiles (0..21).
   */
  drawHoles(rgba, holes) {
    var floor = this.screen.floor;
    holes.forEach((tile) => {
      var x0 = floor.x+tile*floor.tile;
      floor.rows.forEach((y) => {
        for (var x = x0; x < x0+floor.tile && x < floor.x+floor.width; x++) {
          this.setPixel(rgba, x, y, ScreenRender.BLACK);
        }
      });
    });
  } // drawHoles

} // ScreenRender
