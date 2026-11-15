"""Modal banks in the render.

Each test renders through the product path and reads back audio or the in-core
features: a mode in tune across the range, a decay that falls 60 dB in its time,
a brightness and a touch that shape the tone, modes that follow a pitch drop,
every extreme setting bounded, and a hit that renders the same wherever it sits.
Renders are normalized, so levels are compared inside one render.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence
from typing import Any

import pytest

import blipsmith

RATE = 22050
CONGA = [(1.0, 1.0, 400), (1.59, 0.6, 250), (2.14, 0.5, 200), (2.30, 0.4, 160), (2.65, 0.3, 120)]


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


def modal(modes: Sequence[tuple[float, float, float]], **settings: Any) -> dict[str, Any]:
    bank = [{"ratio": r, "level": level, "decayMs": d} for r, level, d in modes]
    return {
        "waveform": "sine",
        "ampEnv": {"attackMs": 0, "decayMs": 0, "sustainLevel": 1, "releaseMs": 150},
        "modal": {**settings, "modes": bank},
    }


def render(spec: dict[str, Any]) -> blipsmith.Rendered:
    return blipsmith.render_sound(spec)


def samples(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def rms(pcm: tuple[int, ...], start_s: float, end_s: float, rate: int = RATE) -> float:
    window = pcm[int(start_s * rate) : int(end_s * rate)]
    return math.sqrt(sum(value * value for value in window) / len(window))


def centroid(voice: dict[str, Any], velocity: float = 0.8, midi: int = 57) -> float:
    return float(render(one_note(voice, velocity, midi)).features["spectralCentroidHz"])


def midi_hz(midi: int) -> float:
    return float(440.0 * 2.0 ** ((midi - 69) / 12))


# --- Pitch and decay ----------------------------------------------------------------


@pytest.mark.parametrize("midi", [45, 69, 93])
def test_one_mode_rings_in_tune(midi: int) -> None:
    spec = one_note(modal([(1.0, 1.0, 3000)]), midi=midi)
    spec["sampleRate"] = 44100
    measured = render(spec).features["estimatedFundamentalHz"]
    assert abs(1200 * math.log2(measured / midi_hz(midi))) < 10


def test_a_mode_falls_sixty_decibels_over_its_decay_time() -> None:
    # 20 dB over a third of the decay time, measured between two windows.
    pcm = samples(render(one_note(modal([(1.0, 1.0, 1500)], brightness=0.2))).wav)
    fall = 20 * math.log10(rms(pcm, 0.1, 0.2) / rms(pcm, 0.6, 0.7))
    assert 19 < fall < 21


def test_a_ratio_sets_the_mode_above_the_pitch() -> None:
    low = centroid(modal([(1.0, 1.0, 800)]))
    high = centroid(modal([(2.5, 1.0, 800)]))
    assert 2.3 < high / low < 2.7


def test_the_modes_add_at_their_levels() -> None:
    one = render(one_note(modal([(1.0, 1.0, 800)]))).wav
    quiet_second = render(one_note(modal([(1.0, 1.0, 800), (3.1, 0.0, 800)]))).wav
    assert quiet_second == one
    assert render(one_note(modal([(1.0, 1.0, 800), (3.1, 0.5, 800)]))).wav != one


# --- Brightness and pitch movement ----------------------------------------------------


def test_brightness_rings_the_upper_modes() -> None:
    dull = modal(CONGA, brightness=0.05)
    bright = modal(CONGA, brightness=1)
    assert centroid(bright, midi=69) > centroid(dull, midi=69) * 1.1


def test_the_modes_follow_a_pitch_drop() -> None:
    plain = modal(CONGA)
    dropped = {**plain, "modEnv": {"target": "pitch", "amount": -0.3, "attackMs": 0, "decayMs": 80}}
    assert render(one_note(dropped)).wav != render(one_note(plain)).wav


def test_a_keyless_bank_follows_a_glide() -> None:
    voice = {**modal([(1.0, 1.0, 2000), (4.0, 0.3, 800)]), "glide": {"timeMs": 300}}
    legato = [
        {"startBeat": 0, "midiNote": 57, "durationBeats": 1.0},
        {"startBeat": 1, "midiNote": 64, "durationBeats": 1.0},
    ]
    plain = modal([(1.0, 1.0, 2000), (4.0, 0.3, 800)])
    glided = samples(render(notes_spec(voice, legato)).wav)
    straight = samples(render(notes_spec(plain, legato)).wav)
    half = RATE // 2
    signs = [[value > 0 for value in pcm] for pcm in (glided, straight)]
    assert signs[0][:half] == signs[1][:half]
    assert signs[0][half:] != signs[1][half:]


def test_a_mode_above_the_ceiling_is_silent() -> None:
    # A mode at 31 x A6 is far above Nyquist at 22050: it adds nothing.
    alone = render(one_note(modal([(1.0, 1.0, 800)]), midi=93)).wav
    with_high = render(one_note(modal([(1.0, 1.0, 800), (31.0, 1.0, 800)]), midi=93)).wav
    assert with_high == alone


# --- Bounds -------------------------------------------------------------------------


@pytest.mark.parametrize("rate", [8000, 22050, 44100])
def test_the_loudest_and_longest_setting_stays_bounded(rate: int) -> None:
    voice = {
        **modal([(1.0 + 0.37 * i, 1.0, 30000) for i in range(16)], brightness=1),
        "vibrato": {"delayMs": 0, "fadeMs": 0, "rateHz": 20, "depthCents": 200},
        "glide": {"timeMs": 5000, "mode": "always"},
        "modEnv": {"target": "pitch", "amount": -2, "attackMs": 0, "decayMs": 50},
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

TOUCHED = {**modal(CONGA, brightness=0.2), "touch": {"pivot": 0.5, "cutoffOctaves": 5}}


def test_touch_makes_a_harder_hit_brighter() -> None:
    assert centroid(TOUCHED, 0.95, midi=69) > centroid(TOUCHED, 0.15, midi=69) * 1.2


def test_at_the_pivot_touch_plays_the_bank_as_written() -> None:
    plain = modal(CONGA, brightness=0.2)
    assert render(one_note(TOUCHED, 0.5)).wav == render(one_note(plain, 0.5)).wav


# --- Kit and determinism --------------------------------------------------------------


def test_a_keyed_bank_plays_its_own_pitch() -> None:
    voice = {**modal(CONGA), "key": 63, "fundamentalHz": 330}
    one = render(notes_spec(voice, [{"startBeat": 0, "midiNote": 63}])).wav
    other = {**voice, "key": 64}
    two = render(notes_spec(other, [{"startBeat": 0, "midiNote": 64}])).wav
    assert one == two


def test_a_hit_renders_the_same_wherever_it_sits() -> None:
    voice = modal(CONGA)
    early = samples(render(notes_spec(voice, [{"startBeat": 0, "midiNote": 60}])).wav)
    late = samples(render(notes_spec(voice, [{"startBeat": 1, "midiNote": 60}])).wav)
    shift = RATE // 2
    assert late[:shift] == (0,) * shift
    assert late[shift:] == early[: len(late) - shift]
