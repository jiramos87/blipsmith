# blipsmith — build context

MCP + CLI tool that turns a natural-language sound description into low-fi, game-ready sound effects. A deterministic DSP engine synthesizes; an LLM only navigates the parameter space. Real consumer: the Territory Developer game-dev effort. Public portfolio project.

## Canon (imported rules)

@~/projects/agentic-dev-kit/rules/code-craft.md
@~/projects/agentic-dev-kit/rules/testing.md
@~/projects/agentic-dev-kit/rules/writing-and-prose.md
@~/projects/agentic-dev-kit/rules/workflow-and-git.md
@~/projects/agentic-dev-kit/rules/reference-systems.md

<!-- Python core (locked at grill). No TS stack-note import; re-add if a TS surface ever lands. -->
<!-- Imports resolve on machines with the kit cloned at ~/projects/agentic-dev-kit. -->
<!-- Canon source: https://github.com/jiramos87/agentic-dev-kit (rules/). Missing imports are non-fatal for other clones. -->
<!-- Validate after editing imports: node ~/projects/agentic-dev-kit/tools/validate-imports.mjs --file CLAUDE.md -->

## What this repo is

An agent-playable lo-fi synthesizer. A C++ DSP core (bound to Python via pybind11) renders `SoundSpec -> PCM/WAV` deterministically; there is no LLM inside the tool. An external agent (Claude Code) plays it over MCP like a physical synth using grouped typed setters, and a human drives the same engine through a deterministic CLI. Five mixer tracks sum to stereo for composition. v1 scope (M0-M3) is locked in `docs/prd/blipsmith-v1.md`.

## Commands

- `./scripts/verify.sh` — the full verify gate: clean native build, lint (ruff check + format), typecheck (mypy), tests (pytest), the no-libm determinism check, then CLI and MCP boot. Every step runs even after one fails; the summary reports each honestly. Steps whose item has not landed report `skip`, never a false pass.
- `uv sync` — create/refresh `.venv` and build the native core. Needs a C++17 compiler; CMake and Ninja come from PyPI through the isolated build env, so no system CMake is required.
- `uv sync --reinstall-package blipsmith` — rebuild the core after editing anything under `core/`. Python sources under `src/` are an editable install and need no rebuild.
- `uv run pytest` / `uv run ruff check .` / `uv run mypy` — individual gate steps while iterating.
- `uv run python scripts/check_no_libm.py` — assert the compiled core links no libm transcendental. This is the determinism invariant's automated guard; it fails the gate rather than skipping when it cannot run.

## Repo-specific rules

- Determinism is the contract, and it is bit-identical *everywhere*: same `SoundSpec` + `seed` in, identical bytes out on every supported platform. This forces the audio path to use fixed-point phase accumulators and wavetable lookups with **no `libm` transcendentals** (`sin`/`cos`/`exp`/`pow`), no fast-math, and no FP contraction. If a stage cannot be made bit-exact, cut it rather than weakening the invariant.
- The master-bus loudness limiter + hard clip guard is a safety gate, not optional. It runs on every render and normalizes to headroom.
- No LLM in the tool. The driving agent supplies the intelligence; blipsmith supplies the instrument.
- The driving agent cannot hear: every render returns a text explanation plus in-core acoustic features (peak, RMS, estimated fundamental, spectral centroid, attack time) so it can steer numerically.
- Out-of-range numerics clamp with a warning; structurally invalid input (unknown enum, bad version, malformed JSON) is a typed error with no state change.
- License-clean by construction: everything is synthesized, no sample libraries, all deps MIT/BSD.

## Gotchas

(Empty at repo creation; append in the moment.)

## Docs map

- docs/idea.md: original concept exploration (superseded by the PRD where they disagree).
- docs/prd/blipsmith-v1.md: v1 behavioral spec (DEFINED). The source of truth.
- docs/design/synthesis-model.md: synthesis + control-surface model (signal chain, composition model, verb list, determinism rationale).
- docs/backlogs/: dependency-ordered implementation backlogs (execute via `/implement`).
- docs/build-plan.md: one-line progress ledger across sessions.
- docs/templates/: PRD and sequential-backlog doc contracts (mirror of canon templates).
- Per-feature PRD template: docs/templates/prd-template.md (canon: ~/projects/agentic-dev-kit/templates/prd-template.md).
