"""B02: every documented numeric bound, exercised on both sides.

The parametrized cases are generated from `RANGES` itself rather than written
out by hand. A parameter added in a later item without a documented range fails
`test_every_numeric_field_has_a_documented_range`, and a parameter added *with*
one is automatically covered below. Coverage cannot quietly fall behind the
model.
"""

from __future__ import annotations

from typing import Any, get_origin

import pytest
from pydantic import BaseModel

from blipsmith import spec as spec_module
from blipsmith.ranges import RANGES, NumericRange
from blipsmith.result import WarningCode
from blipsmith.spec import (
    SpecModel,
    clamp_model,
    closed_set_values,
    unwrap_annotation,
)

MODELS: dict[str, type[BaseModel]] = {
    name: obj
    for name, obj in vars(spec_module).items()
    if isinstance(obj, type) and issubclass(obj, SpecModel) and obj is not SpecModel
}

RANGE_KEYS = sorted(RANGES)


def _minimal_kwargs(model: type[BaseModel]) -> dict[str, Any]:
    """Fill only what the model refuses to be built without."""
    kwargs: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if not field.is_required():
            continue
        annotation = unwrap_annotation(field.annotation)
        values = closed_set_values(annotation)
        if values:
            kwargs[name] = values[0]
        elif annotation is float:
            kwargs[name] = 0.0
        elif annotation is int:
            kwargs[name] = 0
        else:
            kwargs[name] = ""
    return kwargs


def _is_list(model_name: str, field_name: str) -> bool:
    """A list of numbers (a wavetable frame's harmonics) clamps entry by entry."""
    return get_origin(MODELS[model_name].model_fields[field_name].annotation) is list


def _build(model_name: str, field_name: str, value: float) -> BaseModel:
    model = MODELS[model_name]
    kwargs = _minimal_kwargs(model)
    kwargs[field_name] = [value] if _is_list(model_name, field_name) else value
    return model(**kwargs)


def _read(model: BaseModel, field_name: str) -> Any:
    value = getattr(model, field_name)
    return value[0] if isinstance(value, list) else value


def _param(model_name: str, field_name: str) -> str:
    return f"{field_name}[0]" if _is_list(model_name, field_name) else field_name


def _ids(key: tuple[str, str]) -> str:
    return f"{key[0]}.{key[1]}"


@pytest.mark.parametrize("key", RANGE_KEYS, ids=_ids)
def test_clamps_below_minimum(key: tuple[str, str]) -> None:
    model_name, field_name = key
    bounds = RANGES[key]
    requested = bounds.minimum - 1

    clamped, warnings = clamp_model(_build(model_name, field_name, requested))

    assert _read(clamped, field_name) == bounds.minimum
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.code is WarningCode.CLAMPED
    assert warning.param == _param(model_name, field_name)
    assert warning.requested == requested
    assert warning.applied == bounds.minimum


@pytest.mark.parametrize("key", RANGE_KEYS, ids=_ids)
def test_clamps_above_maximum(key: tuple[str, str]) -> None:
    model_name, field_name = key
    bounds = RANGES[key]
    requested = bounds.maximum + 1

    clamped, warnings = clamp_model(_build(model_name, field_name, requested))

    assert _read(clamped, field_name) == bounds.maximum
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.code is WarningCode.CLAMPED
    assert warning.param == _param(model_name, field_name)
    assert warning.requested == requested
    assert warning.applied == bounds.maximum


@pytest.mark.parametrize("key", RANGE_KEYS, ids=_ids)
def test_inclusive_bounds_are_not_clamped(key: tuple[str, str]) -> None:
    """The bounds themselves are legal values; only past them is a clamp."""
    model_name, field_name = key
    bounds = RANGES[key]

    for edge in (bounds.minimum, bounds.maximum):
        clamped, warnings = clamp_model(_build(model_name, field_name, edge))
        assert _read(clamped, field_name) == edge
        assert warnings == [], f"{_ids(key)} warned at its own bound {edge}"


@pytest.mark.parametrize("key", RANGE_KEYS, ids=_ids)
def test_range_table_is_coherent(key: tuple[str, str]) -> None:
    bounds = RANGES[key]
    assert bounds.minimum < bounds.maximum
    assert bounds.contains(bounds.default), "default sits outside its own range"
    if bounds.integer:
        for value in (bounds.minimum, bounds.maximum, bounds.default):
            assert float(value).is_integer(), f"{_ids(key)} is integer but {value} is not"


def test_every_numeric_field_has_a_documented_range() -> None:
    """The PRD promises every numeric parameter has a documented valid range."""
    undocumented: list[str] = []
    for model_name, model in MODELS.items():
        for field_name, field in model.model_fields.items():
            annotation = unwrap_annotation(field.annotation)
            if closed_set_values(annotation) is not None:
                continue
            if not isinstance(annotation, type):
                continue
            if annotation is bool or not issubclass(annotation, int | float):
                continue
            if (model_name, field_name) not in RANGES:
                undocumented.append(f"{model_name}.{field_name}")

    assert not undocumented, f"numeric fields with no documented range: {undocumented}"


def test_clamp_rejects_non_finite_values() -> None:
    """NaN and infinity have no nearest bound, and would poison canonical JSON."""
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(Exception, match="finite"):
            clamp_model(_build("Adsr", "attackMs", value))


def test_numeric_range_clamp_is_inclusive() -> None:
    bounds = NumericRange(0.0, 1.0, 0.5)
    assert bounds.clamp(-0.5) == 0.0
    assert bounds.clamp(1.5) == 1.0
    assert bounds.clamp(0.0) == 0.0
    assert bounds.clamp(1.0) == 1.0
    assert bounds.contains(0.0) and bounds.contains(1.0)
    assert not bounds.contains(1.000001)


def test_integer_ranges_round_to_int() -> None:
    bounds = NumericRange(1, 16, 8, integer=True)
    assert bounds.clamp(7.6) == 8
    assert isinstance(bounds.clamp(7.6), int)
