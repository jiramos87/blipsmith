"""The library call: a spec in, the sound out, in memory.

For a program that uses blipsmith as an instrument (tunesmith is the first):
no files, no text to parse. It goes through the same validate, compile, and
render path as the CLI and the MCP server, so the bytes it returns are the bytes
`blipsmith render` would write for the same spec.

    from blipsmith import render_sound
    sound = render_sound(spec, stems=True)
    sound.wav, sound.features["integratedLufs"], [s.wav for s in sound.stems]

An invalid spec raises `SpecError` (its `.error` names the field); clamped
numbers and dropped notes come back as `warnings`, as everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from blipsmith import _core
from blipsmith.composition import compile_composition
from blipsmith.ranges import MUSIC_SPEC_VERSION
from blipsmith.result import SpecError, SpecWarning, WarningCode, invalid_spec
from blipsmith.spec import SoundSpec, to_canonical_json, validate_for_render


@dataclass(frozen=True)
class Stem:
    """One track's share of the mix: same rate, channels, and length, scaled by
    the same gain, so the stems add up to the mix within one 16-bit step each."""

    track: int
    name: str | None
    wav: bytes


@dataclass(frozen=True)
class Rendered:
    spec: SoundSpec
    wav: bytes
    features: dict[str, float]
    warnings: list[SpecWarning] = field(default_factory=list)
    stems: list[Stem] = field(default_factory=list)


def _spec_data(spec: dict[str, Any] | SoundSpec) -> Any:
    if isinstance(spec, SoundSpec):
        return spec.model_dump(mode="json")
    return spec


def stems_need_music() -> SpecError:
    return invalid_spec(
        f"stems come from the music mode: set version to {MUSIC_SPEC_VERSION}.",
        field="version",
    )


def render_validated(
    spec: SoundSpec, warnings: list[SpecWarning], *, stems: bool = False
) -> Rendered:
    """Render a spec that has already been validated and clamped. The file
    surface uses this too, so the two can never disagree about the bytes."""
    if stems and not spec.is_music:
        raise stems_need_music()
    compiled, composition_warnings = compile_composition(spec)
    warnings = [*warnings, *composition_warnings]
    raw = _core.render(to_canonical_json(compiled), stems)

    rendered_stems: list[Stem] = []
    if stems:
        assert spec.composition is not None  # the music mode requires one
        tracks = spec.composition.tracks
        for index, (wav, clipped) in enumerate(zip(raw["stems"], raw["stemClipped"], strict=True)):
            rendered_stems.append(Stem(track=index, name=tracks[index].name, wav=wav))
            if clipped:
                warnings.append(
                    SpecWarning(
                        code=WarningCode.STEM_CLIPPED,
                        param=f"composition.tracks[{index}]",
                        message=(
                            f"the stem of track {index} went past full scale and was clipped; "
                            "the tracks cancel each other in the mix, so this stem alone is "
                            "louder than the mix. Lower the track or the master gain."
                        ),
                    )
                )
    return Rendered(
        spec=spec,
        wav=raw["wav"],
        features=raw["features"],
        warnings=warnings,
        stems=rendered_stems,
    )


def render_sound(spec: dict[str, Any] | SoundSpec, *, stems: bool = False) -> Rendered:
    """Validate, clamp, compile, and render `spec`; return the sound in memory."""
    validated, warnings = validate_for_render(_spec_data(spec))
    return render_validated(validated, warnings, stems=stems)
