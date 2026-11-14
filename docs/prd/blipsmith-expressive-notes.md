# PRD: expressive notes

Status: DEFINED. Extends the music mode of `blipsmith-music-mode.md`; everything that document and `blipsmith-v1.md` specify still holds, byte for byte.

## Why

In the music mode a note's velocity only changes its level, every change of pitch is instant, and a vibrato starts with the note. Keys and melodies sound mechanical next to a played instrument. Expressive notes give each note what a player gives it: a tone that follows how hard it is struck, a slide from the note before, a vibrato that waits and then blooms.

## User experience (the loop)

An agent or a program adds up to three blocks to a voice of a `"version": 2` spec and renders as before. The notes already carry what the blocks read: velocity, start and length. An agent sets them through the MCP verbs `set_touch`, `set_glide` and `set_vibrato`, and the explanation names each one.

## Inputs & outputs (the contract)

- `Voice.touch`, `Voice.glide`, `Voice.vibrato`: version 2 only, each optional. Unset, they are left out of every dump; on a version 1 spec each is a typed error naming the version that allows it. No new spec version: a spec that never names them is the spec it was.
- `touch {pivot, fmIndex, cutoffOctaves, attackOctaves}`. With `t = velocity - pivot`, per note: FM index `+ fmIndex * t` (held to 0..24, only with `fm`), cutoff `* 2^(cutoffOctaves * t)` (at least 20 Hz, capped below Nyquist as always, only with `filter`), attack `* 2^(-attackOctaves * t)`. At the pivot the voice plays as written. Level still follows velocity.
- `glide {timeMs, mode}`. The note starts at the previous note's pitch and moves to its own, linearly in octaves, over `timeMs`. The previous note is the last one the voice played at an earlier start (on a chord, its top note). `legato`: only when that note is still held at this one's start; `always`: from any previous note. No glide on a voice's first note or between notes without a MIDI pitch. The previous note is not cut. A keyed (kit) voice with a glide is a typed error.
- `vibrato {delayMs, fadeMs, rateHz, depthCents}`. Nothing for `delayMs` from each note's start; then a sine vibrato starting at a zero crossing, its depth rising linearly to `depthCents` either side over `fadeMs`.
- Glide and vibrato add to the voice's own pitch modulation (mod envelope, LFO). Where they add nothing, the carrier runs at exactly the increment it has without them.

## Acceptance (Given / When / Then)

- Given the 40 goldens recorded before expressive notes, When rendered, Then every hash matches.
- Given a voice with touch on cutoff, When two notes differ only in velocity, Then the harder one has the higher spectral centroid; at the pivot the bytes equal the voice without touch.
- Given a legato glide, When two notes touch, Then the second slides from the first's pitch; When they are apart, Then the bytes equal the voice without glide. An `always` glide slides both.
- Given a late vibrato, Then the first `delayMs` of a note are the bytes of the voice without it, and the swing grows over `fadeMs`.

## Quality bar

The determinism contract of v1: fixed-point phase, the baked sine, `octave_ratio` for every pitch and cutoff shift, a glide's distance from MIDI numbers, no libm, no fast-math, identical bytes on Linux and macOS. Three goldens join the corpus (43).

## Out of scope

Legato envelopes that do not retrigger, and monophonic voice stealing; a noise layer for touch to mix; vibrato in beats; four-operator FM, plucked strings, a second kit, wavetables.

## Done looks like

A melody slides between held notes and blooms on long ones, a struck key gets brighter as it gets harder, and every sound made before renders the same bytes.

## Scope changes (living log)

- Touch on a noise mix is cut: a pitched voice has no noise layer to mix into.
