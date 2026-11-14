"""Strings in the spec: `string` is a music-mode voice block.

It is additive to version 2. A spec that never names it dumps exactly as it did,
a version 1 spec that names it is a typed error, and it replaces the oscillator,
so it cannot sit beside `fm` or `fm4` or on a waveform other than sine.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from blipsmith.result import SpecError
from blipsmith.schema import get_schema
from blipsmith.spec import parse_spec, to_canonical_json, validate_spec


def music(*voices: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "voices": list(voices) or [{"waveform": "sine"}],
        "composition": {"tracks": [{}]},
    }


def test_unset_string_is_left_out_of_the_dump() -> None:
    canonical = json.loads(to_canonical_json(parse_spec(music())))
    assert "string" not in canonical["voices"][0]


def test_string_on_version_one_is_a_typed_error() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{"waveform": "sine", "string": {}}]})
    assert caught.value.error.field == "voices[0].string"
    assert "version to 2" in caught.value.error.message


def test_string_materializes_its_defaults() -> None:
    voice = json.loads(to_canonical_json(parse_spec(music({"waveform": "sine", "string": {}}))))[
        "voices"
    ][0]
    assert voice["string"] == {
        "excitation": "pluck",
        "position": 0.2,
        "brightness": 0.6,
        "decayMs": 2500.0,
        "damping": 0.5,
        "body": 0.0,
        "bodyHz": 200.0,
    }


def test_the_excitation_is_a_closed_set() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "string": {"excitation": "bow"}}))
    assert caught.value.error.validValues == ["pluck", "strike"]


@pytest.mark.parametrize("other", ["fm", "fm4"])
def test_a_string_beside_fm_is_a_typed_error(other: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", other: {}, "string": {}}))
    assert caught.value.error.field in ("voices[0].string", "voices[0].fm4")


def test_a_string_needs_a_sine_waveform() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "square", "string": {}}))
    assert caught.value.error.field == "voices[0].waveform"


def test_a_string_sits_beside_touch_glide_vibrato_a_filter_and_a_key() -> None:
    parse_spec(
        music(
            {
                "waveform": "sine",
                "string": {"excitation": "strike"},
                "touch": {},
                "glide": {},
                "vibrato": {},
                "filter": {"type": "lowpass"},
            }
        )
    )


@pytest.mark.parametrize(
    ("field", "asked", "applied"),
    [
        ("position", 0.0, 0.02),
        ("position", 0.9, 0.5),
        ("brightness", 1.5, 1.0),
        ("decayMs", 10, 50.0),
        ("decayMs", 60_000, 30_000.0),
        ("damping", -1, 0.0),
        ("body", 2, 1.0),
        ("bodyHz", 10, 60.0),
        ("bodyHz", 9000, 2000.0),
    ],
)
def test_out_of_range_values_clamp_with_a_warning(field: str, asked: float, applied: float) -> None:
    spec, warnings = validate_spec(music({"waveform": "sine", "string": {field: asked}}))
    assert [w.param for w in warnings] == [f"voices[0].string.{field}"]
    string = spec.voices[0].string
    assert string is not None
    assert getattr(string, field) == applied


def test_schema_publishes_the_string_block() -> None:
    schema = get_schema()
    voice = schema["models"]["Voice"]
    assert "string" in voice["fields"]
    string = schema["models"]["String"]["fields"]
    assert string["excitation"]["enum"] == ["pluck", "strike"]
    assert string["decayMs"]["maximum"] == 30_000
