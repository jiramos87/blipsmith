"""Expressive notes in the spec: touch, glide and vibrato are music-mode voice blocks.

They are additive to version 2. A spec that never names them dumps exactly as it
did, a version 1 spec that names one is a typed error, and a kit voice cannot
glide because it plays its own pitch on every hit.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from blipsmith.explain import explain_spec
from blipsmith.result import SpecError
from blipsmith.schema import get_schema
from blipsmith.session import Session
from blipsmith.spec import parse_spec, to_canonical_json, validate_spec

BLOCKS = ("touch", "glide", "vibrato")


def music(*voices: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "voices": list(voices) or [{"waveform": "sine"}],
        "composition": {"tracks": [{}]},
    }


def test_unset_blocks_are_left_out_of_the_dump() -> None:
    canonical = json.loads(to_canonical_json(parse_spec(music())))
    assert not any(block in canonical["voices"][0] for block in BLOCKS)


@pytest.mark.parametrize("block", BLOCKS)
def test_a_block_on_version_one_is_a_typed_error(block: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{"waveform": "sine", block: {}}]})
    assert caught.value.error.field == f"voices[0].{block}"
    assert "version to 2" in caught.value.error.message


def test_blocks_materialize_their_defaults() -> None:
    spec = parse_spec(music({"waveform": "sine", "touch": {}, "glide": {}, "vibrato": {}}))
    voice = json.loads(to_canonical_json(spec))["voices"][0]
    assert voice["touch"] == {
        "pivot": 0.6,
        "fmIndex": 0.0,
        "cutoffOctaves": 0.0,
        "attackOctaves": 0.0,
    }
    assert voice["glide"] == {"timeMs": 80.0, "mode": "legato"}
    assert voice["vibrato"] == {
        "delayMs": 250.0,
        "fadeMs": 300.0,
        "rateHz": 5.5,
        "depthCents": 20.0,
    }


def test_glide_mode_is_a_closed_set() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "glide": {"mode": "portamento"}}))
    assert caught.value.error.validValues == ["legato", "always"]


def test_a_kit_voice_cannot_glide() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "key": 36, "glide": {}}))
    assert caught.value.error.field == "voices[0].glide"


def test_a_kit_voice_may_have_touch_and_vibrato() -> None:
    parse_spec(music({"waveform": "sine", "key": 38, "touch": {}, "vibrato": {}}))


@pytest.mark.parametrize(
    ("block", "field", "asked", "applied"),
    [
        ("touch", "pivot", 1.5, 1.0),
        ("touch", "fmIndex", -30, -24.0),
        ("touch", "cutoffOctaves", 9, 8.0),
        ("touch", "attackOctaves", -9, -8.0),
        ("glide", "timeMs", 6000, 5000.0),
        ("vibrato", "delayMs", -1, 0.0),
        ("vibrato", "fadeMs", 20000, 10000.0),
        ("vibrato", "rateHz", 0, 0.1),
        ("vibrato", "depthCents", 500, 200.0),
    ],
)
def test_out_of_range_values_clamp_with_a_warning(
    block: str, field: str, asked: float, applied: float
) -> None:
    spec, warnings = validate_spec(music({"waveform": "sine", block: {field: asked}}))
    assert getattr(getattr(spec.voices[0], block), field) == applied
    assert [w.param for w in warnings] == [f"voices[0].{block}.{field}"]


def test_schema_publishes_the_blocks_as_music_fields() -> None:
    schema = get_schema()
    voice = schema["models"]["Voice"]["fields"]
    for block in BLOCKS:
        assert voice[block]["musicMode"] is True
    assert schema["models"]["Glide"]["fields"]["mode"]["enum"] == ["legato", "always"]
    assert schema["models"]["Vibrato"]["fields"]["depthCents"]["unit"] == "cents"


# --- The session verbs and the explanation -----------------------------------------


def music_session() -> Session:
    session = Session()
    session.new_voice("saw")
    session.set_render_options(version=2)
    return session


def test_the_setters_patch_each_block_from_its_defaults() -> None:
    session = music_session()
    session.set_touch(cutoffOctaves=2.0)
    session.set_touch(pivot=0.4)
    session.set_glide(mode="always")
    session.set_vibrato(depthCents=30.0)
    voice = session.spec.voices[0]
    assert voice.touch is not None and voice.glide is not None and voice.vibrato is not None
    assert (voice.touch.pivot, voice.touch.cutoffOctaves) == (0.4, 2.0)
    assert (voice.glide.timeMs, voice.glide.mode.value) == (80.0, "always")
    assert (voice.vibrato.depthCents, voice.vibrato.delayMs) == (30.0, 250.0)


def test_clear_removes_a_block() -> None:
    session = music_session()
    session.set_vibrato(depthCents=30.0)
    session.set_vibrato(clear=True)
    assert session.spec.voices[0].vibrato is None


def test_the_setters_are_refused_on_version_one() -> None:
    session = Session()
    session.new_voice("saw")
    with pytest.raises(SpecError) as caught:
        session.set_glide(timeMs=50.0)
    assert caught.value.error.field == "version"
    assert session.spec.voices[0].glide is None


def test_the_explanation_names_each_block() -> None:
    spec = parse_spec(
        music(
            {
                "waveform": "saw",
                "filter": {"type": "lowpass"},
                "touch": {"cutoffOctaves": 2, "attackOctaves": 1},
                "glide": {"timeMs": 60},
                "vibrato": {"depthCents": 25},
            }
        )
    )
    text = explain_spec(spec)
    assert "touch moving the cutoff and attack with velocity (as written at 0.6)" in text
    assert "a 60 ms legato glide" in text
    assert "a 25 cent vibrato at 5.5 Hz that starts after 250 ms" in text
