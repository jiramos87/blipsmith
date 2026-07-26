# Implementation backlog: blipsmith v1

Source PRD: `docs/prd/blipsmith-v1.md` (Status: DEFINED). Built by `/sequential-backlog` on 2026-07-24.

Items are ordered by dependency, NOT by effort or impact. Effort and impact are retained per item as metadata, never the sort key. Item bodies are immutable once published; a correction appends a `Note ({date}):` line to the item, it never rewrites it.

## How to use this doc

Dispatch one item per implementer session, in ledger order, with `/implement docs/backlogs/blipsmith-v1.md {item-id}`. Each session reads ONLY this header plus its own item (plus ambient CLAUDE.md). Everything an item needs is either inside that item or pinned in the Cross-item seams inventory below.

Supporting design context: `docs/design/synthesis-model.md` (signal chain, D1-D5 decisions). Items cite it where the PRD is silent on mechanism.

## Cross-item seams (pinned)

The shared names later items depend on, fixed here so items cannot drift apart.

- Python package: `blipsmith`, source at `src/blipsmith/`. Introduced by B01, consumed by all.
- Native module: `blipsmith._core`, C++17 sources under `core/src/`, vendored deps under `core/vendor/` (kissfft lands in B08). Built by CMake + pybind11 + scikit-build-core. Introduced by B01.
- Determinism compile flags (pinned in the root `CMakeLists.txt` by B01, never weakened): C++17, `-ffp-contract=off`, no `-ffast-math`, no `-Ofast`. Hot path uses only `+ - * / sqrt` and explicit `fma`; no `libm` transcendentals anywhere that affects output bytes, including once-per-render coefficient math.
- Bridge contract: `blipsmith._core.render(spec_json: str) -> dict` with keys `"wav"` (bytes, complete canonical WAV file) and `"features"` (dict, the six feature keys below). `spec_json` is canonical JSON: already validated, clamped, and defaults-filled by the Python layer; the core never validates or clamps. Canonicalizer: `blipsmith.spec.to_canonical_json(spec)` (sorted keys, defaults materialized). Introduced by B03, consumed by B04-B13.
- Spec `version`: integer `1`. Any other value is `invalid_spec`. Introduced by B02.
- Result envelope (Python dataclass/pydantic model `blipsmith.result.RenderResult`): `{status, wavPath, specPath, explanation, features, warnings, error}`. `status` in `{"rendered_ok", "rendered_with_warnings", "invalid_spec", "render_failed"}`. Introduced by B02 (types), populated end to end from B03.
- Warning shape: `{"code": str, "param": str|null, "requested": number|null, "applied": number|null, "message": str}`. Codes include `clamped`, `duplicate_note_dropped`, `note_beyond_end_dropped`. Introduced by B02.
- Error shape (for `invalid_spec` / `render_failed`): `{"code": str, "field": str|null, "message": str, "validValues": list|null}`. Introduced by B02.
- Feature keys (exact names, in-core computation): `durationMs`, `peakDbfs`, `rmsDbfs`, `estimatedFundamentalHz`, `spectralCentroidHz`, `attackTimeMs`. Introduced by B08; placeholder values (nulls) allowed in the bridge dict before B08.
- Numeric limits (single source of truth is the B02 ranges module; these values are pinned here so later items agree): `MAX_VOICES = 8`; `durationMs` one-shot `[10, 30000]`, composition `[10, 300000]`; supported `sampleRate` set `{8000, 11025, 16000, 22050, 44100}`; supported `channels` `{1, 2}`; limiter normalization target `-1.0 dBFS` peak; tracks exactly 5, indices `0..4`.
- Defaults: omitted `seed` is `0`; one-shot renders mono 22050 Hz 16-bit; composition renders stereo 22050 Hz 16-bit; all overridable per render.
- Noise seeding: deterministic integer PRNG seeded from `(spec.seed, voiceIndex)`; never platform `rand()`. Introduced by B04.
- Output policy: WAV + sidecar written as `{name}.wav` and `{name}.spec.json` into the output directory. Resolution order: explicit per-call path/dir, else env `BLIPSMITH_OUT_DIR`, else `./blipsmith-out`. Directory is created if missing. Existing target file fails the render unless the overwrite flag is set. Introduced by B03, consumed by B11, B12.
- Presets: spec JSON files at `src/blipsmith/presets/{name}.spec.json`, registry API `blipsmith.presets.list_presets() / load_preset(name)`. Introduced by B10.
- Golden corpus: specs at `tests/golden/specs/*.spec.json`, expected hashes at `tests/golden/hashes.json` (map of spec filename to SHA-256 of the WAV bytes). Introduced by B04 (first entries), completed by B13.
- Console entry points (pyproject): `blipsmith` (CLI, B11) and `blipsmith-mcp` (MCP server over stdio, B12).
- Verify gate: `scripts/verify.sh` runs ruff, mypy, pytest, a clean native build, the no-libm check, CLI boot, MCP boot (the last two no-op with a notice until B11/B12 land). No-libm enforcement: `scripts/check_no_libm.py` inspects the compiled core's undefined symbols (`nm`) for `sin/cos/tan/exp/log/pow` families and fails the gate on any hit. Introduced by B01 (script), tightened by B04 (no-libm), extended by B11/B12.

## Ledger (progress, in dependency order)

| Item | Title | Depends on | Effort | Impact | Status |
|---|---|---|---|---|---|
| B01 | Build scaffold and verify gate | none | M | high | done |
| B02 | SoundSpec contract: validation, clamping, ranges | B01 | L | high | done |
| B03 | Core bridge, WAV encoder, render pipeline skeleton | B01, B02 | M | high | done |
| B04 | Oscillators, noise, amp ADSR, no-libm gate | B03 | L | high | done |
| B05 | Modulation: FM, AM/ring, LFO, mod envelope | B04 | M | high | done |
| B06 | Filter, lo-fi stage, effects | B04 | L | high | done |
| B07 | Master bus: mix, pan, limiter, clip guard | B04 | M | high | done |
| B08 | Acoustic features and explanations | B07 | M | high | done |
| B09 | Composition engine: tracks, notes, steps, tempo, swing | B07 | L | high | done |
| B10 | Preset library: game SFX and lo-fi drum kit | B05, B06, B07 | M | med | done |
| B11 | CLI: render, batch, vary, explain, verify-golden | B08, B09 | L | high | done |
| B12 | MCP server: session verbs and stateless contract | B08, B09, B10 | L | high | done |
| B13 | Golden corpus, two-platform CI, wheels, README | B11, B12 | L | high | done |

Statuses: pending -> in-progress -> done. The implementer updates its own row; it never edits an item body. The ledger order is a valid topological sort of the depends-on graph.

Parallelizable (independent once their shared parent is done): B05, B06, B07 after B04; B08 and B09 after B07; B10 alongside B08/B09; B11 and B12 after their parents.

## Items

### B01 - Build scaffold and verify gate

- **Depends on:** none
- **Effort:** M  **Impact:** high
- **PRD reference:** Dependencies (C++ core toolchain, licensing), Quality bar (verify gate), edge case "compiled core missing fails fast".
- **Seam:** establishes the package layout, native build, determinism compile flags, and verify gate that every later item plugs into. Nothing else exists yet.
- **Files:** `pyproject.toml` (scikit-build-core build backend, ruff + mypy + pytest config, MIT license metadata), `CMakeLists.txt`, `core/src/core.cpp` (pybind11 module `blipsmith._core` exposing a `ping()` returning `"pong"` and a `core_version()` string), `src/blipsmith/__init__.py` (imports `_core`, raises a fail-fast actionable `ImportError` message if the native module is missing, never falls back), `tests/test_boot.py`, `scripts/verify.sh`, `scripts/check_no_libm.py` (script exists and runs; B04 makes it load-bearing), `.gitignore` (extend as needed), `CLAUDE.md` (replace the Commands "TBD" with the real commands), `LICENSE` (MIT).
- **Acceptance (Given / When / Then):**
  - Given a clean checkout with cmake and a C++17 compiler present, When `uv pip install -e .` (or equivalent) runs, Then the native extension builds and `python -c "import blipsmith; print(blipsmith._core.ping())"` prints `pong`.
  - Given the built package, When `scripts/verify.sh` runs, Then ruff, mypy, pytest, the native build, and the no-libm script all execute and exit zero (CLI/MCP boot steps print "not yet implemented" and do not fail).
  - Given the native module is absent (e.g. build artifacts deleted), When `import blipsmith` runs, Then it fails immediately with a message naming the rebuild command; no pure-Python fallback exists.
  - Given the compiled objects, When `scripts/check_no_libm.py` inspects them, Then it exits zero today and is wired into `verify.sh` so a future violation fails the gate.
  - Given `CMakeLists.txt`, When flags are inspected, Then `-ffp-contract=off` is set, no fast-math flag is present, and the standard is C++17.
- **Needs human:** cmake is not installed on this machine (`command -v cmake` is empty). Either the human runs `brew install cmake`, or approves the implementer doing it.

Note (2026-07-24): the cmake gap was closed without any system install, so the needs-human step did not apply. `cmake` and `ninja` are pinned in `build-system.requires`, and scikit-build-core's isolated build env pulls both from PyPI; `uv sync` builds the core on a machine that has only a C++17 compiler. `brew install cmake` is not needed locally or in CI.

Note (2026-07-24): two files ship beyond the listed set, both required to keep `mypy --strict` honest about the native bridge: `src/blipsmith/_core.pyi` (stub for the compiled module, extended by each item that grows the bridge) and `src/blipsmith/py.typed`. The `readme` key is deliberately absent from `pyproject.toml` because `README.md` belongs to B13; B13 adds both together.

Note (2026-07-24): the CLI-boot and MCP-boot steps in `scripts/verify.sh` are conditional on `blipsmith.cli` / `blipsmith.mcp_server` being importable, reporting `skip` until then. B11 and B12 activate them by landing those modules; neither needs to edit `verify.sh` unless its boot command differs from `blipsmith --help` / `python -m blipsmith.mcp_server --boot-check`.

### B02 - SoundSpec contract: validation, clamping, ranges

- **Depends on:** B01
- **Effort:** L  **Impact:** high
- **PRD reference:** Inputs & outputs (SoundSpec shape, documented ranges, result states, defaults), edge cases: clamping on both sides of every bound, unknown enum, unsupported version, malformed JSON, no-voices render, voice-count limit; Quality bar "out-of-range handling tested on both sides of every documented numeric bound"; invariant "SoundSpec is the only source of truth".
- **Seam:** the pydantic layer under `src/blipsmith/`. The core (B03+) receives only the canonical JSON this layer emits; all clamping and typed errors live here. Pinned limits and shapes are in the header inventory; this item is their single in-code source of truth.
- **Files:** `src/blipsmith/spec.py` (pydantic models: `SoundSpec`, `Master`, `Voice`, `Fm`, `Am`, `Lfo`, `ModEnv`, `Adsr`, `Filter`, `LoFi`, `Effect`, `Composition`, `Track`, `Note`, `Step`, `Meta`; plus `to_canonical_json`), `src/blipsmith/ranges.py` (every numeric parameter's documented `[min, max]` and default, as data, including `MAX_VOICES = 8` and the pinned duration/sample-rate/track limits), `src/blipsmith/result.py` (`RenderResult`, warning and error shapes, the four statuses), `src/blipsmith/schema.py` (`get_schema()` returning the full JSON-schema-style payload with type, range, and default for every field, sufficient to author a valid spec with no further discovery), `tests/test_spec_validation.py`, `tests/test_ranges.py`.
- **Acceptance (Given / When / Then):**
  - Given the voice model, When fields are enumerated, Then it carries exactly the PRD voice surface: waveform (sine, square, triangle, saw, pulse with duty, white/pink noise), fundamental as Hz or MIDI note, amplitude ADSR, optional mod envelope routed to pitch or cutoff, optional LFO (rate, depth, shape, target), optional 2-op FM (ratio, index), optional AM/ring (rate, depth, mode), filter (LP/HP/BP, cutoff, resonance), lo-fi (bit depth, decimation), effects (distortion/wavefold, delay, reverb), pan, mix level, track assignment.
  - Given any numeric parameter set outside its documented range (tested on both sides of every bound in `ranges.py`), When validated, Then the value is clamped to the nearest bound and a `clamped` warning records requested and applied values.
  - Given an unknown waveform, filter type, LFO target, effect kind, or enum of any sort, When validated, Then the result is `invalid_spec` naming the field and listing the valid values, and no state changes.
  - Given `version != 1`, malformed JSON, a missing required field, or a wrong type, When loaded, Then `invalid_spec` with the offending field named.
  - Given a spec with zero voices, When validated for render, Then `invalid_spec` (silence is never emitted).
  - Given a request that would create voice number `MAX_VOICES + 1`, When validated, Then `invalid_spec` naming the limit and existing voices are untouched.
  - Given a valid spec, When round-tripped through `to_canonical_json` and re-parsed, Then the two models are equal and the JSON is stable (sorted keys, defaults materialized).
  - Given `get_schema()`, When called, Then every field of `SoundSpec` appears with type, valid range, and default.
- **Needs human:** none.

Note (2026-07-24): `sampleRate` and `channels` are modeled as closed sets, so an unsupported value is `invalid_spec` listing the valid ones rather than a clamp. A rate of 12345 is not "outside a range"; picking a neighbour for the caller would be a guess. `SUPPORTED_SAMPLE_RATES` and `SUPPORTED_CHANNELS` in `ranges.py` are the source.

Note (2026-07-24): models set `extra="forbid"`, so an unknown key is `invalid_spec` listing the valid fields for that block. The PRD does not name this case, but a silently ignored `attackMS` typo is invisible to a caller that cannot hear the result.

Note (2026-07-24): non-finite numbers (NaN, Infinity) are `invalid_spec`, rejected both by `load_spec_json` and by the clamp walk. They have no nearest bound and canonical JSON cannot represent them; `to_canonical_json` uses `allow_nan=False` so it can never emit invalid JSON.

Note (2026-07-24): `clamp_model(model)` ships alongside `clamp_spec(spec)` as public API. B12's grouped setters apply one block at a time and need the same bounds and warnings a full render produces.

Note (2026-07-24): a few fields are genuinely required and therefore have no default: `Voice.waveform`, `Effect.kind`, `Filter.type`, `Lfo.target`, `ModEnv.target`, `Am.mode`, `Note.startBeat`, `Note.midiNote`, `Step.index`. `get_schema()` reports these as `required: true` with `default: null`, which is what "sufficient to author a valid spec without further discovery" needs.

Note (2026-07-24): the sample-rate-dependent Nyquist clamp on `Filter.cutoffHz` is NOT implemented here; B06 owns it. B02 applies only the static documented range (20 Hz to 20 kHz). B06 should apply the Nyquist bound in the render path where the sample rate is known, emitting the same `clamped` warning shape.

### B03 - Core bridge, WAV encoder, render pipeline skeleton

- **Depends on:** B01, B02
- **Effort:** M  **Impact:** high
- **PRD reference:** Outputs (WAV file + sidecar, configurable output directory), Dependencies (WAV written directly by the core, no libsndfile), edge cases: output dir created / not writable, overwrite refusal, happy path "rendered twice, byte-identical".
- **Seam:** implements the pinned bridge contract `_core.render(spec_json) -> {"wav": bytes, "features": dict}` and the Python-side `blipsmith.render` orchestration (validate -> canonicalize -> core -> write files -> RenderResult). Audio content is a placeholder (voices render as silence at correct duration/format) until B04; everything around the audio is final.
- **Files:** `core/src/spec_parse.cpp/.h` (parse canonical JSON into a plain numeric struct; a minimal vendored JSON parser or a small hand-rolled one, license MIT/BSD), `core/src/wav.cpp/.h` (canonical PCM WAV writer: 16-bit LE, mono or stereo, fixed 44-byte header, deterministic float-to-int16 conversion with a single defined rounding rule), `core/src/render.cpp/.h` (render entry: allocate sample buffer from durationMs and sampleRate, run per-voice generation stub, interleave, encode), `core/src/core.cpp` (bind `render`), `src/blipsmith/render.py` (the orchestration and file I/O: output-dir resolution per the pinned policy, dir creation, overwrite flag, `render_failed` mapping for unwritable paths and core load failures), `tests/test_render_pipeline.py`, `tests/test_wav_format.py`.
- **Acceptance (Given / When / Then):**
  - Given a valid spec and seed, When rendered twice on the same machine, Then the two WAV files are byte-identical.
  - Given a one-shot spec with no overrides, When rendered, Then the WAV is mono, 22050 Hz, 16-bit, and its data-chunk length matches `durationMs`.
  - Given an output directory that does not exist, When rendering, Then it is created and the WAV plus `{name}.spec.json` sidecar land in it; the sidecar re-parses equal to the canonical spec.
  - Given a directory that is not writable, When rendering, Then `render_failed` with an actionable message and no partial files.
  - Given an existing file at the target path, When rendering without the overwrite flag, Then the render fails naming the path; with the flag, it overwrites.
  - Given the bridge, When `_core.render` receives canonical JSON, Then it returns WAV bytes and a features dict (feature values may be null until B08).
- **Needs human:** none.

Note (2026-07-24): the sidecar is written pretty-printed (indent 2, sorted keys) rather than as the minified canonical JSON, because the PRD has humans hand-editing it. Determinism is unaffected: the WAV renders from the parsed spec via `to_canonical_json`, never from the sidecar's text, and a round-trip test asserts the sidecar re-renders identical bytes.

Note (2026-07-24): the core parses JSON numbers through a classic-locale `std::istringstream`, not `strtod`. `strtod` honours `LC_NUMERIC`, so in a comma-decimal locale it would read "1.5" as 1 and silently render the wrong sound. The remaining assumption, that decimal-to-double conversion is correctly rounded on both platforms, is what B13's two-platform hash gate actually proves.

Note (2026-07-24): `render()` refuses an output name that is not a plain filename (path separators, empty, `.`, `..`) with `render_failed`. `meta.name` is agent-controlled and would otherwise let a crafted name write outside the output directory.

Note (2026-07-24): frame count truncates rather than rounds: `frames = int(durationMs * sampleRate / 1000)`. One fixed rule, no tie-breaking to disagree about across platforms.

Note (2026-07-24): `spec_parse.cpp` currently reads spec-level fields plus the voice core (waveform, fundamentalHz, fundamentalMidi, pulseDuty, ampEnv, pan, mixDb, track). The optional per-voice blocks (`fm`, `am`, `lfo`, `modEnv`, `filter`, `lofi`, `effects`) and `composition` are NOT parsed yet; B05, B06, and B09 extend the parser and the `Voice`/`Spec` structs as each lands.

### B04 - Oscillators, noise, amp ADSR, no-libm gate

- **Depends on:** B03
- **Effort:** L  **Impact:** high
- **PRD reference:** Inputs (waveforms, fundamental, amplitude ADSR), Dependencies (cross-platform bit-exactness approach: fixed-point phase accumulators, wavetables, baked tables), edge case "noise voice byte-identical, seeded from spec seed and voice index", Quality bar "no libm transcendentals, enforced by an automated check", invariant "no libm in the audio path".
- **Seam:** the deterministic oscillator layer inside `core/src/`. From this item on, `scripts/check_no_libm.py` is load-bearing: wavetables and envelope curves are baked integer/float tables generated by a deterministic build-time or init-time routine that itself avoids `libm` (e.g. polynomial or CORDIC sine generation with fixed iteration counts, or tables checked into the source as constants). Design context: `docs/design/synthesis-model.md` sections "Design principles" and "Per-voice signal chain".
- **Files:** `core/src/tables.cpp/.h` (wavetables and curve tables plus their deterministic generation), `core/src/osc.cpp/.h` (fixed-point phase accumulator, e.g. 32-bit integer phase with table interpolation; sine, square, triangle, saw, pulse with duty), `core/src/noise.cpp/.h` (integer PRNG such as xorshift/PCG seeded from `(seed, voiceIndex)`; white and pink, pink via the deterministic Voss-McCartney or filtered-white integer method), `core/src/env.cpp/.h` (ADSR: attack/decay/release in ms plus sustain level, deterministic per-sample ramps), `core/src/render.cpp` (replace the silence stub with real single-voice generation through amp ADSR), `tests/test_oscillators.py`, `tests/test_determinism.py`, first golden entries in `tests/golden/specs/` + `tests/golden/hashes.json` (one per waveform, one noise).
- **Acceptance (Given / When / Then):**
  - Given each of the seven waveforms, When rendered as a one-shot, Then output is non-silent, non-clipping, and byte-identical across two renders.
  - Given a noise voice, When rendered twice with the same spec and seed, Then both renders are byte-identical; When the seed changes, Then the bytes differ.
  - Given two noise voices in one spec, When rendered, Then their streams differ (voice-index enters the seed).
  - Given an ADSR with a 50 ms attack, When rendered and analyzed offline in the test, Then the amplitude ramp reaches peak within 50 ms plus one buffer of tolerance.
  - Given the compiled core, When `scripts/check_no_libm.py` runs, Then it finds no `sin/cos/tan/exp/log/pow` family symbols; When a test deliberately compiles a probe file calling `sin()`, Then the script demonstrably fails it (the check is proven able to fail).
  - Given the golden specs authored in this item, When re-rendered, Then hashes match `tests/golden/hashes.json`.
- **Needs human:** none.

Note (2026-07-24): envelope curve shapes are linear attack, squared (concave) decay and release. A true exponential needs `exp()`, which is banned from this path; squaring the ramp gives the fast-then-slow fall percussive material wants using only multiplication. This is an aesthetic decision baked into every hash from here on, so it is cheapest to revisit before B13 freezes the corpus.

Note (2026-07-24): the release is anchored to the end of the render (a one-shot has no key-up), but may never begin before attack and decay have run. The first version lacked that second rule, and any render shorter than `releaseMs` came out **completely silent**: with the default 150 ms release, a 100 ms blip was silence. Regression covered by `test_a_short_render_is_never_swallowed_by_the_release` on both sides of the boundary.

Note (2026-07-24): sine is a 2048-entry table built at init from a fixed-term Taylor polynomial in Horner form (only `+ - * /`), read with linear interpolation; measured error against an ideal sine is ~1.7e-5, below int16 quantization. Every other waveform is closed-form from the 32-bit phase counter, so it is exact. All shapes are naive and alias on purpose, which is the lo-fi character the PRD asks for.

Note (2026-07-24): noise is xorshift32 seeded through a SplitMix64 avalanche of `(spec.seed, voiceIndex)`; pink is Voss-McCartney over 8 rows plus a per-sample white row. Written from the algorithm rather than adapted from published filter code, keeping the license-clean-by-construction claim intact.

Note (2026-07-24): `scripts/check_no_libm.py` now takes an optional binary path. With no argument it inspects the installed core as before; the argument exists so the suite can point it at a probe that deliberately calls `sin()` and prove the gate fails, since a gate that has never failed is indistinguishable from one that cannot.

Note (2026-07-24, from B03): the float-to-int16 rounding rule in `core/src/wav.cpp` (scale by 32767, round half away from zero, clamp) gets its first real coverage here. B03 can only render silence, so every sample was zero and the rule was never exercised. Assert it at both clip bounds and at a half-way value.

Note (2026-07-24, from B02): MIDI-note-to-hertz conversion is deliberately left to this item and must happen in the core from a baked 128-entry table. `2**((n-69)/12)` goes through the host `libm` pow, so converting in Python would make the rendered bytes platform-dependent and break the invariant. `Voice.fundamentalHz` and `Voice.fundamentalMidi` both travel to the core unconverted; `fundamentalMidi`, when non-null, wins.

### B05 - Modulation: FM, AM/ring, LFO, mod envelope

- **Depends on:** B04
- **Effort:** M  **Impact:** high
- **PRD reference:** Inputs (2-op FM ratio/index, AM/ring rate/depth/mode, LFO rate/depth/shape/target, mod envelope to pitch or cutoff), Quality bar golden corpus "one per processing stage (FM, AM, LFO, mod-envelope)".
- **Seam:** modulation operates in the fixed-point phase domain established by B04 (FM adds the modulator's scaled output to the carrier's phase increment; LFO-to-pitch likewise; AM/ring scales amplitude). LFO-to-cutoff and modEnv-to-cutoff write a per-sample cutoff control signal that B06's filter consumes; until B06 lands, the control signal is computed and tested but has no audible target (unit-test it directly at the C++/bridge level or via pitch behavior). Parallelizable with B06 and B07.
- **Files:** `core/src/mod.cpp/.h` (FM operator, AM/ring stage, LFO with the B04 table oscillators, mod envelope), `core/src/render.cpp` (wire modulation into the voice chain in the design-doc order: oscillator -> FM -> AM -> envelopes -> LFO routing), `tests/test_modulation.py`, golden entries for FM, AM, LFO, mod-envelope in `tests/golden/`.
- **Acceptance (Given / When / Then):**
  - Given a sine carrier with FM `ratio` and `index` set, When rendered, Then output differs from the unmodulated carrier, sidebands are present (spectral test at the PCM level is acceptable), and two renders are byte-identical.
  - Given AM mode vs ring mode at the same rate/depth, When rendered, Then the two outputs differ from each other and from the dry carrier.
  - Given an LFO targeting pitch (vibrato) and one targeting amplitude (tremolo), When rendered, Then periodic variation at the LFO rate is measurable in the PCM and renders are byte-identical.
  - Given a mod envelope routed to pitch with a downward sweep (the "pew" shape), When rendered, Then the estimated pitch at the head is higher than at the tail.
  - Given FM index, ratio, LFO rate, and depth values outside their documented ranges, When set, Then they clamp with warnings (both sides of each bound, via the B02 layer).
  - Given the new golden specs, When re-rendered, Then hashes match.
- **Needs human:** none.

### B06 - Filter, lo-fi stage, effects

- **Depends on:** B04
- **Effort:** L  **Impact:** high
- **PRD reference:** Inputs (filter LP/HP/BP cutoff/resonance, lo-fi bit depth + decimation, effects distortion/wavefold, delay, reverb), edge cases: cutoff clamped below Nyquist and above the minimum, Quality bar golden corpus "one per processing stage (bitcrush, decimate, filter, distortion/wavefold, delay, reverb)".
- **Seam:** the per-voice post-oscillator chain, in the design-doc order oscillator/mod -> filter -> lo-fi -> effects -> pan/mix. Biquad coefficients must come from deterministic shared routines (table-based or polynomial approximations of the tan/cos terms, or a bilinear-transform formulation over baked tables): even once-per-render `libm` calls are barred because coefficients affect output bytes. Consumes the per-sample cutoff control signal from B05 when both are present, but does not depend on B05 to land (static cutoff works alone). Parallelizable with B05 and B07.
- **Files:** `core/src/filter.cpp/.h` (deterministic biquad LP/HP/BP with resonance), `core/src/lofi.cpp/.h` (bit-depth reduction, sample-rate decimation via integer sample-and-hold), `core/src/fx.cpp/.h` (distortion/wavefold via deterministic shaping tables or piecewise math, integer-sample delay line, Schroeder/Freeverb-style reverb with integer delay lengths and plain-arithmetic gains), `core/src/render.cpp` (wire the chain), `tests/test_filter_lofi_fx.py`, golden entries for filter, bitcrush, decimate, distortion/wavefold, delay, reverb.
- **Acceptance (Given / When / Then):**
  - Given a white-noise voice through an LP filter at 1 kHz, When rendered, Then high-band energy is attenuated relative to the unfiltered render (spectral comparison in the test); HP and BP show the corresponding shapes; all byte-identical across two renders.
  - Given a cutoff at or above Nyquist for the render sample rate, When rendered, Then it is clamped below Nyquist with a warning; given a cutoff at or below zero, Then clamped to the documented minimum with a warning.
  - Given resonance, bit depth, and decimation factor values on both sides of their documented bounds, When set, Then they clamp with warnings.
  - Given a bitcrush to a low bit depth, When rendered, Then the output differs from the clean render and quantization is visible in the sample values; decimation shows stair-stepping at the configured factor.
  - Given a delay effect with feedback, When rendered, Then repeats appear at the configured integer-sample spacing; given the reverb, Then the tail decays and the render is byte-identical across runs.
  - Given the new golden specs, When re-rendered, Then hashes match.
- **Needs human:** none.

### B07 - Master bus: mix, pan, limiter, clip guard

- **Depends on:** B04
- **Effort:** M  **Impact:** high
- **PRD reference:** Acceptance "voices summing above full scale: limiter prevents clipping, peak normalized to target headroom", Quality bar "every golden render asserted non-clipping, peak at normalization target within tolerance", invariant "master limiter and hard clip guard run on every render and cannot be disabled".
- **Seam:** the summing bus after all per-voice chains: per-voice pan (deterministic pan law using only allowed ops; constant-power via `sqrt` is permitted) and mix level (dB to linear via a baked table or exp2-free polynomial, no `libm`), master gain, then limiter + hard clip guard, always on, no bypass parameter anywhere in the spec. Parallelizable with B05 and B06.
- **Files:** `core/src/bus.cpp/.h` (summing, pan, gain, limiter, clip guard, headroom normalization to the pinned `-1.0 dBFS` target), `core/src/render.cpp` (route all voices through the bus; multi-voice specs now render), `tests/test_master_bus.py`, golden entry for a deliberately hot multi-voice spec.
- **Acceptance (Given / When / Then):**
  - Given a spec whose voices sum above full scale, When rendered, Then no output sample exceeds full scale and the output peak sits at `-1.0 dBFS` within a documented tolerance.
  - Given a quiet spec well below full scale, When rendered, Then normalization brings its peak to the target headroom (the limiter normalizes, not merely limits).
  - Given two voices panned hard left and hard right in a stereo render, When channels are inspected, Then each voice's energy is confined to its side.
  - Given per-voice mix levels and master gain on both sides of their documented bounds, When set, Then they clamp with warnings.
  - Given the spec surface, When searched, Then no field can disable the limiter or clip guard.
  - Given all existing golden renders, When re-rendered after this item, Then none clips (this item may legitimately regenerate `hashes.json` once, since the bus now sits in the path; the regeneration is a single commit with the rationale recorded).
- **Needs human:** none.

Note (2026-07-24, from B07): `master.gainDb` cannot change the level of a finished file. The item pins the order as master gain then limiter, and the limiter normalizes unconditionally (acceptance 2 requires a quiet spec to be brought *up* to the target), so the normalizer scales the gain straight back out. Implemented as specified and pinned by `test_master_gain_cannot_move_the_finished_level`. `master.limiter.targetDbfs` is the loudness control that does bite, and per-voice `mixDb` still sets the balance between voices. If v1 wants `gainDb` to mean something, that is a spec change (drop the field, or move it after the limiter and accept renders that leave off target), not an implementation fix: it goes back through `/sequential-backlog`.

Note (2026-07-24, from B04): multi-voice specs clip today, and this item is the fix. Voices currently sum straight into the mix at unit gain, so a three-voice triangle chord pins about 10% of its samples at full scale; single-voice renders are clean. `Voice.pan` and `Voice.mixDb` are parsed by the core but not yet applied, for the same reason: converting dB to linear needs `pow`, so it belongs with the bus and its baked gain table rather than scattered through the voice loop.

### B08 - Acoustic features and explanations

- **Depends on:** B07
- **Effort:** M  **Impact:** high
- **PRD reference:** Outputs (deterministic acoustic features, plain-language explanation), UX "the agent cannot hear, it steers by numbers", Dependencies (vendored kissfft BSD-3), stateless verb `explain_spec`.
- **Seam:** features are computed in-core on the final post-bus PCM and returned through the pinned bridge dict, replacing the B03 nulls. The explanation is Python-side: a deterministic template over the canonical spec (no randomness, no LLM), exposed as `blipsmith.explain.explain_spec(spec) -> str` for reuse by CLI (B11) and MCP (B12).
- **Files:** `core/vendor/kissfft/` (vendored, BSD-3 license file retained), `core/src/features.cpp/.h` (peak dBFS, RMS dBFS, estimated fundamental via autocorrelation or FFT peak, spectral centroid via kissfft, attack time from the amplitude envelope), `core/src/render.cpp` (populate the features dict), `src/blipsmith/explain.py`, `tests/test_features.py`, `tests/test_explain.py`.
- **Acceptance (Given / When / Then):**
  - Given a 440 Hz sine one-shot, When rendered, Then `estimatedFundamentalHz` is within a documented tolerance of 440, `peakDbfs` matches the normalization target, and `attackTimeMs` reflects the ADSR attack.
  - Given a bright saw vs a dark filtered sine, When both render, Then the saw's `spectralCentroidHz` is higher.
  - Given the same spec and seed rendered twice, When features are compared, Then they are identical (features are as deterministic as the PCM they measure).
  - Given any render, When the result envelope is inspected, Then all six pinned feature keys are present and non-null.
  - Given a spec, When `explain_spec` runs twice, Then the same text is produced, and it names the waveform, pitch, envelope character, and active stages (filter, lo-fi, effects, modulation) in plain language.
- **Needs human:** none.

Note (2026-07-24, from B08): kissfft was NOT vendored, and `core/vendor/` does not exist. kissfft builds its twiddle factors with `cos`/`sin` from the host libm (`kf_cexp`), which the pinned determinism invariant bars and `scripts/check_no_libm.py` rejects on undefined symbols, so vendoring it as written would have failed the gate this repo runs on every build. The FFT is instead ~40 lines of radix-2 butterflies in `core/src/features.cpp` reading twiddles from the B04 sine table; at the 1024-point size used, every twiddle is an exact table entry rather than an interpolation, so this is more accurate than the libm version as well as deterministic. No third-party license is carried as a result. Same reasoning forced a deterministic `linear_to_db` (dBFS needs `log10`, equally barred): `tables.cpp`, exact exponent split plus a fixed-length series.

Note (2026-07-25, from B13): `explain_spec` picks its article by rule and writes "a 8-bit crush". Visible in the README's MCP transcript, which quotes the real output. Cosmetic, in text the driving agent reads, and a one-line fix (choose the article from the spoken form of the number, not the digit) that belongs to whoever next touches `explain.py`.

### B09 - Composition engine: tracks, notes, steps, tempo, swing

- **Depends on:** B07
- **Effort:** L  **Impact:** high
- **PRD reference:** UX "Composition", Inputs (composition: tempo, swing, five tracks of notes/steps), acceptance: five-track stereo mix, step pattern equals equivalent note list, edge cases: empty track silence, exact-duplicate dedupe with warning, polyphonic overlap sums under the limiter, note beyond composition end dropped with warning; out of scope: no MIDI file I/O, stereo only.
- **Seam:** the composition compiler sits Python-side or core-side at the implementer's discretion, but its output is what the core renders: step grids compile to the note representation before canonicalization (`to_canonical_json` of a spec with steps materializes notes), so the core sees one representation. Track gain/pan feed the B07 bus. Composition default output is stereo per the pinned defaults.
- **Files:** `src/blipsmith/composition.py` (step-to-note compilation, swing application, duplicate and beyond-end policies producing pinned warnings), `core/src/render.cpp` + `core/src/seq.cpp/.h` (schedule note events onto voices across the five tracks, polyphonic summing), `tests/test_composition.py`, golden entries: one five-track composition, one step-grid drum pattern.
- **Acceptance (Given / When / Then):**
  - Given a composition with notes on five tracks, tempo, and swing, When rendered, Then a stereo WAV contains all five tracks at their track gains and pans.
  - Given a step pattern on a drum track, When rendered, Then the bytes equal the render of the equivalent explicit note list at the same tempo and swing.
  - Given a track with zero notes, When rendered, Then that track contributes silence and the render succeeds.
  - Given two notes with identical time, pitch, and duration on one track, When rendered, Then one is dropped with a `duplicate_note_dropped` warning and amplitude is not doubled.
  - Given overlapping notes at different pitches on one track, When rendered, Then they sum polyphonically and the master limiter holds the ceiling.
  - Given a note starting beyond the composition end, When rendered, Then it is dropped with a `note_beyond_end_dropped` warning.
  - Given swing set to zero vs a nonzero value, When the same pattern renders, Then offbeat note times shift by the documented swing formula and renders are byte-identical per setting.
- **Needs human:** none.

Note (2026-07-25): the swing formula, previously unspecified, is now pinned in `composition.py`: a note whose start lands on an **odd position of its track's own grid** (`startBeat * stepsPerBeat`, within 1e-9) is delayed by `swing / stepsPerBeat` beats, which is `swing` of one step. Onbeat positions and notes deliberately placed between steps are left alone. It applies to explicit notes and painted steps alike, which is what makes acceptance 2's equality hold at all: the "equivalent note list" would otherwise have to be pre-shuffled by hand. `stepsPerBeat` being per track is what lets one setting shuffle sixteenths on a hat and eighths on a bass.

Note (2026-07-25): `Note.midiNote` is now optional (`int | None`, default null), which contradicts the B02 note listing it among the required fields. A painted step already allows a null pitch meaning "play the voice's own fundamental", and a step has to compile into a note, so without this a drum grid could not exist: a kick tuned to 55 Hz would be forced onto whatever MIDI number the compiler invented for it. The two fields now mirror each other exactly, and `ranges.py` carries the same description for both so the published schema says what null means.

Note (2026-07-25): compilation is idempotent by construction, and load-bearing that it is. `to_canonical_json` runs the compiler on the way to the core, so every surface (render, the golden harness, later the CLI and MCP) shows the core one representation without having to remember to compile; `render()` also compiles separately to collect the warnings. The compiled spec has no steps left and carries `swing = 0`, so the second pass provably moves nothing. Compiled notes are also **sorted** (start, pitch, duration, velocity): notes are summed in scheduling order and floating-point addition is not associative, so the same pattern typed in a different order could otherwise differ in its last bit.

Note (2026-07-25): the sidecar keeps the pattern as it was authored (steps stay steps, `swing` stays what it was set to) while the core receives the compiled notes. A human editing the committed spec finds the grid they painted rather than the note list it expanded into, and the file still re-renders byte-identically, which is the property B11 depends on.

Note (2026-07-25): files beyond the listed set, each one required rather than convenient. `core/src/spec_parse.cpp/.h` grew the `Note`/`Track`/`Composition` structs (the B03 note flagged this as owed). `core/src/env.cpp/.h` gained `AmpEnvelope::gated`: a one-shot has no key-up and anchors its release to the end of the file, while a note releases when the note ends, so the two are different envelopes over the same ADSR; `at()` also gained a past-the-tail guard, since squaring a negative remaining fraction grows instead of fading. `src/blipsmith/spec.py` carries the model change above, the composition-defaults-to-stereo validator (the pinned default B02 did not implement: an explicit `channels` still wins), and the canonicalization hook. `src/blipsmith/render.py` merges the compile warnings into the result. `schema.py` publishes `channelsDefaultOneShot` / `channelsDefaultComposition`, because a conditional default cannot be expressed as a field default and an agent that cannot hear should not discover stereo from the file size. `CMakeLists.txt` lists `seq.cpp`. All 20 pre-existing golden hashes are unchanged: the one-shot path renders exactly the bytes B08 recorded.

Note (2026-07-25): each note is a full run of the voice chain from a clean slate (fresh phase, filter state, effects, and noise stream seeded from `(seed, voiceIndex)` as before), which is why a hat sounds like itself on every hit rather than drifting through the pattern, and why an exact duplicate note would have doubled the amplitude precisely if it were not dropped. Track gain and voice `mixDb` add in decibels; track pan and voice pan add across the image and the bus clamps the sum, so a voice can sit off-centre within a track that is itself placed off-centre. Cost measured on dev hardware: a 30-second five-track composition with 216 notes renders in 51 ms, against B13's 2-second target.

Note (2026-07-25, for B13 or `/sequential-backlog`): two authoring mistakes a composition still swallows silently. Notes written on a track that no voice is assigned to are inaudible with no warning, and a composition whose tracks are all empty renders a silent file, even though a spec with zero *voices* is refused as `invalid_spec` precisely so silence is never emitted. Both are consistent with this item's acceptance (an empty track contributes silence and the render succeeds), so neither was folded into this diff; if v1 wants them warned, that is a new warning code and a spec change.

### B10 - Preset library: game SFX and lo-fi drum kit

- **Depends on:** B05, B06, B07
- **Effort:** M  **Impact:** med
- **PRD reference:** UX "loads a preset as a starting point", acceptance "list_presets returns authored archetypes (game SFX plus a lo-fi drum kit) with names, tags, one-line descriptions", Quality bar "golden corpus covers at least one render per preset archetype".
- **Seam:** presets are plain `SoundSpec` JSON files at the pinned path, validated by the B02 layer at load; the registry exposes `list_presets()` and `load_preset(name)`. Unknown preset name is `invalid_spec` listing valid names. Authoring uses the full B05/B06 parameter surface (FM bells, filtered noise hits, pitch-drop lasers).
- **Files:** `src/blipsmith/presets/__init__.py` (registry), `src/blipsmith/presets/*.spec.json` (at minimum: laser, jump, pickup/coin, explosion, hit/damage, powerup, ui-blip, plus drum kit: kick, snare, closed hat, open hat, clap, tom; each with `meta.name`, `meta.tags`, one-line `meta.description`), `tests/test_presets.py`, golden entries: one per preset archetype.
- **Acceptance (Given / When / Then):**
  - Given a fresh session, When `list_presets()` runs, Then every authored preset appears with name, tags, and a one-line description, covering game SFX and a lo-fi drum kit.
  - Given each preset, When loaded and rendered with seed 0, Then the render succeeds non-clipping and its hash is recorded in the golden corpus.
  - Given an unknown preset name, When loaded, Then `invalid_spec` lists the valid names and session state is unchanged.
  - Given every preset file, When validated against the B02 contract, Then it parses with zero clamp warnings (presets are authored in-range).
- **Needs human:** preset sound design benefits from a human ear pass; the item ships with agent-authored parameters judged by acoustic features, and Javier spot-listens before B13 freezes the golden corpus.

Note (2026-07-25): 13 presets shipped, exactly the archetypes the item names: `laser`, `jump`, `coin`, `explosion`, `hit`, `powerup`, `ui-blip` (tagged `sfx`) and `kick`, `snare`, `hat-closed`, `hat-open`, `clap`, `tom` (tagged `drum`). The two families are read from those tags by the coverage test, so a preset cannot join a family by renaming itself. All 13 render at seed 0 with zero clamp warnings and peak at -1.0 dBFS.

Note (2026-07-25): the ear pass is still owed and is the only open work here. Renders for listening are at `blipsmith-out/presets/*.wav` (regenerate with `load_preset` through `render`). What the numbers already confirm, so a listening pass can concentrate on taste rather than on correctness: pitch direction on every mod-envelope preset (`laser` 1837 -> 490 Hz, `kick` 75 -> 50, `tom` 175 -> 130, `jump` 125 -> 262 rising), the clap's four decaying bursts, the closed hat silent by 60 ms where the open one still rings at 400 ms, and the powerup's four rising onsets an octave apart.

Note (2026-07-25): `coin` and `powerup` carry a `composition` rather than being single one-shots, because both are sequences (a blip stepping up into a held note; a four-step arpeggio) and voices in a one-shot all start at frame zero. Both pin `channels: 1` explicitly, since a game sound effect wants mono and B09 made a composition default to stereo. This is the first use of the composition engine as an authoring tool rather than as a feature.

Note (2026-07-25): golden coverage is a **copy** of each preset at `tests/golden/specs/preset-{name}.spec.json`, not a reference to the shipped file. The pinned corpus contract is a map from spec *filename* to hash, and `test_every_recorded_hash_still_has_a_spec` requires a 1:1 match with the files in that directory, so a golden has to be a file there. `test_the_golden_copy_matches_the_preset_it_was_taken_from` compares the two byte for byte, which turns the duplication into a drift guard: editing a preset without re-recording its golden fails the gate rather than leaving a hash that guards a file nobody ships.

Note (2026-07-25): presets ship as package data with no packaging configuration. Verified against a built wheel rather than assumed: `scikit-build-core`'s `wheel.packages = ["src/blipsmith"]` carries `blipsmith/presets/*.spec.json` into `blipsmith-0.1.0-cp313-cp313-macosx_26_0_arm64.whl`, so `load_preset` works for someone who pip-installed rather than cloned. B13's cibuildwheel job inherits this for free.

Note (2026-07-25, for B13): `.gitignore` ignores `/out/`, but the pinned output policy defaults to `./blipsmith-out`. WAVs are covered by the separate `*.wav` rule, so the leak is the sidecars: a user's first default render leaves untracked `{name}.spec.json` files in the repo root. One line to fix, in the item that owns the public repo shape.

### B11 - CLI: render, batch, vary, explain, verify-golden

- **Depends on:** B08, B09
- **Effort:** L  **Impact:** high
- **PRD reference:** UX "The human (CLI)", acceptance: sidecar re-render byte-identity, N seeded variations, batch folder with per-file summary; edge cases: output dir, overwrite flag, fail-fast on missing core; Quality bar: CLI boot in the verify gate.
- **Seam:** a deterministic argparse/typer CLI over the same `blipsmith.render` orchestration the MCP server uses; no logic lives only in the CLI. Console script `blipsmith` per the pinned entry points. Exit codes: 0 success, nonzero on `invalid_spec` / `render_failed` / any batch failure.
- **Files:** `src/blipsmith/cli.py`, `pyproject.toml` (console script entry), `scripts/verify.sh` (CLI boot step becomes real: `blipsmith --help` exits 0), `tests/test_cli.py`.
- **Acceptance (Given / When / Then):**
  - Given a committed `{name}.spec.json` exported earlier, When `blipsmith render {name}.spec.json` runs, Then the WAV is byte-identical to the original render.
  - Given `blipsmith render` with `--out-dir`, `--seed`, and `--overwrite`, When run, Then each flag behaves per the pinned output policy and seed override.
  - Given a folder of spec files with one deliberately invalid, When `blipsmith batch dir/` runs, Then every valid spec produces its WAV, the summary reports per-file success or failure, and the exit code is nonzero.
  - Given `blipsmith vary spec.json -n 5`, When run, Then 5 specs and 5 WAVs are emitted, each spec differing only in `seed` and each WAV reproducible from its own sidecar.
  - Given `blipsmith explain spec.json`, When run, Then the B08 explanation prints without rendering audio.
  - Given `blipsmith verify-golden`, When run against `tests/golden/`, Then it re-renders every golden spec and reports hash match or mismatch per file, nonzero exit on any mismatch.
  - Given a broken/missing native core, When any CLI command runs, Then it fails fast with the actionable rebuild message, never a fallback.
- **Needs human:** none.

Note (2026-07-25): argparse, not typer. The item allowed either, and typer would have been the first runtime dependency added since pydantic; "all deps MIT/BSD" is cheapest to keep true by not adding any. The whole CLI is one module with no synthesis logic: every command reads a file, calls `blipsmith.render` or `explain_spec`, and prints. `test_the_cli_renders_through_the_shared_pipeline` pins that by rendering the same spec both ways and comparing bytes, so the MCP surface cannot drift from this one.

Note (2026-07-25): `vary` changes `meta.name` as well as `seed`, which is a deliberate deviation from the acceptance's "each spec differing only in `seed`". With the name left alone, all N sidecars carry the same `meta.name`, so `blipsmith batch` over the output directory renders every variation to one filename and fails on the overwrite guard for all but the first. `meta` never reaches the audio path (the core parses no field of it), so the *sound* still differs by seed alone, and every variation now re-renders from its own sidecar with no extra arguments, which is what the same acceptance's next clause asks for. Seeds are `base + 1 .. base + n`, wrapping modulo the documented maximum rather than clamping, since clamping would hand out the same seed twice and call them two variations.

Note (2026-07-25): `batch` globs `*.spec.json`, the suffix the output policy already pins, and treats "no files matched" as a failure rather than a successful run of nothing: a build script that renders zero assets and exits 0 is the failure nobody notices. `verify-golden` reports four states, two beyond the acceptance's match/mismatch: `UNKNOWN` for a spec with no recorded hash and `ORPHAN` for a recorded hash whose spec is gone. Both are ways a corpus silently stops covering what it claims to, which is the one thing this command exists to catch.

Note (2026-07-25, from B03): the overwrite refusal message said "Pass overwrite=True to replace it", which is the Python API and means nothing to someone at a terminal. Reworded once in `render.py` to name the option neutrally and give the CLI spelling, since that message now has two audiences. No test asserted the old wording.

Note (2026-07-25): `scripts/verify.sh` needed no edit, as B01's note predicted: its CLI step is conditional on `blipsmith.cli` being importable, and landing the module turned the `skip` into a live `blipsmith --help` check. The gate now reads 6 pass, 1 skip (MCP boot, B12). Exit codes are 1 for every failure the tool detects and argparse's own 2 for a usage error.

Note (2026-07-25, for B13 or `/sequential-backlog`): the B10 preset library has no CLI surface. `list_presets` / `load_preset` are reachable from Python and will be MCP tools in B12, but a human at a terminal cannot list or start from a preset without knowing the file path inside the installed package. Not in this item's acceptance, so not added; a `blipsmith presets` / `--preset` flag would be a small follow-up and is worth deciding before the README freezes the documented surface.

### B12 - MCP server: session verbs and stateless contract

- **Depends on:** B08, B09, B10
- **Effort:** L  **Impact:** high
- **PRD reference:** UX "The driving agent (MCP)", scope-change log "stateful synth session with grouped typed setters", acceptance: get_schema, list_presets, grouped setters then render returns path + explanation + features; Quality bar "every MCP tool has a published schema and at least one integration test"; Dependencies (official Python MCP SDK over stdio); design doc D1 (grouped setters, ~15-20 tools).
- **Seam:** one implicit session per server process holding an in-memory `SoundSpec`; every mutation goes through the B02 validation layer (clamp warnings returned in the tool result; structural errors leave state untouched). Session serializes losslessly to `SoundSpec` at all times. Console script `blipsmith-mcp` per the pinned entry points. Pinned tool list (grouped, per design D1): `new_voice`, `select_voice`, `remove_voice`, `set_waveform`, `set_fundamental`, `set_adsr`, `set_mod_env`, `set_lfo`, `set_fm`, `set_am`, `set_filter`, `set_lofi`, `set_effects`, `set_voice_output` (pan, mix, track), `set_master`, `set_tempo_swing`, `set_track` (gain, pan), `add_notes`, `set_steps`, `clear_track`, `set_render_options` (durationMs, sampleRate, channels, seed, name), `render`, `export_spec`, `import_spec`, `explain_session`, plus stateless `render_spec`, `get_schema`, `list_presets`, `load_preset`, `explain_spec`.
- **Files:** `src/blipsmith/mcp_server.py` (server + session), `src/blipsmith/session.py` (the mutable session over `SoundSpec`), `pyproject.toml` (entry point), `scripts/verify.sh` (MCP boot step becomes real: server starts on stdio and answers an initialize + list_tools round-trip), `tests/test_mcp_integration.py` (drives the server over the SDK's in-memory/stdio test transport).
- **Acceptance (Given / When / Then):**
  - Given a fresh session, When `get_schema` is called, Then the full B02 schema payload returns; When `list_presets` is called, Then the B10 registry returns.
  - Given `load_preset` then grouped setters (`set_adsr`, `set_fm`, `set_filter`, `set_lofi`) then `render`, Then a WAV lands in the output directory and the result carries path, explanation, the six features, and any clamp warnings.
  - Given an out-of-range value in any grouped setter, When applied, Then it clamps and the tool result lists the warning; Given a structurally invalid value (unknown enum), Then the tool returns `invalid_spec` with valid values and the session state is unchanged (verified by a subsequent `export_spec`).
  - Given `export_spec` after any edit sequence, When the exported JSON is rendered via the CLI, Then bytes match the session's own render (lossless serialization).
  - Given `import_spec` with a valid spec, Then the session adopts it; with an unsupported version or malformed JSON, Then `invalid_spec` and the prior session survives.
  - Given every pinned tool, When the integration suite runs, Then each tool is exercised at least once and each publishes an input schema.
  - Given `blipsmith-mcp` launched with no arguments, When an MCP initialize handshake is performed over stdio, Then it succeeds (this is the verify-gate boot check).
- **Needs human:** none.

Note (2026-07-25): all 30 pinned tools ship and are published with input schemas, on `mcp` 1.28.1 via `FastMCP`. Every mutation runs the same pattern: edit a plain dict copy of the spec, validate and clamp the whole thing through B02, adopt only if it passed. That is what makes "a refusal changes nothing" true by construction rather than by care, and it means the session has no second validation path to drift from `spec.py`. Setters patch rather than replace: an agent adjusting the attack keeps the decay it set three calls ago, because silently resetting it is a change it cannot hear.

Note (2026-07-25): `load_preset` is listed among the stateless verbs but had to be stateful. Acceptance 2 is "load_preset then grouped setters then render", which only means anything if the preset landed in the session; as a pure reader it would leave the setters editing an empty session and the render refusing for want of voices. It adopts the preset (replacing the session) and reports clamp warnings like any other edit.

Note (2026-07-25): `import_spec` takes one parameter that accepts an object *or* JSON text, rather than the two mutually exclusive parameters the shape first suggested. FastMCP pre-parses any string argument that happens to be valid JSON, so a `specJson: str` parameter can never receive well-formed JSON text: it arrives as a dict. The single tolerant parameter handles all three cases a client can produce (object, JSON text, double-encoded text), and malformed text still arrives as a string, which is exactly the case the acceptance requires to be a typed `invalid_spec`.

Note (2026-07-25): starting a composition (the first `set_tempo_swing`, `add_notes`, `set_steps`, `set_track`, or `clear_track` call) switches the render to stereo, the pinned default for a composition. A session begins as a mono one-shot, and B09's stereo default only applies when a spec arrives with a composition already in it, so without this an agent that built a five-track piece knob by knob would get its pans folded down and no way to notice. `set_render_options(channels=1)` overrides it and sticks.

Note (2026-07-25): `set_fundamental` takes hz or midi, never both, and setting either clears the other. A MIDI note wins over hertz in the core, so a stale note left behind would make a hertz change inaudible, which is the one kind of failure this caller cannot detect. Refusals return a typed result (`status`, `error.validValues`) rather than raising, so the agent reads the valid set instead of a stack trace; a wrong argument *type* is still caught earlier by the SDK against the published schema.

Note (2026-07-25): `scripts/verify.sh` needed no edit, again as B01 predicted. Its MCP step runs `python -m blipsmith.mcp_server --boot-check`, and that flag now launches the real server as a subprocess (the console script when installed, the module otherwise, both with no arguments) and completes an initialize plus list_tools round trip over stdio. Importing the module would have proven none of that. **The gate now runs all seven steps with no skips for the first time.**

Note (2026-07-25, for B13): the dependency tree stopped being strictly MIT/BSD. `mcp` itself is MIT, but it pulls `certifi` (MPL-2.0), `python-multipart` (Apache-2.0), and `typing-extensions` (PSF-2.0), all transitive and all permissive, none of them blocking an MIT release. CLAUDE.md and the PRD both claim "all deps MIT/BSD"; the README's license section should say what is actually shipped rather than repeat the claim.

### B13 - Golden corpus, two-platform CI, wheels, README

- **Depends on:** B11, B12
- **Effort:** L  **Impact:** high
- **PRD reference:** Acceptance "same spec and seed on Linux x86_64 and macOS arm64 hash identically", Quality bar (verify gate all green, golden corpus coverage list, non-clipping assertions, performance targets), Dependencies (GitHub Actions, cibuildwheel), Done looks like (public MIT repo), out of scope note "CI-built wheels installable locally, no PyPI publish".
- **Seam:** freezes the golden corpus (coverage audit: at least one render per preset archetype and one per processing stage: bitcrush, decimate, filter, distortion/wavefold, delay, reverb, FM, AM, LFO, mod-envelope), then builds the CI that proves the invariant across platforms. The determinism gate renders the corpus on `ubuntu-latest` and `macos-latest` and compares SHA-256 sets in a join job; any divergence fails.
- **Files:** `tests/golden/` (coverage audit, final `hashes.json`), `tests/test_golden.py` (hash equality + non-clipping + peak-at-target assertions per golden render), `tests/test_perf.py` (one-second mono one-shot under 50 ms, 30-second five-track composition under 2 s, generous CI multiplier documented), `.github/workflows/ci.yml` (lint, typecheck, tests, native build, no-libm check, CLI boot, MCP boot on both platforms; cross-platform hash-compare join job; cibuildwheel wheel build uploaded as artifacts), `README.md` (both loops end to end: an agent-driven MCP session transcript and a hand-authored spec rendered via CLI; install, build, license).
- **Acceptance (Given / When / Then):**
  - Given the golden corpus, When audited, Then every preset archetype and every processing stage in the Quality bar list has at least one golden render, and every golden render asserts non-clipping with peak at the normalization target within tolerance.
  - Given the CI workflow on a push, When both platform jobs finish, Then the join job compares golden hashes across Linux x86_64 and macOS arm64 and fails on any mismatch.
  - Given the CI run, When green, Then wheels for both platforms are attached as build artifacts and installable locally.
  - Given `scripts/verify.sh` locally, When run, Then all gate steps pass including real CLI and MCP boot.
  - Given the README, When followed verbatim by a new user, Then both loops complete: the MCP session example and the CLI render example, producing the documented outputs.
  - Given the perf test on dev hardware, When run, Then the one-shot renders under 50 ms and the composition under 2 s.
- **Needs human:** create the public GitHub repository, push, and enable Actions (no remote exists today). Confirm the MIT license holder line. Spot-listen sign-off on the frozen golden corpus (carried from B10).

Note (2026-07-25): the corpus needed nothing added. All 35 entries already covered every stage the Quality bar lists, so the audit was written and passed on the first run rather than driving new goldens. What changed is how coverage is asserted: `STAGE_PROBES` in `tests/test_golden.py` is a map from stage name to a predicate over the *parsed spec*, not to a filename. A filename list passes forever once written; a predicate fails the day a golden stops exercising the stage it was recorded for, which is the failure mode a frozen corpus actually has.

Note (2026-07-25): the corpus-wide assertions moved rather than being duplicated. `test_determinism.py` (hash equality, non-clipping, in-range authoring, orphaned hashes) and `test_master_bus.py` (peak at target across every golden) each owned a slice of the corpus from the item that added it; all of it now lives in `tests/test_golden.py`, with a pointer left behind in both files. Nothing was weakened: B04's and B07's acceptance statements are still asserted, over a corpus that is now 35 specs instead of 9 or 20.

Note (2026-07-25): the cross-platform gate needed one file the item did not list, `scripts/golden_hashes.py`. `verify-golden` answers "did the bytes move?" for a human and prints prose; the join job needs "what are the bytes?" as something diffable. The manifest is sorted-key JSON, so the two platforms are compared with a plain `diff -u` and the failure names the exact specs that diverged. `tests/test_golden.py` asserts the manifest covers the whole corpus and agrees with `hashes.json`, so the file CI compares cannot quietly become a different measurement than the one the local gate makes.

Note (2026-07-25): `tests/test_readme.py` also ships, for the acceptance clause "followed verbatim by a new user". The CLI loop's spec is lifted out of the README's heredoc, written to an empty directory with no environment set, rendered, and its printed output compared to the block the README promises; the sidecar is then re-rendered and the bytes compared. The MCP transcript cannot be executed, so what is asserted there is every tool name it uses against the server's published list, plus the quoted tool, preset, and corpus counts. Prose rots silently, and this is the item that publishes it.

Note (2026-07-25, human decision): B11's note about presets having no CLI surface was closed here rather than deferred, on the human's call, because the README freezes the documented surface. `blipsmith presets` lists the catalogue and `blipsmith render --preset {name}` renders one; the spec positional became optional and exactly one of the two is required. Both go through the same `blipsmith.presets` registry the MCP server uses, so there is still one preset library and no CLI-local copy of it.

Note (2026-07-25): CI runs the gate steps individually rather than calling `scripts/verify.sh`, because each step needs to be its own annotated line in the run log and a fresh checkout is already clean. `tests/test_golden.py` asserts every local gate step appears in the workflow, so the two cannot drift apart. Wheels are built with `uvx cibuildwheel` (config in `[tool.cibuildwheel]`, per-wheel test command `import blipsmith`), pinned to cp311-cp313 on exactly the two platforms the determinism gate covers: handing out a wheel for a platform this project has never proven bit-identical would be handing out the one thing it promises not to.

Note (2026-07-25): `estimatedFundamentalHz` measures the whole file at once, so on a voice with a pitch sweep it lands somewhere inside the sweep rather than on the fundamental that was set (the README's heavy-laser reads 1818 Hz for a voice set to 220 Hz). Correct for what it computes and useless as a check on a swept voice. Documented in the README as a caveat rather than changed: B10 already established that a sweep is read by measuring head and tail separately. A windowed variant would be a new feature key, so it goes back through `/sequential-backlog` if v1 wants one.

Note (2026-07-25): two `.gitignore` and packaging leftovers closed here since this item owns the public repo shape. `/blipsmith-out/` is ignored (B10's note: the WAV rule covered the audio but a first default render left untracked sidecars in the repo root), and `readme = "README.md"` was added to `pyproject.toml` (B01's note deferred it to this item, and it is a hard build error until the file exists).

Note (2026-07-25, resolved): **the two-platform gate ran and passed.** `jiramos87/blipsmith` is public, and run 30178690941 on commit `4d40ca1` was green end to end: `gate` on ubuntu-latest and macos-latest, `cross-platform hashes` downloading both manifests and reporting "Bit-identical across Linux x86_64 and macOS arm64", and `wheels` attaching cp311-cp313 artifacts for both platforms. The join job is not vacuous: both artifacts are downloaded and `diff` exits nonzero on a missing file as readily as on a differing one. Thirty-five specs, same SHA-256 on two architectures, two compilers, two operating systems. The invariant this project was designed around is now measured rather than argued. Only the ear pass remains owed. (Cosmetic: GitHub warns that `actions/checkout@v4`, `upload-artifact@v4`, `download-artifact@v4` and `setup-uv@v5` target the deprecated Node 20 and are being forced onto Node 24; bumping the four action majors is a one-line-each follow-up, unrelated to determinism.)

Note (2026-07-25, superseded by the above): the two-platform hash gate has never run. It cannot until the repo exists and Actions is enabled, which is the standing needs-human above. Everything reachable locally was verified instead: the workflow parses, the manifest script agrees with `hashes.json` on this machine, `cibuildwheel --print-build-identifiers` resolves the pinned config, and a real wheel built from this tree installs into a clean venv, ships all 13 presets, and re-renders `preset-laser` to its recorded hash. The human ear pass on the frozen corpus is also still owed, carried from B10.

## Appendix A - Ground-truth verdicts

Every PRD dependency claim verified against live code / infra on 2026-07-24.

- Repo is pre-code: VERIFIED. No commits on `main`, no source files; only docs, CLAUDE.md, AGENTS.md, `.claude/`, `.gitignore`. Nothing can contradict the PRD yet.
- C++ toolchain available: PARTIAL. Apple clang 14 (C++17-capable) present at `/usr/bin/clang++`. cmake is NOT installed (`command -v cmake` empty). Gap closed by `brew install cmake` (flagged needs-human in B01).
- Python toolchain: VERIFIED. Python 3.13.3 and `uv` present. pydantic 2.13.3 available in the default env (the project will pin its own).
- pybind11 / scikit-build-core / cibuildwheel / MCP SDK / kissfft: UNVERIFIED locally (not installed; expected, they are project deps). Verified by B01 (build deps), B08 (kissfft vendoring), B12 (MCP SDK), B13 (cibuildwheel) as each lands.
- Cross-platform bit-exactness approach (fixed-point + wavetables, no libm, no fast-math, no FP contraction): UNVERIFIED by nature until CI exists; the claim is technically sound (IEEE-754 mandates only `+ - * / sqrt fma`). Proven by the B13 two-platform hash gate; enforced earlier by the B04 no-libm symbol check.
- GitHub Actions on ubuntu-latest + macos-latest free tier: UNVERIFIED. No git remote exists. Verified when the repo is created and the first B13 workflow runs (needs-human in B13).
- License cleanliness (all deps MIT/BSD): VERIFIED for the pinned set by their published licenses (pybind11 BSD, kissfft BSD-3, MCP SDK MIT, pydantic MIT); re-checked at each vendoring/adding item.
- Performance targets (50 ms one-shot, 2 s composition): UNVERIFIED until B13's perf test runs on dev hardware; plausible for a native core at 22.05 kHz.

## Appendix B - PRD-vs-reality contradictions

None. The repo contains no implementation for the PRD to contradict. (The missing local cmake and missing GitHub remote are dependency gaps, recorded in Appendix A and flagged needs-human in B01 and B13, not contradictions.)
