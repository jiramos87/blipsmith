"""B04: the determinism invariant, and proof that the gate protecting it works.

Same spec plus same seed must produce identical bytes. These tests cover the
same-machine half; B13's CI matrix covers the cross-platform half.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.spec import to_canonical_json, validate_for_render

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "tests" / "golden"
CHECK_NO_LIBM = REPO_ROOT / "scripts" / "check_no_libm.py"


def render_wav(payload: dict[str, Any]) -> bytes:
    spec, _ = validate_for_render(payload)
    wav: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    return wav


def noise_voice(waveform: str = "noise_white", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"waveform": waveform}
    body.update(overrides)
    return {"voices": [body], "durationMs": 200.0}


# --- Noise is seeded, not random ----------------------------------------------


@pytest.mark.parametrize("waveform", ["noise_white", "noise_pink"])
def test_same_seed_reproduces_the_same_noise(waveform: str) -> None:
    payload = {**noise_voice(waveform), "seed": 4242}
    assert render_wav(payload) == render_wav(payload)


@pytest.mark.parametrize("waveform", ["noise_white", "noise_pink"])
def test_a_different_seed_produces_different_noise(waveform: str) -> None:
    assert render_wav({**noise_voice(waveform), "seed": 1}) != render_wav(
        {**noise_voice(waveform), "seed": 2}
    )


def test_two_noise_voices_do_not_share_a_stream() -> None:
    """The voice index enters the seed, so a second noise voice is not the same
    hiss layered on itself."""
    two_voices = render_wav(
        {
            "seed": 7,
            "durationMs": 200.0,
            "voices": [{"waveform": "noise_white"}, {"waveform": "noise_white"}],
        }
    )
    one_voice = render_wav(
        {"seed": 7, "durationMs": 200.0, "voices": [{"waveform": "noise_white"}]}
    )

    def samples(wav: bytes) -> list[int]:
        count = struct.unpack_from("<I", wav, 40)[0] // 2
        return list(struct.unpack_from(f"<{count}h", wav, 44))

    doubled = samples(one_voice)
    summed = samples(two_voices)
    # Identical streams would sum to exactly twice the single voice.
    assert any(abs(s - 2 * d) > 1 for s, d in zip(summed, doubled, strict=True))


def test_seed_does_not_disturb_a_deterministic_waveform() -> None:
    """Only noise consumes the PRNG; a sine must not drift when the seed moves."""
    base = {"voices": [{"waveform": "sine"}], "durationMs": 100.0}
    assert render_wav({**base, "seed": 1}) == render_wav({**base, "seed": 999})


# --- Repeatability across the whole surface -----------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"voices": [{"waveform": "sine", "fundamentalHz": 440.0}]},
        {"voices": [{"waveform": "pulse", "pulseDuty": 0.3}], "sampleRate": 8000},
        {"voices": [{"waveform": "saw"}], "channels": 2},
        {"voices": [{"waveform": "noise_pink"}], "seed": 31337, "sampleRate": 44100},
        {"voices": [{"waveform": "sine"}, {"waveform": "triangle", "fundamentalHz": 660.0}]},
    ],
    ids=["sine", "low-rate-pulse", "stereo-saw", "pink-hifi", "two-voices"],
)
def test_render_repeats_exactly(payload: dict[str, Any]) -> None:
    assert render_wav(payload) == render_wav(payload)


def test_canonical_json_drives_the_bytes_not_key_order() -> None:
    forwards = render_wav({"seed": 5, "durationMs": 300.0, "voices": [{"waveform": "saw"}]})
    backwards = render_wav({"voices": [{"waveform": "saw"}], "durationMs": 300.0, "seed": 5})
    assert forwards == backwards


# --- Golden corpus ------------------------------------------------------------


def golden_cases() -> list[str]:
    return sorted(path.name for path in (GOLDEN / "specs").glob("*.spec.json"))


def test_golden_corpus_is_not_empty() -> None:
    """Guards against the parametrized checks below silently covering nothing."""
    assert len(golden_cases()) >= 7, "expected at least one golden per waveform"


@pytest.mark.parametrize("name", golden_cases())
def test_golden_render_matches_its_recorded_hash(name: str) -> None:
    expected = json.loads((GOLDEN / "hashes.json").read_text())
    payload = json.loads((GOLDEN / "specs" / name).read_text())

    wav = render_wav(payload)

    assert name in expected, f"{name} has no recorded hash"
    assert hashlib.sha256(wav).hexdigest() == expected[name], (
        f"{name} no longer renders the bytes it was recorded with. If the change "
        "was intended, re-record the corpus and say so in the commit."
    )


@pytest.mark.parametrize("name", golden_cases())
def test_golden_spec_is_authored_in_range(name: str) -> None:
    """A golden that clamps would be recording a warning, not a sound."""
    _, warnings = validate_for_render(json.loads((GOLDEN / "specs" / name).read_text()))
    assert warnings == []


@pytest.mark.parametrize("name", golden_cases())
def test_golden_render_does_not_clip(name: str) -> None:
    wav = render_wav(json.loads((GOLDEN / "specs" / name).read_text()))
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    raw = struct.unpack_from(f"<{count}h", wav, 44)

    assert any(value != 0 for value in raw), "a golden should not be silence"
    assert min(raw) > -32768, "hard-negative full scale suggests wrapping"


def test_every_recorded_hash_still_has_a_spec() -> None:
    """A hash left behind after its spec was deleted would never be checked."""
    recorded = set(json.loads((GOLDEN / "hashes.json").read_text()))
    assert recorded == set(golden_cases())


# --- The no-libm gate can actually fail ---------------------------------------


def test_no_libm_check_passes_on_the_real_core() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECK_NO_LIBM)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("c++") is None, reason="no C++ compiler to build the probe")
def test_no_libm_check_fails_on_a_deliberate_offender(tmp_path: Path) -> None:
    """A gate that has never failed is indistinguishable from one that cannot."""
    source = tmp_path / "probe.cpp"
    source.write_text(
        "#include <cmath>\n"
        'extern "C" double probe(double x) { return std::sin(x) + std::exp(x); }\n'
    )
    library = tmp_path / "probe.so"

    build = subprocess.run(
        ["c++", "-shared", "-fPIC", "-O0", "-o", str(library), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr

    result = subprocess.run(
        [sys.executable, str(CHECK_NO_LIBM), str(library)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1, f"the gate passed a binary that calls sin(): {result.stdout}"
    assert "FAIL" in result.stdout
    assert "sin" in result.stdout
