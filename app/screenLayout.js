// begin code

/**
 * Geometry and palette of the Cheeky Mouse screen, measured pixel by pixel
 * from the original MAME screenshot — see sources/docs/screen_layout.md.
 * Coordinates are in the rotated (in-game) 192x256 raster; OFFSET_X places
 * that raster inside the 208 wide desktop of ArcadePlatform.
 *
 * The palette is the full color space of the machine: the PROMs give one bit
 * per R/G/B component, so the game has exactly eight colors.
 */
export const ScreenLayout = {

  WIDTH: 192,
  HEIGHT: 256,
  OFFSET_X: 8,          // (208-192)/2 — centering in the desktop

  // eight colors of the PROM palette, indexed the way data/screen.json is coded
  PALETTE: ['#000000', '#0000FF', '#00FFFF', '#00FF00', '#FFFF00', '#FF0000', '#FFFFFF', '#FF00FF'],
  BLACK: 0, BLUE: 1, CYAN: 2, GREEN: 3, YELLOW: 4, RED: 5, WHITE: 6, MAGENTA: 7,

  // HUD: two 8 px text rows on top, one at the bottom
  HUD_TOP_ROW1_Y: 0,    // 1ST / HI SCORE / 2ND labels
  HUD_TOP_ROW2_Y: 8,    // the three scores
  HUD_BOTTOM_Y: 248,    // remaining men + CREDIT n

  // the band lifted from the original screenshot (data/screen.json)
  BAND_Y: 16,
  BAND_HEIGHT: 232,

  // playfield: x 8..183, y 64..191 — the mice, the man and the windows live here
  PLAY_X: 8,
  PLAY_Y: 64,
  PLAY_WIDTH: 176,
  PLAY_HEIGHT: 128,

  // four holes in the lair, outer edges; centers 31.5 / 71.5 / 119.5 / 159.5
  HOLE_Y: 52,
  HOLE_HEIGHT: 12,
  HOLE_WIDTH: 14,
  HOLE_X: [25, 65, 113, 153],

  // The floor rows and the cheese grid are measured too, but they belong to the
  // picture, so tools/mkscreen.py writes them into data/screen.json and
  // screenRender.js reads them from there — they are deliberately not repeated
  // here. Only the floor line the man walks on is needed for the game logic.
  FLOOR_Y: 192,
  FLOOR_TILE: 8,
  FLOOR_TILES: 22,       // 176 px of floor / 8 px per tile

  // The man. Everything about him — his eight poses, how fast he walks, how
  // long a walking frame lasts, how the swing runs and where he may go — is
  // measured from the running original and lives in data/sprites.json
  // (tools/mksprites.py over the tracing emulator). Nothing here is a guess,
  // so the constants are not repeated: the model passes them to the worker.
  MAN_Y: 160             // his feet end on 191, the floor starts on 192

}; // ScreenLayout
