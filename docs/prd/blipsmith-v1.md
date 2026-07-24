# PRD: blipsmith v1 — an agent-playable lo-fi synthesizer

Status: DEFINED. Grilled 2026-07-24 from `docs/idea.md`. Behavior only; the implementer owns architecture within the invariants below.

Scope cut: M0-M3 of the idea doc (deterministic engine, lo-fi/FX/sequencer, preset library, MCP + CLI surfaces). M4-M6 are follow-on PRDs.

## Why

Game and app builders need short lo-fi sound effects and musical elements without sample licensing, a sound designer, or a generative audio model. Coding agents cannot produce audio at all, and generative audio models are non-deterministic, opaque, and license-murky. blipsmith gives an agent a real instrument it plays like a physical synth: grouped parameter verbs in, deterministic audio out, same spec and seed producing identical bytes on every platform. The sound is reproducible, diff-able, and free of sample-library exposure.

## User experience (the loop)

Two consumers, one contract.

**The driving agent (MCP).** An external LLM agent (Claude Code today) treats the server as a synthesizer sitting on the desk. It calls `get_schema` and `list_presets` to learn the instrument, loads a preset as a starting point, then shapes the sound with grouped setters (waveform, fundamental, envelope, FM, AM, LFO, filter, lo-fi, effects). It renders. Because it cannot hear, the render call returns a WAV path plus a plain-language explanation plus deterministic acoustic features (peak, RMS, estimated fundamental, brightness, attack time). The agent compares those numbers to what it wanted, adjusts, and renders again. When satisfied it exports the spec, and the asset lands in the consuming project as `{name}.wav` beside `{name}.spec.json`.

**The human (CLI).** No LLM anywhere. The human hand-edits a `.spec.json`, renders it, batches a folder, emits N seeded variations, prints an explanation, and verifies golden hashes. This is the reproducible backbone: everything the agent can produce, a human can re-render byte-for-byte from the committed spec.

**Composition.** The session carries five mixer tracks, each with gain, pan, and a note track. The agent sets tempo and swing, places notes (or paints a step grid for drums and percussion), and renders the mix down to stereo. Drums, percussion, bass, and lead coexist; any voice type can sit on any track. Looping cells and per-track offsets are enough to build minimalist, phase-shifted material without any special engine feature.

## Inputs & outputs (the contract)

**Inputs**

- A `SoundSpec` document: `version`, `seed`, `sampleRate`, `channels`, `durationMs`, `master` (gain, limiter), `voices[]`, optional `composition` (tempo, swing, five tracks of notes/steps), `meta` (name, tags, description).
- Or a sequence of session verbs that mutate the server's in-memory `SoundSpec`: voice editing, composition editing, and output verbs. One implicit session per server process.
- A voice carries: waveform (sine, square, triangle, saw, pulse with duty, white/pink noise), fundamental (Hz or MIDI note), amplitude ADSR, optional modulation envelope routed to pitch or cutoff, optional LFO (rate, depth, shape, target), optional 2-operator FM (ratio, index), optional AM/ring modulation (rate, depth, mode), filter (LP/HP/BP with cutoff and resonance), lo-fi stage (bit depth, decimation), effects (distortion/wavefold, delay, reverb), pan, mix level, and track assignment.
- Every numeric parameter has a documented valid range.

**Outputs**

- A WAV file written to a configurable output directory, plus a sidecar `{name}.spec.json` that regenerates it exactly. Inline base64 audio is available on request.
- A plain-language explanation of what the spec will sound like.
- Deterministic acoustic features measured from the rendered PCM: `durationMs`, `peakDbfs`, `rmsDbfs`, `estimatedFundamentalHz`, `spectralCentroidHz`, `attackTimeMs`.
- A `warnings[]` list naming every parameter that was clamped, with the requested and applied values.

**Result states**

- `rendered_ok` — audio produced, no clamps.
- `rendered_with_warnings` — audio produced, one or more parameters clamped.
- `invalid_spec` — structurally invalid input (unknown enum value, missing required field, wrong type, unsupported `version`, malformed JSON). No audio, no state change, error names the offending field and the valid set.
- `render_failed` — an environment failure (core unavailable, output path not writable). No audio, actionable message.

Defaults: one-shots render mono at 22.05 kHz / 16-bit; compositions render stereo at 22.05 kHz / 16-bit. All overridable per render. Omitted `seed` defaults to `0`.

## Acceptance (Given / When / Then)

**Happy path**

- Given a valid spec and seed, When rendered twice on the same machine, Then the two WAV files are byte-identical.
- Given the same spec and seed, When rendered on Linux x86_64 and on macOS arm64, Then both WAV files hash to the same value.
- Given a fresh session, When the agent calls `get_schema`, Then it receives the full `SoundSpec` schema with every field's type, valid range, and default, sufficient to author a valid spec without further discovery.
- Given a fresh session, When the agent calls `list_presets`, Then it receives the authored archetypes (game SFX plus a lo-fi drum kit) with names, tags, and one-line descriptions.
- Given a loaded preset, When the agent applies grouped setters (envelope, FM, filter, lo-fi) and renders, Then a WAV is written to the output directory and the result carries the path, an explanation, and the acoustic features.
- Given a rendered sound, When the agent exports the spec and a human later renders that sidecar file through the CLI, Then the output is byte-identical to the agent's render.
- Given a composition with notes on five tracks, tempo, and swing, When rendered, Then a stereo WAV containing all five tracks mixed at their track gains and pans is produced.
- Given a step pattern painted on a drum track, When rendered, Then it produces the same audio as the equivalent explicit note list at the same tempo and swing.
- Given any spec whose voices sum above full scale, When rendered, Then the master limiter prevents clipping and the output peak is normalized to the target headroom.
- Given a spec file and a variation count N, When the CLI is asked for variations, Then N specs and N WAVs are emitted, each reproducible from its own seed.
- Given a folder of spec files, When the CLI batch-renders it, Then every spec produces its WAV and a summary reports per-file success or failure.

**Edge cases and failure modes**

- Given a duration at or below zero, When set, Then it is clamped to the documented minimum and a warning names the clamp.
- Given a duration above the documented maximum (one-shot and composition limits differ), When set, Then it is clamped to that maximum with a warning.
- Given a filter cutoff at or above Nyquist for the render sample rate, When rendered, Then it is clamped below Nyquist with a warning; given a cutoff at or below zero, Then it is clamped to the documented minimum with a warning.
- Given any other numeric parameter outside its documented range (envelope times, LFO rate/depth, FM index/ratio, resonance, gains, pan, bit depth, decimation factor), When set, Then it is clamped to the nearest bound and a warning records requested and applied values.
- Given an unknown waveform, preset name, filter type, or LFO target, When set, Then the call fails with `invalid_spec`, the session state is unchanged, and the error lists the valid values.
- Given a spec whose `version` is unsupported, When loaded, Then it fails with `invalid_spec` naming the supported version. Given malformed JSON, Then it fails the same way.
- Given a session with no voices, When rendered, Then it fails with `invalid_spec` rather than emitting silence.
- Given a request to add a voice beyond the documented maximum voice count, When issued, Then it fails with `invalid_spec` naming the limit; the existing voices are untouched.
- Given a track with zero notes, When the composition renders, Then that track contributes silence and the render succeeds.
- Given two notes at the same time, pitch, and duration on the same track, When rendered, Then the duplicate is dropped with a warning (an exact double-trigger is treated as an authoring mistake, not a doubling of amplitude).
- Given overlapping notes at different pitches on one track, When rendered, Then they sum polyphonically, subject to the master limiter.
- Given a note placed beyond the composition end, When rendered, Then it is dropped with a warning.
- Given an output directory that does not exist, When rendering, Then it is created. Given a directory that is not writable, Then the render fails with `render_failed` and an actionable message.
- Given an existing file at the target path, When rendering without an explicit overwrite flag, Then the render fails rather than silently replacing the asset; with the flag, it overwrites.
- Given a noise voice, When rendered twice with the same spec and seed, Then both renders are byte-identical (noise is seeded deterministically from the spec seed and voice index).
- Given the compiled core is missing or fails to load, When the CLI or MCP server starts, Then it fails fast with an actionable message and never falls back to a substitute implementation (a fallback would break byte-identity).

## Quality bar

- A one-second mono one-shot at 22.05 kHz renders in under 50 ms on dev hardware; a 30-second five-track composition renders in under 2 seconds.
- Verify gate, all green before any ship: lint (ruff), typecheck (mypy or pyright), tests (pytest), native core build (CMake), golden-render byte-equality on both CI platforms, CLI boot, MCP server boot.
- Golden-render corpus covers at least one render per preset archetype and one per processing stage (bitcrush, decimate, filter, distortion/wavefold, delay, reverb, FM, AM, LFO, mod-envelope).
- Every golden render is asserted non-clipping: no sample exceeds full scale, and peak sits at the normalization target within tolerance.
- The audio path contains no `libm` transcendental calls, enforced by an automated check rather than by convention.
- Every MCP tool has a published schema and at least one integration test exercising it.
- Out-of-range handling is tested on both sides of every documented numeric bound.
- README shows both loops end to end: an agent-driven session and a hand-authored spec rendered from the CLI.

## Out of scope

- Any LLM inside the tool. v1 is driven entirely by an external agent; an API-driven natural-language layer is a later version.
- Reference imitation, librosa, CLAP, and any audio-ML dependency (M4).
- The audio eval harness: embedding similarity, spectrogram LLM-judge, CI quality gate (M5).
- Fine-tuning, RAG over a recipe corpus, voice input (M6).
- The npm/WASM package. The core stays free of platform and OS dependencies so the WASM target is a later build-configuration exercise, not a rewrite (v1.1).
- Live audio-device playback. "Play" means render to a file and return its path.
- Surround or 5.1 output. Five mixer tracks sum to stereo.
- `.mid` file import or export. Notes are MIDI-like internally; no MIDI file I/O.
- `vary_sound` by embedding neighborhood and `match_reference` as MCP tools. CLI seeded variations cover the v1 need.
- PyPI and npm publication. v1 delivers CI-built wheels installable locally; publishing is a follow-on decision.

**Invariants** — must not change:

- Same `SoundSpec` plus same `seed` produces identical bytes, on every supported platform.
- The master limiter and hard clip guard run on every render and cannot be disabled.
- The engine never calls an LLM and never emits audio samples chosen by one.
- Everything is synthesized. No sample libraries, ever.
- `SoundSpec` is the only source of truth; any session serializes to it losslessly.
- No `libm` transcendental functions in the audio path.

## Dependencies

Each pinned with approach, fallback, cost, and whether it runs at build time or runtime.

- **C++ core toolchain** — C++17 built by CMake, bound to Python with pybind11 (BSD), packaged via scikit-build-core, wheels built per platform by cibuildwheel. Fallback: none required, all standard and permissive. Cost: free. Build time only.
- **Cross-platform bit-exactness** — IEEE-754 mandates only `+ - * / sqrt fma`; `sin`/`cos`/`exp` are per-platform library routines and differ bit-for-bit, and WASM treats them the same way. Approach: fixed-point phase accumulators with wavetable lookup, all derived constants (filter coefficients, phase increments, envelope curves) computed by shared deterministic routines or baked tables, compiled with no fast-math and no FP contraction. Fallback: if a stage proves impossible to make bit-exact, it is cut from v1 rather than weakening the invariant. Runtime behavior, enforced at build and in CI.
- **FFT for acoustic features** — vendored kissfft (BSD-3) inside the core. Fallback: a hand-rolled radix-2 FFT. Cost: free, license-clean. Runtime.
- **WAV encoding** — written directly by the core as canonical PCM WAV, no libsndfile. Keeps output bytes under our control and the dependency count at zero. Fallback: `soundfile`, at the cost of trusting a third party with byte-level output. Runtime.
- **MCP transport** — official Python MCP SDK over stdio. Fallback: raw JSON-RPC over stdio. Cost: free. Runtime.
- **Schema and validation** — pydantic on the Python side; the core receives an already-validated numeric structure. Runtime.
- **CI** — GitHub Actions, `ubuntu-latest` (x86_64) plus `macos-latest` (arm64), both on the free tier. The determinism gate compares golden hashes across both. Build time.
- **LLM** — none at runtime. Cost: $0. The driving agent is supplied by the consumer.
- **Licensing** — MIT, public from the first commit. Every dependency is MIT or BSD. No sample content of any kind.

## Success metric

A driving agent, given a fixed brief set of 12 game SFX and 2 short musical loops with no human parameter tweaking, produces assets Javier judges acceptable for at least 80% of briefs within a maximum of 3 render iterations each. Every render in that run must also pass the technical gates (deterministic, non-clipping, spec round-trips).

## Done looks like

A public MIT repo whose C++ core renders lo-fi one-shots and five-track compositions byte-identically on Linux and macOS, driven either by an external agent through a grouped-verb MCP surface with text and acoustic feedback, or by a human through a deterministic CLI, with every asset regenerable from its committed spec.

## Scope changes (living log)

- 2026-07-24: LLM moved out of the tool - dropped - the idea doc put NL->SoundSpec inside blipsmith (`describe_sound`); the tool is now a pure instrument driven by an external agent, with an API-driven LLM layer deferred to a later version.
- 2026-07-24: engine language changed from numpy/Python to C++ via pybind11 - added - Python keeps MCP, CLI, schema, and packaging; the DSP core is native and WASM-ready.
- 2026-07-24: determinism raised from per-platform to bit-identical everywhere - promoted - forces a transcendental-free, wavetable-and-fixed-point audio path, verified by a two-platform CI hash gate.
- 2026-07-24: MCP surface reframed from spec-in/audio-out to a stateful synth session - added - grouped typed setters over one implicit session, plus stateless `render_spec`, `get_schema`, `list_presets`, `explain_spec`.
- 2026-07-24: composition model added (5 mixer tracks to stereo, MIDI-like note tracks with step sugar, tempo and swing) - added - the idea doc only sketched `pattern`; music composition is now a first-class v1 capability.
- 2026-07-24: acoustic-feature feedback added to every render - added - the driving agent cannot hear, so it needs deterministic numbers to steer by; computed in-core, no librosa.
- 2026-07-24: `vary_sound` and `match_reference` dropped from the v1 tool surface - deferred - CLI seeded variations cover v1; embedding-space work belongs with M4.
- 2026-07-24: scope cut to M0-M3 - deferred - M4 imitation, M5 audio evals, and M6 fine-tuning/RAG/voice become separate PRDs.
- 2026-07-24: npm/WASM moved out of v1 - deferred - the core is built WASM-ready from day one, but the package ships in v1.1.
- 2026-07-24: exact duplicate notes deduplicated with a warning, and renders refuse to overwrite an existing file without an explicit flag - added - assumptions made while filling the edge-case sweep; both are reversible if they prove annoying in practice.
- 2026-07-24: WAV written by the core rather than through libsndfile - added - assumption; byte-level output stays under our control and the runtime dependency count stays at zero.

Move `Status` to SHIPPED once `/reconcile` confirms the body matches the live product.
