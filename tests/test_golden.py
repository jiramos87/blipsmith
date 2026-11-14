"""B13: the golden corpus, frozen.

Every earlier item authored goldens for its own stage. This is where the corpus
stops being a pile of files and becomes a contract: one audit that says what the
corpus must cover, and one gate that re-renders all of it.

The audit is written as predicates over the parsed spec rather than as a list of
filenames. A filename list would pass forever once written; a predicate fails the
moment a golden stops exercising the stage it was recorded for, which is the
failure that would otherwise go unnoticed for a year.

The cross-platform half of the freeze cannot run here: it needs two machines. It
lives in `.github/workflows/ci.yml`, and the last section of this file asserts
that workflow still has the shape the invariant depends on.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.presets import list_presets
from blipsmith.ranges import LIMITER_TARGET_DBFS, RANGES
from blipsmith.spec import SoundSpec, to_canonical_json, validate_for_render

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "tests" / "golden"
SPECS = GOLDEN / "specs"
HASHES = GOLDEN / "hashes.json"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

# One quantization step of tolerance: the bus works in doubles and the encoder
# rounds once on the way to int16.
PEAK_TOLERANCE_DB = 0.05

# `bitDepth` at its documented maximum is no crush at all, and `decimation` at 1
# is the stage switched off. A golden has to be past those to count as coverage.
NO_CRUSH_BITS = int(RANGES[("LoFi", "bitDepth")].maximum)
NO_DECIMATION = int(RANGES[("LoFi", "decimation")].minimum)


# --- Loading and measuring ----------------------------------------------------


def golden_names() -> list[str]:
    return sorted(path.name for path in SPECS.glob("*.spec.json"))


def payload_of(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SPECS / name).read_text())
    return data


def spec_of(name: str) -> SoundSpec:
    spec, _ = validate_for_render(payload_of(name))
    return spec


def render_wav(name: str) -> bytes:
    wav: bytes = blipsmith._core.render(to_canonical_json(spec_of(name)))["wav"]
    return wav


def samples_of(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def peak_dbfs(samples: tuple[int, ...]) -> float:
    top = max(abs(value) for value in samples)
    return 20 * math.log10(top / 32767.0) if top else -math.inf


def target_dbfs(payload: dict[str, Any]) -> float:
    limiter = payload.get("master", {}).get("limiter", {})
    value: float = limiter.get("targetDbfs", LIMITER_TARGET_DBFS)
    return value


# --- The coverage audit -------------------------------------------------------


def _has_voice(spec: SoundSpec, test: Callable[[Any], bool]) -> bool:
    return any(test(voice) for voice in spec.voices)


def _has_effect(spec: SoundSpec, kind: str) -> bool:
    return _has_voice(spec, lambda v: any(effect.kind == kind for effect in v.effects))


def _waveform(name: str) -> Callable[[SoundSpec], bool]:
    return lambda spec: _has_voice(spec, lambda v: v.waveform == name)


# What the corpus is required to cover, and how a render proves it does. The
# Quality bar names the processing stages; the waveform rows come from B04 and
# the composition rows from B09, so the whole signal chain is audited in one
# place rather than one item at a time.
STAGE_PROBES: dict[str, Callable[[SoundSpec], bool]] = {
    "waveform: sine": _waveform("sine"),
    "waveform: square": _waveform("square"),
    "waveform: triangle": _waveform("triangle"),
    "waveform: saw": _waveform("saw"),
    "waveform: pulse": _waveform("pulse"),
    "waveform: white noise": _waveform("noise_white"),
    "waveform: pink noise": _waveform("noise_pink"),
    "pitch as a MIDI note": lambda spec: _has_voice(spec, lambda v: v.fundamentalMidi is not None),
    "amplitude ADSR": lambda spec: _has_voice(spec, lambda v: v.ampEnv.attackMs > 0),
    "FM": lambda spec: _has_voice(spec, lambda v: v.fm is not None),
    "AM / ring": lambda spec: _has_voice(spec, lambda v: v.am is not None),
    "LFO": lambda spec: _has_voice(spec, lambda v: v.lfo is not None),
    "mod envelope": lambda spec: _has_voice(spec, lambda v: v.modEnv is not None),
    "filter": lambda spec: _has_voice(spec, lambda v: v.filter is not None),
    "bitcrush": lambda spec: _has_voice(
        spec, lambda v: v.lofi is not None and v.lofi.bitDepth < NO_CRUSH_BITS
    ),
    "decimate": lambda spec: _has_voice(
        spec, lambda v: v.lofi is not None and v.lofi.decimation > NO_DECIMATION
    ),
    "distortion": lambda spec: _has_effect(spec, "distortion"),
    "wavefold": lambda spec: _has_effect(spec, "wavefold"),
    "delay": lambda spec: _has_effect(spec, "delay"),
    "reverb": lambda spec: _has_effect(spec, "reverb"),
    "master bus under load": lambda spec: len(spec.voices) >= 3,
    "composition: notes on five tracks": lambda spec: (
        spec.composition is not None
        and sum(1 for track in spec.composition.tracks if track.notes or track.steps) == 5
    ),
    "composition: a painted step grid": lambda spec: (
        spec.composition is not None and any(track.steps for track in spec.composition.tracks)
    ),
    "composition: swing": lambda spec: spec.composition is not None and spec.composition.swing > 0,
    "stereo output": lambda spec: int(spec.channels) == 2,
    # docs/prd/blipsmith-music-mode.md
    "music: more than five tracks": lambda spec: (
        spec.is_music and spec.composition is not None and len(spec.composition.tracks) > 5
    ),
    "music: a kit on one track": lambda spec: _has_voice(spec, lambda v: v.key is not None),
    "music: a voice effect ringing past its notes": lambda spec: (
        spec.is_music and _has_voice(spec, lambda v: bool(v.effects))
    ),
    "music: a track effect": lambda spec: (
        spec.composition is not None and any(t.effects for t in spec.composition.tracks)
    ),
    "music: a master room": lambda spec: bool(spec.master.effects),
    "music: the loop": lambda spec: spec.composition is not None and bool(spec.composition.loop),
    # docs/prd/blipsmith-expressive-notes.md
    "expressive: touch on a pitched voice": lambda spec: _has_voice(
        spec, lambda v: v.touch is not None and v.key is None
    ),
    "expressive: touch on a kit voice": lambda spec: _has_voice(
        spec, lambda v: v.touch is not None and v.key is not None
    ),
    "expressive: legato glide": lambda spec: _has_voice(
        spec, lambda v: v.glide is not None and v.glide.mode == "legato"
    ),
    "expressive: always glide": lambda spec: _has_voice(
        spec, lambda v: v.glide is not None and v.glide.mode == "always"
    ),
    "expressive: late vibrato": lambda spec: _has_voice(spec, lambda v: v.vibrato is not None),
    "expressive: vibrato beside an LFO on pitch": lambda spec: _has_voice(
        spec, lambda v: v.vibrato is not None and v.lfo is not None and v.lfo.target == "pitch"
    ),
}


@pytest.mark.parametrize("stage", sorted(STAGE_PROBES))
def test_every_processing_stage_has_a_golden(stage: str) -> None:
    """The Quality bar's coverage list, asserted against what the specs actually
    contain rather than against what they are called."""
    probe = STAGE_PROBES[stage]

    covered = [name for name in golden_names() if probe(spec_of(name))]

    assert covered, f"no golden render exercises {stage}"


def test_every_preset_archetype_has_a_golden() -> None:
    """Both preset families ship, and every archetype in them is frozen. A family
    that lost its last preset would otherwise leave the corpus looking complete."""
    frozen = set(golden_names())
    families = {tag for preset in list_presets() for tag in preset.tags} & {"sfx", "drum"}

    assert families == {"sfx", "drum"}, "the corpus is meant to cover game SFX and a drum kit"
    for preset in list_presets():
        assert f"preset-{preset.name}.spec.json" in frozen, f"{preset.name} is not frozen"


def test_the_corpus_is_not_empty() -> None:
    """Guards the parametrized gates below against silently covering nothing."""
    assert len(golden_names()) >= len(STAGE_PROBES)


# --- The gate -----------------------------------------------------------------


@pytest.mark.parametrize("name", golden_names())
def test_every_golden_render_matches_its_recorded_hash(name: str) -> None:
    recorded = json.loads(HASHES.read_text())

    assert name in recorded, f"{name} has no recorded hash"
    assert hashlib.sha256(render_wav(name)).hexdigest() == recorded[name], (
        f"{name} no longer renders the bytes it was recorded with. If the change "
        "was intended, re-record the corpus and say so in the commit."
    )


@pytest.mark.parametrize("name", golden_names())
def test_every_golden_render_lands_at_the_target_without_clipping(name: str) -> None:
    """The Quality bar for the corpus: nothing clips, nothing is silence, and
    every render leaves the bus at the normalization target."""
    samples = samples_of(render_wav(name))

    assert any(value != 0 for value in samples), "a golden should not be silence"
    assert min(samples) > -32768, f"{name} wrapped past negative full scale"
    assert max(samples) <= 32767
    assert peak_dbfs(samples) == pytest.approx(target_dbfs(payload_of(name)), abs=PEAK_TOLERANCE_DB)


@pytest.mark.parametrize("name", golden_names())
def test_every_golden_is_authored_in_range(name: str) -> None:
    """A golden that clamps would be recording a warning, not a sound."""
    _, warnings = validate_for_render(payload_of(name))

    assert warnings == []


def test_every_recorded_hash_still_has_a_spec() -> None:
    """A hash left behind after its spec was deleted would never be checked."""
    assert set(json.loads(HASHES.read_text())) == set(golden_names())


# --- The cross-platform half, which only CI can run ---------------------------


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_workflow_exists() -> None:
    assert WORKFLOW.is_file(), "the two-platform determinism gate lives in this file"


@pytest.mark.parametrize("runner", ["ubuntu-latest", "macos-latest"])
def test_the_gate_runs_on_both_platforms(runner: str) -> None:
    """Linux x86_64 and macOS arm64 are the two the acceptance names. One of them
    quietly dropping would leave the invariant unproven while CI stayed green."""
    assert runner in workflow_text()


def test_the_join_job_compares_hashes_across_platforms() -> None:
    text = workflow_text()

    assert "determinism:" in text, "the join job is what actually compares the two platforms"
    assert "scripts/golden_hashes.py" in text, "each platform emits its manifest with this script"
    assert "needs:" in text


def test_the_workflow_builds_wheels_for_both_platforms() -> None:
    text = workflow_text()

    assert "cibuildwheel" in text
    assert "upload-artifact" in text


@pytest.mark.parametrize(
    "step",
    [
        "ruff check",
        "ruff format",
        "mypy",
        "pytest",
        "check_no_libm",
        "blipsmith --help",
        "--boot-check",
    ],
)
def test_the_workflow_runs_every_local_gate_step(step: str) -> None:
    """CI has to be at least as strict as `scripts/verify.sh`, or the gate a
    contributor runs locally is not the gate the repo enforces."""
    assert step in workflow_text()


def emitted_manifest() -> dict[str, str]:
    """Run the manifest script the way CI runs it, rather than importing it: what
    CI consumes is this process's stdout, so that is what is worth testing."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "golden_hashes.py"), str(GOLDEN)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    parsed: dict[str, str] = json.loads(result.stdout)
    return parsed


def test_the_manifest_script_covers_the_whole_corpus() -> None:
    """The join job compares two manifests. One that skipped a spec would make
    the comparison pass on a corpus it never rendered."""
    assert set(emitted_manifest()) == set(golden_names())


def test_the_manifest_matches_the_recorded_hashes_on_this_platform() -> None:
    """The manifest and `hashes.json` have to be the same numbers, or the join
    job would be comparing something the local gate never checks."""
    assert emitted_manifest() == json.loads(HASHES.read_text())


def test_the_readme_documents_the_corpus_size() -> None:
    """The README quotes the corpus count. A number that drifts is worse than no
    number, because a reader has no way to tell it went stale."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    quoted = re.search(r"(\d+) golden specs", readme)

    assert quoted is not None, "the README should say how big the corpus is"
    assert int(quoted.group(1)) == len(golden_names())
