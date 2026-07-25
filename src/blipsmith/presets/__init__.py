"""The preset library: authored starting points for an agent that cannot hear.

A preset is a plain `SoundSpec` JSON file, nothing more. There is no preset
format, no inheritance, and no macro layer: what an agent loads is exactly what
it could have written itself, so every parameter stays visible and editable the
moment it lands. That matters more here than economy of expression, because the
driving agent's whole loop is "load something close, change one thing, listen to
the numbers".

The library exists because the parameter space is large and silent. An agent
asked for a laser has no way to discover that a laser is a saw with a four-octave
pitch drop; handed `laser`, it has a working sound in one call and can spend its
turns on the part that is actually its job.

Everything is validated through the B02 contract on the way out, so a broken
preset fails here rather than in the middle of someone's session, and every
shipped preset is authored in range: loading one produces no clamp warnings.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel

from blipsmith.result import invalid_spec
from blipsmith.spec import SoundSpec, validate_spec

PRESET_DIR = Path(__file__).resolve().parent
PRESET_SUFFIX = ".spec.json"


class PresetInfo(BaseModel):
    """One entry in the catalogue: enough to choose from, not enough to render.

    The agent picks from these, then calls `load_preset` for the spec itself.
    """

    name: str
    tags: list[str]
    description: str


def preset_names() -> list[str]:
    """Every shipped preset, sorted, so the catalogue never reorders itself."""
    return sorted(path.name[: -len(PRESET_SUFFIX)] for path in PRESET_DIR.glob(f"*{PRESET_SUFFIX}"))


def _path_for(name: str) -> Path:
    valid = preset_names()
    if name not in valid:
        raise invalid_spec(
            f"unknown preset {name!r}. Valid presets: {', '.join(valid)}.",
            field="preset",
            valid_values=list(valid),
        )
    return PRESET_DIR / f"{name}{PRESET_SUFFIX}"


def load_preset(name: str) -> SoundSpec:
    """The preset as a spec, freshly parsed.

    Each call returns its own object: a caller that edits what it loaded (which
    is the entire point of a starting point) cannot change what the next caller
    gets.
    """
    spec, _ = validate_spec(json.loads(_path_for(name).read_text(encoding="utf-8")))
    return spec


def list_presets() -> list[PresetInfo]:
    """The catalogue. Every entry is loaded on the way past, so the listing can
    never advertise a preset that would fail to load."""
    catalogue: list[PresetInfo] = []
    for name in preset_names():
        spec = load_preset(name)
        catalogue.append(
            PresetInfo(
                name=name,
                tags=list(spec.meta.tags),
                description=spec.meta.description,
            )
        )
    return catalogue
