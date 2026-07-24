#!/usr/bin/env python3
"""Fail the verify gate if the compiled core links a libm transcendental.

blipsmith promises that the same SoundSpec plus the same seed renders to
identical bytes on every supported platform. IEEE-754 only mandates exact
results for `+ - * / sqrt` and `fma`; `sin`, `cos`, `exp`, `pow` and the rest of
the transcendental family are per-platform library routines whose last bits
differ between glibc, Apple's libm, and WASM runtimes. One such call anywhere in
the audio path silently breaks the invariant, so this check reads the compiled
core's undefined symbols and refuses any of them.

Usage: check_no_libm.py [binary]. With no argument it inspects the installed
core; a path inspects that file instead.

Exit code 0 means clean, 1 means a forbidden symbol was found, 2 means the check
could not run (which also fails the gate: a determinism guard that silently
skips is worse than no guard at all).
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

# Transcendentals: results are implementation-defined in the last bits.
FORBIDDEN_BASES = frozenset(
    {
        "acos",
        "acosh",
        "asin",
        "asinh",
        "atan",
        "atan2",
        "atanh",
        "cbrt",
        "cos",
        "cosh",
        "erf",
        "erfc",
        "exp",
        "exp10",
        "exp2",
        "expm1",
        "hypot",
        "lgamma",
        "log",
        "log10",
        "log1p",
        "log2",
        "pow",
        "sin",
        "sincos",
        "sinh",
        "tan",
        "tanh",
        "tgamma",
    }
)

# Allowed by IEEE-754 (exactly rounded or purely structural), listed so the
# reason for their absence from FORBIDDEN_BASES is on the record rather than an
# oversight: sqrt, fma, fabs, floor, ceil, round, trunc, fmod, ldexp, frexp,
# copysign, nextafter.

# Precision-suffix variants: expf, powl, exp2f128, sinf32x ...
_SUFFIX = re.compile(r"(f|l|f16|f32|f64|f128|f32x|f64x|f128x)$")


def _normalize(symbol: str) -> str:
    """Strip the platform decoration around a bare C symbol name."""
    name = symbol.split("@", 1)[0]  # glibc versioning: pow@@GLIBC_2.2.5
    return name.lstrip("_")  # Mach-O leading underscore, __sincos_stret


def _is_forbidden(name: str) -> bool:
    if name.startswith("sincos"):  # Apple's __sincos_stret and friends
        return True
    return _SUFFIX.sub("", name) in FORBIDDEN_BASES or name in FORBIDDEN_BASES


def find_core_binary() -> Path:
    try:
        spec = importlib.util.find_spec("blipsmith._core")
    except ImportError as exc:
        raise SystemExit(f"[check-no-libm] cannot import blipsmith._core: {exc}") from exc
    if spec is None or spec.origin is None:
        raise SystemExit("[check-no-libm] blipsmith._core has no file on disk; build it first.")
    return Path(spec.origin)


def undefined_symbols(binary: Path) -> list[str]:
    command = (
        ["nm", "-u", str(binary)]
        if sys.platform == "darwin"
        else ["nm", "-D", "--undefined-only", str(binary)]
    )
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise SystemExit(f"[check-no-libm] `nm` is not available, cannot verify: {exc}") from exc
    if result.returncode != 0:
        raise SystemExit(f"[check-no-libm] `{' '.join(command)}` failed: {result.stderr.strip()}")
    return [line.split()[-1] for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    # An explicit path lets the test suite point the check at a deliberately
    # offending probe binary and prove the gate can fail. A gate that has never
    # failed is indistinguishable from one that cannot.
    binary = Path(args[0]) if args else find_core_binary()
    symbols = undefined_symbols(binary)
    violations = sorted({s for s in symbols if _is_forbidden(_normalize(s))})

    print(f"[check-no-libm] core: {binary}")
    print(f"[check-no-libm] undefined symbols inspected: {len(symbols)}")

    if violations:
        print("[check-no-libm] FAIL: libm transcendentals reachable from the audio path:")
        for symbol in violations:
            print(f"  - {symbol}")
        print(
            "\nReplace these with fixed-point phase accumulators, wavetables, or baked\n"
            "constants. If a stage cannot be made bit-exact, cut it rather than\n"
            "weakening the determinism invariant."
        )
        return 1

    print("[check-no-libm] OK: no transcendental symbols found.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            sys.exit(2)
        raise
