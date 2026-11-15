# PRD: a second drum kit (modal banks)

Status: DEFINED. Extends the music mode of `blipsmith-music-mode.md`, the expressive notes of `blipsmith-expressive-notes.md`, the four-operator FM of `blipsmith-fm4.md` and the strings of `blipsmith-strings.md`; everything those documents and `blipsmith-v1.md` specify still holds, byte for byte.

## Why

A kit built from oscillators and noise makes a kick, a snare and hats. A ride cymbal's inharmonic ring, a side stick's wood and a conga's tuned skin are something else: a handful of modes, each at its own frequency, each dying at its own pace. A modal bank gives a music voice those sounds without leaving the determinism contract. Brushes, a shaker and a kit that answers touch come from the voices that already exist.

## User experience (the loop)

An agent or a program adds a `modal` block to a sine voice of a `"version": 2` spec, usually a keyed kit voice, and renders as before. An agent sets it through the MCP verb `set_modal`, and the explanation names the strike's brightness, the modes and the longest ring.

## Inputs & outputs (the contract)

- `Voice.modal`: version 2 only, optional. Unset, it is left out of every dump; on a version 1 spec it is a typed error naming the version that allows it. No new spec version. With `fm`, `fm4` or `string` on the same voice, or a waveform other than `sine`, it is a typed error: the bank replaces the oscillator; AM, the LFO, the mod envelope, the filter, lo-fi and effects run as before.
- `modal {brightness, modes}`: `brightness` 0 to 1 (default 0.6); `modes` 1 to 16 (default one mode), each `{ratio, level, decayMs}`: `ratio` 0.1 to 32 of the voice's pitch (default 1), `level` 0 to 1 (default 1), `decayMs` 5 to 30000 (default 500, the time to fall 60 dB). Fewer than 1 or more than 16 modes is a typed error.
- Each mode is a complex one-pole resonator: every frame the point turns by the mode's angle and shrinks by `2^(-log2(1000) / (rate x decay))`, held below 1, and the strike is added to its real part; the imaginary part is heard. A unit impulse rings a mode at amplitude 1, starting from zero. The modes' outputs add at their levels.
- The angle comes from the voice's pitch every frame, so the mod envelope, the LFO, glide and vibrato move every mode; a turn keeps the point's size, so the level does not jump. A mode at or above the filters' ceiling at the note's first frame is silent for the note; one a sweep lifts there is held at the ceiling.
- The strike is one raised-cosine pulse of unit area, as wide as one cycle of the corner `pitch x 2^(7 x brightness)` (capped at the ceiling), fed in from the note's first frame.
- On a keyed voice the bank plays the voice's own pitch on every hit, as every kit voice does.
- The voice's amp envelope shapes each note as before; its release mutes the bank.
- Touch: with `touch.cutoffOctaves`, the corner moves by `cutoffOctaves x t` octaves (`t = velocity - pivot`), the brightness held to 0 to 1. At the pivot the voice plays as written.

## Acceptance (Given / When / Then)

- Given the 52 goldens recorded before modal banks, When rendered, Then every hash matches.
- Given one mode at A2, A4 and A6, Then the estimated fundamental is within 10 cents of the note; given a mode's `decayMs`, Then it falls 20 dB over a third of it, within 1 dB.
- Given sixteen modes at level 1, the longest decay, the brightest strike, the deepest vibrato, the longest glide, a deep pitch drop and the loudest touch, at every sample rate, Then the render is finite, lands at the normalization target and is silent once the last release ends.
- Given touch on a bank, When two hits differ only in velocity, Then the harder one has the higher spectral centroid; at the pivot the bytes equal the voice without touch.
- Given a mode above the ceiling, Then it adds nothing; given one hit at two places in a render, Then it renders the same samples at each.

## Quality bar

The determinism contract of v1: no libm (the decay through `octave_ratio`, the angles and the pulse on the baked sine), no fast-math, identical bytes on Linux and macOS. Four goldens join the corpus (56): a ride and its bell, congas with a slap, brushes and a shaker on today's noise voices, and touch on a kit.

## Out of scope

A noise excitation of the modes, a different noise stream per note, modes that couple to each other, a damper that changes the decay at key-up; wavetables, unison, chorus, samples.

## Done looks like

A kit plays a ride that rings and washes, a side stick, congas that drop a little in pitch when struck hard, brushes and a shaker, and its ghost notes sound softer in tone, not only in level; every sound made before renders the same bytes.

## Scope changes (living log)

- None yet.
