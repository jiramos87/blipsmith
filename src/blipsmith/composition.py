"""The composition compiler: step grids, swing, and the note list the core plays.

A composition is authored two ways and rendered one way. A melodic track carries
explicit notes; a drum track is painted on a step grid. Both mean the same
thing, so the grid is compiled into notes before anything reaches the core: the
sequencer schedules one representation, and a painted pattern renders
byte-for-byte like the note list a human would have typed instead.

Three policies live here. All of them produce warnings rather than errors,
because the sound still exists and the agent can steer from what came out:

- **Swing** delays every offbeat position on the track's own grid by `swing` of
  one step. `stepsPerBeat` defines that grid, so one swing setting shuffles
  sixteenths on a hat track and eighths on a bass track. It applies to explicit
  notes and painted steps alike, which is what makes the two equivalent.
- **Exact duplicates** (same start, pitch, and duration on one track) are an
  authoring slip rather than a request for twice the amplitude, so the second
  one is dropped with a warning.
- **Notes starting at or past the composition end** are dropped with a warning.
  A note that begins after the file has ended cannot be heard, and leaving it in
  silently would hide the mistake from a caller who cannot listen for it.

Compilation is idempotent by construction: the compiled spec has no steps left
and carries `swing = 0`, since the shuffle is already baked into the note times.
Compiling it again is a no-op, which is what lets `to_canonical_json` run it on
the way to the core without caring whether the caller already did.
"""

from __future__ import annotations

from blipsmith.result import SpecWarning, WarningCode
from blipsmith.spec import Note, SoundSpec, Step, Track

MS_PER_MINUTE = 60_000.0

# A note counts as sitting on the grid when its start lands on a step position.
# Beats are authored as fractions (a third of a beat is 0.3333...), so the
# comparison needs a tolerance; anything deliberately placed between steps is
# left where the author put it rather than being shuffled.
ON_GRID_TOLERANCE = 1e-9


def beat_ms(tempo_bpm: float) -> float:
    """How long one beat lasts at this tempo."""
    return MS_PER_MINUTE / tempo_bpm


def swung_start(start_beat: float, steps_per_beat: int, swing: float) -> float:
    """The documented swing formula: offbeat grid positions are delayed by
    `swing` of one step, onbeat positions and off-grid notes are left alone."""
    if swing <= 0.0:
        return start_beat
    position = start_beat * steps_per_beat
    nearest = round(position)
    if abs(position - nearest) > ON_GRID_TOLERANCE or nearest % 2 == 0:
        return start_beat
    return start_beat + swing / steps_per_beat


def _note_from_step(step: Step, track: Track) -> Note:
    """One painted step as the note it stands for: one grid cell long, at the
    grid position its index names, pitched by the voice unless the step says
    otherwise."""
    return Note(
        startBeat=step.index / track.stepsPerBeat,
        midiNote=step.midiNote,
        durationBeats=1.0 / track.stepsPerBeat,
        velocity=step.velocity,
    )


def _pitch_of(note: Note) -> str:
    return "the voice's own pitch" if note.midiNote is None else f"MIDI note {note.midiNote}"


def _dropped(code: WarningCode, track_index: int, note: Note, why: str) -> SpecWarning:
    param = f"composition.tracks[{track_index}].notes"
    return SpecWarning(
        code=code,
        param=param,
        requested=note.startBeat,
        applied=None,
        message=(f"{param}: dropped the note at beat {note.startBeat} ({_pitch_of(note)}); {why}."),
    )


def _sort_key(note: Note) -> tuple[float, int, float, float]:
    # Notes are summed in the order they are scheduled, and floating-point
    # addition is not associative, so two specs holding the same notes in a
    # different order could otherwise differ in their last bit. Sorting makes a
    # painted pattern and the note list it stands for the same render, whichever
    # order the author wrote them in.
    return (
        note.startBeat,
        -1 if note.midiNote is None else note.midiNote,
        note.durationBeats,
        note.velocity,
    )


def _compile_track(
    track: Track,
    track_index: int,
    swing: float,
    tempo_bpm: float,
    duration_ms: float,
    warnings: list[SpecWarning],
) -> list[Note]:
    authored = [*track.notes, *(_note_from_step(step, track) for step in track.steps)]
    per_beat_ms = beat_ms(tempo_bpm)

    seen: set[tuple[float, int | None, float]] = set()
    kept: list[Note] = []
    for note in authored:
        signature = (note.startBeat, note.midiNote, note.durationBeats)
        if signature in seen:
            warnings.append(
                _dropped(
                    WarningCode.DUPLICATE_NOTE_DROPPED,
                    track_index,
                    note,
                    "an identical note is already on this track",
                )
            )
            continue
        seen.add(signature)

        start = swung_start(note.startBeat, track.stepsPerBeat, swing)
        if start * per_beat_ms >= duration_ms:
            warnings.append(
                _dropped(
                    WarningCode.NOTE_BEYOND_END_DROPPED,
                    track_index,
                    note,
                    f"it starts at or past the composition end ({duration_ms} ms)",
                )
            )
            continue
        kept.append(note.model_copy(update={"startBeat": start}))

    kept.sort(key=_sort_key)
    return kept


def compile_composition(spec: SoundSpec) -> tuple[SoundSpec, list[SpecWarning]]:
    """Materialize steps into notes, apply swing, and drop what cannot sound.

    Returns the spec the core renders plus the warnings the caller needs to see.
    A spec with no composition passes through untouched.
    """
    if spec.composition is None:
        return spec, []

    working = spec.model_copy(deep=True)
    composition = working.composition
    assert composition is not None  # the deep copy preserves it

    warnings: list[SpecWarning] = []
    for index, track in enumerate(composition.tracks):
        track.notes = _compile_track(
            track,
            index,
            composition.swing,
            composition.tempoBpm,
            working.durationMs,
            warnings,
        )
        track.steps = []

    # The shuffle now lives in the note times, so the setting has done its job.
    # Zeroing it is what makes a second pass a no-op.
    composition.swing = 0.0
    return working, warnings
