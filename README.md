# blipsmith

An agent-playable lo-fi synthesizer. A C++ DSP core renders sound effects from a
JSON `SoundSpec`, deterministically. An LLM never generates a sample: it turns
the knobs.

There is no model inside this tool. An agent drives it over MCP the way it would
drive a physical synth, one typed setter at a time, and a human drives the same
engine from a terminal. Both paths run the same code and produce the same bytes.

**Same spec, same seed, identical WAV. Every time, on every supported platform.**
That is the contract the whole design serves, and CI proves it by rendering 35
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
panel: 30 tools, grouped so that one call sets one block of related parameters.

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

The render comes back with both files, a plain-language explanation, and six
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
    "attackTimeMs": 6.26
  },
  "warnings": []
}
```

The features are the point (rounded above; the tool returns full precision). The
agent cannot hear, so it steers by numbers: too bright means lower
`spectralCentroidHz`, too soft an onset means shorter `attackTimeMs`. One
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
- 35 golden specs cover every waveform, every processing stage and every preset
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
