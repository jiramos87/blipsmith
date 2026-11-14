"""B08: the six acoustic features, measured from the finished audio.

These are the only thing standing between a driving agent and total blindness,
so the tests care about two properties above all: that a number means what its
name says, and that it is as reproducible as the PCM it was taken from.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.ranges import LIMITER_TARGET_DBFS
from blipsmith.spec import to_canonical_json, validate_for_render

GOLDEN = Path(__file__).resolve().parent / "golden"

FEATURE_KEYS = (
    "durationMs",
    "peakDbfs",
    "rmsDbfs",
    "estimatedFundamentalHz",
    "spectralCentroidHz",
    "attackTimeMs",
    # docs/prd/blipsmith-music-mode.md: loudness and true peak, on every render.
    "integratedLufs",
    "truePeakDbtp",
)

FLAT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 1.0,
    "releaseMs": 0.0,
}
# Every stage at zero, which is the only way to ask for an actually silent
# render: leaving the default 5 ms attack in place still makes a click.
SILENT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 0.0,
    "releaseMs": 0.0,
}

# The pitch estimator reads the audio, not the spec. Hard-edged waveforms at a
# pitch that does not divide the sample rate genuinely differ from cycle to
# cycle, so 2% is the honest ceiling rather than a placeholder.
PITCH_TOLERANCE = 0.02

# Silence has no decibel value; the core reports this floor instead of -inf so
# the number stays serializable and comparable.
SILENCE_DBFS = -120.0


def features_of(payload: dict[str, Any]) -> dict[str, float]:
    spec, _ = validate_for_render(payload)
    measured: dict[str, float] = blipsmith._core.render(to_canonical_json(spec))["features"]
    return measured


def tone(waveform: str = "sine", duration_ms: float = 500.0, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "waveform": waveform,
        "fundamentalHz": 440.0,
        "ampEnv": dict(FLAT_ENV),
    }
    body.update(overrides)
    return {"voices": [body], "durationMs": duration_ms}


# --- The contract: eight keys, always present, never null ---------------------


def test_every_pinned_feature_key_is_present() -> None:
    assert set(features_of(tone())) == set(FEATURE_KEYS)


@pytest.mark.parametrize(
    "payload",
    [
        tone("sine"),
        tone("noise_white"),
        tone("square", duration_ms=10.0),
        {**tone(), "channels": 2},
        {**tone(), "sampleRate": 8000},
        {"voices": [{"waveform": "sine", "ampEnv": dict(SILENT_ENV)}]},
    ],
    ids=["sine", "noise", "very-short", "stereo", "low-rate", "silent"],
)
def test_no_feature_is_ever_null(payload: dict[str, Any]) -> None:
    """Including the awkward renders: a 10 ms blip is too short to hold a pitch,
    and silence has no peak, but neither may hand back a null."""
    measured = features_of(payload)

    assert set(measured) == set(FEATURE_KEYS)
    for key, value in measured.items():
        assert value is not None, f"{key} came back null"
        assert isinstance(value, float)
        assert math.isfinite(value), f"{key} is not a finite number"


# --- Level -------------------------------------------------------------------


def test_peak_matches_the_normalization_target() -> None:
    """The bus normalizes every render, so this is the number that proves it."""
    assert features_of(tone())["peakDbfs"] == pytest.approx(LIMITER_TARGET_DBFS, abs=0.01)


@pytest.mark.parametrize("target", [-0.5, -6.0, -18.0])
def test_peak_follows_the_limiter_target(target: float) -> None:
    measured = features_of({**tone(), "master": {"limiter": {"targetDbfs": target}}})
    assert measured["peakDbfs"] == pytest.approx(target, abs=0.01)


def test_rms_sits_below_the_peak_by_the_waveform_crest() -> None:
    """A sine's RMS is 3 dB under its peak, a square's is at it. Getting both
    right is what makes the pair worth reporting rather than just the peak."""
    sine = features_of(tone("sine"))
    square = features_of(tone("square"))

    assert sine["peakDbfs"] - sine["rmsDbfs"] == pytest.approx(3.01, abs=0.1)
    assert square["peakDbfs"] - square["rmsDbfs"] == pytest.approx(0.0, abs=0.1)


def test_a_sparse_sound_reads_quieter_than_a_sustained_one() -> None:
    """Both peak at the target; RMS is what tells them apart."""
    sustained = features_of(tone("sine", duration_ms=500.0))
    blip = features_of(
        tone(
            "sine",
            duration_ms=500.0,
            ampEnv={"attackMs": 0.0, "decayMs": 20.0, "sustainLevel": 0.0, "releaseMs": 0.0},
        )
    )

    assert blip["rmsDbfs"] < sustained["rmsDbfs"] - 10
    assert blip["peakDbfs"] == pytest.approx(sustained["peakDbfs"], abs=0.01)


def test_silence_reports_the_floor_rather_than_negative_infinity() -> None:
    measured = features_of({"voices": [{"waveform": "sine", "ampEnv": dict(SILENT_ENV)}]})

    assert measured["peakDbfs"] == SILENCE_DBFS
    assert measured["rmsDbfs"] == SILENCE_DBFS
    assert math.isfinite(measured["peakDbfs"])


def test_the_decibel_conversion_round_trips_against_the_spec() -> None:
    """dBFS needs a logarithm, which is as banned as `pow`, so the core builds
    one. This checks it against Python's, which is the reference it replaced."""
    for mix_db in (-40.0, -12.0, -3.0):
        measured = features_of(
            {**tone(), "master": {"limiter": {"targetDbfs": max(mix_db, -24.0)}}}
        )
        expected = max(mix_db, -24.0)
        assert measured["peakDbfs"] == pytest.approx(expected, abs=0.01)


# --- Pitch --------------------------------------------------------------------


@pytest.mark.parametrize("hz", [55.0, 110.0, 220.0, 440.0, 880.0, 1760.0])
@pytest.mark.parametrize("waveform", ["sine", "square", "saw", "triangle"])
def test_the_estimated_fundamental_finds_the_pitch(waveform: str, hz: float) -> None:
    measured = features_of(tone(waveform, fundamentalHz=hz))
    assert measured["estimatedFundamentalHz"] == pytest.approx(hz, rel=PITCH_TOLERANCE)


@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050, 44100])
def test_the_pitch_estimate_holds_across_sample_rates(sample_rate: int) -> None:
    measured = features_of({**tone(), "sampleRate": sample_rate})
    assert measured["estimatedFundamentalHz"] == pytest.approx(440.0, rel=PITCH_TOLERANCE)


@pytest.mark.parametrize("note", [36, 60, 69, 96])
def test_a_midi_note_reads_back_as_its_own_frequency(note: int) -> None:
    measured = features_of(tone("sine", fundamentalMidi=note))
    expected = 440.0 * 2 ** ((note - 69) / 12)
    assert measured["estimatedFundamentalHz"] == pytest.approx(expected, rel=PITCH_TOLERANCE)


def test_the_pitch_estimate_does_not_answer_an_octave_down() -> None:
    """Every multiple of the period correlates about as well as the period, so
    the naive reading of an autocorrelation halves the pitch. Checked explicitly
    because it is the failure this estimator is built to avoid."""
    for hz in (220.0, 440.0, 880.0):
        measured = features_of(tone("saw", fundamentalHz=hz))
        assert measured["estimatedFundamentalHz"] > 0.75 * hz


def test_a_pitchless_render_reports_zero_rather_than_a_guess() -> None:
    """The documented "could not estimate" answer, and it is a number rather
    than a null so the caller can test for it. Silence is the case that reaches
    it: there is no peak to correlate against."""
    measured = features_of({"voices": [{"waveform": "sine", "ampEnv": dict(SILENT_ENV)}]})
    assert measured["estimatedFundamentalHz"] == 0.0
    assert measured["spectralCentroidHz"] == 0.0
    assert measured["attackTimeMs"] == 0.0


def test_the_shortest_allowed_render_still_measures_a_pitch() -> None:
    """The other side of that boundary. The floor is 10 ms, which at the lowest
    sample rate is 80 samples: thin, but four cycles of a 440 Hz tone, and the
    estimator should use them rather than give up."""
    measured = features_of({**tone(duration_ms=10.0), "sampleRate": 8000})
    assert measured["estimatedFundamentalHz"] == pytest.approx(440.0, rel=PITCH_TOLERANCE)


# --- Brightness ---------------------------------------------------------------


def test_a_bright_saw_reads_brighter_than_a_dark_filtered_sine() -> None:
    saw = features_of(tone("saw", fundamentalHz=220.0))
    filtered_sine = features_of(
        tone("sine", fundamentalHz=220.0, filter={"type": "lowpass", "cutoffHz": 300.0})
    )

    assert saw["spectralCentroidHz"] > 5 * filtered_sine["spectralCentroidHz"]


def test_the_centroid_of_a_sine_sits_on_the_sine() -> None:
    """A pure tone has one partial, so its centre of mass is its own pitch."""
    measured = features_of(tone("sine", fundamentalHz=440.0))
    assert measured["spectralCentroidHz"] == pytest.approx(440.0, rel=0.05)


def test_closing_a_filter_lowers_the_centroid() -> None:
    """The measurement an agent would actually steer by: it darkened the sound,
    did the number move?"""
    open_ = features_of(tone("saw", filter={"type": "lowpass", "cutoffHz": 8000.0}))
    closed = features_of(tone("saw", filter={"type": "lowpass", "cutoffHz": 600.0}))

    assert closed["spectralCentroidHz"] < open_["spectralCentroidHz"]


def test_white_noise_reads_brighter_than_pink() -> None:
    """Pink noise falls off with frequency and white does not, so this is the
    ordering the names promise."""
    white = features_of(tone("noise_white"))
    pink = features_of(tone("noise_pink"))

    assert white["spectralCentroidHz"] > pink["spectralCentroidHz"]


def test_more_fm_index_reads_brighter() -> None:
    gentle = features_of(tone("sine", fm={"ratio": 2.0, "index": 0.5}))
    clangy = features_of(tone("sine", fm={"ratio": 2.0, "index": 12.0}))

    assert clangy["spectralCentroidHz"] > 2 * gentle["spectralCentroidHz"]


# --- Attack -------------------------------------------------------------------


@pytest.mark.parametrize("attack_ms", [0.0, 20.0, 50.0, 200.0])
def test_the_attack_time_reflects_the_envelope(attack_ms: float) -> None:
    """Measured from the audio, so it cannot resolve finer than a quarter cycle
    of the fundamental: a 440 Hz sine takes 0.57 ms to first reach its peak."""
    measured = features_of(
        tone(
            "sine",
            duration_ms=800.0,
            ampEnv={
                "attackMs": attack_ms,
                "decayMs": 0.0,
                "sustainLevel": 1.0,
                "releaseMs": 0.0,
            },
        )
    )

    assert measured["attackTimeMs"] == pytest.approx(attack_ms, abs=2.0)


def test_a_slow_attack_reads_slower_than_a_fast_one() -> None:
    def attack_of(attack_ms: float) -> float:
        return features_of(
            tone(
                "square",
                duration_ms=800.0,
                ampEnv={
                    "attackMs": attack_ms,
                    "decayMs": 0.0,
                    "sustainLevel": 1.0,
                    "releaseMs": 0.0,
                },
            )
        )["attackTimeMs"]

    assert attack_of(300.0) > attack_of(100.0) > attack_of(10.0)


def test_duration_is_measured_from_the_frames_that_exist() -> None:
    for duration in (100.0, 250.0, 1000.0):
        assert features_of(tone(duration_ms=duration))["durationMs"] == pytest.approx(
            duration, abs=1.0
        )


# --- Determinism --------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        tone("sine"),
        tone("noise_pink"),
        {**tone("saw", filter={"type": "lowpass", "cutoffHz": 900.0}), "channels": 2},
        tone("square", effects=[{"kind": "reverb", "roomSize": 0.7, "mixWet": 0.5}]),
    ],
    ids=["sine", "pink-noise", "stereo-filtered", "reverb"],
)
def test_features_repeat_exactly(payload: dict[str, Any]) -> None:
    """A feature is something an agent steers by, so it has to be as
    reproducible as the PCM it measures."""
    assert features_of(payload) == features_of(payload)


def test_the_seed_moves_noise_features_and_leaves_a_sine_alone() -> None:
    base = tone("noise_white")
    assert features_of({**base, "seed": 1}) != features_of({**base, "seed": 2})

    sine = tone("sine")
    assert features_of({**sine, "seed": 1}) == features_of({**sine, "seed": 2})


# --- The corpus ---------------------------------------------------------------


def golden_cases() -> list[str]:
    return sorted(path.name for path in (GOLDEN / "specs").glob("*.spec.json"))


@pytest.mark.parametrize("name", golden_cases())
def test_every_golden_reports_a_complete_feature_set(name: str) -> None:
    measured = features_of(json.loads((GOLDEN / "specs" / name).read_text()))

    assert set(measured) == set(FEATURE_KEYS)
    assert all(value is not None and math.isfinite(value) for value in measured.values())
    assert measured["durationMs"] > 0
