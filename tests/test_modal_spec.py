"""A modal bank in the spec: `modal` is a music-mode voice block.

It is additive to version 2. A spec that never names it dumps exactly as it did,
a version 1 spec that names it is a typed error, and it replaces the oscillator,
so it cannot sit beside `fm`, `fm4` or `string` or on a waveform other than sine.
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


def test_unset_modal_is_left_out_of_the_dump() -> None:
    canonical = json.loads(to_canonical_json(parse_spec(music())))
    assert "modal" not in canonical["voices"][0]


def test_modal_on_version_one_is_a_typed_error() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{"waveform": "sine", "modal": {}}]})
    assert caught.value.error.field == "voices[0].modal"
    assert "version to 2" in caught.value.error.message


def test_modal_materializes_its_defaults() -> None:
    voice = json.loads(to_canonical_json(parse_spec(music({"waveform": "sine", "modal": {}}))))[
        "voices"
    ][0]
    assert voice["modal"] == {
        "brightness": 0.6,
        "modes": [{"ratio": 1.0, "level": 1.0, "decayMs": 500.0}],
    }


@pytest.mark.parametrize("count", [0, 17])
def test_a_bank_holds_one_to_sixteen_modes(count: int) -> None:
    modes = [{"ratio": 1 + i} for i in range(count)]
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "modal": {"modes": modes}}))
    assert caught.value.error.field == "voices[0].modal.modes"


def test_sixteen_modes_parse() -> None:
    modes = [{"ratio": 1 + i} for i in range(16)]
    spec = parse_spec(music({"waveform": "sine", "modal": {"modes": modes}}))
    modal = spec.voices[0].modal
    assert modal is not None
    assert len(modal.modes) == 16


@pytest.mark.parametrize("other", ["fm", "fm4", "string"])
def test_a_modal_bank_beside_another_tone_is_a_typed_error(other: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", other: {}, "modal": {}}))
    assert caught.value.error.field in (
        "voices[0].modal",
        "voices[0].fm4",
        "voices[0].string",
    )


def test_a_modal_bank_needs_a_sine_waveform() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "noise_white", "modal": {}}))
    assert caught.value.error.field == "voices[0].waveform"


def test_a_modal_bank_sits_beside_touch_glide_vibrato_a_filter_and_a_key() -> None:
    parse_spec(
        music(
            {
                "waveform": "sine",
                "modal": {"brightness": 0.3},
                "touch": {},
                "vibrato": {},
                "modEnv": {"target": "pitch"},
                "filter": {"type": "highpass"},
                "key": 63,
            },
            {"waveform": "sine", "modal": {}, "glide": {}},
        )
    )


@pytest.mark.parametrize(
    ("path", "asked", "applied"),
    [
        (("brightness",), -0.5, 0.0),
        (("brightness",), 1.5, 1.0),
        (("modes", 0, "ratio"), 0.01, 0.1),
        (("modes", 0, "ratio"), 64, 32.0),
        (("modes", 0, "level"), 2, 1.0),
        (("modes", 0, "decayMs"), 1, 5.0),
        (("modes", 0, "decayMs"), 60_000, 30_000.0),
    ],
)
def test_out_of_range_values_clamp_with_a_warning(
    path: tuple[str | int, ...], asked: float, applied: float
) -> None:
    block: dict[str, Any] = {"modes": [{}]}
    if path[0] == "brightness":
        block["brightness"] = asked
        param = "voices[0].modal.brightness"
    else:
        block["modes"][0][path[2]] = asked
        param = f"voices[0].modal.modes[0].{path[2]}"
    spec, warnings = validate_spec(music({"waveform": "sine", "modal": block}))
    assert [w.param for w in warnings] == [param]
    modal = spec.voices[0].modal
    assert modal is not None
    value = modal.brightness if path[0] == "brightness" else getattr(modal.modes[0], str(path[2]))
    assert value == applied


def test_schema_publishes_the_modal_block() -> None:
    schema = get_schema()
    assert "modal" in schema["models"]["Voice"]["fields"]
    assert schema["models"]["Modal"]["fields"]["brightness"]["maximum"] == 1
    mode = schema["models"]["Mode"]["fields"]
    assert mode["ratio"]["maximum"] == 32
    assert mode["decayMs"]["minimum"] == 5
