"""The published SoundSpec schema.

The driving agent cannot hear and cannot experiment cheaply, so the schema has
to be complete enough to author a valid spec on the first try: every field with
its type, its bounds or its closed set, its default, and a sentence on what it
does. This is what the MCP `get_schema` verb returns.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from blipsmith.ranges import (
    DURATION_MS_COMPOSITION,
    MASTER_EFFECT_KINDS,
    MAX_CUTOFF_FRACTION,
    MAX_VOICES,
    MUSIC_MAX_TRACKS,
    MUSIC_MAX_VOICES,
    MUSIC_SPEC_VERSION,
    RANGES,
    SPEC_VERSION,
    SUPPORTED_CHANNELS,
    SUPPORTED_SAMPLE_RATES,
    TRACK_COUNT,
)
from blipsmith.spec import SoundSpec, closed_set_values, unwrap_annotation

_SCALAR_TYPES: dict[type, str] = {
    bool: "boolean",
    int: "integer",
    float: "number",
    str: "string",
}


def _collect_models(root: type[BaseModel]) -> dict[str, type[BaseModel]]:
    """Every model reachable from the root, in discovery order."""
    found: dict[str, type[BaseModel]] = {root.__name__: root}
    queue: list[type[BaseModel]] = [root]
    while queue:
        model = queue.pop(0)
        for field in model.model_fields.values():
            annotation = unwrap_annotation(field.annotation)
            if (
                isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
                and annotation.__name__ not in found
            ):
                found[annotation.__name__] = annotation
                queue.append(annotation)
    return found


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _default_of(field: FieldInfo) -> Any:
    if field.is_required():
        return None
    try:
        return _jsonable(field.get_default(call_default_factory=True))
    except TypeError:
        return None


def _describe_field(model_name: str, field_name: str, field: FieldInfo) -> dict[str, Any]:
    annotation = unwrap_annotation(field.annotation)
    described: dict[str, Any] = {}

    origin = get_origin(field.annotation)
    if origin in (list, set, tuple):
        described["type"] = "array"
        item = unwrap_annotation(get_args(field.annotation)[0])
        described["items"] = (
            item.__name__
            if isinstance(item, type) and issubclass(item, BaseModel)
            else _scalar(item)
        )
    elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
        described["type"] = "object"
        described["model"] = annotation.__name__
    else:
        described["type"] = _scalar(annotation)

    values = closed_set_values(annotation)
    if values is not None:
        described["enum"] = values

    described["required"] = field.is_required()
    described["default"] = _default_of(field)
    described["nullable"] = type(None) in get_args(field.annotation)

    bounds = RANGES.get((model_name, field_name))
    if bounds is not None:
        described["minimum"] = bounds.minimum
        described["maximum"] = bounds.maximum
        described["integer"] = bounds.integer
        if bounds.unit:
            described["unit"] = bounds.unit
        if bounds.description:
            described["description"] = bounds.description

    # Version 1 limits; the music mode's are under `limits.music`.
    if field_name == "voices":
        described["maxItems"] = MAX_VOICES
    if field_name == "tracks":
        described["minItems"] = TRACK_COUNT
        described["maxItems"] = TRACK_COUNT
    if model_name in _MUSIC_FIELDS and field_name in _MUSIC_FIELDS[model_name]:
        described["musicMode"] = True

    return described


def _scalar(annotation: Any) -> str:
    if get_origin(annotation) is Literal:
        args = get_args(annotation)
        return _SCALAR_TYPES.get(type(args[0]), "string") if args else "string"
    if isinstance(annotation, type):
        for base, name in _SCALAR_TYPES.items():
            if issubclass(annotation, base):
                return name
    return "string"


# Fields only a version 2 spec may set.
_MUSIC_FIELDS: dict[str, tuple[str, ...]] = {
    "Master": ("effects",),
    "Voice": ("key",),
    "Track": ("name", "effects"),
    "Composition": ("loop",),
}


def get_schema() -> dict[str, Any]:
    """The complete SoundSpec contract: models, fields, bounds, defaults, limits."""
    models: dict[str, Any] = {}
    for name, model in _collect_models(SoundSpec).items():
        models[name] = {
            "description": (model.__doc__ or "").strip(),
            "fields": {
                field_name: _describe_field(name, field_name, field)
                for field_name, field in model.model_fields.items()
            },
        }

    return {
        "specVersion": SPEC_VERSION,
        "specVersions": [SPEC_VERSION, MUSIC_SPEC_VERSION],
        "root": SoundSpec.__name__,
        "limits": {
            "maxVoices": MAX_VOICES,
            "trackCount": TRACK_COUNT,
            "sampleRates": list(SUPPORTED_SAMPLE_RATES),
            "channels": list(SUPPORTED_CHANNELS),
            # The one default that depends on the rest of the spec, published so
            # an agent authoring a composition is not surprised by a stereo file.
            "channelsDefaultOneShot": 1,
            "channelsDefaultComposition": 2,
            "durationMsOneShot": [
                RANGES[("SoundSpec", "durationMs")].minimum,
                RANGES[("SoundSpec", "durationMs")].maximum,
            ],
            "durationMsComposition": [
                DURATION_MS_COMPOSITION.minimum,
                DURATION_MS_COMPOSITION.maximum,
            ],
            # Published so the caller can work out the real cutoff ceiling for
            # the sample rate it picked, instead of discovering it as a warning.
            "maxCutoffFraction": MAX_CUTOFF_FRACTION,
            # Version 2: any number of tracks, a kit, shared effects, the loop.
            "music": {
                "specVersion": MUSIC_SPEC_VERSION,
                "maxVoices": MUSIC_MAX_VOICES,
                "minTracks": 1,
                "maxTracks": MUSIC_MAX_TRACKS,
                "masterEffectKinds": list(MASTER_EFFECT_KINDS),
            },
        },
        "models": models,
    }
