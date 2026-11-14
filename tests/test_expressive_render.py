"""Expressive notes in the render: touch, glide and late vibrato.

Each test renders through the product path and reads back audio or the in-core
features, because what the contract promises is sound: a harder note that is
brighter, a pitch that slides, a vibrato that waits before it blooms. A voice
without the blocks is the control in every case.
"""

from __future__ import annotations

import struct
from itertools import pairwise
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


# --- Glide and late vibrato -------------------------------------------------------

FRAMES_PER_BEAT = RATE // 2  # 120 BPM

ORGAN = {
    "waveform": "square",
    "ampEnv": {"attackMs": 0, "decayMs": 0, "sustainLevel": 1, "releaseMs": 0},
}


def line(voice: dict[str, Any], notes: list[tuple[float, float, int]]) -> dict[str, Any]:
    """A one-track piece of (startBeat, durationBeats, midiNote) notes."""
    return {
        "version": 2,
        "seed": 3,
        "sampleRate": RATE,
        "channels": 1,
        "durationMs": 2000,
        "voices": [voice],
        "composition": {
            "tempoBpm": 120,
            "tracks": [
                {
                    "notes": [
                        {"startBeat": s, "durationBeats": d, "midiNote": m, "velocity": 0.8}
                        for s, d, m in notes
                    ]
                }
            ],
        },
    }


def crossings(pcm: tuple[int, ...], start: int, stop: int) -> list[int]:
    """Frames where a square wave turns from low to high, between two frames."""
    return [i for i in range(max(start, 1), stop) if pcm[i - 1] < 0 <= pcm[i]]


def rising_edges(spec: dict[str, Any], start: int, stop: int) -> int:
    return len(crossings(samples(render(spec).wav), start, stop))


TOUCHING = [(0, 1, 57), (1, 1, 64)]
DETACHED = [(0, 0.5, 57), (1, 1, 64)]


def test_legato_glide_slides_a_touching_pair_up_from_the_previous_pitch() -> None:
    glide = {**ORGAN, "glide": {"timeMs": 300}}
    window = (FRAMES_PER_BEAT, FRAMES_PER_BEAT + RATE // 10)
    slid = rising_edges(line(glide, TOUCHING), *window)
    plain = rising_edges(line(ORGAN, TOUCHING), *window)
    assert slid < plain
    # Once landed, the note runs at its own pitch.
    late = (FRAMES_PER_BEAT + RATE // 2, 2 * FRAMES_PER_BEAT + RATE // 4)
    assert (
        abs(rising_edges(line(glide, TOUCHING), *late) - rising_edges(line(ORGAN, TOUCHING), *late))
        <= 1
    )


def test_legato_glide_leaves_a_detached_pair_alone() -> None:
    glide = {**ORGAN, "glide": {"timeMs": 300, "mode": "legato"}}
    assert render(line(glide, DETACHED)).wav == render(line(ORGAN, DETACHED)).wav


def test_always_glide_slides_a_detached_pair() -> None:
    glide = {**ORGAN, "glide": {"timeMs": 300, "mode": "always"}}
    assert render(line(glide, DETACHED)).wav != render(line(ORGAN, DETACHED)).wav


def test_a_first_note_and_a_repeated_pitch_do_not_glide() -> None:
    glide = {**ORGAN, "glide": {"timeMs": 300, "mode": "always"}}
    for notes in ([(0, 1, 57)], [(0, 1, 57), (1, 1, 57)]):
        assert render(line(glide, notes)).wav == render(line(ORGAN, notes)).wav


def test_a_chord_glides_from_the_top_note_of_the_previous_chord() -> None:
    # The second note at beat 1 glides from 64 (the top of the first chord), so
    # it is the same as a line that glides from 64 alone.
    glide = {**ORGAN, "glide": {"timeMs": 300}}
    chord = render(line(glide, [(0, 1, 52), (0, 1, 64), (1, 1, 60)])).wav
    top_only = render(line(glide, [(0, 1, 64), (1, 1, 60)])).wav
    low_only = render(line(ORGAN, [(0, 1, 52)])).wav
    pcm = samples(chord)
    expected = [a + b for a, b in zip(samples(top_only), samples(low_only), strict=True)]
    after = range(FRAMES_PER_BEAT, 2 * FRAMES_PER_BEAT)
    # Normalization differs between the renders; compare the second note's shape.
    assert crossings(pcm, after.start, after.stop) == crossings(
        tuple(expected), after.start, after.stop
    )


VIBRATO = {"delayMs": 300, "fadeMs": 300, "rateHz": 6, "depthCents": 60}


def test_late_vibrato_waits_for_its_delay() -> None:
    voice = {**ORGAN, "vibrato": VIBRATO}
    held = [(0, 3, 57)]
    with_it = samples(render(line(voice, held)).wav)
    without = samples(render(line(ORGAN, held)).wav)
    delay = RATE * 300 // 1000
    assert with_it[:delay] == without[:delay]
    assert with_it[delay : delay + RATE // 2] != without[delay : delay + RATE // 2]


def test_late_vibrato_fades_in() -> None:
    voice = {**ORGAN, "vibrato": VIBRATO}
    pcm = samples(render(line(voice, [(0, 3, 57)])).wav)
    delay = RATE * 300 // 1000

    def swing(start: int, stop: int) -> int:
        edges = crossings(pcm, start, stop)
        periods = [b - a for a, b in pairwise(edges)]
        return max(periods) - min(periods)

    early = swing(delay, delay + RATE // 12)  # the first 80 ms of the fade
    full = swing(delay + RATE * 300 // 1000, delay + RATE * 600 // 1000)
    assert full > early


def test_vibrato_with_no_depth_is_the_voice_as_written() -> None:
    voice = {**ORGAN, "vibrato": {**VIBRATO, "depthCents": 0}}
    assert render(line(voice, [(0, 3, 57)])).wav == render(line(ORGAN, [(0, 3, 57)])).wav
