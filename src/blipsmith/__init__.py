"""blipsmith: an agent-playable lo-fi synthesizer.

The audio path lives entirely in the compiled core. There is deliberately no
pure-Python fallback renderer: a substitute implementation could not produce
byte-identical output, and byte-identical output is the whole product. When the
core is missing, importing this package fails loudly instead of degrading.
"""

from __future__ import annotations

from importlib import metadata

_CORE_MISSING_HINT = (
    "blipsmith's native core (blipsmith._core) is not built or failed to load.\n"
    "\n"
    "There is no pure-Python fallback by design: a substitute renderer would break\n"
    "the bit-identical determinism invariant, so the import fails instead.\n"
    "\n"
    "Rebuild it with:\n"
    "    uv sync --reinstall-package blipsmith\n"
    "or, without uv:\n"
    "    pip install --force-reinstall --no-deps -e .\n"
    "\n"
    "The build needs a C++17 compiler; CMake and Ninja are fetched from PyPI when\n"
    "the system does not provide them."
)

try:
    from . import _core
except ImportError as exc:
    raise ImportError(f"{_CORE_MISSING_HINT}\n\nUnderlying import error: {exc}") from exc

try:
    __version__ = metadata.version("blipsmith")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "_core"]
