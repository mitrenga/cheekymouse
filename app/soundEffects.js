// begin code

/**
 * Cheeky Mouse sound data — M1 placeholder.
 *
 * The board has no sound processor: nine logic lines gate 555/556 oscillators,
 * an LM324 and a noise transistor (sources/mame/nl_cheekyms.cpp). The measured
 * component values give the frequencies below — see sources/docs/hw_notes.md,
 * which M5 turns into the real Web Audio synthesis:
 *
 *   hammer      ~480 Hz square, gated, ~100 ms envelope
 *   mouse       ~1.05 kHz with a downward pitch sweep (~47 ms)
 *   pest        ~1.05 kHz warbled by a ~16 Hz LFO
 *   mouse dies  ~2.15 kHz with a fast sweep
 *   pest dies   ~460 Hz plain tone
 *   coin/extra  ~1.52 kHz plain tone
 *   cheese      filtered white noise
 *   music       a one-bit square wave the CPU toggles itself — the notes can
 *               only come from the disassembly (M0)
 *
 * Until then the menu volume dialogs need two samples for the svision
 * AudioOscillatorHandler: the hammer swing (SOUNDS) and a few bars of a square
 * wave tune (MUSIC). The hammer already uses its measured 480 Hz; the tune is
 * provisional.
 */

var TICKS_PER_BEAT = 4;

var INSTRUMENTS = {
  lead: {
    class: 'OscillatorInstrument',
    osc: [{type: 'square'}],
    filter: {type: 'lowpass', freq: 4000, Q: 0.7},
    env: {attack: 0.005, decay: 0.25, sustain: 0.6, release: 0.05},
    gain: 0.25
  },
  bass: {
    class: 'OscillatorInstrument',
    osc: [{type: 'square'}],
    filter: {type: 'lowpass', freq: 1800, Q: 0.7},
    env: {attack: 0.005, decay: 0.3, sustain: 0.5, release: 0.05},
    gain: 0.2
  },
  // the hammer 556: R18 1k, R19 150k, C14 10nF -> ~480 Hz, decay ~100 ms
  hammer: {
    class: 'OscillatorInstrument',
    osc: [{type: 'square'}],
    env: {attack: 0.002, decay: 0.1, sustain: 0.0},
    gain: 0.3
  }
};

/**
 * A bar of "pitch:durTicks" tokens (rest "-:n"), placed sequentially. A pitch
 * is either a note name (C4, A#4) or a plain frequency in Hz — the circuits of
 * the original are measured in hertz, not in notes.
 */
function bar(tokens) {
  var notes = [], tick = 0;
  tokens.split(' ').forEach(function(tok) {
    var parts = tok.split(':');
    var dur = parseInt(parts[1] || '4', 10);
    if (parts[0] !== '-') {
      var pitch = /^[0-9]+$/.test(parts[0]) ? parseInt(parts[0], 10) : parts[0];
      notes.push({tick: tick, pitch: pitch, dur: dur});
    }
    tick += dur;
  });
  return notes;
} // bar

/** SOUNDS volume sample: one hammer swing at the measured 480 Hz, ~0.1 s */
export function createHammerSampleScore() {
  return {
    tempo: 240, beatsPerBar: 4, volume: 0.6, defaultDuration: TICKS_PER_BEAT,
    instruments: INSTRUMENTS,
    tracks: [{instrument: 'hammer', pattern: [bar('480:2 -:14')]}],
    repeat: false
  };
} // createHammerSampleScore

/** MUSIC volume sample: four bars in 4/4 (placeholder for the original tune) */
export function createMelodySampleScore(repeat) {
  var lead = [
    'E5:2 E5:2 -:2 E5:2 -:2 C5:2 E5:4',
    'G5:8 -:8',
    'C5:6 G4:6 E4:4',
    'A4:4 B4:4 A#4:2 A4:6'
  ];
  var bass = [
    'D3:2 D3:2 -:2 D3:2 -:2 D3:2 D3:4',
    'G3:8 -:8',
    'G3:6 E3:6 C3:4',
    'F3:4 G3:4 F#3:2 F3:6'
  ];
  return {
    tempo: 150, beatsPerBar: 4, volume: 0.5, defaultDuration: TICKS_PER_BEAT,
    instruments: INSTRUMENTS,
    tracks: [
      {instrument: 'lead', pattern: lead.map(bar)},
      {instrument: 'bass', pattern: bass.map(bar)}
    ],
    repeat: (repeat === undefined) ? true : repeat
  };
} // createMelodySampleScore
