"""B13: the performance targets, measured on the path a user actually walks.

The PRD's numbers are a one-second mono one-shot under 50 ms and a thirty-second
five-track composition under 2 s. Both are measured end to end through
`blipsmith.render` (validate, compile the composition, render, encode, write the
WAV and its sidecar), because that is what the CLI does and what a build script
waits for. Timing the core alone would report a number nobody experiences.

Both specs are deliberately loaded rather than minimal: a bare sine would prove
the budget is generous, not that the engine is fast. The one-shot runs the whole
per-voice chain, and the composition paints 600 notes across five tracks.

The measurement is best-of-N, not mean. A shared CI runner is preempted at random
and the mean measures the neighbours; the best run is the one where the machine
let the work happen, and it is the only number that answers "can it do this at
all". Noise can only make a run slower, so a best-of that passes is honest.

CI multiplier: shared runners are several times slower than dev hardware, so the
budgets are multiplied by `BLIPSMITH_PERF_MULTIPLIER` when set, defaulting to
`CI_MULTIPLIER` on any machine that sets `CI` and to 1.0 otherwise. The point of
these tests is to catch an order-of-magnitude regression, not to police a runner.
Headroom on dev hardware as recorded: one-shot 7.6 ms of 50, composition 73 ms of
2000, so even the multiplied budgets stay far from the measurement.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from blipsmith.render import render

ONE_SHOT_BUDGET_MS = 50.0
COMPOSITION_BUDGET_MS = 2000.0

# Generous on purpose: a GitHub-hosted runner has no performance guarantee at all.
CI_MULTIPLIER = 5.0

RUNS = 5


def budget_multiplier() -> float:
    override = os.environ.get("BLIPSMITH_PERF_MULTIPLIER")
    if override:
        return float(override)
    return CI_MULTIPLIER if os.environ.get("CI") else 1.0


# --- The two specs the targets are stated for ---------------------------------


def loaded_one_shot() -> dict[str, Any]:
    """One second, mono, every per-voice stage switched on."""
    return {
        "durationMs": 1000.0,
        "channels": 1,
        "voices": [
            {
                "waveform": "saw",
                "fundamentalHz": 220.0,
                "fm": {"ratio": 2.0, "index": 3.0},
                "am": {"mode": "am", "rateHz": 6.0, "depth": 0.4},
                "lfo": {"target": "pitch", "rateHz": 5.0, "depth": 0.2, "shape": "sine"},
                "modEnv": {"target": "cutoff", "amount": 0.6, "attackMs": 1.0, "decayMs": 200.0},
                "filter": {"type": "lowpass", "cutoffHz": 3000.0, "resonance": 4.0},
                "lofi": {"bitDepth": 6, "decimation": 3},
                "effects": [
                    {"kind": "distortion", "drive": 0.6},
                    {"kind": "delay"},
                    {"kind": "reverb"},
                ],
            }
        ],
    }


def dense_composition(seconds: float = 30.0, tempo: float = 120.0) -> dict[str, Any]:
    """Thirty seconds, five tracks, an eighth-note grid painted solid on all of
    them: 600 notes, each a full run of its voice's chain from a clean slate."""
    steps_per_beat = 2
    beats = int(seconds / 60.0 * tempo)
    voices = [
        {
            "waveform": waveform,
            "fundamentalHz": hz,
            "track": index,
            "ampEnv": {
                "attackMs": 1.0,
                "decayMs": 60.0,
                "sustainLevel": 0.2,
                "releaseMs": 80.0,
            },
        }
        for index, (waveform, hz) in enumerate(
            [
                ("sine", 55.0),
                ("noise_white", 400.0),
                ("noise_pink", 900.0),
                ("square", 220.0),
                ("triangle", 330.0),
            ]
        )
    ]
    tracks = [
        {
            "stepsPerBeat": steps_per_beat,
            "gainDb": -6.0,
            "pan": (index - 2) * 0.4,
            "steps": [{"index": step, "velocity": 0.8} for step in range(beats * steps_per_beat)],
        }
        for index in range(5)
    ]
    return {
        "durationMs": seconds * 1000.0,
        "channels": 2,
        "voices": voices,
        "composition": {"tempoBpm": tempo, "swing": 0.1, "tracks": tracks},
    }


# --- Measurement --------------------------------------------------------------


def timed_render_ms(payload: dict[str, Any], out_dir: Path, run: int) -> float:
    named = {**payload, "meta": {"name": f"perf-{run}"}}
    start = time.perf_counter()
    result = render(named, out_dir=out_dir, overwrite=True)
    elapsed = (time.perf_counter() - start) * 1000.0

    assert result.error is None, result.error
    return elapsed


def best_render_ms(payload: dict[str, Any], out_dir: Path) -> float:
    # Run 0 is a warm-up and is thrown away: the first call into the core pages
    # in the baked tables, and charging that to the budget measures the import.
    timed_render_ms(payload, out_dir, 0)
    return min(timed_render_ms(payload, out_dir, run) for run in range(1, RUNS + 1))


def test_a_one_second_one_shot_renders_under_the_budget(tmp_path: Path) -> None:
    budget = ONE_SHOT_BUDGET_MS * budget_multiplier()

    elapsed = best_render_ms(loaded_one_shot(), tmp_path)

    assert elapsed < budget, f"one-shot took {elapsed:.1f} ms against a {budget:.0f} ms budget"


def test_a_thirty_second_five_track_composition_renders_under_the_budget(tmp_path: Path) -> None:
    budget = COMPOSITION_BUDGET_MS * budget_multiplier()

    elapsed = best_render_ms(dense_composition(), tmp_path)

    assert elapsed < budget, f"composition took {elapsed:.1f} ms against a {budget:.0f} ms budget"


# --- The measurement is measuring what it claims to ---------------------------


def test_the_composition_really_carries_five_tracks_of_notes() -> None:
    """A budget met by rendering an empty grid would prove nothing."""
    from blipsmith.composition import compile_composition
    from blipsmith.spec import validate_for_render

    spec, _ = validate_for_render(dense_composition())
    compiled, warnings = compile_composition(spec)

    assert compiled.composition is not None
    counts = [len(track.notes) for track in compiled.composition.tracks]
    assert all(count > 0 for count in counts), counts
    assert sum(counts) == 600
    assert warnings == [], "a dropped note would quietly shrink the benchmark"


def test_the_one_shot_really_runs_the_whole_chain() -> None:
    from blipsmith.spec import validate_for_render

    spec, warnings = validate_for_render(loaded_one_shot())
    voice = spec.voices[0]

    assert warnings == [], "a clamped benchmark is measuring a different spec"
    assert voice.fm and voice.am and voice.lfo and voice.modEnv
    assert voice.filter and voice.lofi
    assert len(voice.effects) == 3


@pytest.mark.parametrize(
    ("environment", "expected"),
    [({}, 1.0), ({"CI": "true"}, CI_MULTIPLIER), ({"BLIPSMITH_PERF_MULTIPLIER": "3"}, 3.0)],
    ids=["dev", "ci", "explicit-override"],
)
def test_the_ci_multiplier_is_applied_where_documented(
    environment: dict[str, str], expected: float, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("BLIPSMITH_PERF_MULTIPLIER", raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)

    assert budget_multiplier() == expected


def test_an_explicit_multiplier_wins_over_the_ci_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("BLIPSMITH_PERF_MULTIPLIER", "2")

    assert budget_multiplier() == 2.0
