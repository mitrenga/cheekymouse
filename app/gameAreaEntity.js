const { RasterEntity } = await import('./svision/js/platform/canvas2D/rasterEntity.js?ver='+window.srcVersion);
const { ScreenRender } = await import('./screenRender.js?ver='+window.srcVersion);
// begin code

/**
 * The 192x256 game picture. The pixels are produced by ScreenRender (the same
 * DOM-free module an offline tool can use), the entity owns only the off-screen
 * cache: a frame is rendered once into an ImageData and then blitted — and
 * scaled by the layout ratio — on every draw.
 *
 * Feed it with setFrame() from the worker 'frame' message (WORKER-PROTOCOL.md).
 */
export class GameAreaEntity extends RasterEntity {

  /**
   * @param {AbstractEntity} parentEntity - The parent entity.
   * @param {number} x - X position relative to the parent (ScreenLayout.OFFSET_X).
   * @param {number} y - Y position relative to the parent.
   * @param {ScreenRender} render - The shared renderer.
   */
  constructor(parentEntity, x, y, render) {
    super(parentEntity, x, y, ScreenRender.WIDTH, ScreenRender.HEIGHT, false, false);
    this.id = 'GameAreaEntity';

    this.render = render;
    this.frameState = {cheese: 8, holes: []};
  } // constructor

  /**
   * Stores the video state of the newest frame and invalidates the cache.
   * @param {Object} state - {cheese, holes} as sent by the worker.
   */
  setFrame(state) {
    this.frameState = state;
    this.cleanCache();
  } // setFrame

  /**
   * Fills the frame; RasterEntity calls it only when the cache is dirty.
   * @param {Uint8ClampedArray} data - The RGBA bytes of the frame.
   */
  paintRaster(data) {
    this.render.renderInto(data, this.frameState);
  } // paintRaster

} // GameAreaEntity
