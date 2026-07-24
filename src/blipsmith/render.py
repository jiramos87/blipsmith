"""Render orchestration: validate, canonicalize, call the core, write the files.

Both surfaces go through here. The CLI and the MCP server differ in how they
collect a spec, never in how a spec becomes audio, which is what makes the
PRD's round-trip promise hold: what the agent rendered, the human re-renders
byte-for-byte from the committed sidecar.

Failures split the same way they do in `spec.py`. A bad spec is `invalid_spec`
and never touches the filesystem. An environment problem (unwritable directory,
a file already sitting at the target, a core that will not load) is
`render_failed` with a message that says what to do about it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from blipsmith import _core
from blipsmith.result import (
    ErrorCode,
    ErrorInfo,
    RenderResult,
    RenderStatus,
    SpecError,
)
from blipsmith.spec import SoundSpec, to_canonical_json, validate_for_render

OUT_DIR_ENV = "BLIPSMITH_OUT_DIR"
DEFAULT_OUT_DIR = "blipsmith-out"


def resolve_out_dir(out_dir: str | Path | None = None) -> Path:
    """Explicit argument, then $BLIPSMITH_OUT_DIR, then ./blipsmith-out."""
    if out_dir is not None:
        return Path(out_dir)
    from_env = os.environ.get(OUT_DIR_ENV)
    if from_env:
        return Path(from_env)
    return Path(DEFAULT_OUT_DIR)


def to_sidecar_json(spec: SoundSpec) -> str:
    """The committed spec file: indented so a human can edit it, key-sorted so
    diffs stay readable. The audio is rendered from the parsed spec rather than
    from this text, so the formatting costs nothing in determinism."""
    return json.dumps(spec.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _failed(message: str) -> RenderResult:
    return RenderResult(
        status=RenderStatus.RENDER_FAILED,
        error=ErrorInfo(code=ErrorCode.RENDER_FAILED, message=message),
    )


def render(
    spec_data: Any,
    *,
    out_dir: str | Path | None = None,
    name: str | None = None,
    overwrite: bool = False,
) -> RenderResult:
    """Render a spec to `{name}.wav` plus its `{name}.spec.json` sidecar.

    Returns a `RenderResult` in every case rather than raising, so the MCP and
    CLI surfaces can report a failure as data.
    """
    try:
        spec, warnings = validate_for_render(spec_data)
    except SpecError as exc:
        return exc.as_result()

    stem = name if name is not None else spec.meta.name
    # The name reaches here from spec `meta`, which an agent controls. Keeping it
    # a plain filename stops a crafted name from writing outside the output
    # directory.
    if not stem or Path(stem).name != stem or stem in {".", ".."}:
        return _failed(
            f"invalid output name {stem!r}: it must be a plain filename with no "
            "path separators. Set meta.name, or pass an explicit name."
        )

    directory = resolve_out_dir(out_dir)
    wav_path = directory / f"{stem}.wav"
    spec_path = directory / f"{stem}.spec.json"

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _failed(
            f"cannot create output directory {directory}: {exc}. "
            "Choose a different directory or fix its permissions."
        )

    if not overwrite:
        for target in (wav_path, spec_path):
            if target.exists():
                return _failed(
                    f"refusing to overwrite {target}. Pass overwrite=True to replace it, "
                    "or render under a different name."
                )

    try:
        rendered = _core.render(to_canonical_json(spec))
    except Exception as exc:  # the core reports every failure as an exception
        return _failed(f"the native core failed to render: {exc}")

    written: list[Path] = []
    try:
        wav_path.write_bytes(rendered["wav"])
        written.append(wav_path)
        spec_path.write_text(to_sidecar_json(spec), encoding="utf-8")
        written.append(spec_path)
    except OSError as exc:
        # A half-written pair is worse than none: the sidecar would no longer
        # regenerate the WAV beside it.
        for path in written:
            path.unlink(missing_ok=True)
        return _failed(
            f"cannot write to {directory}: {exc}. "
            "Choose a different directory or fix its permissions."
        )

    return RenderResult(
        status=RenderStatus.RENDERED_WITH_WARNINGS if warnings else RenderStatus.RENDERED_OK,
        wavPath=str(wav_path),
        specPath=str(spec_path),
        features=rendered["features"],
        warnings=warnings,
    )
