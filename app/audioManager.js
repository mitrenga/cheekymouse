const { AbstractAudioManager } = await import('./svision/js/audio/abstractAudioManager.js?ver='+window.srcVersion);
const { AudioOscillatorHandler } = await import('./svision/js/audio/audioOscillatorHandler.js?ver='+window.srcVersion);
const { Tool } = await import('./svision/js/tool.js?ver='+window.srcVersion);
const { createHammerSampleScore, createMelodySampleScore } = await import('./soundEffects.js?ver='+window.srcVersion);
// begin code

/**
 * Audio manager — M1 skeleton. Two buses ('sounds', 'music') on the svision
 * AudioOscillatorHandler, used only by the menu volume dialogs for now. M5
 * replaces the 'sounds' bus with the synthesis of the nine discrete circuits
 * of the original sound board (frequencies in sources/docs/hw_notes.md), fed
 * every frame from frame.soundBoard, and adds the tune the CPU bit-bangs on
 * port 40h d7. The menu never opens a bus; the volume dialogs and the game do
 * (MM pattern).
 */
var EFFECT_BUSES = ['sounds'];

export class AudioManager extends AbstractAudioManager {

  constructor(app) {
    super(app);
    this.id = 'AudioManager';
    this.volume = {};
    this.volume.sounds = Math.min(10, Math.max(0, Math.round(Number(Tool.readCookie('audioBusSoundsLevel', 7)))));
    this.volume.music = Math.min(10, Math.max(0, Math.round(Number(Tool.readCookie('audioBusMusicLevel', 7)))));
    this.latencyHint = 'interactive';
  } // constructor

  static get effectBuses() {
    return EFFECT_BUSES;
  } // effectBuses

  // the user level a bus follows
  volumeKey(bus) {
    return (bus === 'music') ? 'music' : 'sounds';
  } // volumeKey

  createAudioHandler(bus, options) {
    return new AudioOscillatorHandler(this.app);
  } // createAudioHandler

  volumeFactor(volume) {
    var levels = [0, 0.005, 0.01, 0.02, 0.04, 0.07, 0.1, 0.14, 0.18, 0.23, 0.29];
    return levels[volume]/levels[10];
  } // volumeFactor

  openBus(bus, options) {
    super.openBus(bus, options);
    this.refreshVolume(bus);
    this.muteBus(bus, ('muted' in options) ? options.muted : false);
  } // openBus

  refreshVolume(bus) {
    var handler = this.buses[bus];
    if (handler === undefined) {
      return;
    }
    handler.setBusVolume(this.volumeFactor(this.volume[this.volumeKey(bus)]));
  } // refreshVolume

  // muting 'sounds' mutes every effect bus
  muteBus(bus, muted) {
    if (bus === 'sounds') {
      EFFECT_BUSES.forEach((b) => super.muteBus(b, muted));
      return;
    }
    super.muteBus(bus, muted);
  } // muteBus

  /**
   * One worker frame (frame.soundBoard, WORKER-PROTOCOL.md) — the nine trigger
   * lines of the original board. M1: nothing to play yet; M5 feeds the
   * synthesis here. Never throws.
   */
  playFrame(frame) {
  } // playFrame

  audioData(bus, sound, options) {
    var data = super.audioData(bus, sound, options);
    if (data !== false) {
      return data;
    }
    switch (sound) {
      case 'exampleHammerSound': return createHammerSampleScore();
      case 'exampleMelodySound': return createMelodySampleScore(false);
    }
    return false;
  } // audioData

} // AudioManager
