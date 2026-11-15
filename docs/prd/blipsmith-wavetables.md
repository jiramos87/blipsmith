# PRD: wavetables, partials, unison and chorus

Status: DEFINED. Extends the music mode of `blipsmith-music-mode.md` and the voices of `blipsmith-expressive-notes.md`, `blipsmith-fm4.md`, `blipsmith-strings.md` and `blipsmith-drum-kit-two.md`; everything those documents and `blipsmith-v1.md` specify still holds, byte for byte.

## Why

Every pitched music voice is one source per note: an oscillator, FM, a string or a modal bank. None morphs its shape over a note (a vowel opening, a pad brightening), none is built from chosen partials that fade at their own pace (organ drawbars, tines, a round bass), none doubles itself into detuned copies (a fuller piano, a thick lead), and nothing widens a part across the stereo image.

## User experience (the loop)

An agent or a program adds a `wavetable`, `additive` or `unison` block to a voice of a `"version": 2` spec, or a `chorus` to a voice's or a track's effects, and renders as before. An agent sets them through the MCP verbs `set_wavetable` (by table name or frames), `set_additive` and `set_unison`, and a chorus through `set_effects` or `set_track`; the explanation names each one.

## Inputs & outputs (the contract)

- All four are version 2 only and optional. Unset, a block is left out of every dump, and a chorus's three fields are left out of every other effect's dump; on a version 1 spec each is a typed error naming the version that allows it. No new spec version.
- `Voice.wavetable {frames, position, positionEnd, sweepMs}` and `Voice.additive {brightness, stretch, partials}` replace the oscillator: beside `fm`, `fm4`, `string`, `modal` or each other, or on a waveform other than `sine`, they are a typed error. AM, the LFO, the mod envelope, the filter, lo-fi and effects run as before.
- `frames`: 1 to 8 frames `{harmonics}`, each 1 to 64 amplitudes from -1 to 1 in sine phase, the fundamental first; each frame is scaled to the RMS of one full sine. `position` 0 to 1 (default 0) is where each note reads (0 the first frame, 1 the last); `positionEnd` 0 to 1 (default null, no sweep) is where it moves, linearly over `sweepMs` 1 to 30000 (default 1000), then holds. Between two frames the harmonics crossfade. Named tables (`bright`, `organ`, `vowel`, `glass`) are a shorthand of the verbs; a spec holds frames only.
- `partials`: 1 to 32 `{ratio 0.5 to 32 (default 1), level 0 to 1 (default 1), decayMs 0 to 30000 (default 0)}`; a decay falls 60 dB over its time, 0 holds the partial. `stretch` 0 to 0.02 (default 0) makes each ratio `ratio x sqrt(1 + stretch x ratio^2)`. `brightness` 0 to 1 (default 1, no roll-off) gives a partial the gain `1 / (1 + (ratio / 2^(7 x brightness))^4)`. The levels are scaled together to the RMS of one full sine.
- Both sum sine partials on the baked sine, each at its ratio of the voice's pitch every frame, so glide, vibrato, the LFO and the pitch envelope move them together. A partial sounds in full below 0.35 cycles per sample, fades linearly to silence at 0.45 and stays silent above: nothing folds back.
- `Voice.unison {voices 2 to 8 (default 2), detuneCents 0 to 100 (default 12)}`: each note plays as that many copies of the voice spread evenly across the detune (an odd count keeps one at pitch), each at one over the square root of the count. Each copy's oscillator, operators or partials start at a point hashed from the seed, the voice and the copy, the same on every note; a plucked string's copy draws its own noise stream; struck strings and modal banks start together. On a noise waveform it is a typed error.
- Effect kind `chorus {delayMs 1 to 40 (default 12), depthMs 0 to 10 (default 2), rateHz 0.05 to 8 (default 0.8), mixWet}`: one delay line read at `delayMs + depthMs x sin(LFO)` through a centred 4-point Lagrange interpolation, never closer than two samples to now, blended with the dry input by `mixWet`. On a stereo track the right channel's LFO starts a quarter turn on, so the sides swing apart. Allowed on a voice and a track, not on the master. Tail `delayMs + depthMs`.
- Touch: `touch.cutoffOctaves` moves a wavetable's start and end position by `cutoffOctaves x t / 4` and an additive voice's brightness by `cutoffOctaves x t / 7` (`t = velocity - pivot`), held to 0 to 1. At the pivot the voice plays as written.

## Acceptance (Given / When / Then)

- Given the 56 goldens recorded before this, When rendered, Then every hash matches.
- Given a wavetable or partials at A2, A4 and A6, Then the estimated fundamental is within 10 cents of the note; given partials far above Nyquist, Then they add nothing.
- Given a sweep from a sine to a saw, Then the upper harmonics grow while the RMS stays within 1 dB; given a partial with a decay, Then it falls 60 dB over that time within 1.5 dB.
- Given a stack of four copies and one copy in one render, Then their RMS is within 1.5 dB; given eight copies, Then the first cycle does not peak above the rest of the note.
- Given a chorus on a stereo track, Then the left and right channels differ and their RMS is within 1 dB; at a mix of 0 it passes the part through byte for byte.
- Given touch, When two notes differ only in velocity, Then the harder one has the higher spectral centroid; at the pivot the bytes equal the voice without touch.
- Given every setting at its largest at every sample rate, Then the render is finite, lands at the normalization target and is silent once the last release and tail end.

## Quality bar

The determinism contract of v1: no libm (the sine is the table, decays and detunes through `octave_ratio`, levels through `sqrt`, start points from an integer hash), no fast-math, identical bytes on Linux and macOS. Five goldens join the corpus (61).

## Out of scope

An LFO on the table position, stereo unison, drawn or recorded waveforms, per-octave mip tables, a chorus on the master, samples.

## Done looks like

A music voice sings a vowel that opens over the note, plays tines and drawbars partial by partial, doubles a piano string into a detuned pair or a lead into a stack, and a part widens under a chorus, while every sound made before renders the same bytes.

## Scope changes (living log)

- None yet.
