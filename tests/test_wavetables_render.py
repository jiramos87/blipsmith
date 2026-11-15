"""Wavetables, partials, unison and chorus in the render.

Each test renders through the product path and reads back audio or the in-core
features: both additive blocks in tune across the range, partials above the
ceiling silent, a sweep that moves the tone at a steady level, a partial that
falls 60 dB in its time, a unison stack about as loud as one copy, a chorus that
widens a stereo part, touch on both blocks, every extreme setting bounded, and a
note that renders the same wherever it sits. Renders are normalized, so levels
are compared inside one render.
"""

from __future__ import annotations

import math
import struct
from typing import Any

import pytest

import blipsmith
from blipsmith.wavetables import table_frames

RATE = 22050
HELD = {"attackMs": 0, "decayMs": 0, "sustainLevel": 1, "releaseMs": 150}


def notes_spec(
    voices: list[dict[str, Any]],
    tracks: list[list[dict[str, Any]]],
    duration_ms: float = 2000,
    rate: int = RATE,
    channels: int = 1,
    track_effects: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    built = [{"notes": notes} for notes in tracks]
    if track_effects is not None:
        built[0]["effects"] = track_effects
    return {
        "version": 2,
        "seed": 5,
        "sampleRate": rate,
        "channels": channels,
        "durationMs": duration_ms,
        "voices": voices,
        "composition": {"tempoBpm": 120, "tracks": built},
    }


def note(
    start: float = 0, midi: int = 57, velocity: float = 0.8, beats: float = 3.0
) -> dict[str, Any]:
    return {"startBeat": start, "midiNote": midi, "velocity": velocity, "durationBeats": beats}


def one_note(voice: dict[str, Any], velocity: float = 0.8, midi: int = 57) -> dict[str, Any]:
    return notes_spec([voice], [[note(midi=midi, velocity=velocity)]])


def wavetable(frames: list[list[float]] | None = None, **settings: Any) -> dict[str, Any]:
    block: dict[str, Any] = dict(settings)
    if frames is not None:
        block["frames"] = [{"harmonics": f} for f in frames]
    return {"waveform": "sine", "ampEnv": HELD, "wavetable": block}


def additive(partials: list[tuple[float, float, float]], **settings: Any) -> dict[str, Any]:
    listed = [{"ratio": r, "level": level, "decayMs": d} for r, level, d in partials]
    return {"waveform": "sine", "ampEnv": HELD, "additive": {**settings, "partials": listed}}


def render(spec: dict[str, Any]) -> blipsmith.Rendered:
    return blipsmith.render_sound(spec)


def samples(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def window(pcm: tuple[int, ...] | list[int], start_s: float, end_s: float) -> list[int]:
    return list(pcm[int(start_s * RATE) : int(end_s * RATE)])


def rms(values: list[int]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values))


def db(ratio: float) -> float:
    return 20 * math.log10(ratio)


def tone_level(values: list[int], hz: float) -> float:
    """The amplitude of one frequency in a window (a Goertzel)."""
    coefficient = 2 * math.cos(2 * math.pi * hz / RATE)
    before = after = 0.0
    for value in values:
        before, after = value + coefficient * before - after, before
    power = before * before + after * after - coefficient * before * after
    return math.sqrt(max(power, 0.0)) / len(values)


def midi_hz(midi: int) -> float:
    return float(440.0 * 2.0 ** ((midi - 69) / 12))


def centroid(voice: dict[str, Any], velocity: float = 0.8, midi: int = 57) -> float:
    return float(render(one_note(voice, velocity, midi)).features["spectralCentroidHz"])


SAW = [[round(1.0 / h, 6) for h in range(1, 33)]]

# --- Pitch and the ceiling ------------------------------------------------------------


@pytest.mark.parametrize("midi", [45, 69, 93])
def test_a_wavetable_plays_in_tune(midi: int) -> None:
    spec = one_note(wavetable(SAW), midi=midi)
    spec["sampleRate"] = 44100
    measured = render(spec).features["estimatedFundamentalHz"]
    assert abs(1200 * math.log2(measured / midi_hz(midi))) < 10


@pytest.mark.parametrize("midi", [45, 69, 93])
def test_an_additive_voice_plays_in_tune(midi: int) -> None:
    spec = one_note(additive([(1, 1, 0), (2, 0.5, 0), (3, 0.3, 0)]), midi=midi)
    spec["sampleRate"] = 44100
    measured = render(spec).features["estimatedFundamentalHz"]
    assert abs(1200 * math.log2(measured / midi_hz(midi))) < 10


def test_partials_above_the_ceiling_are_silent() -> None:
    # At A6 a partial at 31 times the pitch is far above Nyquist at 22050: once
    # the render is normalized, it adds nothing.
    alone = samples(render(one_note(additive([(1, 1, 0)]), midi=93)).wav)
    high = samples(render(one_note(additive([(1, 1, 0), (31, 1, 0)]), midi=93)).wav)
    assert max(abs(a - b) for a, b in zip(alone, high, strict=True)) <= 1


def test_a_high_saw_holds_no_tone_past_the_ceiling() -> None:
    pcm = window(samples(render(one_note(wavetable(SAW), midi=93)).wav), 0.2, 1.2)
    fundamental = tone_level(pcm, midi_hz(93))
    # The fifth harmonic sits at 0.40 turns, inside the fade; the sixth past it.
    assert tone_level(pcm, 6 * midi_hz(93) - RATE) < fundamental / 1000
    assert tone_level(pcm, 6 * midi_hz(93)) < fundamental / 1000


# --- The sweep and the partials' own decay ---------------------------------------------


def test_a_sweep_brightens_the_tone_at_a_steady_level() -> None:
    voice = wavetable([[1.0], SAW[0]], position=0, positionEnd=1, sweepMs=1000)
    pcm = samples(render(one_note(voice, midi=45)).wav)
    start, end = window(pcm, 0.0, 0.05), window(pcm, 1.1, 1.3)
    third = 3 * midi_hz(45)
    assert tone_level(end, third) > 20 * tone_level(start, third)
    assert abs(db(rms(end) / rms(start))) < 1.0


def test_crossfaded_frames_sit_between_them() -> None:
    voice = wavetable([[1.0], [1.0, 1.0]], position=0.5)
    pcm = window(samples(render(one_note(voice, midi=45)).wav), 0.2, 1.2)
    ratio = tone_level(pcm, 2 * midi_hz(45)) / tone_level(pcm, midi_hz(45))
    # Half of a sine plus half of the second frame, scaled to one sine.
    second = 1 / math.sqrt(2)
    assert ratio == pytest.approx(0.5 * second / (0.5 + 0.5 * second), rel=0.02)


def test_a_partial_falls_sixty_decibels_over_its_decay_time() -> None:
    pcm = samples(render(one_note(additive([(1, 1, 1000)]), midi=57)).wav)
    fall = db(rms(window(pcm, 1.1, 1.2)) / rms(window(pcm, 0.1, 0.2)))
    assert fall == pytest.approx(-60, abs=1.5)


def test_stretch_sharpens_an_upper_partial() -> None:
    spec = one_note(additive([(4, 1, 0)], stretch=0.01), midi=45)
    spec["sampleRate"] = 44100
    measured = render(spec).features["estimatedFundamentalHz"]
    expected = midi_hz(45) * 4 * math.sqrt(1 + 0.01 * 16)
    assert abs(1200 * math.log2(measured / expected)) < 10


def test_brightness_rolls_the_upper_partials_off() -> None:
    partials = [(float(n), 1.0, 0.0) for n in range(1, 17)]
    dark = centroid(additive(partials, brightness=0.2), midi=45)
    bright = centroid(additive(partials, brightness=1), midi=45)
    assert bright > dark * 1.5


# --- Unison ---------------------------------------------------------------------------


def test_a_unison_stack_is_about_as_loud_as_one_copy() -> None:
    saw = {"waveform": "saw", "ampEnv": HELD, "track": 0}
    stack = {**saw, "track": 1, "unison": {"voices": 4, "detuneCents": 20}}
    spec = notes_spec([saw, stack], [[note(0, beats=1.5)], [note(2, beats=1.5)]], duration_ms=2000)
    pcm = samples(render(spec).wav)
    one, four = rms(window(pcm, 0.2, 0.7)), rms(window(pcm, 1.2, 1.7))
    assert abs(db(four / one)) < 1.5


def test_unison_copies_do_not_peak_together_on_the_first_cycle() -> None:
    voice = {"waveform": "saw", "ampEnv": HELD, "unison": {"voices": 8, "detuneCents": 30}}
    pcm = samples(render(one_note(voice, midi=45)).wav)
    first = max(abs(v) for v in window(pcm, 0.0, 0.02))
    later = max(abs(v) for v in window(pcm, 0.5, 1.4))
    assert first < 1.2 * later


def test_an_odd_stack_keeps_a_copy_at_pitch() -> None:
    voice = {"waveform": "triangle", "ampEnv": HELD, "unison": {"voices": 3, "detuneCents": 10}}
    spec = one_note(voice, midi=57)
    spec["sampleRate"] = 44100
    measured = render(spec).features["estimatedFundamentalHz"]
    assert abs(1200 * math.log2(measured / midi_hz(57))) < 10


@pytest.mark.parametrize(
    "source",
    [
        {"waveform": "square"},
        {"waveform": "sine", "fm": {"ratio": 2, "index": 2}},
        {"waveform": "sine", "fm4": {}},
        {"waveform": "sine", "string": {"excitation": "strike"}},
        {"waveform": "sine", "string": {"excitation": "pluck"}},
        {"waveform": "sine", "modal": {}},
        {"waveform": "sine", "wavetable": {"frames": [{"harmonics": [1, 0.5]}]}},
        {"waveform": "sine", "additive": {"partials": [{"ratio": 1}, {"ratio": 2.7}]}},
    ],
    ids=["oscillator", "fm", "fm4", "struck", "plucked", "modal", "wavetable", "additive"],
)
def test_unison_rides_on_every_pitched_source(source: dict[str, Any]) -> None:
    plain = {**source, "ampEnv": HELD}
    stacked = {**plain, "unison": {"voices": 2, "detuneCents": 8}}
    one, two = render(one_note(plain)), render(one_note(stacked))
    assert one.wav != two.wav
    assert two.features["peakDbfs"] <= 0.0
    assert any(samples(two.wav))


def test_without_detune_a_stack_still_starts_its_copies_apart() -> None:
    plain = {"waveform": "saw", "ampEnv": HELD}
    stacked = {**plain, "unison": {"voices": 2, "detuneCents": 0}}
    assert render(one_note(stacked)).wav != render(one_note(plain)).wav


# --- Chorus ---------------------------------------------------------------------------

CHORUS = {"kind": "chorus", "delayMs": 12, "depthMs": 3, "rateHz": 0.8, "mixWet": 0.5}


def stereo(pcm: tuple[int, ...]) -> tuple[list[int], list[int]]:
    return list(pcm[0::2]), list(pcm[1::2])


def test_a_chorus_on_a_stereo_part_widens_it() -> None:
    voice = {"waveform": "saw", "ampEnv": HELD}
    spec = notes_spec([voice], [[note()]], channels=2, track_effects=[CHORUS])
    left, right = stereo(samples(render(spec).wav))
    assert left != right
    assert abs(db(rms(left[4410:30000]) / rms(right[4410:30000]))) < 1.0
    dry = notes_spec([voice], [[note()]], channels=2)
    dry_left, dry_right = stereo(samples(render(dry).wav))
    assert dry_left == dry_right


def test_a_chorus_on_a_voice_thickens_it_in_mono() -> None:
    plain = {"waveform": "saw", "ampEnv": HELD}
    wet = {**plain, "effects": [CHORUS]}
    assert render(one_note(wet)).wav != render(one_note(plain)).wav


def test_a_chorus_at_no_mix_passes_the_part_through() -> None:
    voice = {"waveform": "saw", "ampEnv": HELD}
    dry = notes_spec([voice], [[note()]], channels=2)
    still = notes_spec([voice], [[note()]], channels=2, track_effects=[{**CHORUS, "mixWet": 0}])
    assert render(still).wav == render(dry).wav


# --- Touch ----------------------------------------------------------------------------

TABLE = {**wavetable([f["harmonics"] for f in table_frames("bright")], position=0.4)}


def test_touch_reads_a_brighter_frame_for_a_harder_note() -> None:
    voice = {**TABLE, "touch": {"pivot": 0.5, "cutoffOctaves": 4}}
    assert centroid(voice, 0.95, midi=45) > centroid(voice, 0.15, midi=45) * 1.2


def test_touch_brightens_an_additive_voice() -> None:
    partials = [(float(n), 1.0, 0.0) for n in range(1, 17)]
    voice = {**additive(partials, brightness=0.4), "touch": {"pivot": 0.5, "cutoffOctaves": 6}}
    assert centroid(voice, 0.95, midi=45) > centroid(voice, 0.15, midi=45) * 1.2


@pytest.mark.parametrize("plain", [TABLE, additive([(1, 1, 0), (2, 0.5, 300)], brightness=0.5)])
def test_at_the_pivot_touch_plays_as_written(plain: dict[str, Any]) -> None:
    touched = {**plain, "touch": {"pivot": 0.5, "cutoffOctaves": 4}}
    assert render(one_note(touched, 0.5)).wav == render(one_note(plain, 0.5)).wav


# --- Bounds and determinism -----------------------------------------------------------


@pytest.mark.parametrize("rate", [8000, 22050, 44100])
def test_the_loudest_and_longest_setting_stays_bounded(rate: int) -> None:
    frames = [[1.0] * 64 for _ in range(8)]
    voice = {
        **wavetable(frames, position=0, positionEnd=1, sweepMs=30000),
        "vibrato": {"delayMs": 0, "fadeMs": 0, "rateHz": 20, "depthCents": 200},
        "glide": {"timeMs": 5000, "mode": "always"},
        "modEnv": {"target": "pitch", "amount": -2, "attackMs": 0, "decayMs": 50},
        "touch": {"pivot": 0, "cutoffOctaves": 8},
        "unison": {"voices": 8, "detuneCents": 100},
        "effects": [{**CHORUS, "depthMs": 10, "delayMs": 40, "rateHz": 8, "mixWet": 1}],
    }
    partials = {
        **additive([(1 + 0.97 * i, 1.0, 30000) for i in range(32)], stretch=0.02),
        "unison": {"voices": 8, "detuneCents": 100},
        "track": 1,
    }
    notes = [
        {"startBeat": 0, "midiNote": 0, "velocity": 1, "durationBeats": 1},
        {"startBeat": 1, "midiNote": 127, "velocity": 1, "durationBeats": 1},
        {"startBeat": 2, "midiNote": 20, "velocity": 1, "durationBeats": 1},
    ]
    spec = notes_spec([voice, partials], [notes, notes], duration_ms=2500, rate=rate, channels=2)
    spec["composition"]["tracks"][1]["effects"] = [{**CHORUS, "depthMs": 10, "mixWet": 1}]
    result = render(spec)
    assert all(
        math.isfinite(value) for value in result.features.values() if isinstance(value, float)
    )
    assert result.features["peakDbfs"] <= 0.0
    pcm = samples(result.wav)
    assert any(pcm)
    # The last note ends at 1.5 s and releases over 150 ms, the chorus rings 50 ms more.
    assert not any(pcm[int(1.75 * rate) * 2 :])


@pytest.mark.parametrize(
    "voice",
    [
        {**TABLE, "unison": {"voices": 3}},
        additive([(1, 1, 400), (2.01, 0.5, 200)], stretch=0.002),
    ],
    ids=["wavetable-unison", "additive"],
)
def test_a_note_renders_the_same_wherever_it_sits(voice: dict[str, Any]) -> None:
    held = {**voice, "ampEnv": {**HELD, "releaseMs": 50}}
    early = samples(render(notes_spec([held], [[note(0, 60, beats=0.5)]])).wav)
    late = samples(render(notes_spec([held], [[note(1, 60, beats=0.5)]])).wav)
    shift = RATE // 2
    assert late[:shift] == (0,) * shift
    assert late[shift:] == early[: len(late) - shift]
