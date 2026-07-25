"""SoundSpec: the only source of truth for a blipsmith sound.

Validation runs as two deliberately separate passes, because the PRD asks for
two different outcomes:

1. **Structural** (pydantic). Unknown enum, unsupported version, missing field,
   wrong type, unknown key, too many voices. These raise `SpecError`, produce no
   audio, and change no state. Guessing what the caller meant would be a
   fabrication, so the error names the field and lists the valid values.
2. **Numeric** (`clamp_spec`). Any parameter outside its documented range is
   pulled to the nearest bound and a `clamped` warning records what was asked
   for and what was applied. The intent survives; only the value moves.

Everything downstream consumes `to_canonical_json`, which materializes defaults
and sorts keys so the same spec always produces the same bytes to hash.
"""

from __future__ import annotations

import json
import math
from enum import Enum, IntEnum, StrEnum
from types import UnionType
from typing import Any, Literal, TypeVar, Union, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from blipsmith.ranges import (
    DURATION_MS_COMPOSITION,
    MAX_VOICES,
    RANGES,
    SPEC_VERSION,
    TRACK_COUNT,
    NumericRange,
    cutoff_range_for,
)
from blipsmith.result import SpecError, SpecWarning, WarningCode, invalid_spec

ModelT = TypeVar("ModelT", bound=BaseModel)

# --- Closed sets --------------------------------------------------------------


class Waveform(StrEnum):
    SINE = "sine"
    SQUARE = "square"
    TRIANGLE = "triangle"
    SAW = "saw"
    PULSE = "pulse"
    NOISE_WHITE = "noise_white"
    NOISE_PINK = "noise_pink"


class FilterType(StrEnum):
    LOWPASS = "lowpass"
    HIGHPASS = "highpass"
    BANDPASS = "bandpass"


class LfoShape(StrEnum):
    SINE = "sine"
    TRIANGLE = "triangle"
    SQUARE = "square"
    SAW = "saw"


class LfoTarget(StrEnum):
    PITCH = "pitch"
    AMPLITUDE = "amplitude"
    CUTOFF = "cutoff"


class ModEnvTarget(StrEnum):
    PITCH = "pitch"
    CUTOFF = "cutoff"


class AmMode(StrEnum):
    AM = "am"
    RING = "ring"


class EffectKind(StrEnum):
    DISTORTION = "distortion"
    WAVEFOLD = "wavefold"
    DELAY = "delay"
    REVERB = "reverb"


class SampleRate(IntEnum):
    SR_8000 = 8000
    SR_11025 = 11025
    SR_16000 = 16000
    SR_22050 = 22050
    SR_44100 = 44100


class Channels(IntEnum):
    MONO = 1
    STEREO = 2


# --- Models -------------------------------------------------------------------


class SpecModel(BaseModel):
    """Shared config. `extra="forbid"` turns a misspelled key into a typed error
    rather than a silently ignored one, which matters when the caller is an agent
    that cannot hear the difference."""

    model_config = ConfigDict(extra="forbid", validate_assignment=False)


class Limiter(SpecModel):
    """The master safety gate. There is deliberately no `enabled` field: the PRD
    makes the limiter and clip guard non-optional on every render."""

    targetDbfs: float = RANGES[("Limiter", "targetDbfs")].default


class Master(SpecModel):
    gainDb: float = RANGES[("Master", "gainDb")].default
    limiter: Limiter = Field(default_factory=Limiter)


class Adsr(SpecModel):
    attackMs: float = RANGES[("Adsr", "attackMs")].default
    decayMs: float = RANGES[("Adsr", "decayMs")].default
    sustainLevel: float = RANGES[("Adsr", "sustainLevel")].default
    releaseMs: float = RANGES[("Adsr", "releaseMs")].default


class ModEnv(SpecModel):
    target: ModEnvTarget
    amount: float = RANGES[("ModEnv", "amount")].default
    attackMs: float = RANGES[("ModEnv", "attackMs")].default
    decayMs: float = RANGES[("ModEnv", "decayMs")].default


class Lfo(SpecModel):
    target: LfoTarget
    shape: LfoShape = LfoShape.SINE
    rateHz: float = RANGES[("Lfo", "rateHz")].default
    depth: float = RANGES[("Lfo", "depth")].default


class Fm(SpecModel):
    ratio: float = RANGES[("Fm", "ratio")].default
    index: float = RANGES[("Fm", "index")].default


class Am(SpecModel):
    mode: AmMode
    rateHz: float = RANGES[("Am", "rateHz")].default
    depth: float = RANGES[("Am", "depth")].default


class Filter(SpecModel):
    type: FilterType
    cutoffHz: float = RANGES[("Filter", "cutoffHz")].default
    resonance: float = RANGES[("Filter", "resonance")].default


class LoFi(SpecModel):
    bitDepth: int = int(RANGES[("LoFi", "bitDepth")].default)
    decimation: int = int(RANGES[("LoFi", "decimation")].default)


class Effect(SpecModel):
    """One flat model per the pinned contract. Each kind reads the parameters
    that apply to it and ignores the rest: distortion and wavefold read `drive`,
    delay reads `timeMs`/`feedback`/`mixWet`, reverb reads
    `roomSize`/`damping`/`mixWet`."""

    kind: EffectKind
    drive: float = RANGES[("Effect", "drive")].default
    timeMs: float = RANGES[("Effect", "timeMs")].default
    feedback: float = RANGES[("Effect", "feedback")].default
    mixWet: float = RANGES[("Effect", "mixWet")].default
    roomSize: float = RANGES[("Effect", "roomSize")].default
    damping: float = RANGES[("Effect", "damping")].default


class Voice(SpecModel):
    waveform: Waveform
    fundamentalHz: float = RANGES[("Voice", "fundamentalHz")].default
    # Pitch as a MIDI note, when set, wins over fundamentalHz. The note-to-hertz
    # conversion is deliberately NOT done here: it needs 2**(n/12), and a host
    # libm pow would make the rendered bytes platform-dependent. The core does it
    # from a baked table instead, so both fields travel to it unconverted.
    fundamentalMidi: int | None = None
    pulseDuty: float = RANGES[("Voice", "pulseDuty")].default
    ampEnv: Adsr = Field(default_factory=Adsr)
    modEnv: ModEnv | None = None
    lfo: Lfo | None = None
    fm: Fm | None = None
    am: Am | None = None
    filter: Filter | None = None
    lofi: LoFi | None = None
    effects: list[Effect] = Field(default_factory=list)
    pan: float = RANGES[("Voice", "pan")].default
    mixDb: float = RANGES[("Voice", "mixDb")].default
    track: int = int(RANGES[("Voice", "track")].default)


class Note(SpecModel):
    startBeat: float
    midiNote: int
    durationBeats: float = RANGES[("Note", "durationBeats")].default
    velocity: float = RANGES[("Note", "velocity")].default


class Step(SpecModel):
    index: int
    velocity: float = RANGES[("Step", "velocity")].default
    midiNote: int | None = None


class Track(SpecModel):
    gainDb: float = RANGES[("Track", "gainDb")].default
    pan: float = RANGES[("Track", "pan")].default
    stepsPerBeat: int = int(RANGES[("Track", "stepsPerBeat")].default)
    notes: list[Note] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)


def _default_tracks() -> list[Track]:
    return [Track() for _ in range(TRACK_COUNT)]


class Composition(SpecModel):
    tempoBpm: float = RANGES[("Composition", "tempoBpm")].default
    swing: float = RANGES[("Composition", "swing")].default
    tracks: list[Track] = Field(
        default_factory=_default_tracks, min_length=TRACK_COUNT, max_length=TRACK_COUNT
    )


class Meta(SpecModel):
    name: str = "untitled"
    tags: list[str] = Field(default_factory=list)
    description: str = ""


class SoundSpec(SpecModel):
    version: Literal[1] = SPEC_VERSION
    seed: int = int(RANGES[("SoundSpec", "seed")].default)
    sampleRate: SampleRate = SampleRate.SR_22050
    channels: Channels = Channels.MONO
    durationMs: float = RANGES[("SoundSpec", "durationMs")].default
    master: Master = Field(default_factory=Master)
    voices: list[Voice] = Field(default_factory=list, max_length=MAX_VOICES)
    composition: Composition | None = None
    meta: Meta = Field(default_factory=Meta)


# --- Annotation helpers (shared with schema.py) --------------------------------


def unwrap_annotation(annotation: Any) -> Any:
    """Strip Optional and sequence wrappers down to the meaningful type."""
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return unwrap_annotation(args[0]) if len(args) == 1 else annotation
    if origin in (list, set, tuple):
        item_args = get_args(annotation)
        return unwrap_annotation(item_args[0]) if item_args else annotation
    return annotation


def closed_set_values(annotation: Any) -> list[str | int] | None:
    """The valid values, when the annotation is an enum or a Literal."""
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return [member.value for member in annotation]
    if get_origin(annotation) is Literal:
        return list(get_args(annotation))
    return None


def _model_and_annotation_at(loc: tuple[int | str, ...]) -> tuple[Any, Any]:
    """Walk a pydantic error location down from SoundSpec.

    Returns (owning model class, field annotation) so an error can report both
    the valid values for the field and the valid keys for its parent.
    """
    owner: Any = SoundSpec
    current: Any = SoundSpec
    annotation: Any = None
    for part in loc:
        if isinstance(part, int):
            continue
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            return owner, None
        field = current.model_fields.get(part)
        if field is None:
            return current, None
        owner = current
        annotation = unwrap_annotation(field.annotation)
        current = annotation
    return owner, annotation


def _format_loc(loc: tuple[int | str, ...]) -> str:
    rendered = ""
    for part in loc:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered = f"{rendered}.{part}" if rendered else str(part)
    return rendered


# --- Structural validation ----------------------------------------------------


def _error_from_validation(exc: ValidationError) -> SpecError:
    first = exc.errors()[0]
    loc = tuple(first["loc"])
    field = _format_loc(loc) or None
    kind = first["type"]
    owner, annotation = _model_and_annotation_at(loc)

    if kind == "too_long" and loc == ("voices",):
        return invalid_spec(
            f"a spec may hold at most {MAX_VOICES} voices; the existing voices are unchanged.",
            field="voices",
        )

    if kind == "extra_forbidden":
        is_model = isinstance(owner, type) and issubclass(owner, BaseModel)
        keys = sorted(owner.model_fields) if is_model else []
        return invalid_spec(
            f"unknown field {field!r}. Valid fields here: {', '.join(keys)}.",
            field=field,
            valid_values=list(keys),
        )

    valid = closed_set_values(annotation)

    # Order matters: a missing enum field reports as missing, not as "'{}' is not
    # a valid waveform", which would send the caller hunting for a typo that is
    # not there. It still lists the valid values, since that is what to supply.
    if kind == "missing":
        message = f"{field} is required but missing."
        if valid is not None:
            message += f" Valid values: {', '.join(repr(v) for v in valid)}."
        return invalid_spec(message, field=field, valid_values=valid)

    if valid is not None:
        supplied = first.get("input")
        return invalid_spec(
            f"{field}: {supplied!r} is not valid. Valid values: "
            f"{', '.join(repr(v) for v in valid)}.",
            field=field,
            valid_values=valid,
        )

    return invalid_spec(f"{field}: {first['msg']}.", field=field)


def parse_spec(data: Any) -> SoundSpec:
    """Structural validation only. Raises `SpecError`; never clamps."""
    try:
        return SoundSpec.model_validate(data)
    except ValidationError as exc:
        raise _error_from_validation(exc) from exc


def load_spec_json(text: str) -> SoundSpec:
    """Parse spec JSON. Malformed JSON and non-finite numbers are typed errors."""
    try:
        data = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, ValueError) as exc:
        raise invalid_spec(f"malformed JSON: {exc}") from exc
    return parse_spec(data)


def _reject_json_constant(name: str) -> float:
    raise ValueError(f"{name} is not a representable spec value")


# --- Numeric clamping ---------------------------------------------------------


def _clamp_model(
    model: BaseModel,
    path: str,
    warnings: list[SpecWarning],
    overrides: dict[tuple[str, str], NumericRange],
) -> None:
    class_name = type(model).__name__
    for name in type(model).model_fields:
        value = getattr(model, name)
        child = f"{path}.{name}" if path else name

        if isinstance(value, BaseModel):
            _clamp_model(value, child, warnings, overrides)
            continue
        if isinstance(value, list):
            for index, entry in enumerate(value):
                if isinstance(entry, BaseModel):
                    _clamp_model(entry, f"{child}[{index}]", warnings, overrides)
            continue
        # Enums are a closed set already, and bool is an int subclass we never mean.
        if isinstance(value, Enum | bool) or not isinstance(value, int | float):
            continue

        bounds = overrides.get((class_name, name)) or RANGES.get((class_name, name))
        if bounds is None:
            continue
        if not math.isfinite(value):
            raise invalid_spec(f"{child}: {value!r} is not a finite number.", field=child)

        applied = bounds.clamp(value)
        if applied != value:
            setattr(model, name, applied)
            warnings.append(
                SpecWarning(
                    code=WarningCode.CLAMPED,
                    param=child,
                    requested=value,
                    applied=applied,
                    message=(
                        f"{child}: requested {value}, applied {applied} "
                        f"(valid range {bounds.minimum} to {bounds.maximum}"
                        f"{' ' + bounds.unit if bounds.unit else ''})."
                    ),
                )
            )


def clamp_model(model: ModelT) -> tuple[ModelT, list[SpecWarning]]:
    """Clamp any spec fragment, not just a whole spec.

    The MCP grouped setters (`set_lfo`, `set_filter`, ...) apply one block at a
    time and need the same bounds and warnings a full render would produce.
    """
    working = model.model_copy(deep=True)
    warnings: list[SpecWarning] = []
    _clamp_model(working, "", warnings, {})
    return working, warnings


def clamp_spec(spec: SoundSpec) -> tuple[SoundSpec, list[SpecWarning]]:
    """Pull every out-of-range number to its nearest bound, reporting each move."""
    working = spec.model_copy(deep=True)
    warnings: list[SpecWarning] = []
    # The two bounds that depend on the rest of the spec rather than on the field
    # alone: a composition may run longer than a one-shot, and a filter cutoff
    # has to stay below the Nyquist frequency of *this* render.
    overrides: dict[tuple[str, str], NumericRange] = {
        ("Filter", "cutoffHz"): cutoff_range_for(int(working.sampleRate))
    }
    if working.composition is not None:
        overrides[("SoundSpec", "durationMs")] = DURATION_MS_COMPOSITION
    _clamp_model(working, "", warnings, overrides)
    return working, warnings


# --- Public entry points ------------------------------------------------------


def validate_spec(data: Any) -> tuple[SoundSpec, list[SpecWarning]]:
    """Structural validation then clamping. Raises `SpecError` on the former."""
    return clamp_spec(parse_spec(data))


def validate_spec_json(text: str) -> tuple[SoundSpec, list[SpecWarning]]:
    return clamp_spec(load_spec_json(text))


def validate_for_render(data: Any) -> tuple[SoundSpec, list[SpecWarning]]:
    """As `validate_spec`, plus the checks that only matter at render time."""
    spec, warnings = validate_spec(data)
    if not spec.voices:
        raise invalid_spec(
            "a spec needs at least one voice to render; refusing to emit silence.",
            field="voices",
        )
    return spec, warnings


def to_canonical_json(spec: SoundSpec) -> str:
    """Serialize with defaults materialized and keys sorted.

    This is the byte-level contract: the core receives exactly this, and golden
    hashes are taken over renders driven by it.
    """
    return json.dumps(
        spec.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
