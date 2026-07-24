"""B01: the native core loads, and nothing is allowed to stand in for it."""

from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

import pytest

import blipsmith

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def test_core_ping_returns_pong() -> None:
    assert blipsmith._core.ping() == "pong"


def test_core_version_matches_package_version() -> None:
    assert blipsmith._core.core_version() == blipsmith.__version__


def test_core_is_a_compiled_extension() -> None:
    """A pure-Python module here would mean a fallback renderer had crept in."""
    origin = Path(blipsmith._core.__file__)
    assert origin.suffix in {".so", ".pyd", ".dylib"}, f"core is not compiled: {origin}"


# The core can go missing two ways: the extension is absent (ModuleNotFoundError,
# which the `from . import` machinery swallows into an ImportError) or it is
# present but unloadable (ImportError, which propagates directly). Both must
# reach the same actionable failure.
_BLOCK_CORE = """
import sys
from importlib.abc import MetaPathFinder


class _BlockCore(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "blipsmith._core":
            raise {exception}
        return None


sys.meta_path.insert(0, _BlockCore())

try:
    import blipsmith
except ImportError as exc:
    print(str(exc))
    raise SystemExit(0)
raise SystemExit("import unexpectedly succeeded while the core was blocked")
"""


@pytest.mark.parametrize(
    "exception",
    [
        'ModuleNotFoundError("simulated: core not built", name="blipsmith._core")',
        'ImportError("simulated: core present but unloadable")',
    ],
    ids=["core-absent", "core-unloadable"],
)
def test_import_fails_fast_when_core_is_missing(exception: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _BLOCK_CORE.format(exception=exception)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    message = result.stdout
    assert "uv sync --reinstall-package blipsmith" in message, message
    assert "no pure-Python fallback" in message, message


def test_cmakelists_pins_determinism_flags() -> None:
    text = (REPO_ROOT / "CMakeLists.txt").read_text()

    assert "-ffp-contract=off" in text
    assert "CMAKE_CXX_STANDARD 17" in text

    # The exact spellings that would enable fast math. The build's own guard
    # matches on looser patterns, so those never collide with these.
    for flag in ("-ffast-math", "-Ofast", "-funsafe-math-optimizations", "-ffp-contract=fast"):
        assert flag not in text, f"{flag} would break bit-identical renders"


def test_check_no_libm_passes_on_the_built_core() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_no_libm.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_verify_gate_runs_the_no_libm_check() -> None:
    verify = SCRIPTS / "verify.sh"
    assert "check_no_libm.py" in verify.read_text()
    assert verify.stat().st_mode & stat.S_IXUSR, "verify.sh is not executable"
