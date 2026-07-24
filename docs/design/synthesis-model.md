# blipsmith — synthesis & control-surface model (DRAFT proposal)

Status: DRAFT. Feeds the v1 PRD once the open decisions below are locked. Authored from synthesis-design fundamentals + the determinism research in the grill session.

## Design principles

1. **Deterministic by construction.** No `libm` transcendentals (`sin`/`cos`/`exp`/`pow`) anywhere that affects output bytes. Oscillators are fixed-point phase accumulators + wavetable lookups. Wavetables and any derived constants (filter coefficients, LFO increments) come from shared deterministic routines or baked tables, never platform `libm`. Compiled with no `-ffast-math`, `-ffp-contract=off`, consistent rounding, denormals handled consistently. Only IEEE-754-mandated ops (`+ - * / sqrt`, explicit `fma`) in the hot path. Result: byte-identical native (x86/ARM) + WASM, proven by a CI byte-equality matrix.
2. **SoundSpec is the single source of truth.** The "virtual synthesizer" is a stateful editing session over an in-memory `SoundSpec` (the patch + composition). Setter verbs mutate it; `render` turns `SoundSpec` + `seed` into PCM. Same spec + seed -> identical bytes. Any session serializes to a `SoundSpec` JSON that can be committed and re-rendered.
3. **Lo-fi is a first-class stage.** Low sample rate (8 / 11.025 / 16 / 22.05 kHz), bit-depth reduction (bitcrush), sample-rate decimation, optional wavefolding. Master bus: loudness limiter + hard clip guard, always on (safety gate).

## Per-voice signal chain

A voice is one sound generator:

- **Oscillator:** waveform in {sine, square, triangle, saw, pulse(duty), noise(white/pink)}. Wavetable-based, fixed-point phase. Fundamental as Hz or MIDI note number.
- **FM (Chowning):** 2-operator (1 modulator -> 1 carrier). Params: `ratio` (mod/carrier freq), `index` (depth). Enough for lo-fi bells, blips, clangs.
- **AM / ring mod:** modulator oscillator over carrier amplitude. Params: `freq` (or ratio), `depth`, `mode` (AM | ring).
- **Envelopes:** one amplitude ADSR (attack/decay/sustain/release, ms + level) + one optional mod-envelope routable to pitch or filter cutoff (the classic "pew" pitch-drop for lasers/jumps/pickups).
- **LFO:** freq, depth, shape, target in {pitch (vibrato), amplitude (tremolo), filter cutoff}.
- **Filter:** LP / HP / BP, cutoff, resonance (deterministic biquad; coefficients computed once per render via shared deterministic math, passed as plain numbers into the hot path).
- **Effects:** distortion / wavefolding, bitcrush, decimation, integer-sample delay, cheap reverb (Schroeder/Freeverb comb+allpass, integer delays + gains).
- **Output:** pan + mix level into the channel bus.

## Composition model (the "5-channel" mixer)

5 channels/tracks, each with gain, pan, and a sequence. Framing: drums + percs + synth voices summed into one mix. Any voice type on any channel (not fixed roles). **Open: whether "5-channel" means 5 mixer tracks summed to a mono/stereo WAV, or 5.0/5.1 surround output channels** (decision D2 below).

Sequencing (decision D3 below): proposed as a per-channel note/event track (MIDI-like: `{time, pitch, velocity, duration, param-overrides}`) with step-sequencer sugar for drums/percs (grid -> events). Tempo (BPM) + swing at the composition level. `record_play` / `stop_record` capture triggered notes into the active channel's track. Minimalist composition (Reich/Glass/Riley phasing, looping cells, additive process) needs no special engine feature: loops + per-channel time offsets from the driving agent are enough.

## Control surface (verbs)

Two layers, reconciled:

- **Stateful synth-session verbs** (the physical-synth metaphor): voice editing (`new_voice`, `select_voice`, `set_waveform`, `set_fundamental`, `set_duration`, `set_intensity`, `set_adsr`, `set_lfo`, `set_fm`, `set_am`, `set_filter`, `add_effect`, `set_lofi`); composition (`select_channel`, `set_tempo`, `set_swing`, `set_channel_gain`, `set_channel_pan`, `add_note` / `set_step`, `record_play` / `stop_record`, `clear_channel`); output (`render`, `play`, `explain_session`, `export_spec`, `import_spec`).
- **Stateless contract verbs:** `render_spec(spec)` (the pure function), `get_schema`, `list_presets`, `load_preset`, `explain_spec`.

**Open: verb granularity** (decision D1) — per-knob micro-verbs (`set_lfo_freq`, `set_lfo_depth`, ...) vs. grouped typed setters (`set_lfo({freq, depth, target})`). Grouped means far fewer MCP tools and a compact schema the driving LLM composes from more reliably; micro-verbs are closer to a literal knob-per-tool physical synth.

## SoundSpec (the contract) — refined field sketch

- `version`, `seed`, `sampleRate`, `channels` (output), `durationMs`
- `master`: `{ gainDb, limiter }`
- `voices[]`: `{ waveform, fundamental, osc params, fm?, am?, ampEnv (adsr), modEnv?, lfo?, filter?, effects[], pan, mixDb, channel }`
- `composition?`: `{ tempoBpm, swing, tracks[5]: { gainDb, pan, notes[] | steps[] } }`
- `meta`: `{ name, tags[], description }`

Typed (pydantic on the Python side; the C++ core takes the validated numeric struct). Bit-identical determinism is a hard invariant.

## Distribution

One C++ core -> native build (pybind11) powers CLI + MCP + pip; WASM build (Emscripten) powers npm. **Open: whether npm/WASM ships *in* v1 or is a fast-follow** (decision D4), with the core built WASM-ready from day one either way.

## Decisions (resolved 2026-07-24, locked in the PRD)

- **D1** verb granularity: **grouped typed setters** (`set_lfo({freq,depth,target})`), ~15-20 tools. Micro-verbs rejected as MCP-surface bloat.
- **D2** "5-channel": **5 mixer tracks summed to stereo**. Surround output is out of scope.
- **D3** sequencing: **MIDI-like note track per channel + step-grid sugar** that compiles down to notes. No `.mid` file I/O.
- **D4** npm/WASM: **v1.1**. Core stays transcendental-free and OS-dependency-free so the WASM build is a build-config exercise.
- **D5** determinism: **bit-identical everywhere confirmed**, accepting the no-`libm` / wavetable / two-platform CI-hash cost. If a stage cannot be made bit-exact, it is cut rather than weakening the invariant.

Additional locks: session state is one implicit session per server process; out-of-range numerics clamp with a warning while structurally invalid input is a typed error; the master bus limits and normalizes to headroom on every render; features are computed in-core with a vendored FFT; renders emit `{name}.wav` plus a `{name}.spec.json` sidecar.

Full spec: `docs/prd/blipsmith-v1.md` (Status: DEFINED).
