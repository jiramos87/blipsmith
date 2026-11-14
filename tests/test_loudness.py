"""Integrated loudness and true peak, the two measures the music mode adds.

The reference point is the one BS.1770 itself gives: a 1 kHz sine at full scale
in one channel reads -3.01 LUFS. blipsmith normalizes every render to its
limiter target, so the sine here peaks at -1 dBFS and should read 1 dB lower.
"""

from __future__ import annotations

from typing import Any

import pytest

import blipsmith
from blipsmith.spec import to_canonical_json, validate_for_render


def sine(rate: int, **top: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "sampleRate": rate,
        "durationMs": 3000,
        "voices": [
            {
                "waveform": "sine",
                "fundamentalHz": 1000.0,
                "ampEnv": {"attackMs": 0, "decayMs": 0, "sustainLevel": 1, "releaseMs": 0},
            }
        ],
    }
    spec.update(top)
    return spec


def features(spec: dict[str, Any]) -> dict[str, float]:
    validated, _ = validate_for_render(spec)
    result: dict[str, float] = blipsmith._core.render(to_canonical_json(validated))["features"]
    return result


@pytest.mark.parametrize("rate", [22050, 44100])
def test_a_full_scale_sine_reads_the_reference_loudness(rate: int) -> None:
    measured = features(sine(rate))
    assert measured["integratedLufs"] == pytest.approx(-3.01 - 1.0, abs=0.1)


def test_two_identical_channels_read_three_db_louder() -> None:
    mono = features(sine(44100))["integratedLufs"]
    stereo = features(sine(44100, channels=2))["integratedLufs"]
    # Both channels are normalized to the same peak, and BS.1770 sums their
    # power: twice the power is 3 dB.
    assert stereo == pytest.approx(mono + 3.01, abs=0.05)


def test_true_peak_never_reads_below_the_sample_peak() -> None:
    measured = features(sine(8000))
    assert measured["truePeakDbtp"] >= measured["peakDbfs"] - 1e-9
    assert measured["truePeakDbtp"] == pytest.approx(-1.0, abs=0.2)


def test_the_measures_repeat_exactly() -> None:
    assert features(sine(16000)) == features(sine(16000))
