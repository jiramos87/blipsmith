# PRD: plucked and struck strings

Status: DEFINED. Extends the music mode of `blipsmith-music-mode.md`, the expressive notes of `blipsmith-expressive-notes.md` and the four-operator FM of `blipsmith-fm4.md`; everything those documents and `blipsmith-v1.md` specify still holds, byte for byte.

## Why

Every pitched music voice is an oscillator: five shapes, two-operator and four-operator FM. A guitar, a harp, a plucked bass or a struck dulcimer string is none of those: it is a string set ringing once, losing its highs as it rings and dying at its own pace. A physical string model gives a music voice that family without leaving the determinism contract.

## User experience (the loop)

An agent or a program adds a `string` block to a sine voice of a `"version": 2` spec and renders as before. An agent sets it through the MCP verb `set_string`, and the explanation names the excitation, where it lands on the string, the brightness, the decay and the damping.

## Inputs & outputs (the contract)

- `Voice.string`: version 2 only, optional. Unset, it is left out of every dump; on a version 1 spec it is a typed error naming the version that allows it. No new spec version. With `fm` or `fm4` on the same voice, or a waveform other than `sine`, it is a typed error: the string replaces the oscillator; AM, the LFO, the mod envelope, the filter, lo-fi and effects run as before.
- `string {excitation, position, brightness, decayMs, damping, body, bodyHz}`: `excitation` `pluck` (default) or `strike`; `position` 0.02 to 0.5 (default 0.2); `brightness` 0 to 1 (default 0.6); `decayMs` 50 to 30000 (default 2500); `damping` 0 to 1 (default 0.5); `body` 0 to 1 (default 0); `bodyHz` 60 to 2000 (default 200).
- The loop: a delay line read back at the period less one sample through a centred 4-point Lagrange interpolation, a loss filter `[c, 1 - 2c, c]` with `c = damping / 4` (exactly one sample of delay at every frequency) and a loop gain that falls 60 dB over `decayMs`, held below 1. The period comes from the voice's pitch every frame, between 4 samples and the period of 20 Hz.
- The excitation fills one period at the note's start. Its corner is `brightness` times seven octaves above the pitch, below the filters' ceiling. `pluck`: the voice's seeded white noise, fresh on each note, through a lowpass at the corner. `strike`: one raised-cosine hammer pulse as wide as one cycle of the corner. Then the comb of the place, `e[n] - e[n - position x period]` around the period, the mean removed and the level set to unit RMS.
- `body` above 0 adds a bandpass at `bodyHz` (Q 3, twice its output times `body`) after the loop.
- The voice's amp envelope shapes each note as before; its release mutes the string.
- Touch: with `touch.cutoffOctaves`, the corner moves by `cutoffOctaves x t` octaves (`t = velocity - pivot`), the brightness held to 0 to 1. At the pivot the voice plays as written. `fmIndex` does nothing on a string.

## Acceptance (Given / When / Then)

- Given the 48 goldens recorded before strings, When rendered, Then every hash matches.
- Given a pluck or a strike at A2, A4 and A6, Then the estimated fundamental is within 10 cents of the note.
- Given every setting at its longest and brightest, the deepest vibrato, the longest glide and the loudest touch, at every sample rate, Then the render is finite, lands at the normalization target and is silent once the last release ends.
- Given touch on a string, When two notes differ only in velocity, Then the harder one has the higher spectral centroid; at the pivot the bytes equal the voice without touch.
- Given a glide, Then the string's pitch slides; given one note at two places in a render, Then it renders the same samples at each.

## Quality bar

The determinism contract of v1: no libm (the decay through `octave_ratio`, the hammer and the filters on the baked sine, the level through `sqrt`), no fast-math, the noise from the spec's seed and the voice, identical bytes on Linux and macOS. Four goldens join the corpus (52).

## Out of scope

Unison and detuned string pairs, sympathetic strings, a damper that changes the loop at key-up, a different noise stream per note; a second kit, wavetables, chorus, samples.

## Done looks like

A music voice plays a harp, a nylon guitar, a plucked bass, a dulcimer or a felted piano string that rings in tune, darkens as it fades and plays brighter under a harder touch, and every sound made before renders the same bytes.

## Scope changes (living log)

- None yet.
