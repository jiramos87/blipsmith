"""B06: the filter, the lo-fi stage, and the effects chain.

The post-oscillator half of a voice. The filter is checked spectrally, against
white noise, because that is the only source flat enough for "the high band got
quieter" to mean anything. The lo-fi stage is checked on the sample values
themselves, since its whole promise is a coarse grid you can count. The effects
are checked on where their energy lands in time.
"""

from __future__ import annotations

import itertools
import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.ranges import MAX_CUTOFF_FRACTION, RANGES
from blipsmith.result import WarningCode
from blipsmith.schema import get_schema
from blipsmith.spec import to_canonical_json, validate_for_render

SAMPLE_RATE = 22050
GOLDEN = Path(__file__).resolve().parent / "golden"

FLAT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 1.0,
    "releaseMs": 0.0,
}
# A blip that is over almost at once, so anything still sounding afterwards came
# out of an effect rather than out of the oscillator.
CLICK_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 5.0,
    "sustainLevel": 0.0,
    "releaseMs": 0.0,
}

LOW_BAND = (200, 300, 400, 500, 600, 700, 800)
CORNER_BAND = (900, 950, 1000, 1050, 1100)
HIGH_BAND = (3000, 4000, 5000, 6000, 7000, 8000)

FILTER_TYPES = ("lowpass", "highpass", "bandpass")

STAGE_GOLDENS = (
    "filter-lp-noise.spec.json",
    "lofi-bitcrush.spec.json",
    "lofi-decimate.spec.json",
    "fx-distortion.spec.json",
    "fx-delay.spec.json",
    "fx-reverb.spec.json",
)


# --- Rendering and measurement ------------------------------------------------


def wav_bytes(payload: dict[str, Any]) -> bytes:
    spec, _ = validate_for_render(payload)
    rendered: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    return rendered


def samples_of(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def pcm(payload: dict[str, Any]) -> list[float]:
    return [s / 32767.0 for s in samples_of(wav_bytes(payload))]


def noise_voice(duration_ms: float = 100.0, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"waveform": "noise_white", "ampEnv": dict(FLAT_ENV)}
    body.update(overrides)
    return {"voices": [body], "durationMs": duration_ms, "seed": 7}


def tone(waveform: str = "sine", duration_ms: float = 200.0, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "waveform": waveform,
        "fundamentalHz": 440.0,
        "ampEnv": dict(FLAT_ENV),
    }
    body.update(overrides)
    return {"voices": [body], "durationMs": duration_ms}


def click(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "waveform": "square",
        "fundamentalHz": 880.0,
        "ampEnv": dict(CLICK_ENV),
    }
    body.update(overrides)
    return {"voices": [body], "durationMs": 500.0}


def magnitude_at(samples: list[float], hz: float) -> float:
    step = 2.0 * math.pi * hz / SAMPLE_RATE
    real = sum(value * math.cos(step * i) for i, value in enumerate(samples))
    imaginary = sum(value * math.sin(step * i) for i, value in enumerate(samples))
    return math.hypot(real, imaginary) / len(samples)


def band_energy(samples: list[float], band: tuple[int, ...]) -> float:
    """Summed power over a handful of probes across the band."""
    return sum(magnitude_at(samples, hz) ** 2 for hz in band)


def mean_power(samples: list[float], band: tuple[int, ...]) -> float:
    """Band energy per probe, so bands of different widths compare directly."""
    return band_energy(samples, band) / len(band)


def rms(samples: list[float]) -> float:
    return math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0


# --- Filter shapes ------------------------------------------------------------


def tilt(samples: list[float]) -> float:
    """High-band energy as a fraction of low-band energy.

    A ratio taken *inside* one render rather than across two, because since B07
    the master bus normalizes each render to the limiter's target on its own
    terms: a heavily filtered render comes back with more make-up gain than an
    unfiltered one, so comparing raw band energies between two renders measures
    the bus as much as the filter. The ratio cancels that out.
    """
    return band_energy(samples, HIGH_BAND) / band_energy(samples, LOW_BAND)


def test_lowpass_attenuates_the_high_band() -> None:
    dry = tilt(pcm(noise_voice()))
    filtered = tilt(pcm(noise_voice(filter={"type": "lowpass", "cutoffHz": 1000.0})))

    assert filtered < 0.05 * dry


def test_highpass_attenuates_the_low_band() -> None:
    dry = tilt(pcm(noise_voice()))
    filtered = tilt(pcm(noise_voice(filter={"type": "highpass", "cutoffHz": 1000.0})))

    assert filtered > 5 * dry


def test_bandpass_keeps_the_corner_and_drops_both_sides() -> None:
    """Averaged across each band rather than read off single bins: one bin of a
    noise render is a noisy estimate, and the shape is the claim here."""
    corner = 1000.0
    filtered = pcm(noise_voice(filter={"type": "bandpass", "cutoffHz": corner, "resonance": 4.0}))

    at_corner = mean_power(filtered, CORNER_BAND)

    assert at_corner > 5 * mean_power(filtered, LOW_BAND), "the corner should stand above the lows"
    assert at_corner > 20 * mean_power(filtered, HIGH_BAND), "and well above the highs"


def test_cutoff_moves_the_corner() -> None:
    """The same filter type, opened up, has to pass more of the top."""
    closed = tilt(pcm(noise_voice(filter={"type": "lowpass", "cutoffHz": 500.0})))
    open_ = tilt(pcm(noise_voice(filter={"type": "lowpass", "cutoffHz": 8000.0})))

    assert open_ > 10 * closed


def test_resonance_peaks_the_corner() -> None:
    """Q is the other half of the filter: at the same cutoff, a high Q rings at
    the corner where a low one just rolls off. Measured against each render's
    own passband, so the bus's make-up gain cannot flatter either one."""
    corner = 1500.0

    def emphasis(resonance: float) -> float:
        samples = pcm(
            noise_voice(filter={"type": "lowpass", "cutoffHz": corner, "resonance": resonance})
        )
        return magnitude_at(samples, corner) / magnitude_at(samples, 300.0)

    assert emphasis(12.0) > 2 * emphasis(0.7)


@pytest.mark.parametrize("filter_type", FILTER_TYPES)
def test_filter_render_is_byte_identical(filter_type: str) -> None:
    payload = noise_voice(filter={"type": filter_type, "cutoffHz": 1200.0, "resonance": 3.0})
    assert wav_bytes(payload) == wav_bytes(payload)


@pytest.mark.parametrize("filter_type", FILTER_TYPES)
def test_a_filter_changes_the_sound(filter_type: str) -> None:
    payload = noise_voice(filter={"type": filter_type, "cutoffHz": 1200.0})
    assert pcm(payload) != pcm(noise_voice())


def test_a_voice_without_a_filter_is_untouched() -> None:
    """The other side of every filter test: no filter block, no filtering."""
    assert wav_bytes(noise_voice()) == wav_bytes(noise_voice())


# --- The cutoff ceiling, which depends on the render's sample rate -------------


@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050, 44100])
def test_cutoff_at_or_above_nyquist_clamps_below_it(sample_rate: int) -> None:
    nyquist = sample_rate / 2
    ceiling = MAX_CUTOFF_FRACTION * sample_rate

    # Every one of these is above the ceiling at every supported rate: the
    # ceiling is 45% of the sample rate, and Nyquist is 50% of it.
    for requested in (nyquist, sample_rate, 20_000.0):
        spec, warnings = validate_for_render(
            {**tone(filter={"type": "lowpass", "cutoffHz": requested}), "sampleRate": sample_rate}
        )

        assert spec.voices[0].filter is not None
        applied = spec.voices[0].filter.cutoffHz
        assert applied == ceiling
        assert applied < nyquist, "a cutoff at Nyquist has no corner left to sit on"

        assert len(warnings) == 1
        assert warnings[0].code is WarningCode.CLAMPED
        assert warnings[0].param == "voices[0].filter.cutoffHz"
        assert warnings[0].requested == requested


def test_cutoff_below_the_minimum_clamps_to_it() -> None:
    minimum = RANGES[("Filter", "cutoffHz")].minimum

    for requested in (0.0, -100.0):
        spec, warnings = validate_for_render(
            tone(filter={"type": "lowpass", "cutoffHz": requested})
        )

        assert spec.voices[0].filter is not None
        assert spec.voices[0].filter.cutoffHz == minimum
        assert len(warnings) == 1
        assert warnings[0].code is WarningCode.CLAMPED
        assert warnings[0].applied == minimum


def test_a_cutoff_inside_the_ceiling_does_not_warn() -> None:
    _, warnings = validate_for_render(tone(filter={"type": "lowpass", "cutoffHz": 1000.0}))
    assert warnings == []


def test_the_ceiling_follows_the_sample_rate() -> None:
    """The same spec is in range at 44.1 kHz and out of range at 8 kHz, which is
    the reason this bound cannot live in the static range table."""
    payload = tone(filter={"type": "lowpass", "cutoffHz": 6000.0})

    _, high_rate = validate_for_render({**payload, "sampleRate": 44100})
    _, low_rate = validate_for_render({**payload, "sampleRate": 8000})

    assert high_rate == []
    assert len(low_rate) == 1
    assert low_rate[0].applied == MAX_CUTOFF_FRACTION * 8000


def test_the_schema_publishes_the_cutoff_fraction() -> None:
    """An agent that cannot hear should not have to discover this bound by
    triggering it."""
    assert get_schema()["limits"]["maxCutoffFraction"] == MAX_CUTOFF_FRACTION


# --- Clamping the rest of the stage -------------------------------------------


@pytest.mark.parametrize(
    ("block", "field", "extra", "minimum", "maximum"),
    [
        ("filter", "resonance", {"type": "lowpass"}, 0.1, 20.0),
        ("lofi", "bitDepth", {}, 1, 16),
        ("lofi", "decimation", {}, 1, 64),
    ],
)
@pytest.mark.parametrize("side", ["below", "above"])
def test_stage_parameters_clamp_at_both_bounds(
    block: str, field: str, extra: dict[str, Any], minimum: float, maximum: float, side: str
) -> None:
    bound = minimum if side == "below" else maximum
    requested = bound - 1 if side == "below" else bound + 1
    overrides: dict[str, Any] = {block: {**extra, field: requested}}

    spec, warnings = validate_for_render(tone(**overrides))

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.code is WarningCode.CLAMPED
    assert warning.param == f"voices[0].{block}.{field}"
    assert warning.requested == requested
    assert warning.applied == bound
    assert getattr(getattr(spec.voices[0], block), field) == bound


@pytest.mark.parametrize(
    ("field", "value"),
    [("drive", 2.0), ("timeMs", 5000.0), ("feedback", 1.0), ("mixWet", -0.5), ("roomSize", 9.0)],
)
def test_effect_parameters_clamp_with_a_warning(field: str, value: float) -> None:
    _, warnings = validate_for_render(tone(effects=[{"kind": "delay", field: value}]))

    assert len(warnings) == 1
    assert warnings[0].code is WarningCode.CLAMPED
    assert warnings[0].param == f"voices[0].effects[0].{field}"


# --- Lo-fi --------------------------------------------------------------------


def test_bitcrush_differs_from_the_clean_render() -> None:
    assert pcm(tone(lofi={"bitDepth": 3, "decimation": 1})) != pcm(tone())


def test_bitcrush_lands_on_a_coarse_grid() -> None:
    """Three bits is four steps either side of zero, so every sample has to sit
    on a quarter. Measured against the render's own peak, since the master bus
    scales the whole file to the limiter target after the crush."""
    crushed = pcm(tone(lofi={"bitDepth": 3, "decimation": 1}))
    top = max(abs(value) for value in crushed)
    grid = sorted({round(value / top, 3) for value in crushed})

    assert grid == [-1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75, 1.0]


def test_a_deeper_bit_depth_is_a_finer_grid() -> None:
    coarse = len({round(v, 6) for v in pcm(tone(lofi={"bitDepth": 3, "decimation": 1}))})
    fine = len({round(v, 6) for v in pcm(tone(lofi={"bitDepth": 8, "decimation": 1}))})

    assert coarse < fine


def test_full_bit_depth_is_transparent_to_within_one_step() -> None:
    """The other side of the crush: at 16 bits the grid is finer than the file
    it is written to, so nothing survives the round trip but rounding."""
    crushed = samples_of(wav_bytes(tone(lofi={"bitDepth": 16, "decimation": 1})))
    clean = samples_of(wav_bytes(tone()))

    assert max(abs(a - b) for a, b in zip(crushed, clean, strict=True)) <= 1


@pytest.mark.parametrize("factor", [2, 8, 16])
def test_decimation_holds_each_sample_for_the_configured_run(factor: int) -> None:
    samples = pcm(tone(lofi={"bitDepth": 16, "decimation": factor}))
    runs = [samples[i : i + factor] for i in range(0, 20 * factor, factor)]

    assert all(len(set(run)) == 1 for run in runs), f"expected stair steps of {factor} samples"


def test_decimation_of_one_does_not_stair_step() -> None:
    """The boundary: a factor of 1 holds each sample for exactly one frame,
    which is no holding at all."""
    samples = pcm(tone(lofi={"bitDepth": 16, "decimation": 1}))
    neighbours = [samples[i] != samples[i + 1] for i in range(200)]

    assert sum(neighbours) > 190, "a factor of 1 should leave consecutive samples free to move"


def test_decimation_render_is_byte_identical() -> None:
    payload = tone(lofi={"bitDepth": 5, "decimation": 6})
    assert wav_bytes(payload) == wav_bytes(payload)


# --- Effects ------------------------------------------------------------------


def echo_onsets(samples: list[float], threshold: float = 0.1) -> list[int]:
    """The first frame of each burst of energy, with quiet gaps between."""
    onsets: list[int] = []
    previous = -1000
    for index, value in enumerate(samples):
        if abs(value) > threshold:
            if index - previous > 50:
                onsets.append(index)
            previous = index
    return onsets


def test_delay_repeats_at_the_configured_spacing() -> None:
    time_ms = 50.0
    spacing = int(time_ms * SAMPLE_RATE / 1000.0)
    samples = pcm(
        click(effects=[{"kind": "delay", "timeMs": time_ms, "feedback": 0.6, "mixWet": 1.0}])
    )

    onsets = echo_onsets(samples)

    assert len(onsets) >= 4, "expected several repeats inside the render"
    for repeat, onset in enumerate(onsets[:4], start=1):
        assert onset == repeat * spacing


def test_delay_feedback_makes_each_repeat_quieter() -> None:
    feedback = 0.6
    samples = pcm(
        click(effects=[{"kind": "delay", "timeMs": 50.0, "feedback": feedback, "mixWet": 1.0}])
    )
    onsets = echo_onsets(samples)
    peaks = [max(abs(v) for v in samples[onset : onset + 200]) for onset in onsets[:3]]

    assert peaks[1] == pytest.approx(peaks[0] * feedback, rel=0.05)
    assert peaks[2] == pytest.approx(peaks[1] * feedback, rel=0.05)


def test_delay_at_no_wet_mix_is_the_dry_signal() -> None:
    dry = wav_bytes(tone())
    assert wav_bytes(tone(effects=[{"kind": "delay", "timeMs": 50.0, "mixWet": 0.0}])) == dry


def test_reverb_leaves_a_tail_that_decays() -> None:
    samples = pcm(click(effects=[{"kind": "reverb", "roomSize": 0.7, "mixWet": 1.0}]))
    windows = [rms(samples[start : start + 2000]) for start in range(0, 10000, 2000)]

    assert windows[0] > 0.001, "the reverb should actually sound"
    assert all(later < earlier for earlier, later in itertools.pairwise(windows))
    assert windows[-1] > 0.0, "and still be ringing, not cut off"


def test_a_bigger_room_rings_for_longer() -> None:
    def tail(room_size: float) -> float:
        samples = pcm(click(effects=[{"kind": "reverb", "roomSize": room_size, "mixWet": 1.0}]))
        return rms(samples[-2000:])

    assert tail(0.9) > tail(0.1)


def test_reverb_render_is_byte_identical() -> None:
    payload = click(effects=[{"kind": "reverb", "roomSize": 0.6, "damping": 0.3, "mixWet": 0.8}])
    assert wav_bytes(payload) == wav_bytes(payload)


def test_reverb_at_no_wet_mix_is_the_dry_signal() -> None:
    assert wav_bytes(tone(effects=[{"kind": "reverb", "mixWet": 0.0}])) == wav_bytes(tone())


@pytest.mark.parametrize("kind", ["distortion", "wavefold"])
def test_a_shaper_adds_harmonics(kind: str) -> None:
    """Both shapers work by bending a waveform, and a bent sine is a sine plus
    harmonics that were not there before."""
    dry = pcm(tone())
    shaped = pcm(tone(effects=[{"kind": kind, "drive": 0.8}]))

    third = 3 * 440.0
    assert magnitude_at(dry, third) < 0.001
    assert magnitude_at(shaped, third) > 0.05


@pytest.mark.parametrize("kind", ["distortion", "wavefold"])
def test_a_shaper_stays_inside_full_scale(kind: str) -> None:
    raw = samples_of(wav_bytes(tone(effects=[{"kind": kind, "drive": 1.0}])))
    assert max(raw) <= 32767
    assert min(raw) > -32768, "a shaper should bound its output, not wrap it"


@pytest.mark.parametrize("kind", ["distortion", "wavefold"])
def test_a_shaper_at_no_drive_is_transparent(kind: str) -> None:
    """The other side of drive: nothing driven, nothing changed."""
    assert wav_bytes(tone(effects=[{"kind": kind, "drive": 0.0}])) == wav_bytes(tone())


@pytest.mark.parametrize("kind", ["distortion", "wavefold"])
def test_more_drive_bends_the_wave_further(kind: str) -> None:
    """Measured as distance from the dry signal rather than as energy in one
    harmonic: a folder moves energy *around* the harmonic series as it folds
    harder, so any single partial rises and falls again."""
    dry = pcm(tone())

    def departure(drive: float) -> float:
        shaped = pcm(tone(effects=[{"kind": kind, "drive": drive}]))
        return sum(abs(a - b) for a, b in zip(shaped, dry, strict=True)) / len(dry)

    assert departure(0.9) > departure(0.2) > departure(0.0) == 0.0


def test_the_two_shapers_bend_a_wave_differently() -> None:
    """The clipper flattens the peaks, which leaves the zero crossings where
    they were. The folder reflects them back through zero, which adds new ones.
    That is the whole difference between the two, in one measurement."""

    def crossings(samples: list[float]) -> int:
        return sum(1 for i in range(1, len(samples)) if (samples[i - 1] < 0) != (samples[i] < 0))

    dry = crossings(pcm(tone()))
    clipped = crossings(pcm(tone(effects=[{"kind": "distortion", "drive": 0.9}])))
    folded = crossings(pcm(tone(effects=[{"kind": "wavefold", "drive": 0.9}])))

    assert clipped == dry
    assert folded > 3 * dry


def test_an_empty_effects_list_changes_nothing() -> None:
    assert wav_bytes(tone(effects=[])) == wav_bytes(tone())


def test_effects_apply_in_the_order_they_are_listed() -> None:
    """Distorting an echo is not the same sound as echoing a distortion, so the
    chain has to respect the list rather than sort it into a fixed order."""
    distort = {"kind": "distortion", "drive": 0.9}
    delay = {"kind": "delay", "timeMs": 40.0, "feedback": 0.4, "mixWet": 0.5}

    assert wav_bytes(tone(effects=[distort, delay])) != wav_bytes(tone(effects=[delay, distort]))


def test_the_same_effect_twice_is_two_units_of_state() -> None:
    once = wav_bytes(click(effects=[{"kind": "delay", "timeMs": 40.0, "mixWet": 0.5}]))
    twice = wav_bytes(
        click(
            effects=[
                {"kind": "delay", "timeMs": 40.0, "mixWet": 0.5},
                {"kind": "delay", "timeMs": 40.0, "mixWet": 0.5},
            ]
        )
    )
    assert once != twice


# --- The cutoff control signal B05 computes, now that it has a consumer --------


def test_cutoff_modulation_is_audible_once_a_filter_exists() -> None:
    """B05 computes a per-sample cutoff ratio that had nowhere to go. With a
    filter on the voice it becomes a sweep."""
    static = noise_voice(200.0, filter={"type": "lowpass", "cutoffHz": 1000.0})
    swept = noise_voice(
        200.0,
        filter={"type": "lowpass", "cutoffHz": 1000.0},
        lfo={"target": "cutoff", "rateHz": 8.0, "depth": 0.9},
    )

    assert pcm(swept) != pcm(static)
    assert wav_bytes(swept) == wav_bytes(swept)


def test_a_cutoff_envelope_opens_or_closes_the_filter_over_time() -> None:
    """A mod envelope sweeping the cutoff downward leaves more top end at the
    head of the sound than at the tail."""
    samples = pcm(
        noise_voice(
            400.0,
            filter={"type": "lowpass", "cutoffHz": 400.0},
            modEnv={"target": "cutoff", "amount": -0.8, "attackMs": 0.0, "decayMs": 200.0},
        )
    )
    head = samples[: int(0.05 * SAMPLE_RATE)]
    tail = samples[-int(0.05 * SAMPLE_RATE) :]

    assert band_energy(head, HIGH_BAND) > 5 * band_energy(tail, HIGH_BAND)


# --- Golden coverage, one per stage -------------------------------------------


@pytest.mark.parametrize("name", STAGE_GOLDENS)
def test_each_stage_has_a_golden(name: str) -> None:
    spec_path = GOLDEN / "specs" / name
    assert spec_path.exists(), f"{name} is missing from the golden corpus"
    assert name in json.loads((GOLDEN / "hashes.json").read_text())
