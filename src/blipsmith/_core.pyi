"""Type stubs for the compiled core (blipsmith._core).

Kept in step with core/src/core.cpp as each item extends the bridge.
"""

from typing import Any

def ping() -> str: ...
def core_version() -> str: ...
def render(spec_json: str) -> dict[str, Any]:
    """Canonical spec JSON in, {"wav": bytes, "features": dict} out."""
    ...
