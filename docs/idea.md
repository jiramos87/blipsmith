# blipsmith (working name) — Initial Spec (exploration)

Status: idea / pre-PRD. This doc is the concept definition to grill into a locked PRD.
Owner: Javier Ramos. Working name `blipsmith` is a placeholder, rename is trivial.

One-liner: an MCP + CLI tool that turns a natural-language sound description (plus
optional physical parameters) into low-fi, multichannel, game-ready sound effects and
short musical elements. A deterministic DSP engine does the synthesis; an LLM only
navigates the parameter space.

Real consumer: the **Territory Developer** game-dev effort. The coding agent building
the game requests sounds inline and gets a rendered asset plus a reproducible spec.

Related prior art in this workspace: `~/projects/jazz-backing-track-generator`
(has an `mcp-server/` and `templates/`, musical-accompaniment sibling) and
`~/projects/unity-mcp-bridge` (if Territory Developer runs on Unity, this is the
delivery path into the editor).

---

## The core idea: deterministic engine, LLM navigator

- **Deterministic core (no LLM):** a pure function `SoundSpec -> PCM/WAV`. Seeded,
  testable, fast, reproducible. This is the physics layer Javier controls directly:
  fundamentals, timbre, phase, additive partials, FM index/ratio, grain size/density,
  envelopes, intensity, rhythm.
- **LLM layer:** translate a NL description into a typed `SoundSpec` (structured
  output / function calling). The LLM never emits audio samples, only parameters.
- **Why this split:** controllable, cheap, license-clean, reproducible, and it lets
  Javier tweak real acoustic values by hand at any point. Pedagogically it is a clean
  teaching artifact: "an LLM as a navigator over a deterministic synthesizer."

---

## What it produces

Low-fi / chiptune one-shots (blips, pickups, hits, jumps, UI confirms, alerts, deaths)
and short stings / loops. Multichannel / multi-voice. WAV at a low sample rate for
authentic lo-fi character. Fully synthesized, so no sample-licensing exposure.

---

## Synthesis capabilities (deterministic core)

- Methods: additive, FM, granular, subtractive + noise (percussion). Multi-voice mix.
- Shaping: ADSR envelopes, LFOs, arpeggios, a step sequencer with tempo and swing.
- Lo-fi character: bit-crush, sample-rate decimation, wavefolding.
- Effects: filter (LP/HP/BP), delay, distortion, a cheap reverb.
- Master bus: loudness limiter + hard clip guard (this is a safety gate, not optional).
- Javier's tacit sound-design knowledge is encoded as authored presets and recipes.

---

## SoundSpec (the contract) — field sketch, not code

- `version`, `seed`, `sampleRate`, `channels`, `durationMs`
- `master`: { `gainDb`, `limiter` }
- `voices[]`: { `method` (additive | fm | granular | noise), method-specific `params`,
  `envelope` (adsr), optional `lfo`, `effects[]`, `pan`, `mixDb` }
- `pattern?`: { `tempoBpm`, `swing`, `steps[]` } for sequences and loops
- `meta`: { `name`, `tags[]`, `description` }

Typed (pydantic or Zod). The renderer must be a pure, deterministic function of a
`SoundSpec` plus its `seed`. Same spec in, identical bytes out.

---

## Interfaces

- **CLI (deterministic, no LLM):** render a spec file to WAV, batch a folder, emit N
  seeded variations, print a spec explanation. This is the reproducible backbone.
- **MCP tools (for the game-dev agent):**
  - `describe_sound(nl, hints?)` -> SoundSpec + rendered WAV
  - `render_spec(spec)` -> WAV
  - `vary_sound(spec, n)` -> N related specs (parameter-space neighbors)
  - `match_reference(clip, nl?)` -> SoundSpec steered toward a reference clip
  - `list_presets()` / `explain_spec(spec)` -> human-readable rationale

---

## Territory Developer integration (the real consumer)

- The game-dev agent calls `describe_sound` inline while building a scene, receives a
  WAV dropped into the game asset dir plus the `SoundSpec` committed to the game repo,
  so every sound is regenerable and diff-able.
- OPEN: engine and asset pipeline. If Unity, deliver via `unity-mcp-bridge`. Confirm
  target format (WAV vs OGG), sample rate, mono vs stereo, naming/manifest convention.

---

## Deterministic vs LLM split (learning intent)

| Layer | Deterministic or LLM | Why |
|---|---|---|
| Synthesis render | Deterministic | reproducible, fast, physically precise, testable |
| NL to SoundSpec | LLM (structured output) | maps fuzzy description to typed params |
| Variations / neighbors | Both | LLM proposes, engine + embeddings measure |
| Reference imitation | Both | analysis (deterministic + audio model) steers LLM params |
| Quality judgement (evals) | Both | acoustic metrics + audio/vision LLM judge |

---

## Roadmap concepts this exercises (the learning payload)

- structured-output, tools / function-calling (NL to SoundSpec) [reinforce]
- MCP server + transports, now over an audio tool [reinforce, new modality]
- Multimodal audio: audio OUTPUT (render), audio UNDERSTANDING (analyze a reference),
  and vision (judge a spectrogram image) [new, biggest gap]
- Local / open-source models: `librosa` features plus a Hugging Face audio-embedding
  model (e.g. CLAP) run locally for similarity and imitation [new]
- Fine-tuning (real): train a small model mapping descriptive tags to preset params,
  OR a match-scorer; document the rag-vs-fine-tuning call with numbers [new]
- RAG: retrieve synthesis recipes and Javier's sound-design notes to ground NL->spec
- Audio evals (the differentiator): golden set of (description -> acoustic targets);
  embedding similarity between rendered audio and the text description (CLAP text-audio
  alignment); a spectrogram-image LLM-judge; wired as a CI gate. Extends the existing
  golden-set + LLM-judge harness into a non-text output.
- Guardrails: loudness/clip limiter, deterministic seed, LLM cost cap, prompt-injection
  defense on NL input, license-clean by construction
- Sampling / temperature: low temp for precise matches, higher for creative variation
- Recommendation: `vary_sound` and reference neighbors as embedding-space retrieval

---

## Milestones (digested for grill -> implement)

- **M0** repo skeleton, `SoundSpec` schema, deterministic engine for additive + noise +
  ADSR + master limiter, CLI render, golden render tests. No LLM.
- **M1** add FM + granular + multi-voice mix + lo-fi (bitcrush/decimate) + effects +
  sequencer. Author a preset library from Javier's sound knowledge.
- **M2** LLM layer: NL -> SoundSpec via structured output. `describe_sound`. Cost cap,
  seed, limiter as a hard gate.
- **M3** MCP server exposing the tool set. Wire into a coding agent; Territory Developer
  consumes it end to end.
- **M4** imitation: analyze a reference clip (librosa + CLAP), steer params.
  `match_reference`. First local/open model in the loop.
- **M5** audio evals: acoustic golden set + embedding-similarity metric +
  spectrogram-image LLM-judge, run as a gate. The portfolio-grade artifact.
- **M6** (stretch) fine-tune the tag->preset or match-scorer model; RAG over a recipe
  corpus; optional voice input (Whisper STT) to describe sounds by speaking.

---

## Stack recommendation

Python core: `numpy` synthesis (chiptune synthesis is clean in pure numpy), `librosa`
for analysis, Hugging Face for the audio-embedding model, `soundfile` for I/O, a Python
MCP server. Rationale: this unlocks the audio-ML ecosystem, which is the whole learning
point. TS alternative exists (his MCP muscle) but would push audio ML into a Python
sidecar anyway. Lean Python core, revisit at grill.

---

## Open questions to grill

- Territory Developer engine and asset pipeline (Unity via `unity-mcp-bridge`? format,
  sample rate, mono/stereo, manifest)?
- Core language: Python (audio-ML) vs TS-with-Python-sidecar? Recommendation: Python.
- LLM provider for NL->spec (cheap structured-output model via OpenRouter/Groq/Claude)?
- Scope of "musical": one-shots only, or also loops, sequences, short melodies?
- How literal is "imitation"? Scope to feature-steering, not exact resynthesis.
- How much tacit knowledge to encode as presets vs let the LLM explore?
- Distribution: local MCP only for now, or publish to pypi/npm later?

---

## Handoff

A fresh session should read this file and grill it into a locked PRD under
`docs/prd/blipsmith-v1.md`, then decompose M0 to M6 into a sequential backlog. The
repo needs the agentic-dev-kit skills wired into `.claude/commands/` first (same setup
as `~/projects/ecommerce-order-error-fix-agent`).
