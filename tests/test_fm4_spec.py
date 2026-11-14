"""Four-operator FM in the spec: `fm4` is a music-mode voice block.

It is additive to version 2. A spec that never names it dumps exactly as it did,
a version 1 spec that names it is a typed error, and it replaces the oscillator,
so it cannot sit beside the two-operator `fm` or on a waveform other than sine.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from blipsmith.ranges import FM4_ALGORITHMS, FM4_OPERATORS
from blipsmith.result import SpecError
from blipsmith.schema import get_schema
from blipsmith.spec import parse_spec, to_canonical_json, validate_spec


def music(*voices: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": 2,
        "voices": list(voices) or [{"waveform": "sine"}],
        "composition": {"tracks": [{}]},
    }


def test_unset_fm4_is_left_out_of_the_dump() -> None:
    canonical = json.loads(to_canonical_json(parse_spec(music())))
    assert "fm4" not in canonical["voices"][0]


def test_fm4_on_version_one_is_a_typed_error() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{"waveform": "sine", "fm4": {}}]})
    assert caught.value.error.field == "voices[0].fm4"
    assert "version to 2" in caught.value.error.message


def test_fm4_materializes_four_default_operators() -> None:
    voice = json.loads(to_canonical_json(parse_spec(music({"waveform": "sine", "fm4": {}}))))[
        "voices"
    ][0]
    operator = {
        "ratio": 1.0,
        "detuneCents": 0.0,
        "level": 1.0,
        "attackMs": 0.0,
        "decayMs": 0.0,
        "sustainLevel": 1.0,
    }
    assert voice["fm4"] == {"algorithm": 0, "feedback": 0.0, "operators": [operator] * 4}


def test_a_fixed_frequency_is_dumped_only_when_set() -> None:
    operators = [{"fixedHz": 1200}, {}, {}, {}]
    voice = json.loads(
        to_canonical_json(parse_spec(music({"waveform": "sine", "fm4": {"operators": operators}})))
    )["voices"][0]
    assert voice["fm4"]["operators"][0]["fixedHz"] == 1200
    assert "fixedHz" not in voice["fm4"]["operators"][1]


@pytest.mark.parametrize("count", [3, 5])
def test_exactly_four_operators(count: int) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "fm4": {"operators": [{}] * count}}))
    assert caught.value.error.field == "voices[0].fm4.operators"


def test_the_algorithm_is_a_closed_set() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "fm4": {"algorithm": 8}}))
    assert caught.value.error.validValues == list(range(8))


def test_fm_and_fm4_together_is_a_typed_error() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "fm": {}, "fm4": {}}))
    assert caught.value.error.field == "voices[0].fm4"


def test_fm4_needs_a_sine_waveform() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "saw", "fm4": {}}))
    assert caught.value.error.field == "voices[0].waveform"


def test_fm4_sits_beside_touch_glide_vibrato_and_a_filter() -> None:
    parse_spec(
        music(
            {
                "waveform": "sine",
                "fm4": {},
                "touch": {},
                "glide": {},
                "vibrato": {},
                "filter": {"type": "lowpass"},
            }
        )
    )


@pytest.mark.parametrize(
    ("path", "asked", "applied"),
    [
        (("feedback",), 2, 1.0),
        (("operators", 0, "ratio"), 40, 24.0),
        (("operators", 1, "fixedHz"), 0.5, 1.0),
        (("operators", 2, "detuneCents"), -300, -100.0),
        (("operators", 3, "level"), 1.5, 1.0),
        (("operators", 0, "attackMs"), -1, 0.0),
        (("operators", 1, "decayMs"), 20000, 10000.0),
        (("operators", 2, "sustainLevel"), 2, 1.0),
    ],
)
def test_out_of_range_values_clamp_with_a_warning(
    path: tuple[str | int, ...], asked: float, applied: float
) -> None:
    block: dict[str, Any] = {"operators": [{}, {}, {}, {}]}
    if path[0] == "feedback":
        block["feedback"] = asked
        expected = "voices[0].fm4.feedback"
    else:
        _, index, field = path
        assert isinstance(index, int) and isinstance(field, str)
        block["operators"][index][field] = asked
        expected = f"voices[0].fm4.operators[{index}].{field}"
    spec, warnings = validate_spec(music({"waveform": "sine", "fm4": block}))
    assert [w.param for w in warnings] == [expected]
    fm4 = spec.voices[0].fm4
    assert fm4 is not None
    if path[0] == "feedback":
        assert fm4.feedback == applied
    else:
        assert getattr(fm4.operators[path[1]], str(path[2])) == applied  # type: ignore[index]


def test_schema_publishes_fm4_and_its_algorithms() -> None:
    schema = get_schema()
    assert schema["models"]["Voice"]["fields"]["fm4"]["musicMode"] is True
    assert schema["models"]["Fm4"]["fields"]["algorithm"]["enum"] == list(range(8))
    assert schema["models"]["Operator"]["fields"]["fixedHz"]["nullable"] is True
    music_limits = schema["limits"]["music"]
    assert music_limits["fm4Operators"] == FM4_OPERATORS
    assert len(music_limits["fm4Algorithms"]) == 8
    assert music_limits["fm4Algorithms"][4] == {
        "modulators": [[], [1], [], [3]],
        "carriers": [2, 4],
    }


@pytest.mark.parametrize("algorithm", range(8))
def test_every_modulator_comes_before_what_it_feeds(algorithm: int) -> None:
    routing, carriers = FM4_ALGORITHMS[algorithm]
    for target, feeds in enumerate(routing, start=1):
        assert all(1 <= source < target for source in feeds)
    assert carriers and all(1 <= carrier <= FM4_OPERATORS for carrier in carriers)
    # Every operator is heard or feeds something that is.
    used = set(carriers) | {source for feeds in routing for source in feeds}
    assert used == {1, 2, 3, 4}
