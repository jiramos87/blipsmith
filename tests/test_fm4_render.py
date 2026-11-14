"""Four-operator FM in the render.

Each test renders through the product path and reads back audio or the in-core
features: a lone carrier that is a plain sine, modulators that brighten only
what they feed, feedback that stays bounded, touch that reaches the modulators,
and phases that start on the note.
"""

from __future__ import annotations

import math
import struct
from typing import Any

import pytest

import blipsmith

RATE = 22050
SILENT: dict[str, Any] = {"level": 0}


def notes_spec(
    voice: dict[str, Any], notes: list[dict[str, Any]], duration_ms: float = 1200
) -> dict[str, Any]:
    return {
        "version": 2,
        "seed": 3,
        "sampleRate": RATE,
        "channels": 1,
        "durationMs": duration_ms,
        "voices": [voice],
        "composition": {"tempoBpm": 120, "tracks": [{"notes": notes}]},
    }


def one_note(voice: dict[str, Any], velocity: float = 0.8, midi: int = 57) -> dict[str, Any]:
    return notes_spec(voice, [{"startBeat": 0, "midiNote": midi, "velocity": velocity}])


def fm4(algorithm: int, *operators: dict[str, Any], feedback: float = 0.0) -> dict[str, Any]:
    return {
        "waveform": "sine",
        "ampEnv": {"attackMs": 2, "decayMs": 100, "sustainLevel": 0.8, "releaseMs": 60},
        "fm4": {"algorithm": algorithm, "feedback": feedback, "operators": list(operators)},
    }


def render(spec: dict[str, Any]) -> blipsmith.Rendered:
    return blipsmith.render_sound(spec)


def samples(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def centroid(voice: dict[str, Any], velocity: float = 0.8) -> float:
    return float(render(one_note(voice, velocity)).features["spectralCentroidHz"])


# --- Operators and algorithms ----------------------------------------------------


def test_a_lone_carrier_is_a_plain_sine() -> None:
    plain = fm4(0, SILENT, SILENT, SILENT, {})
    del plain["fm4"]
    lone = fm4(0, SILENT, SILENT, SILENT, {})
    assert render(one_note(lone)).wav == render(one_note(plain)).wav


def test_a_modulator_brightens_its_carrier() -> None:
    dull = fm4(0, SILENT, SILENT, SILENT, {})
    bright = fm4(0, SILENT, SILENT, {"level": 0.3}, {})
    assert centroid(bright) > centroid(dull) * 1.5


@pytest.mark.parametrize(("algorithm", "matters"), [(4, False), (6, False), (5, True)])
def test_a_modulator_only_reaches_what_it_feeds(algorithm: int, matters: bool) -> None:
    # Operator 2 is silent. In algorithms 4 and 6 operator 1 feeds only operator 2,
    # so its level cannot be heard; in 5 it also feeds the carriers 3 and 4.
    def voice(level: float) -> dict[str, Any]:
        return fm4(algorithm, {"level": level, "ratio": 3}, SILENT, {}, {"ratio": 2})

    quiet = render(one_note(voice(0.0))).wav
    loud = render(one_note(voice(0.6))).wav
    assert (quiet != loud) is matters


def test_carriers_mix_without_modulating_in_algorithm_seven() -> None:
    # Two carriers an octave apart: the octave is heard, and the centroid sits
    # between the two pitches rather than spreading the way modulation does.
    voice = fm4(7, {"ratio": 1}, {"ratio": 2}, SILENT, SILENT)
    hz = 220.0
    measured = centroid(voice)
    assert hz < measured < 2 * hz * 1.1


def test_a_fixed_operator_ignores_the_note() -> None:
    voice = fm4(0, SILENT, SILENT, SILENT, {"fixedHz": 440})
    assert render(one_note(voice, midi=48)).wav == render(one_note(voice, midi=72)).wav


def test_operators_follow_a_glide() -> None:
    voice = {**fm4(0, SILENT, SILENT, {"level": 0.2}, {}), "glide": {"timeMs": 200}}
    legato = [
        {"startBeat": 0, "midiNote": 57, "durationBeats": 1.0},
        {"startBeat": 1, "midiNote": 64, "durationBeats": 1.0},
    ]
    plain = {**voice}
    del plain["glide"]
    assert render(notes_spec(voice, legato)).wav != render(notes_spec(plain, legato)).wav


def test_phases_start_on_the_note() -> None:
    voice = fm4(
        4, {"level": 0.4, "ratio": 3.5}, {}, {"level": 0.2, "ratio": 1.01}, {}, feedback=0.4
    )
    early = samples(render(notes_spec(voice, [{"startBeat": 0, "midiNote": 60}])).wav)
    late = samples(render(notes_spec(voice, [{"startBeat": 1, "midiNote": 60}])).wav)
    shift = RATE // 2  # one beat at 120 BPM
    assert late[:shift] == (0,) * shift
    assert late[shift:] == early[: len(late) - shift]


def test_an_operator_envelope_decays_the_brightness() -> None:
    # A modulator that falls to nothing leaves the carrier plain by the end.
    voice = fm4(0, SILENT, SILENT, {"level": 0.4, "decayMs": 150, "sustainLevel": 0}, {})
    spec = notes_spec(voice, [{"startBeat": 0, "midiNote": 57, "durationBeats": 2}])
    pcm = samples(render(spec).wav)
    plain = samples(
        render(
            notes_spec(
                fm4(0, SILENT, SILENT, SILENT, {}), spec["composition"]["tracks"][0]["notes"]
            )
        ).wav
    )
    # Past the decay the modulated voice is a plain sine; only the normalizing
    # scale (set by the louder start) can differ, so compare shapes by sign.
    window = slice(int(0.5 * RATE), int(0.6 * RATE))
    assert [s > 0 for s in pcm[window]] == [s > 0 for s in plain[window]]
    assert pcm[: int(0.05 * RATE)] != plain[: int(0.05 * RATE)]


# --- Feedback ---------------------------------------------------------------------


def test_feedback_brightens_operator_one() -> None:
    clean = fm4(7, {}, SILENT, SILENT, SILENT)
    driven = fm4(7, {}, SILENT, SILENT, SILENT, feedback=0.8)
    assert centroid(driven) > centroid(clean) * 1.5


def test_the_loudest_legal_setting_stays_bounded() -> None:
    loud = {"ratio": 24, "level": 1, "detuneCents": 100}
    for algorithm in range(8):
        voice = {
            **fm4(algorithm, loud, loud, loud, loud, feedback=1.0),
            "touch": {"pivot": 0, "fmIndex": 24},
        }
        result = render(one_note(voice, velocity=1.0))
        assert all(
            math.isfinite(value) for value in result.features.values() if isinstance(value, float)
        )
        assert result.features["peakDbfs"] <= 0.0
        assert any(samples(result.wav))


# --- Touch --------------------------------------------------------------------------

PIANO = fm4(
    4,
    {"level": 0.15, "ratio": 1},
    {},
    {"level": 0.1, "ratio": 14, "decayMs": 300, "sustainLevel": 0},
    {},
)


def test_touch_makes_a_harder_note_brighter() -> None:
    voice = {**PIANO, "touch": {"pivot": 0.5, "fmIndex": 8}}
    assert centroid(voice, 0.95) > centroid(voice, 0.2) * 1.2


def test_at_the_pivot_touch_plays_the_voice_as_written() -> None:
    voice = {**PIANO, "touch": {"pivot": 0.5, "fmIndex": 8}}
    assert render(one_note(voice, 0.5)).wav == render(one_note(PIANO, 0.5)).wav


def test_touch_leaves_silent_modulators_and_carriers_alone() -> None:
    lone = fm4(0, SILENT, SILENT, SILENT, {})
    touched = {**lone, "touch": {"pivot": 0.2, "fmIndex": 20}}
    assert render(one_note(touched, 0.9)).wav == render(one_note(lone, 0.9)).wav
