"""Expressive notes in the render: touch, glide and late vibrato.

Each test renders through the product path and reads back audio or the in-core
features, because what the contract promises is sound: a harder note that is
brighter, a pitch that slides, a vibrato that waits before it blooms. A voice
without the blocks is the control in every case.
"""

from __future__ import annotations

import struct
from typing import Any

import blipsmith

RATE = 22050


def one_note(
    voice: dict[str, Any], velocity: float = 0.8, duration_ms: float = 1000
) -> dict[str, Any]:
    return {
        "version": 2,
        "seed": 3,
        "sampleRate": RATE,
        "channels": 1,
        "durationMs": duration_ms,
        "voices": [voice],
        "composition": {
            "tempoBpm": 120,
            "tracks": [{"notes": [{"startBeat": 0, "midiNote": 57, "velocity": velocity}]}],
        },
    }


def render(spec: dict[str, Any]) -> blipsmith.Rendered:
    return blipsmith.render_sound(spec)


def samples(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


# --- Touch ----------------------------------------------------------------------

BRIGHT = {
    "waveform": "saw",
    "ampEnv": {"attackMs": 40, "decayMs": 200, "sustainLevel": 0.7, "releaseMs": 50},
    "filter": {"type": "lowpass", "cutoffHz": 900, "resonance": 0.7},
    "fm": {"ratio": 1, "index": 1.0},
}


def test_touch_makes_a_harder_note_brighter() -> None:
    voice = {**BRIGHT, "touch": {"cutoffOctaves": 3, "fmIndex": 4}}
    soft = render(one_note(voice, velocity=0.3)).features["spectralCentroidHz"]
    hard = render(one_note(voice, velocity=0.9)).features["spectralCentroidHz"]
    plain_soft = render(one_note(BRIGHT, velocity=0.3)).features["spectralCentroidHz"]
    plain_hard = render(one_note(BRIGHT, velocity=0.9)).features["spectralCentroidHz"]
    assert hard > soft * 1.5
    # Without touch the render normalizes the level away and the tone is the same.
    assert plain_hard == plain_soft


def test_touch_makes_a_harder_note_attack_faster() -> None:
    voice = {**BRIGHT, "touch": {"attackOctaves": 3}}
    soft = render(one_note(voice, velocity=0.3)).features["attackTimeMs"]
    hard = render(one_note(voice, velocity=0.9)).features["attackTimeMs"]
    assert hard < soft


def test_at_the_pivot_touch_plays_the_voice_as_written() -> None:
    touch = {"pivot": 0.5, "cutoffOctaves": 3, "fmIndex": 4, "attackOctaves": 2}
    voice = {**BRIGHT, "touch": touch}
    assert render(one_note(voice, velocity=0.5)).wav == render(one_note(BRIGHT, velocity=0.5)).wav


def test_touch_with_no_amounts_is_the_voice_as_written() -> None:
    voice = {**BRIGHT, "touch": {}}
    assert render(one_note(voice, velocity=0.2)).wav == render(one_note(BRIGHT, velocity=0.2)).wav


def test_touch_only_moves_what_the_voice_has() -> None:
    # No filter and no FM: only the attack can move, so these amounts change nothing.
    plain = {"waveform": "triangle"}
    voice = {**plain, "touch": {"cutoffOctaves": 5, "fmIndex": 10}}
    assert render(one_note(voice, velocity=0.95)).wav == render(one_note(plain, velocity=0.95)).wav
