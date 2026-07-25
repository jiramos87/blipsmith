"""B09: the composition engine. Tracks, notes, steps, tempo, swing.

Two authoring surfaces, one render. A melodic track carries explicit notes and a
drum track is painted on a step grid, and the whole point of the compiler is
that those two are the same thing: the equality test between a painted pattern
and the note list it stands for is the load-bearing one here, because it is what
lets an agent paint and a human read the result back as music.

The rest of the file is about what a composition refuses to do: double an
amplitude because a note was written twice, keep a note that starts after the
file ends, or let five tracks at once push the mix past full scale.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.composition import compile_composition, swung_start
from blipsmith.ranges import LIMITER_TARGET_DBFS, TRACK_COUNT
from blipsmith.render import render
from blipsmith.result import RenderStatus, WarningCode
from blipsmith.schema import get_schema
from blipsmith.spec import Note, SoundSpec, to_canonical_json, validate_for_render

GOLDEN = Path(__file__).resolve().parent / "golden"

SAMPLE_RATE = 22050
# 120 BPM makes one beat 500 ms, which is a whole number of frames at every
# supported sample rate and a whole number of cycles for the pitches below.
TEMPO_BPM = 120.0
BEAT_MS = 500.0

FLAT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 1.0,
    "releaseMs": 0.0,
}

A3_MIDI = 57  # 220 Hz
A4_MIDI = 69  # 440 Hz

PEAK_TOLERANCE_DB = 0.05

COMPOSITION_GOLDENS = (
    "composition-five-track.spec.json",
    "composition-step-drums.spec.json",
)


# --- Rendering and measurement ------------------------------------------------


def wav_bytes(payload: dict[str, Any]) -> bytes:
    spec, _ = validate_for_render(payload)
    rendered: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    return rendered


def samples_of(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def channel_count(wav: bytes) -> int:
    return int(struct.unpack_from("<H", wav, 22)[0])


def raw_samples(payload: dict[str, Any]) -> tuple[int, ...]:
    return samples_of(wav_bytes(payload))


def pcm(payload: dict[str, Any]) -> list[float]:
    return [value / 32767.0 for value in raw_samples(payload)]


def channels_of(samples: tuple[int, ...]) -> tuple[list[int], list[int]]:
    return list(samples[0::2]), list(samples[1::2])


def rms(values: list[int] | list[float]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def peak_dbfs(samples: tuple[int, ...]) -> float:
    top = max(abs(value) for value in samples)
    return 20 * math.log10(top / 32767.0) if top else -math.inf


def magnitude_at(samples: list[float], hz: float) -> float:
    """Energy at one frequency: a single direct-transform bin, normalized."""
    step = 2.0 * math.pi * hz / SAMPLE_RATE
    real = sum(value * math.cos(step * i) for i, value in enumerate(samples))
    imaginary = sum(value * math.sin(step * i) for i, value in enumerate(samples))
    return math.hypot(real, imaginary) / len(samples)


# --- Spec builders ------------------------------------------------------------


def tone_voice(track: int = 0, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "waveform": "sine",
        "fundamentalHz": 220.0,
        "ampEnv": dict(FLAT_ENV),
        "track": track,
    }
    body.update(overrides)
    return body


def tracks(**by_index: dict[str, Any]) -> list[dict[str, Any]]:
    """Five tracks, with the named indices filled in."""
    built: list[dict[str, Any]] = [{} for _ in range(TRACK_COUNT)]
    for key, body in by_index.items():
        built[int(key.removeprefix("t"))] = body
    return built


def composition(
    voices: list[dict[str, Any]],
    track_bodies: list[dict[str, Any]],
    *,
    durationMs: float = 1000.0,
    swing: float = 0.0,
    **overrides: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "durationMs": durationMs,
        "voices": voices,
        "composition": {"tempoBpm": TEMPO_BPM, "swing": swing, "tracks": track_bodies},
    }
    payload.update(overrides)
    return payload


def one_note(midi: int | None = A4_MIDI, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"startBeat": 0.0, "midiNote": midi, "durationBeats": 1.0}
    body.update(overrides)
    return body


def sustained_notes_spec(*midi: int | None, **voice_overrides: Any) -> dict[str, Any]:
    """Flat-envelope notes filling a 500 ms mono render, so a direct transform
    over the whole file sees whole cycles and no leakage."""
    return composition(
        [tone_voice(**voice_overrides)],
        tracks(t0={"notes": [one_note(pitch) for pitch in midi]}),
        durationMs=BEAT_MS,
        channels=1,
    )


# --- A five-track composition renders as a stereo mix --------------------------


def five_track_payload(**overrides: Any) -> dict[str, Any]:
    voices = [
        tone_voice(0, waveform="sine", fundamentalHz=220.0),
        tone_voice(1, waveform="square", fundamentalHz=110.0),
        tone_voice(2, waveform="triangle", fundamentalHz=330.0),
        tone_voice(3, waveform="saw", fundamentalHz=165.0),
        tone_voice(4, waveform="pulse", fundamentalHz=440.0, pulseDuty=0.25),
    ]
    bodies = [
        {"pan": -0.8, "notes": [one_note(60)]},
        {"pan": -0.4, "notes": [one_note(62)]},
        {"pan": 0.0, "notes": [one_note(64)]},
        {"pan": 0.4, "notes": [one_note(67)]},
        {"pan": 0.8, "notes": [one_note(71)]},
    ]
    return composition(voices, bodies, durationMs=1000.0, **overrides)


def test_a_five_track_composition_renders_a_stereo_mix() -> None:
    wav = wav_bytes(five_track_payload())
    samples = samples_of(wav)

    assert channel_count(wav) == 2
    assert any(value != 0 for value in samples)
    assert peak_dbfs(samples) == pytest.approx(LIMITER_TARGET_DBFS, abs=PEAK_TOLERANCE_DB)


@pytest.mark.parametrize("silenced", range(TRACK_COUNT))
def test_every_track_reaches_the_mix(silenced: int) -> None:
    """Taking any one track's notes away has to change the file. Without this a
    composition could quietly render four of its five tracks."""
    full = five_track_payload()
    muted = json.loads(json.dumps(full))
    muted["composition"]["tracks"][silenced]["notes"] = []

    assert raw_samples(full) != raw_samples(muted)


def test_track_pan_places_the_track_in_the_image() -> None:
    """A track panned hard puts its voice on that side and nothing on the other.
    The square is two-valued, so a right channel carrying only the square holds
    a handful of distinct values; a leaked sine would fill it in."""
    payload = composition(
        [tone_voice(0, waveform="sine", fundamentalHz=440.0), tone_voice(1, waveform="square")],
        tracks(
            t0={"pan": -1.0, "notes": [one_note(None)]},
            t1={"pan": 1.0, "notes": [one_note(None)]},
        ),
    )
    left, right = channels_of(raw_samples(payload))

    assert len(set(right)) <= 4, "the right side should carry the square alone"
    assert len(set(left)) > 100, "the left side should carry the sine alone"


def test_track_gain_changes_the_balance_between_tracks() -> None:
    """Two hard-panned tracks make the balance readable straight off the
    channels: turning one track down has to move the ratio, and the limiter
    normalizing the whole mix cannot undo a change between tracks."""
    even = composition(
        [tone_voice(0), tone_voice(1)],
        tracks(t0={"pan": -1.0, "notes": [one_note()]}, t1={"pan": 1.0, "notes": [one_note()]}),
    )
    tilted = json.loads(json.dumps(even))
    tilted["composition"]["tracks"][1]["gainDb"] = -24.0

    even_left, even_right = channels_of(raw_samples(even))
    tilted_left, tilted_right = channels_of(raw_samples(tilted))

    assert rms(even_left) / rms(even_right) == pytest.approx(1.0, abs=0.01)
    assert rms(tilted_left) / rms(tilted_right) > 10


def test_a_voice_pan_offsets_its_track_rather_than_replacing_it() -> None:
    """Two voices on one panned track: the voice pan moves each within the
    track's placement, so they cannot both land in the same spot."""
    payload = composition(
        [tone_voice(0, pan=-0.5), tone_voice(0, fundamentalHz=330.0, pan=0.5)],
        tracks(t0={"pan": 0.5, "notes": [one_note(None)]}),
    )
    left, right = channels_of(raw_samples(payload))

    assert rms(right) > rms(left), "the track's own placement should still lead"
    assert left != right


# --- A painted pattern is the note list it stands for -------------------------


STEP_PATTERN = [{"index": index} for index in (0, 1, 2, 3, 5, 7)]
# Same grid (four steps to the beat), spelled out: each step is one cell long
# and sits at index/stepsPerBeat beats.
NOTE_PATTERN = [{"startBeat": index / 4, "durationBeats": 0.25} for index in (0, 1, 2, 3, 5, 7)]


@pytest.mark.parametrize("swing", [0.0, 0.25, 0.5])
def test_a_step_pattern_renders_as_the_note_list_it_stands_for(swing: float) -> None:
    """The acceptance that ties the two authoring surfaces together, checked at
    the only level that admits no interpretation: the bytes."""
    painted = composition(
        [tone_voice(0, waveform="noise_white")],
        tracks(t0={"stepsPerBeat": 4, "steps": STEP_PATTERN}),
        swing=swing,
    )
    written = composition(
        [tone_voice(0, waveform="noise_white")],
        tracks(t0={"stepsPerBeat": 4, "notes": NOTE_PATTERN}),
        swing=swing,
    )

    assert raw_samples(painted) == raw_samples(written)


def test_the_note_order_does_not_change_the_render() -> None:
    """Floating-point addition is not associative, so notes are scheduled in a
    sorted order rather than in the order they were typed. Otherwise the same
    pattern written backwards could differ in its last bit."""
    forwards = composition(
        [tone_voice(0)], tracks(t0={"notes": [one_note(60), one_note(64, startBeat=1.0)]})
    )
    backwards = composition(
        [tone_voice(0)], tracks(t0={"notes": [one_note(64, startBeat=1.0), one_note(60)]})
    )

    assert raw_samples(forwards) == raw_samples(backwards)


def test_canonical_json_materializes_steps_into_notes() -> None:
    """The core is only ever shown one representation, whichever surface
    authored the pattern."""
    spec, _ = validate_for_render(
        composition([tone_voice(0)], tracks(t0={"stepsPerBeat": 4, "steps": STEP_PATTERN}))
    )
    canonical = json.loads(to_canonical_json(spec))
    track = canonical["composition"]["tracks"][0]

    assert track["steps"] == []
    assert [note["startBeat"] for note in track["notes"]] == [0.0, 0.25, 0.5, 0.75, 1.25, 1.75]
    assert all(note["durationBeats"] == 0.25 for note in track["notes"])


def test_compiling_twice_changes_nothing() -> None:
    """`render` compiles to collect its warnings and `to_canonical_json`
    compiles on the way to the core, so the second pass has to be a no-op."""
    spec, _ = validate_for_render(
        composition(
            [tone_voice(0)],
            tracks(t0={"stepsPerBeat": 4, "steps": STEP_PATTERN}),
            swing=0.5,
        )
    )
    once, first_warnings = compile_composition(spec)
    twice, second_warnings = compile_composition(once)

    assert once == twice
    assert first_warnings == second_warnings == []


# --- An empty track is silence, not a held note -------------------------------


def test_a_track_with_no_notes_contributes_silence() -> None:
    """Nothing on the track means nothing in the mix: the voice sitting there is
    waiting to be triggered, not sounding on its own."""
    played = composition([tone_voice(0)], tracks(t0={"notes": [one_note()]}))
    with_idle_track = composition(
        [tone_voice(0), tone_voice(1, waveform="saw", fundamentalHz=110.0)],
        tracks(t0={"notes": [one_note()]}),
    )

    assert any(value != 0 for value in raw_samples(played))
    assert raw_samples(with_idle_track) == raw_samples(played)


def test_a_composition_with_no_notes_at_all_still_renders() -> None:
    payload = composition([tone_voice(0)], tracks())
    samples = raw_samples(payload)

    assert set(samples) == {0}, "nothing was triggered, so there is nothing to hear"


# --- Exact duplicates are an authoring slip, not a doubling -------------------


def test_an_exact_duplicate_note_is_dropped_with_a_warning() -> None:
    spec, _ = validate_for_render(
        composition([tone_voice(0)], tracks(t0={"notes": [one_note(60), one_note(60)]}))
    )
    compiled, warnings = compile_composition(spec)

    assert len(warnings) == 1
    assert warnings[0].code is WarningCode.DUPLICATE_NOTE_DROPPED
    assert warnings[0].param == "composition.tracks[0].notes"
    assert compiled.composition is not None
    assert len(compiled.composition.tracks[0].notes) == 1


def test_a_duplicate_does_not_double_the_amplitude() -> None:
    doubled = composition([tone_voice(0)], tracks(t0={"notes": [one_note(60), one_note(60)]}))
    single = composition([tone_voice(0)], tracks(t0={"notes": [one_note(60)]}))

    assert raw_samples(doubled) == raw_samples(single)


@pytest.mark.parametrize(
    ("field", "value"),
    [("startBeat", 0.5), ("midiNote", 62), ("durationBeats", 0.5)],
)
def test_notes_differing_in_any_of_the_three_are_both_kept(field: str, value: float) -> None:
    """The other side of the duplicate rule: only an exact repeat of time,
    pitch, and duration counts. Two notes that differ anywhere are music."""
    spec, _ = validate_for_render(
        composition(
            [tone_voice(0)], tracks(t0={"notes": [one_note(60), one_note(60, **{field: value})]})
        )
    )
    compiled, warnings = compile_composition(spec)

    assert warnings == []
    assert compiled.composition is not None
    assert len(compiled.composition.tracks[0].notes) == 2


def test_a_duplicated_step_is_dropped_the_same_way() -> None:
    spec, _ = validate_for_render(
        composition(
            [tone_voice(0)],
            tracks(t0={"stepsPerBeat": 4, "steps": [{"index": 2}, {"index": 2}]}),
        )
    )
    compiled, warnings = compile_composition(spec)

    assert [warning.code for warning in warnings] == [WarningCode.DUPLICATE_NOTE_DROPPED]
    assert compiled.composition is not None
    assert len(compiled.composition.tracks[0].notes) == 1


# --- Overlapping notes sum, and the limiter still holds -----------------------


def test_overlapping_notes_sum_polyphonically() -> None:
    """Both pitches have to be in the mix at once. Measured spectrally, because
    "it sounds like a chord" is exactly what the driving agent cannot check."""
    both = pcm(sustained_notes_spec(A3_MIDI, A4_MIDI))
    low_only = pcm(sustained_notes_spec(A3_MIDI))
    high_only = pcm(sustained_notes_spec(A4_MIDI))

    assert magnitude_at(both, 220.0) > 0.1
    assert magnitude_at(both, 440.0) > 0.1
    # The controls: neither note on its own carries the other's pitch, so the
    # two-note render is a sum rather than one trigger stealing the voice.
    assert magnitude_at(low_only, 440.0) < 0.01
    assert magnitude_at(high_only, 220.0) < 0.01


def test_polyphony_stays_under_the_limiter() -> None:
    """Eight voices, all triggered at once across the five tracks: the hot case
    the limiter exists for."""
    voices = [
        tone_voice(index % TRACK_COUNT, waveform="saw", fundamentalHz=110.0 * (index + 1))
        for index in range(8)
    ]
    payload = composition(
        voices,
        [{"notes": [one_note(60), one_note(64), one_note(67)]} for _ in range(TRACK_COUNT)],
    )
    samples = raw_samples(payload)

    assert min(samples) > -32768, "a hot mix must not wrap"
    assert max(samples) < 32767
    assert peak_dbfs(samples) == pytest.approx(LIMITER_TARGET_DBFS, abs=PEAK_TOLERANCE_DB)


# --- A note that cannot be heard is dropped, and said so ----------------------


def test_a_note_past_the_end_is_dropped_with_a_warning() -> None:
    spec, _ = validate_for_render(
        composition(
            [tone_voice(0)],
            tracks(t0={"notes": [one_note(60), one_note(62, startBeat=8.0)]}),
            durationMs=1000.0,
        )
    )
    compiled, warnings = compile_composition(spec)

    assert len(warnings) == 1
    assert warnings[0].code is WarningCode.NOTE_BEYOND_END_DROPPED
    assert warnings[0].requested == 8.0
    assert compiled.composition is not None
    assert [note.midiNote for note in compiled.composition.tracks[0].notes] == [60]


def test_the_note_that_starts_exactly_at_the_end_is_dropped() -> None:
    """Two beats is exactly 1000 ms at this tempo, and a note beginning as the
    file ends is silence with a start time."""
    spec, _ = validate_for_render(
        composition(
            [tone_voice(0)], tracks(t0={"notes": [one_note(60, startBeat=2.0)]}), durationMs=1000.0
        )
    )
    _, warnings = compile_composition(spec)

    assert [warning.code for warning in warnings] == [WarningCode.NOTE_BEYOND_END_DROPPED]


def test_the_note_just_inside_the_end_is_kept() -> None:
    """The other side of the same bound."""
    spec, _ = validate_for_render(
        composition(
            [tone_voice(0)], tracks(t0={"notes": [one_note(60, startBeat=1.99)]}), durationMs=1000.0
        )
    )
    compiled, warnings = compile_composition(spec)

    assert warnings == []
    assert compiled.composition is not None
    assert len(compiled.composition.tracks[0].notes) == 1


def test_a_tail_running_past_the_end_is_truncated_not_dropped() -> None:
    """A note that starts in time but rings longer than the file is still a
    note; it just does not get to finish."""
    payload = composition(
        [
            tone_voice(
                0,
                waveform="square",
                ampEnv={"attackMs": 0.0, "decayMs": 0.0, "sustainLevel": 1.0, "releaseMs": 5000.0},
            )
        ],
        tracks(t0={"notes": [one_note(60, durationBeats=0.1)]}),
        durationMs=500.0,
    )
    samples = raw_samples(payload)

    assert any(value != 0 for value in samples[-100:]), "the tail should still be sounding"


# --- Swing --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start_beat", "expected"),
    [
        (0.0, 0.0),  # onbeat: never shuffled
        (0.25, 0.25 + 0.5 / 4),  # offbeat: delayed by half a step
        (0.5, 0.5),
        (0.75, 0.75 + 0.5 / 4),
        (0.1, 0.1),  # off the grid entirely: left where the author put it
    ],
)
def test_swing_delays_only_the_offbeat_positions(start_beat: float, expected: float) -> None:
    assert swung_start(start_beat, 4, 0.5) == pytest.approx(expected)


def test_swing_of_zero_moves_nothing() -> None:
    for position in (0.0, 0.25, 0.5, 0.75, 1.0):
        assert swung_start(position, 4, 0.0) == position


def test_the_grid_a_track_swings_on_is_its_own() -> None:
    """The same swing setting shuffles sixteenths on one track and eighths on
    another, because `stepsPerBeat` is per track."""
    assert swung_start(0.5, 2, 0.5) == pytest.approx(0.5 + 0.5 / 2)
    assert swung_start(0.5, 4, 0.5) == pytest.approx(0.5)


def test_swing_shifts_the_notes_in_the_compiled_spec() -> None:
    spec, _ = validate_for_render(
        composition(
            [tone_voice(0)],
            tracks(t0={"stepsPerBeat": 4, "steps": [{"index": i} for i in range(4)]}),
            swing=0.5,
        )
    )
    compiled, _ = compile_composition(spec)

    assert compiled.composition is not None
    assert [note.startBeat for note in compiled.composition.tracks[0].notes] == [
        0.0,
        0.375,
        0.5,
        0.875,
    ]
    assert compiled.composition.swing == 0.0, "the shuffle now lives in the note times"


def test_swing_changes_the_render_and_repeats_exactly() -> None:
    def pattern(swing: float) -> dict[str, Any]:
        return composition(
            [tone_voice(0, waveform="noise_white")],
            tracks(t0={"stepsPerBeat": 4, "steps": [{"index": i} for i in range(8)]}),
            swing=swing,
        )

    straight = raw_samples(pattern(0.0))
    shuffled = raw_samples(pattern(0.5))

    assert straight != shuffled
    assert raw_samples(pattern(0.0)) == straight
    assert raw_samples(pattern(0.5)) == shuffled


# --- Pitch and velocity per note ----------------------------------------------


def test_a_note_pitch_overrides_the_voice_fundamental() -> None:
    samples = pcm(
        composition(
            [tone_voice(0, fundamentalHz=220.0)],
            tracks(t0={"notes": [one_note(A4_MIDI)]}),
            durationMs=BEAT_MS,
            channels=1,
        )
    )

    assert magnitude_at(samples, 440.0) > 0.1
    assert magnitude_at(samples, 220.0) < 0.01


def test_a_note_without_a_pitch_plays_the_voice_fundamental() -> None:
    """What a drum track needs: a kick tuned in hertz keeps its own tuning on
    every hit rather than being forced onto a MIDI note."""
    samples = pcm(
        composition(
            [tone_voice(0, fundamentalHz=220.0)],
            tracks(t0={"notes": [one_note(None)]}),
            durationMs=BEAT_MS,
            channels=1,
        )
    )

    assert magnitude_at(samples, 220.0) > 0.1
    assert magnitude_at(samples, 440.0) < 0.01


def test_a_step_without_a_pitch_plays_the_voice_fundamental_too() -> None:
    painted = composition(
        [tone_voice(0, fundamentalHz=220.0)],
        tracks(t0={"stepsPerBeat": 1, "steps": [{"index": 0}]}),
        durationMs=BEAT_MS,
        channels=1,
    )
    written = composition(
        [tone_voice(0, fundamentalHz=220.0)],
        tracks(t0={"stepsPerBeat": 1, "notes": [one_note(None)]}),
        durationMs=BEAT_MS,
        channels=1,
    )

    assert raw_samples(painted) == raw_samples(written)


def test_velocity_sets_the_balance_between_notes() -> None:
    """Two hard-panned tracks again, so the balance survives the limiter."""
    payload = composition(
        [tone_voice(0), tone_voice(1)],
        tracks(
            t0={"pan": -1.0, "notes": [one_note(velocity=1.0)]},
            t1={"pan": 1.0, "notes": [one_note(velocity=0.25)]},
        ),
    )
    left, right = channels_of(raw_samples(payload))

    assert rms(left) / rms(right) == pytest.approx(4.0, rel=0.02)


# --- Defaults and the result envelope -----------------------------------------


def test_a_composition_defaults_to_stereo() -> None:
    spec, _ = validate_for_render(composition([tone_voice(0)], tracks(t0={"notes": [one_note()]})))
    assert int(spec.channels) == 2


def test_an_explicit_channel_count_still_wins() -> None:
    spec, _ = validate_for_render(
        composition([tone_voice(0)], tracks(t0={"notes": [one_note()]}), channels=1)
    )
    assert int(spec.channels) == 1


def test_a_one_shot_is_still_mono() -> None:
    spec, _ = validate_for_render({"voices": [tone_voice(0)]})
    assert int(spec.channels) == 1


def test_a_note_needs_no_pitch_to_be_valid() -> None:
    """`midiNote` is optional on a note for the same reason it is on a step."""
    assert Note(startBeat=0.0).midiNote is None
    assert SoundSpec.model_fields["composition"].default is None


def test_the_schema_says_what_a_composition_will_do() -> None:
    """The agent authors from the schema and cannot listen to the result, so
    both of this item's surprises have to be published: a note pitch may be
    omitted, and a composition comes back in stereo."""
    schema = get_schema()
    pitch = schema["models"]["Note"]["fields"]["midiNote"]

    assert pitch["required"] is False
    assert pitch["nullable"] is True
    assert "null plays the voice's own fundamental" in pitch["description"]
    assert schema["limits"]["channelsDefaultOneShot"] == 1
    assert schema["limits"]["channelsDefaultComposition"] == 2


def test_composition_warnings_reach_the_render_result(tmp_path: Path) -> None:
    """The agent cannot hear the note that went missing, so the result has to
    say which one it was."""
    payload = composition(
        [tone_voice(0)],
        tracks(t0={"notes": [one_note(60), one_note(60), one_note(62, startBeat=9.0)]}),
        durationMs=1000.0,
        meta={"name": "warned"},
    )
    result = render(payload, out_dir=tmp_path)

    assert result.status is RenderStatus.RENDERED_WITH_WARNINGS
    assert {warning.code for warning in result.warnings} == {
        WarningCode.DUPLICATE_NOTE_DROPPED,
        WarningCode.NOTE_BEYOND_END_DROPPED,
    }


def test_the_sidecar_keeps_the_pattern_as_it_was_painted(tmp_path: Path) -> None:
    """A human editing the sidecar should find the step grid they wrote, not the
    note list it expanded into. It re-renders to the same bytes either way."""
    payload = composition(
        [tone_voice(0)],
        tracks(t0={"stepsPerBeat": 4, "steps": STEP_PATTERN}),
        swing=0.5,
        meta={"name": "painted"},
    )
    result = render(payload, out_dir=tmp_path)

    assert result.specPath is not None
    sidecar = json.loads(Path(result.specPath).read_text())
    assert sidecar["composition"]["tracks"][0]["steps"] != []
    assert sidecar["composition"]["swing"] == 0.5

    assert result.wavPath is not None
    assert Path(result.wavPath).read_bytes() == wav_bytes(sidecar)


def test_a_composition_repeats_exactly() -> None:
    payload = five_track_payload()
    assert raw_samples(payload) == raw_samples(payload)


# --- Golden corpus ------------------------------------------------------------


@pytest.mark.parametrize("name", COMPOSITION_GOLDENS)
def test_the_corpus_covers_the_composition_surface(name: str) -> None:
    assert (GOLDEN / "specs" / name).exists()
    assert name in json.loads((GOLDEN / "hashes.json").read_text())


def test_the_step_golden_and_its_note_equivalent_agree() -> None:
    """The corpus entry for the drum grid is only worth freezing if it still
    means the same thing as the note list a human would write."""
    painted = json.loads((GOLDEN / "specs" / "composition-step-drums.spec.json").read_text())
    spec, _ = validate_for_render(painted)
    compiled, warnings = compile_composition(spec)

    assert warnings == [], "a golden should not be recording a dropped note"
    written = json.loads(to_canonical_json(compiled))
    assert raw_samples(written) == raw_samples(painted)
