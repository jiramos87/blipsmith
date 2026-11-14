"""Strings in the render.

Each test renders through the product path and reads back audio or the in-core
features: a string in tune across the range, a decay and a damping that shape
the tail, a brightness and a touch that shape the tone, a pitch that follows a
glide, every extreme setting bounded, and a note that renders the same wherever
it sits. Renders are normalized, so levels are compared inside one render.
"""

from __future__ import annotations

import math
import struct
from typing import Any

import pytest

import blipsmith

RATE = 22050


def notes_spec(
    voice: dict[str, Any],
    notes: list[dict[str, Any]],
    duration_ms: float = 2000,
    rate: int = RATE,
) -> dict[str, Any]:
    return {
        "version": 2,
        "seed": 3,
        "sampleRate": rate,
        "channels": 1,
        "durationMs": duration_ms,
        "voices": [voice],
        "composition": {"tempoBpm": 120, "tracks": [{"notes": notes}]},
    }


def one_note(
    voice: dict[str, Any], velocity: float = 0.8, midi: int = 57, beats: float = 3.0
) -> dict[str, Any]:
    note = {"startBeat": 0, "midiNote": midi, "velocity": velocity, "durationBeats": beats}
    return notes_spec(voice, [note])


def string(**settings: Any) -> dict[str, Any]:
    return {
        "waveform": "sine",
        "ampEnv": {"attackMs": 0, "decayMs": 0, "sustainLevel": 1, "releaseMs": 150},
        "string": settings,
    }


def render(spec: dict[str, Any]) -> blipsmith.Rendered:
    return blipsmith.render_sound(spec)


def samples(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def rms(pcm: tuple[int, ...], start_s: float, end_s: float) -> float:
    window = pcm[int(start_s * RATE) : int(end_s * RATE)]
    return math.sqrt(sum(value * value for value in window) / len(window))


def centroid(voice: dict[str, Any], velocity: float = 0.8, midi: int = 57) -> float:
    return float(render(one_note(voice, velocity, midi)).features["spectralCentroidHz"])


def midi_hz(midi: int) -> float:
    return 440.0 * 2.0 ** ((midi - 69) / 12)


# --- Pitch --------------------------------------------------------------------------


@pytest.mark.parametrize("excitation", ["pluck", "strike"])
@pytest.mark.parametrize("midi", [45, 69, 93])
def test_a_string_plays_in_tune(excitation: str, midi: int) -> None:
    spec = one_note(string(excitation=excitation), midi=midi)
    spec["sampleRate"] = 44100
    measured = render(spec).features["estimatedFundamentalHz"]
    assert abs(1200 * math.log2(measured / midi_hz(midi))) < 10


def test_a_string_follows_a_glide() -> None:
    voice = {**string(), "glide": {"timeMs": 300, "mode": "legato"}}
    legato = [
        {"startBeat": 0, "midiNote": 45, "durationBeats": 1.0},
        {"startBeat": 1, "midiNote": 52, "durationBeats": 1.0},
    ]
    plain = string()
    glided = samples(render(notes_spec(voice, legato)).wav)
    straight = samples(render(notes_spec(plain, legato)).wav)
    # Renders are normalized, so the shapes are compared by sign: the first note
    # is the same string, the second slides.
    half = RATE // 2  # one beat at 120 BPM
    signs = [[value > 0 for value in pcm] for pcm in (glided, straight)]
    assert signs[0][:half] == signs[1][:half]
    assert signs[0][half:] != signs[1][half:]


# --- Decay, damping, brightness ------------------------------------------------------


def tail_ratio(voice: dict[str, Any]) -> float:
    pcm = samples(render(one_note(voice)).wav)
    return rms(pcm, 1.0, 1.2) / rms(pcm, 0.05, 0.25)


def test_a_shorter_decay_dies_sooner() -> None:
    assert tail_ratio(string(decayMs=600, damping=0)) < tail_ratio(string(decayMs=6000, damping=0))


def test_the_decay_time_falls_sixty_decibels() -> None:
    # Undamped, the loop alone sets the fall: about 60 dB per decay time, so
    # 20 dB over a third of it.
    pcm = samples(render(one_note(string(decayMs=1500, damping=0, brightness=0.2))).wav)
    fall = 20 * math.log10(rms(pcm, 0.1, 0.2) / rms(pcm, 0.6, 0.7))
    assert 17 < fall < 23


def test_damping_darkens_the_tail() -> None:
    assert centroid(string(damping=1)) < centroid(string(damping=0)) * 0.8


@pytest.mark.parametrize("excitation", ["pluck", "strike"])
def test_brightness_brightens(excitation: str) -> None:
    dull = string(excitation=excitation, brightness=0.1)
    bright = string(excitation=excitation, brightness=0.9)
    assert centroid(bright) > centroid(dull) * 1.3


def test_the_position_and_the_body_change_the_sound() -> None:
    base = render(one_note(string())).wav
    assert render(one_note(string(position=0.5))).wav != base
    assert render(one_note(string(body=0.6, bodyHz=180))).wav != base


# --- Bounds -------------------------------------------------------------------------


@pytest.mark.parametrize("rate", [8000, 22050, 44100])
@pytest.mark.parametrize("excitation", ["pluck", "strike"])
def test_the_longest_and_brightest_setting_stays_bounded(rate: int, excitation: str) -> None:
    voice = {
        **string(
            excitation=excitation,
            position=0.02,
            brightness=1,
            decayMs=30000,
            damping=0,
            body=1,
            bodyHz=60,
        ),
        "vibrato": {"delayMs": 0, "fadeMs": 0, "rateHz": 20, "depthCents": 200},
        "glide": {"timeMs": 5000, "mode": "always"},
        "touch": {"pivot": 0, "cutoffOctaves": 8},
    }
    notes = [
        {"startBeat": 0, "midiNote": 0, "velocity": 1, "durationBeats": 1},
        {"startBeat": 1, "midiNote": 127, "velocity": 1, "durationBeats": 1},
        {"startBeat": 2, "midiNote": 20, "velocity": 1, "durationBeats": 1},
    ]
    result = render(notes_spec(voice, notes, duration_ms=2500, rate=rate))
    assert all(
        math.isfinite(value) for value in result.features.values() if isinstance(value, float)
    )
    assert result.features["peakDbfs"] <= 0.0
    pcm = samples(result.wav)
    assert any(pcm)
    # The last note ends at 1.5 s and releases over 150 ms: then silence.
    assert not any(pcm[int(1.7 * rate) :])


# --- Touch --------------------------------------------------------------------------

TOUCHED = {**string(brightness=0.4), "touch": {"pivot": 0.5, "cutoffOctaves": 3}}


@pytest.mark.parametrize("excitation", ["pluck", "strike"])
def test_touch_makes_a_harder_note_brighter(excitation: str) -> None:
    voice = {**TOUCHED, "string": {"excitation": excitation, "brightness": 0.4}}
    assert centroid(voice, 0.95) > centroid(voice, 0.15) * 1.2


def test_at_the_pivot_touch_plays_the_string_as_written() -> None:
    plain = string(brightness=0.4)
    assert render(one_note(TOUCHED, 0.5)).wav == render(one_note(plain, 0.5)).wav


# --- Determinism --------------------------------------------------------------------


def test_a_note_renders_the_same_wherever_it_sits() -> None:
    voice = string(excitation="pluck")
    early = samples(render(notes_spec(voice, [{"startBeat": 0, "midiNote": 60}])).wav)
    late = samples(render(notes_spec(voice, [{"startBeat": 1, "midiNote": 60}])).wav)
    shift = RATE // 2
    assert late[:shift] == (0,) * shift
    assert late[shift:] == early[: len(late) - shift]


def test_the_seed_picks_the_pluck() -> None:
    spec = one_note(string())
    other = {**spec, "seed": 4}
    assert render(spec).wav == render(one_note(string())).wav
    assert render(other).wav != render(spec).wav
