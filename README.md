# blipsmith

An agent-playable lo-fi synthesizer. A C++ DSP core renders sound effects from a
JSON `SoundSpec`, deterministically. An LLM never generates a sample: it turns
the knobs.

There is no model inside this tool. An agent drives it over MCP the way it would
drive a physical synth, one typed setter at a time, and a human drives the same
engine from a terminal. Both paths run the same code and produce the same bytes.

**Same spec, same seed, identical WAV. Every time, on every supported platform.**
That is the contract the whole design serves, and CI proves it by rendering 56
golden specs on Linux x86_64 and macOS arm64 and comparing SHA-256 sets.

## Install

Needs Python 3.11+ and a C++17 compiler. CMake and Ninja come from PyPI through
the isolated build environment, so no system CMake is required.

```bash
git clone https://github.com/jiramos87/blipsmith.git
cd blipsmith
uv sync
```

`uv sync` builds the native core and creates `.venv`. After editing anything
under `core/`, rebuild with `uv sync --reinstall-package blipsmith`; Python
sources are an editable install and need no rebuild.

There is no pure-Python fallback. If the compiled core is missing, `import
blipsmith` fails immediately with the rebuild command, rather than quietly
rendering something else.

## Loop 1: the agent (MCP)

Register the server, which speaks stdio:

```bash
claude mcp add blipsmith -- uv run --project /path/to/blipsmith blipsmith-mcp
```

Then ask for a sound. The agent holds one session, shaped like a synth front
panel: 39 tools, grouped so that one call sets one block of related parameters.

> **You:** Make me a laser shot, but heavier and dirtier than the stock one.

The agent starts from a preset rather than from silence, then edits:

```
list_presets()          -> 13 presets, sfx and drum families
load_preset("laser")    -> the session adopts it
explain_session()       -> "260 ms, mono at 22050 Hz, seed 0. Voice 1: a bright
                           saw at 440 Hz that starts instantly and drops away,
                           through a mod envelope sweeping pitch down to the
                           fundamental over 90 ms, a lowpass filter at 6000 Hz
                           and a 8-bit crush. ..."
set_fundamental(hz=220) -> an octave lower
set_filter(type="lowpass", cutoffHz=1800, resonance=6)
set_lofi(bitDepth=5, decimation=3)
set_effects([{"kind": "distortion", "drive": 0.7}])
render(name="heavy-laser")
```

The render comes back with both files, a plain-language explanation, and eight
measurements:

```json
{
  "status": "rendered_ok",
  "wavPath": "blipsmith-out/heavy-laser.wav",
  "specPath": "blipsmith-out/heavy-laser.spec.json",
  "explanation": "260 ms, mono at 22050 Hz, seed 0. Voice 1: a bright saw at 220 Hz that starts instantly and drops away, through a mod envelope sweeping pitch down to the fundamental over 90 ms, a lowpass filter at 1800 Hz with resonance, a 5-bit crush and 3x decimation and distortion at 70% drive. The master bus normalizes the mix to -1 dBFS.",
  "features": {
    "durationMs": 260.0,
    "peakDbfs": -1.0,
    "rmsDbfs": -8.79,
    "estimatedFundamentalHz": 1817.94,
    "spectralCentroidHz": 3390.48,
    "attackTimeMs": 6.26,
    "integratedLufs": -7.58,
    "truePeakDbtp": 0.3
  },
  "warnings": []
}
```

The features are the point (rounded above; the tool returns full precision). The
agent cannot hear, so it steers by numbers: too bright means lower
`spectralCentroidHz`, too soft an onset means shorter `attackTimeMs`.
`integratedLufs` and `truePeakDbtp` read loudness the way a broadcast meter does
(ITU-R BS.1770, 4x oversampled peak); a true peak a little above the sample peak
is normal and is why a file meant for a lossy encoder wants some headroom. One
caveat worth knowing: `estimatedFundamentalHz` measures the whole file at once,
so on a voice with a pitch sweep like this one it lands somewhere in the sweep
rather than on the fundamental you set. It is a reliable number for steady tones
and a directional one for sweeps.

Out-of-range values clamp and say so in `warnings`; an unknown enum is refused
outright with the valid values listed, and the session is left exactly as it was.

Every session serializes losslessly. `export_spec()` gives a `SoundSpec` that
renders the same bytes through the CLI, which is what makes the next loop work.

## Loop 2: the human (CLI)

A spec is a plain JSON file you can write by hand, commit, and re-render years
later. Nothing in the CLI knows anything the MCP server does not.

```bash
cat > blip.spec.json <<'JSON'
{
  "version": 1,
  "seed": 7,
  "durationMs": 220,
  "meta": { "name": "blip", "description": "A short arcade blip." },
  "voices": [
    {
      "waveform": "square",
      "fundamentalHz": 660,
      "ampEnv": { "attackMs": 1, "decayMs": 60, "sustainLevel": 0.25, "releaseMs": 90 },
      "filter": { "type": "lowpass", "cutoffHz": 4000, "resonance": 1.5 },
      "lofi": { "bitDepth": 8, "decimation": 2 }
    }
  ]
}
JSON

blipsmith render blip.spec.json
```

```
blipsmith-out/blip.wav
blipsmith-out/blip.spec.json
  220 ms | peak -1.0 dBFS | rms -11.8 dBFS | f0 653 Hz | centroid 3375 Hz | attack 1.6 ms
```

Two files land: the audio, and the sidecar that reproduces it. Render the
sidecar and you get the same WAV back, byte for byte.

The rest of the surface:

```bash
blipsmith presets                        # the 13 shipped starting points
blipsmith render --preset kick           # render one straight from the library
blipsmith vary blip.spec.json -n 5       # five seeded variations, each with its own sidecar
blipsmith batch sounds/                  # every *.spec.json in a folder, with a summary
blipsmith explain blip.spec.json         # what the spec says, in words, without rendering
blipsmith verify-golden                  # re-render the corpus and compare hashes
```

Output goes to `--out-dir`, else `$BLIPSMITH_OUT_DIR`, else `./blipsmith-out`.
An existing file is never overwritten without `--overwrite`. Exit code is 0 when
everything asked for happened and 1 when any of it did not.

## What you can build

One spec is either a **one-shot** (up to 8 voices, all starting together, mono
22050 Hz by default) or a **composition** (five mixer tracks of notes or painted
step grids, with tempo and swing, stereo by default). Sample rates are 8000,
11025, 16000, 22050 and 44100 Hz; output is always 16-bit PCM.

Per voice: sine, square, triangle, saw, pulse with duty, white or pink noise;
pitch in hertz or as a MIDI note; an amplitude ADSR; an optional mod envelope to
pitch or cutoff; an LFO; 2-operator FM; AM or ring modulation; a resonant
lowpass, highpass or bandpass filter; bit-depth crush and sample decimation;
distortion, wavefolding, delay and reverb; then pan and mix level into a track.

A master limiter and hard clip guard run on every render and normalize to
-1.0 dBFS. No field can switch them off, which is why nothing this tool emits
can clip.

`get_schema()` returns every field with its type, range and default, so an agent
can author a valid spec without guessing.

### The music mode

`"version": 2` turns a composition into a whole piece in one render. Everything
above still holds, and a spec without it renders exactly as it always has.

- **Any number of tracks**, 1 to 32, each with an optional `name`, and up to 64
  voices.
- **A kit on one track.** A voice with a `key` (a MIDI note) plays only the
  notes of that key, at its own pitch, so a kick, a snare and two hats share one
  track and one drum part. Voices without a key play every note, as before.
- **Effects with tails.** A voice's own effects run once over all its notes, so
  an echo rings past the note that made it. A track has its own stereo
  `effects`, and `master.effects` (delay and reverb) is the room every track
  shares.
- **The loop.** With `"loop": true` the file is exactly `durationMs`: every
  release and every effect tail that runs past the end is wrapped onto the
  start, so the file plays round without a seam.
- **Stems** from the same render, one WAV per track at the same gain as the mix,
  adding up to it: `render --stems`, or `stems=true` on the MCP `render`.

For a program, the same render is a library call, with no files and no text to
parse:

```python
from blipsmith import render_sound

sound = render_sound(spec, stems=True)
sound.wav, sound.features["integratedLufs"], [stem.wav for stem in sound.stems]
```

and `blipsmith render piece.spec.json --json` prints the result as one JSON
object. The behaviour is specified in `docs/prd/blipsmith-music-mode.md`.

### Expressive notes

Three optional blocks on a music-mode voice give each note expression. A voice
without them plays exactly as before.

- **Touch.** Velocity changes the tone, not only the level: per unit of velocity
  above `pivot`, the FM index moves by `fmIndex`, the cutoff by `cutoffOctaves`
  and the attack shortens by `attackOctaves`. A harder note is brighter and
  sharper; at the pivot the voice plays as written.
- **Glide.** Each note slides in from the previous note's pitch over `timeMs`:
  in `legato` mode only when the previous note is still held, in `always` mode
  from any. Kit voices do not glide.
- **Late vibrato.** Nothing for `delayMs` from the note's start, then a vibrato
  of `depthCents` at `rateHz` fades in over `fadeMs`, so a held note blooms.

The MCP verbs are `set_touch`, `set_glide` and `set_vibrato`. The behaviour is
specified in `docs/prd/blipsmith-expressive-notes.md`.

### Four-operator FM

A music-mode voice can trade its oscillator for four sine operators, the
architecture behind the classic FM electric pianos, bells, brass and basses. A
voice without it plays exactly as before, and the two-operator `fm` block is
unchanged.

- **Operators.** Each runs at `ratio` times the note's pitch (so glide and
  vibrato move it) or at a `fixedHz`, with a `detuneCents`, a `level` (loudness
  for a carrier, depth for a modulator: 1 is 4 pi radians) and its own attack,
  decay and sustain. The voice's amp envelope carries the release.
- **Algorithms.** `algorithm` 0 to 7 is the classic set: 0 one stack
  1 > 2 > 3 > 4, 1 (1 + 2) > 3 > 4, 2 (1 + (2 > 3)) > 4, 3 ((1 > 2) + 3) > 4,
  4 two pairs (1 > 2) + (3 > 4), 5 1 into each of 2, 3 and 4, 6 (1 > 2) + 3 + 4,
  7 four carriers. The carriers are summed and divided by their count.
- **Feedback.** Operator 1 can modulate itself by `feedback` (1 is pi radians),
  through the mean of its last two outputs, which keeps it stable at any
  setting.
- **Touch** reaches the modulators: `fmIndex` deepens each in proportion to its
  level, so a harder note is brighter.

The MCP verbs are `set_fm4` and `set_operator`. The behaviour is specified in
`docs/prd/blipsmith-fm4.md`.

### Plucked and struck strings

A music-mode voice can trade its oscillator for a string: a Karplus-Strong loop
that is set ringing once per note and then loses its highs and dies away on its
own, the sound of a guitar, a harp, a plucked bass, a dulcimer or a piano
string. A voice without it plays exactly as before.

- **Excitation.** `pluck` fills the string with a burst of the voice's seeded
  noise; `strike` hits it with a hammer, which sets it moving rather than bending
  it. `position` (0.02 to 0.5) is where along the string: near the end is thin
  and bright, the middle hollow.
- **Tone.** `brightness` (0 to 1) is how hard and bright the pluck or hammer is,
  `damping` (0 to 1) how much faster the high partials die than the fundamental,
  `decayMs` how long the string takes to fall 60 dB. `body` mixes in a resonance
  at `bodyHz`.
- **Stable by construction.** The loop is a centred Lagrange read, a symmetric
  loss filter and a gain below 1, each with a gain of at most 1, so every legal
  setting dies away. The pitch is read every frame, so glide, vibrato and the
  pitch modulators move the string.
- **Touch** reaches the brightness: `cutoffOctaves` moves it in octaves, so a
  harder note is a harder pick. The amp envelope's release mutes the string.

The MCP verb is `set_string`. The behaviour is specified in
`docs/prd/blipsmith-strings.md`.

### Modal banks: skins, cymbals, wood

A music-mode voice can trade its oscillator for a modal bank: up to sixteen
tuned resonators struck once per note, each ringing at its own frequency and
dying at its own pace. That is how a drum skin, a cymbal, a wood block or a
mallet bar sounds, and what the oscillators cannot make. A voice without it
plays exactly as before.

- **Modes.** Each mode has a `ratio` to the voice's pitch (0.1 to 32), a
  `level` and a `decayMs` (the time it takes to fall 60 dB). A skin rings near
  the Bessel ratios 1, 1.59, 2.14, 2.30, 2.65; a cymbal at many close,
  inharmonic ratios with long decays.
- **Strike.** `brightness` (0 to 1) sets how hard and bright the strike is: a
  soft mallet rings only the low modes, a hard stick rings them all.
- **Stable by construction.** Each mode is a point turned by its angle and
  shrunk by its decay every frame, the shrink held below 1, so every legal
  setting dies away. A turn keeps the point's size, so a pitch drop, a glide or
  vibrato moves the modes without the level jumping.
- **On a kit** the bank plays the voice's own pitch on every hit; noise voices
  on the same key add a slap, a crack or a wash. **Touch** reaches the
  brightness through `cutoffOctaves`, so a ghost note is darker, not only
  quieter.

The MCP verb is `set_modal`. The behaviour is specified in
`docs/prd/blipsmith-drum-kit-two.md`.

## Determinism, and how it is enforced

The audio path uses fixed-point phase accumulators and baked wavetables, with no
`libm` transcendentals anywhere that affects output bytes: no `sin`, `cos`,
`exp`, `pow`, not even once per render for filter coefficients or decibel
conversions. IEEE-754 guarantees `+ - * / sqrt fma` exactly; everything else is a
platform's choice of approximation, and a spec that renders differently on two
machines is worthless as a build artifact.

That invariant is enforced, not just intended:

- `scripts/check_no_libm.py` reads the compiled core's undefined symbols and
  fails the gate on any transcendental. The test suite builds a probe that calls
  `sin()` and asserts the check rejects it, so the gate is known to be able to
  fail.
- `-ffp-contract=off`, no fast-math, C++17, pinned in `CMakeLists.txt`.
- 56 golden specs cover every waveform, every processing stage and every preset
  archetype. Each one asserts its recorded hash, non-clipping output, and a peak
  at the normalization target.
- CI renders that corpus on Linux x86_64 and macOS arm64 and diffs the hash
  manifests. A single diverging byte fails the build.

Run the whole gate locally:

```bash
./scripts/verify.sh
```

Seven steps: clean native build, ruff, mypy, pytest, the no-libm check, CLI boot,
MCP boot. Every step runs even after one fails, and the summary reports each one
honestly.

## License

MIT. Everything audible is synthesized from first principles; no sample library
or third-party DSP code is vendored, so the audio you render is yours with no
attribution owed.

Runtime dependencies are `pydantic` (MIT) and the official `mcp` SDK (MIT), which
transitively brings `certifi` (MPL-2.0), `python-multipart` (Apache-2.0) and
`typing-extensions` (PSF-2.0). Build-time only: `pybind11` (BSD-3),
`scikit-build-core` (Apache-2.0), CMake and Ninja. All permissive; none of them
constrain an MIT release.
