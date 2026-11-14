# PRD: four-operator FM

Status: DEFINED. Extends the music mode of `blipsmith-music-mode.md` and the expressive notes of `blipsmith-expressive-notes.md`; everything those documents and `blipsmith-v1.md` specify still holds, byte for byte.

## Why

The two-operator `fm` block makes one family of tones. The FM sounds people know, the electric piano, the bell, the brass stab, the slap bass, come from four operators with their own ratios and envelopes, wired in a handful of fixed ways, with one operator feeding itself. Four-operator FM gives a music voice that palette without leaving the determinism contract.

## User experience (the loop)

An agent or a program adds an `fm4` block to a sine voice of a `"version": 2` spec and renders as before. An agent sets it through the MCP verbs `set_fm4` (algorithm, feedback) and `set_operator` (one operator at a time), and the explanation names the algorithm and the operators that are heard.

## Inputs & outputs (the contract)

- `Voice.fm4`: version 2 only, optional. Unset, it is left out of every dump; on a version 1 spec it is a typed error naming the version that allows it. No new spec version. With `fm` on the same voice, or a waveform other than `sine`, it is a typed error: the operators replace the oscillator; AM, the LFO, the mod envelope, the filter, lo-fi and effects run as before.
- `fm4 {algorithm, feedback, operators}`: `algorithm` one of 0 to 7 (default 0); `feedback` 0 to 1 (default 0); exactly four operators.
- `Operator {ratio, fixedHz, detuneCents, level, attackMs, decayMs, sustainLevel}`: `ratio` 0.01 to 24 of the voice's pitch at every frame; `fixedHz` 1 to 20000 or null (null follows the pitch); `detuneCents` -100 to 100; `level` 0 to 1; attack and decay 0 to 10000 ms; sustain 0 to 1. The envelope rises linearly, falls to the sustain on a squared curve and holds there; the voice's amp envelope carries the release.
- Algorithms (operators 1 to 4, `>` is "modulates"): 0 `1>2>3>4`; 1 `(1+2)>3>4`; 2 `(1+(2>3))>4`; 3 `((1>2)+3)>4`; 4 `(1>2)+(3>4)`; 5 `1>2, 1>3, 1>4`; 6 `(1>2)+3+4`; 7 `1+2+3+4`. The schema publishes the table.
- A modulator adds `level x envelope x sine x 4 pi` radians to its targets' phase. The carriers are summed, each at `level x envelope`, and divided by their count.
- Feedback: operator 1's phase gets `feedback x pi` radians times the mean of its last two outputs (sine times envelope).
- Touch: with `touch.fmIndex`, every modulator's depth becomes `level x 4 pi + fmIndex x t x level` radians (`t = velocity - pivot`), held to 0 to 24. Carriers are untouched; at the pivot the voice plays as written.

## Acceptance (Given / When / Then)

- Given the 43 goldens recorded before four-operator FM, When rendered, Then every hash matches.
- Given algorithm 0 with operators 1 to 3 at level 0, Then the bytes equal a plain sine voice at that pitch.
- Given a modulator, When its carrier is silent and it feeds nothing else, Then its level changes no byte.
- Given feedback 1 and every level at its maximum, Then the render is finite and lands at the normalization target.
- Given touch on a four-operator voice, When two notes differ only in velocity, Then the harder one has the higher spectral centroid; at the pivot the bytes equal the voice without touch.

## Quality bar

The determinism contract of v1: fixed-point phase from zero on each note, the baked sine, `octave_ratio` for detune, offsets folded to whole turns before the cast, no libm, no fast-math, identical bytes on Linux and macOS. Five goldens join the corpus (48).

## Out of scope

Operator waveforms other than sine, a release per operator, feedback on other operators, more algorithms; velocity on a noise mix; plucked strings, a second kit, wavetables, chorus, samples.

## Done looks like

A music voice plays an electric piano that brightens under a harder touch, a bell, a brass stab or a growling bass, and every sound made before renders the same bytes.

## Scope changes (living log)

- None yet.
