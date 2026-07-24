"""The result envelope every surface returns: statuses, warnings, errors.

Two failure kinds are deliberately different types rather than one. A clamped
number is a `SpecWarning` attached to a successful render, because the audio
still exists and the agent can steer from it. A structural problem is a
`SpecError` with no audio and no state change, because there is nothing
trustworthy to hand back.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class RenderStatus(StrEnum):
    RENDERED_OK = "rendered_ok"
    RENDERED_WITH_WARNINGS = "rendered_with_warnings"
    INVALID_SPEC = "invalid_spec"
    RENDER_FAILED = "render_failed"


class WarningCode(StrEnum):
    CLAMPED = "clamped"
    DUPLICATE_NOTE_DROPPED = "duplicate_note_dropped"
    NOTE_BEYOND_END_DROPPED = "note_beyond_end_dropped"


class ErrorCode(StrEnum):
    INVALID_SPEC = "invalid_spec"
    RENDER_FAILED = "render_failed"


class SpecWarning(BaseModel):
    """A parameter blipsmith changed on the caller's behalf, and what it changed."""

    code: WarningCode
    param: str | None = None
    requested: float | None = None
    applied: float | None = None
    message: str


class ErrorInfo(BaseModel):
    """A refusal. `validValues` is populated whenever the field is a closed set."""

    code: ErrorCode
    field: str | None = None
    message: str
    validValues: list[str | int] | None = None


class RenderResult(BaseModel):
    """What a render call hands back, successful or not."""

    status: RenderStatus
    wavPath: str | None = None
    specPath: str | None = None
    explanation: str | None = None
    features: dict[str, float | None] | None = None
    warnings: list[SpecWarning] = Field(default_factory=list)
    error: ErrorInfo | None = None


class SpecError(Exception):
    """Raised for structurally invalid input. Carries the typed error envelope."""

    def __init__(self, error: ErrorInfo) -> None:
        super().__init__(error.message)
        self.error = error

    def as_result(self) -> RenderResult:
        return RenderResult(status=RenderStatus.INVALID_SPEC, error=self.error)


def invalid_spec(
    message: str,
    field: str | None = None,
    valid_values: list[str | int] | None = None,
) -> SpecError:
    return SpecError(
        ErrorInfo(
            code=ErrorCode.INVALID_SPEC,
            field=field,
            message=message,
            validValues=valid_values,
        )
    )
