const { ArcadePlatform } = await import('./svision/js/platform/canvas2D/arcade/arcadePlatform.js?ver='+window.srcVersion);
// begin code

/**
 * Cheeky Mouse: the original raster is 192x256 portrait (hardware 256x192
 * rotated by ROT270, ZADANI chap. 1). That is the narrowest screen in the
 * family and the shared svision ZX dialogs (player name keyboard, volume,
 * settings) are laid out for ~202 logical pixels, so they would be clipped.
 *
 * The desktop is therefore 208x256 — the same as Pleiads — and the 192x256
 * game raster is drawn centered in it at x=8 (ScreenLayout.OFFSET_X). The
 * bezel is black, so the eight columns on each side are invisible; the game
 * picture itself stays pixel-exact and integer-scaled.
 */
export function appPlatform() {
  return new ArcadePlatform({
    width: 208,
    height: 256,
    bezelColor: '#000000',
    screenColor: '#000000',
    minimalBorder: 0,
    overlay: {enabled: false, bands: []}
  });
} // appPlatform
