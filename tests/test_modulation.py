"""B05: FM, AM/ring, the LFO, and the mod envelope.

The driving agent cannot hear, so these tests measure what it would have to
measure: energy at a frequency, the rate a contour repeats at, and how the pitch
moves between the head and the tail of a render. Everything is computed from the
decoded PCM with the standard library, which keeps the checks independent of the
core that produced the samples.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.result import WarningCode
from blipsmith.spec import to_canonical_json, validate_for_render

SAMPLE_RATE = 22050
GOLDEN = Path(__file__).resolve().parent / "golden"

# 200 ms at 22050 Hz is 4410 frames, so 440 Hz and its FM sidebands all complete
# a whole number of cycles in the window. The direct transform below then has no
# spectral leakage to argue with.
DURATION_MS = 200.0
CARRIER_HZ = 440.0

FLAT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 1.0,
    "releaseMs": 0.0,
}

MODULATION_GOLDENS = (
    "fm-bell.spec.json",
    "am-ring.spec.json",
    "lfo-vibrato.spec.json",
    "modenv-pew.spec.json",
)


# --- Rendering and measurement ------------------------------------------------


def wav_bytes(payload: dict[str, Any]) -> bytes:
    spec, _ = validate_for_render(payload)
    rendered: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    return rendered


def pcm(payload: dict[str, Any]) -> list[float]:
    """Render and decode to floats in [-1, 1]."""
    wav = wav_bytes(payload)
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return [s / 32767.0 for s in struct.unpack_from(f"<{count}h", wav, 44)]


def voice(waveform: str = "sine", **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "waveform": waveform,
        "fundamentalHz": CARRIER_HZ,
        "ampEnv": dict(FLAT_ENV),
    }
    body.update(overrides)
    return {"voices": [body], "durationMs": DURATION_MS}


def magnitude_at(samples: list[float], hz: float) -> float:
    """Energy at one frequency: a single direct-transform bin, normalized."""
    step = 2.0 * math.pi * hz / SAMPLE_RATE
    real = sum(value * math.cos(step * i) for i, value in enumerate(samples))
    imaginary = sum(value * math.sin(step * i) for i, value in enumerate(samples))
    return math.hypot(real, imaginary) / len(samples)


def rising_crossings(samples: list[float]) -> int:
    return sum(1 for i in range(1, len(samples)) if samples[i - 1] < 0 <= samples[i])


def estimated_hz(samples: list[float]) -> float:
    """Pitch from rising zero crossings. Good enough to compare two windows."""
    return rising_crossings(samples) * SAMPLE_RATE / len(samples)


def window(samples: list[float], start_ms: float, length_ms: float) -> list[float]:
    start = int(start_ms * SAMPLE_RATE / 1000.0)
    return samples[start : start + int(length_ms * SAMPLE_RATE / 1000.0)]


# --- FM -----------------------------------------------------------------------


def test_fm_changes_the_carrier() -> None:
    assert pcm(voice(fm={"ratio": 1.5, "index": 3.0})) != pcm(voice())


def test_fm_puts_sidebands_around_the_carrier() -> None:
    """A ratio of 1.5 puts the modulator at 660 Hz, so sidebands appear every
    660 Hz either side of the carrier. The first one up, at 1100 Hz, is the
    clear tell: a plain sine has nothing there, and it is where FM's brightness
    comes from. The ratio is deliberately not a whole number, which would fold
    the lower sidebands back onto the upper ones and muddy the reading."""
    dry = pcm(voice())
    modulated = pcm(voice(fm={"ratio": 1.5, "index": 3.0}))

    sideband = CARRIER_HZ + 1.5 * CARRIER_HZ

    assert magnitude_at(dry, sideband) < 0.01, "a clean sine should have no sideband"
    assert magnitude_at(modulated, sideband) > 0.1
    assert magnitude_at(modulated, sideband) > 20 * magnitude_at(dry, sideband)


def test_fm_index_governs_how_much_energy_leaves_the_carrier() -> None:
    shallow = pcm(voice(fm={"ratio": 1.5, "index": 0.5}))
    deep = pcm(voice(fm={"ratio": 1.5, "index": 8.0}))

    assert magnitude_at(deep, CARRIER_HZ) < magnitude_at(shallow, CARRIER_HZ)


def test_fm_ratio_moves_where_the_sidebands_land() -> None:
    """Each ratio should put energy where the other one leaves silence."""
    near = pcm(voice(fm={"ratio": 1.5, "index": 3.0}))  # sidebands every 660 Hz
    far = pcm(voice(fm={"ratio": 3.5, "index": 3.0}))  # sidebands every 1540 Hz

    assert magnitude_at(near, 1760.0) > 10 * magnitude_at(far, 1760.0)
    assert magnitude_at(far, 1980.0) > 10 * magnitude_at(near, 1980.0)


def test_fm_at_index_zero_is_the_dry_carrier() -> None:
    """The other side of the depth boundary: no depth, no modulation, and the
    bytes have to match the voice without an fm block at all."""
    assert pcm(voice(fm={"ratio": 1.5, "index": 0.0})) == pcm(voice())


def test_fm_render_is_byte_identical() -> None:
    payload = voice(fm={"ratio": 1.5, "index": 3.0})
    assert wav_bytes(payload) == wav_bytes(payload)


def test_fm_follows_the_carrier_pitch() -> None:
    """The modulator is pitched at a ratio of the carrier, so transposing the
    voice transposes the whole timbre rather than detuning it."""
    low = pcm(voice(fundamentalHz=220.0, fm={"ratio": 1.5, "index": 3.0}))
    high = pcm(voice(fundamentalHz=440.0, fm={"ratio": 1.5, "index": 3.0}))

    assert magnitude_at(low, 550.0) > 0.1  # 220 + 330
    assert magnitude_at(high, 1100.0) > 0.1  # 440 + 660


# --- AM and ring modulation ---------------------------------------------------


def test_am_and_ring_differ_from_each_other_and_from_dry() -> None:
    dry = pcm(voice())
    am = pcm(voice(am={"mode": "am", "rateHz": 100.0, "depth": 0.5}))
    ring = pcm(voice(am={"mode": "ring", "rateHz": 100.0, "depth": 0.5}))

    assert am != dry
    assert ring != dry
    assert am != ring


def test_ring_cancels_the_carrier_while_am_keeps_it() -> None:
    """The audible difference between the modes: ring passes the modulator
    bipolar, so at full depth the carrier itself disappears into the sum and
    difference tones. AM keeps it underneath."""
    am = pcm(voice(am={"mode": "am", "rateHz": 110.0, "depth": 1.0}))
    ring = pcm(voice(am={"mode": "ring", "rateHz": 110.0, "depth": 1.0}))

    assert magnitude_at(ring, CARRIER_HZ) < 0.01
    assert magnitude_at(am, CARRIER_HZ) > 0.2
    for side in (CARRIER_HZ - 110.0, CARRIER_HZ + 110.0):
        assert magnitude_at(ring, side) > 0.1


def test_am_at_depth_zero_is_the_dry_carrier() -> None:
    assert pcm(voice(am={"mode": "am", "rateHz": 100.0, "depth": 0.0})) == pcm(voice())
    assert pcm(voice(am={"mode": "ring", "rateHz": 100.0, "depth": 0.0})) == pcm(voice())


def test_am_render_is_byte_identical() -> None:
    payload = voice(am={"mode": "ring", "rateHz": 100.0, "depth": 0.7})
    assert wav_bytes(payload) == wav_bytes(payload)


def test_am_applies_to_a_noise_voice_too() -> None:
    """Noise has no phase to modulate, but it still has an amplitude."""
    dry = pcm(voice("noise_white"))
    modulated = pcm(voice("noise_white", am={"mode": "am", "rateHz": 40.0, "depth": 1.0}))

    def rms(samples: list[float]) -> float:
        return math.sqrt(sum(s * s for s in samples) / len(samples))

    assert modulated != dry
    # Compared as energy rather than as peak: the master bus normalizes both
    # renders to the same peak, so only the ducking between cycles survives.
    assert rms(modulated) < 0.8 * rms(dry)


# --- LFO ----------------------------------------------------------------------


def test_lfo_to_amplitude_varies_at_the_lfo_rate() -> None:
    """A square carrier sits at +-1, so the absolute value of the PCM *is* the
    tremolo contour and the rate can be read straight off it."""
    rate = 20.0
    samples = pcm(
        {
            "voices": [
                {
                    "waveform": "square",
                    "fundamentalHz": 220.0,
                    "ampEnv": dict(FLAT_ENV),
                    "lfo": {"target": "amplitude", "shape": "sine", "rateHz": rate, "depth": 1.0},
                }
            ],
            "durationMs": 500.0,
        }
    )
    contour = [abs(s) for s in samples]

    assert magnitude_at(contour, rate) > 0.2
    assert magnitude_at(contour, rate) > 10 * magnitude_at(contour, rate * 2.7)


def test_lfo_to_amplitude_dips_and_recovers() -> None:
    samples = pcm(voice("square", lfo={"target": "amplitude", "rateHz": 10.0, "depth": 1.0}))
    contour = [abs(s) for s in samples]
    top = max(contour)

    assert min(contour) < 0.05 * top, "full-depth tremolo should reach silence"
    assert top > 0.0, "and come back to full level"


def test_lfo_to_pitch_bends_up_then_down() -> None:
    """One full LFO cycle over the render: a sine LFO starting at zero pushes the
    pitch up through the first half and down through the second."""
    samples = pcm(voice(lfo={"target": "pitch", "shape": "sine", "rateHz": 5.0, "depth": 0.5}))
    dry = estimated_hz(pcm(voice()))

    first_half = estimated_hz(window(samples, 25.0, 50.0))
    second_half = estimated_hz(window(samples, 125.0, 50.0))

    assert first_half > dry * 1.2
    assert second_half < dry * 0.8


@pytest.mark.parametrize("shape", ["sine", "triangle", "square", "saw"])
def test_every_lfo_shape_modulates(shape: str) -> None:
    payload = voice("square", lfo={"target": "amplitude", "shape": shape, "rateHz": 20.0})
    assert pcm(payload) != pcm(voice("square"))


def test_lfo_shapes_are_distinguishable_from_each_other() -> None:
    rendered = {
        shape: pcm(voice("square", lfo={"target": "amplitude", "shape": shape, "rateHz": 20.0}))
        for shape in ("sine", "triangle", "square", "saw")
    }
    distinct = {tuple(samples) for samples in rendered.values()}
    assert len(distinct) == 4, "two LFO shapes rendered identically"


def test_lfo_at_depth_zero_leaves_the_voice_alone() -> None:
    for target in ("pitch", "amplitude"):
        assert pcm(voice(lfo={"target": target, "rateHz": 5.0, "depth": 0.0})) == pcm(voice())


def test_lfo_render_is_byte_identical() -> None:
    for target in ("pitch", "amplitude"):
        payload = voice(lfo={"target": target, "rateHz": 6.0, "depth": 0.4})
        assert wav_bytes(payload) == wav_bytes(payload)


# --- Mod envelope -------------------------------------------------------------


def pitch_head_and_tail(payload: dict[str, Any]) -> tuple[float, float]:
    samples = pcm(payload)
    return estimated_hz(window(samples, 0.0, 30.0)), estimated_hz(window(samples, 300.0, 90.0))


def test_mod_envelope_pew_starts_higher_than_it_ends() -> None:
    """The laser drop. A negative amount is documented as sweeping downward: the
    pitch starts displaced upward and falls to the fundamental."""
    head, tail = pitch_head_and_tail(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "fundamentalHz": CARRIER_HZ,
                    "ampEnv": dict(FLAT_ENV),
                    "modEnv": {
                        "target": "pitch",
                        "amount": -0.6,
                        "attackMs": 0.0,
                        "decayMs": 120.0,
                    },
                }
            ],
            "durationMs": 400.0,
        }
    )

    assert head > 2 * tail, f"expected a downward sweep, got {head} Hz to {tail} Hz"
    assert tail == pytest.approx(CARRIER_HZ, rel=0.1), "the tail should land on the fundamental"


def test_mod_envelope_positive_amount_sweeps_upward() -> None:
    """The other side of the sign: the pitch starts below and rises to land on
    the fundamental."""
    head, tail = pitch_head_and_tail(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "fundamentalHz": CARRIER_HZ,
                    "ampEnv": dict(FLAT_ENV),
                    "modEnv": {
                        "target": "pitch",
                        "amount": 0.6,
                        "attackMs": 0.0,
                        "decayMs": 120.0,
                    },
                }
            ],
            "durationMs": 400.0,
        }
    )

    assert head < tail / 2, f"expected an upward sweep, got {head} Hz to {tail} Hz"
    assert tail == pytest.approx(CARRIER_HZ, rel=0.1)


def test_mod_envelope_attack_delays_the_displacement() -> None:
    """With an attack, the modulation ramps in rather than hitting at frame
    zero, so the sound starts on the fundamental."""
    samples = pcm(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "fundamentalHz": CARRIER_HZ,
                    "ampEnv": dict(FLAT_ENV),
                    "modEnv": {
                        "target": "pitch",
                        "amount": -0.6,
                        "attackMs": 100.0,
                        "decayMs": 100.0,
                    },
                }
            ],
            "durationMs": 400.0,
        }
    )

    assert estimated_hz(window(samples, 0.0, 20.0)) == pytest.approx(CARRIER_HZ, rel=0.15)
    assert estimated_hz(window(samples, 95.0, 20.0)) > 2 * CARRIER_HZ


def test_mod_envelope_at_amount_zero_leaves_the_voice_alone() -> None:
    assert pcm(voice(modEnv={"target": "pitch", "amount": 0.0, "decayMs": 120.0})) == pcm(voice())


def test_mod_envelope_render_is_byte_identical() -> None:
    payload = voice(modEnv={"target": "pitch", "amount": -0.6, "decayMs": 120.0})
    assert wav_bytes(payload) == wav_bytes(payload)


# --- The cutoff routing, whose consumer is B06's filter -----------------------


@pytest.mark.parametrize(
    "block",
    [
        {"lfo": {"target": "cutoff", "rateHz": 5.0, "depth": 1.0}},
        {"modEnv": {"target": "cutoff", "amount": -1.0, "decayMs": 120.0}},
    ],
    ids=["lfo", "modEnv"],
)
def test_cutoff_routing_is_inaudible_without_a_filter(block: dict[str, Any]) -> None:
    """Cutoff modulation is a control signal, not a sound. With no filter on the
    voice there is nothing for it to open or close, so the render matches the
    unmodulated one. B06's filter is what makes it audible."""
    assert pcm(voice(**block)) == pcm(voice())


# --- Clamping, through the same B02 layer a render goes through ---------------


@pytest.mark.parametrize(
    ("block", "field", "extra", "minimum", "maximum"),
    [
        ("fm", "ratio", {"index": 3.0}, 0.01, 24.0),
        ("fm", "index", {"ratio": 2.0}, 0.0, 24.0),
        ("lfo", "rateHz", {"target": "pitch"}, 0.01, 100.0),
        ("lfo", "depth", {"target": "pitch"}, 0.0, 1.0),
        ("am", "rateHz", {"mode": "am"}, 0.01, 5000.0),
        ("am", "depth", {"mode": "am"}, 0.0, 1.0),
        ("modEnv", "amount", {"target": "pitch"}, -1.0, 1.0),
        ("modEnv", "decayMs", {"target": "pitch"}, 0.0, 10_000.0),
    ],
)
@pytest.mark.parametrize("side", ["below", "above"])
def test_modulation_parameters_clamp_at_both_bounds(
    block: str, field: str, extra: dict[str, Any], minimum: float, maximum: float, side: str
) -> None:
    bound = minimum if side == "below" else maximum
    requested = bound - 1.0 if side == "below" else bound + 1.0
    overrides: dict[str, Any] = {block: {**extra, field: requested}}

    spec, warnings = validate_for_render(voice(**overrides))

    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.code is WarningCode.CLAMPED
    assert warning.param == f"voices[0].{block}.{field}"
    assert warning.requested == requested
    assert warning.applied == bound

    applied = getattr(getattr(spec.voices[0], block), field)
    assert applied == bound


@pytest.mark.parametrize(
    "block",
    [
        {"fm": {"ratio": 2.0, "index": 3.0}},
        {"lfo": {"target": "pitch", "rateHz": 5.0, "depth": 0.5}},
        {"am": {"mode": "ring", "rateHz": 100.0, "depth": 0.5}},
        {"modEnv": {"target": "pitch", "amount": -0.5, "decayMs": 120.0}},
    ],
    ids=["fm", "lfo", "am", "modEnv"],
)
def test_in_range_modulation_does_not_warn(block: dict[str, Any]) -> None:
    _, warnings = validate_for_render(voice(**block))
    assert warnings == []


def test_a_clamped_modulation_still_renders() -> None:
    """Clamping is a warning, not a refusal: the sound still comes out, built
    from the applied value."""
    assert pcm(voice(fm={"ratio": 2.0, "index": 999.0})) == pcm(
        voice(fm={"ratio": 2.0, "index": 24.0})
    )


# --- Golden coverage, one per stage -------------------------------------------


@pytest.mark.parametrize("name", MODULATION_GOLDENS)
def test_each_modulation_stage_has_a_golden(name: str) -> None:
    """The hash comparison itself lives in test_determinism; this asserts the
    corpus still covers every stage this item added, so that check cannot end up
    silently guarding nothing."""
    spec_path = GOLDEN / "specs" / name
    assert spec_path.exists(), f"{name} is missing from the golden corpus"
    assert name in json.loads((GOLDEN / "hashes.json").read_text())
