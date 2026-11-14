# PRD: the music mode

Status: DEFINED. Widens the composition model of `blipsmith-v1.md`; everything that document specifies for a version 1 spec still holds, byte for byte.

## Why

A piece of game music needs more than five tracks where every voice plays every note: a drum kit, a room the parts share, echoes that ring past their notes, a loop that plays round without a seam, and stems that keep their balance. Before this, a piece took several renders mixed outside the tool, which threw away the determinism contract at the last step. The music mode puts the whole piece in one render.

## User experience (the loop)

An agent or a program writes a `"version": 2` composition: tracks, a kit, effects, the loop. One render returns the mixed WAV, its measures (integrated loudness and true peak among them), and on request one stem per track. A program calls `blipsmith.render_sound(spec, stems=True)` and reads bytes and numbers, never text. An agent plays the same mode through the MCP session verbs.

## Inputs & outputs (the contract)

- `version: 2` turns the music mode on and requires a `composition`. Version 1 (the default) renders through the original code path; a music field on a version 1 spec is a typed error naming the version that allows it. Unset music fields are left out of every dump.
- `composition.tracks`: 1 to 32. `Track.name` (up to 40 characters) labels the stem. `voices`: up to 64.
- `Voice.key` (MIDI 0 to 127): the voice plays only notes of that key, at its own pitch. Keyless voices play every note of their track at the note's pitch. A note no voice plays is silent and warns `note_unplayed`.
- `Voice.effects` run once per voice over all its notes. `Track.effects` is the track's stereo insert chain. `master.effects` (delay and reverb only) is the shared room. A reverb's right channel is spread by 23 samples at 44.1 kHz.
- Order, which is part of the bytes: per track, per voice its dry notes summed into a mono line, the voice effects, pan and level into the track's stereo line, the track effects, the master effects (per track; linear, so equal to one shared chain), the loop fold, then the tracks summed, the master gain, one normalizing scale, the clip guard.
- `composition.loop: true`: the render runs past the end until every tail has fallen 96 dB (at most 60 s) and folds everything past the end onto the start; the file is exactly `durationMs`. Without it, tails past the end are cut.
- Stems: a render option. One WAV per track at the mix's gain, summing to the mix within one 16-bit step per track; a stem that clips warns `stem_clipped`. Files are `{name}.stem-NN[-track].wav`.
- Measures: `integratedLufs` (BS.1770) and `truePeakDbtp` (4x oversampled) on every render, version 1 included, measured in the core from baked constants; no byte depends on them.
- `blipsmith render --json` prints the result as one JSON object; `--stems` writes the stems.

## Acceptance (Given / When / Then)

- Given the 35 goldens recorded before the music mode, When rendered, Then every hash matches.
- Given a kit track, When a note of key 36 plays, Then only the voices keyed 36 sound, at their own pitch.
- Given a voice, track or master effect, When its notes end, Then its tail rings on until the file ends or, looped, wraps onto the start.
- Given `loop: true`, Then the file is exactly `durationMs` long.
- Given stems, Then they sum to the mix within one step per track, and the mix is the same bytes with or without them.

## Quality bar

The determinism contract of v1: fixed-point phase, baked tables, no libm, no fast-math, identical bytes on Linux and macOS. Five music goldens join the corpus.

## Out of scope

Expressive notes, richer FM, plucked strings, a second kit, wavetables (later instrument stages); MIDI files; sections and layers; distortion on the master; a loudness target in place of the peak normalizer.

## Done looks like

A whole piece, kit and room and loop, renders in one call with its stems and its loudness, and every sound made before it still renders the same bytes.

## Scope changes (living log)

- The no-booleans rule of the v1 spec surface keeps one exception, `composition.loop`; the limiter still has no switch.
