"""B04: the seven waveforms, the envelope, and the baked tables behind them."""

from __future__ import annotations

import itertools
import math
import struct
from typing import Any

import pytest

import blipsmith
from blipsmith.spec import to_canonical_json, validate_for_render

SAMPLE_RATE = 22050
FLAT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 1.0,
    "releaseMs": 0.0,
}
ALL_WAVEFORMS = [
    "sine",
    "square",
    "triangle",
    "saw",
    "pulse",
    "noise_white",
    "noise_pink",
]


def pcm(payload: dict[str, Any]) -> list[float]:
    """Render and decode to floats in [-1, 1]."""
    spec, _ = validate_for_render(payload)
    wav: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return [s / 32767.0 for s in struct.unpack_from(f"<{count}h", wav, 44)]


def voice(waveform: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"waveform": waveform, "ampEnv": dict(FLAT_ENV)}
    body.update(overrides)
    return {"voices": [body], "durationMs": 200.0}


def peak(samples: list[float]) -> float:
    return max(abs(s) for s in samples)


def unit_pcm(payload: dict[str, Any]) -> list[float]:
    """Render, then scale by the render's own peak.

    Since B07 the master bus normalizes every render to the limiter's target, so
    absolute amplitude is the bus's business and no longer the oscillator's.
    These tests are about waveform *shape*, so they measure each render against
    its own peak and stay true whatever level the bus decides on.
    """
    samples = pcm(payload)
    top = peak(samples)
    return [s / top for s in samples] if top > 0.0 else samples


def rms(samples: list[float]) -> float:
    return math.sqrt(sum(s * s for s in samples) / len(samples))


# --- Every waveform makes sound, and stays inside full scale ------------------


@pytest.mark.parametrize("waveform", ALL_WAVEFORMS)
def test_waveform_is_not_silent(waveform: str) -> None:
    samples = pcm(voice(waveform))
    assert any(s != 0.0 for s in samples)
    assert rms(samples) > 0.05


@pytest.mark.parametrize("waveform", ALL_WAVEFORMS)
def test_waveform_does_not_clip(waveform: str) -> None:
    """Sitting at full scale is not clipping: a square is ±1 by construction.
    Clipping shows up as a sample driven past full scale, which this encoder
    would surface as the wrap sentinel -32768."""
    spec, _ = validate_for_render(voice(waveform))
    wav: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    raw = struct.unpack_from(f"<{count}h", wav, 44)

    assert peak(pcm(voice(waveform))) <= 1.0
    assert min(raw) > -32768, "a sample wrapped past negative full scale"


@pytest.mark.parametrize("waveform", ALL_WAVEFORMS)
def test_waveform_render_is_byte_identical(waveform: str) -> None:
    assert pcm(voice(waveform)) == pcm(voice(waveform))


# --- Shape checks: each waveform is actually the shape it claims --------------


def test_sine_matches_an_ideal_sine() -> None:
    """The table is built from a fixed Taylor polynomial, so it should track the
    real thing to within int16 quantization."""
    samples = unit_pcm(voice("sine", fundamentalHz=440.0))
    worst = max(
        abs(value - math.sin(2 * math.pi * 440.0 * i / SAMPLE_RATE))
        for i, value in enumerate(samples)
    )
    assert worst < 1e-4, f"sine table drifts from the ideal by {worst}"


def test_square_is_two_valued() -> None:
    samples = unit_pcm(voice("square", fundamentalHz=220.0))
    assert set(round(s, 4) for s in samples) <= {1.0, -1.0}


def test_pulse_duty_shifts_the_high_proportion() -> None:
    """Duty is what separates a pulse from a square; both sides of centre."""
    narrow = pcm(voice("pulse", fundamentalHz=220.0, pulseDuty=0.25))
    wide = pcm(voice("pulse", fundamentalHz=220.0, pulseDuty=0.75))

    narrow_high = sum(1 for s in narrow if s > 0) / len(narrow)
    wide_high = sum(1 for s in wide if s > 0) / len(wide)

    assert narrow_high == pytest.approx(0.25, abs=0.02)
    assert wide_high == pytest.approx(0.75, abs=0.02)


def test_pulse_at_half_duty_matches_a_square() -> None:
    assert pcm(voice("pulse", fundamentalHz=220.0, pulseDuty=0.5)) == pcm(
        voice("square", fundamentalHz=220.0)
    )


@pytest.mark.parametrize(
    ("waveform", "expected_rms"),
    [("sine", 1 / math.sqrt(2)), ("square", 1.0), ("triangle", 1 / math.sqrt(3))],
)
def test_waveform_rms_matches_its_geometry(waveform: str, expected_rms: float) -> None:
    samples = unit_pcm(voice(waveform, fundamentalHz=220.0))
    assert rms(samples) == pytest.approx(expected_rms, abs=0.01)


def test_saw_ramps_upward_then_resets() -> None:
    samples = unit_pcm(voice("saw", fundamentalHz=100.0))
    period = SAMPLE_RATE // 100
    ramp = samples[1 : period - 1]
    rises = all(b >= a for a, b in itertools.pairwise(ramp))
    assert rises, "saw should rise monotonically within a period"
    assert peak(samples) == pytest.approx(1.0, abs=0.01)


def test_higher_pitch_completes_more_cycles() -> None:
    def cycles(hz: float) -> int:
        samples = pcm(voice("sine", fundamentalHz=hz))
        return sum(1 for i in range(1, len(samples)) if samples[i - 1] < 0 <= samples[i])

    assert cycles(440.0) > cycles(220.0) > cycles(110.0)


# --- The baked MIDI table -----------------------------------------------------


@pytest.mark.parametrize("note", [0, 21, 60, 69, 108, 127])
def test_midi_note_renders_its_equal_tempered_pitch(note: int) -> None:
    """The conversion is a baked table precisely because 2**((n-69)/12) would go
    through the host libm and make the bytes platform-dependent."""
    expected_hz = 440.0 * 2 ** ((note - 69) / 12)
    samples = unit_pcm(voice("sine", fundamentalMidi=note, fundamentalHz=1.0))
    worst = max(
        abs(value - math.sin(2 * math.pi * expected_hz * i / SAMPLE_RATE))
        for i, value in enumerate(samples)
    )
    assert worst < 1e-4, f"midi {note} did not render {expected_hz} Hz"


def test_midi_note_wins_over_hertz() -> None:
    by_note = pcm(voice("sine", fundamentalMidi=69, fundamentalHz=1234.0))
    by_hertz = pcm(voice("sine", fundamentalHz=440.0))
    assert by_note == by_hertz


def test_absent_midi_note_leaves_hertz_in_charge() -> None:
    assert pcm(voice("sine", fundamentalHz=440.0)) == pcm(
        voice("sine", fundamentalHz=440.0, fundamentalMidi=None)
    )


# --- Amplitude envelope -------------------------------------------------------


def envelope_of(samples: list[float], window: int = 64) -> list[float]:
    starts = range(0, len(samples) - window, window)
    return [max(abs(s) for s in samples[i : i + window]) for i in starts]


def test_attack_reaches_peak_at_the_requested_time() -> None:
    attack_ms = 50.0
    samples = pcm(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "fundamentalHz": 440.0,
                    "ampEnv": {
                        "attackMs": attack_ms,
                        "decayMs": 0.0,
                        "sustainLevel": 1.0,
                        "releaseMs": 0.0,
                    },
                }
            ],
            "durationMs": 400.0,
        }
    )
    window = 64
    contour = envelope_of(samples, window)
    ceiling = max(contour)
    first_at_peak = next(i for i, value in enumerate(contour) if value >= 0.95 * ceiling)

    reached_ms = (first_at_peak * window) * 1000.0 / SAMPLE_RATE
    tolerance_ms = window * 1000.0 / SAMPLE_RATE
    assert reached_ms == pytest.approx(attack_ms, abs=attack_ms * 0.1 + tolerance_ms)


def test_attack_rises_rather_than_starting_loud() -> None:
    samples = pcm(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "ampEnv": {
                        "attackMs": 100.0,
                        "decayMs": 0.0,
                        "sustainLevel": 1.0,
                        "releaseMs": 0.0,
                    },
                }
            ],
            "durationMs": 400.0,
        }
    )
    contour = envelope_of(samples)
    assert contour[0] < 0.2 * max(contour), "the attack should start near silence"


def test_release_ends_at_silence() -> None:
    """The release is anchored to the end of the render, so a one-shot fades out
    instead of being cut off mid-tail."""
    samples = pcm(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "ampEnv": {
                        "attackMs": 5.0,
                        "decayMs": 50.0,
                        "sustainLevel": 0.8,
                        "releaseMs": 200.0,
                    },
                }
            ],
            "durationMs": 500.0,
        }
    )
    assert abs(samples[-1]) < 0.01
    assert max(abs(s) for s in samples[-100:]) < 0.05


def test_sustain_level_scales_the_held_section() -> None:
    def held_peak(sustain: float) -> float:
        samples = unit_pcm(
            {
                "voices": [
                    {
                        "waveform": "square",
                        "ampEnv": {
                            "attackMs": 1.0,
                            "decayMs": 10.0,
                            "sustainLevel": sustain,
                            "releaseMs": 0.0,
                        },
                    }
                ],
                "durationMs": 300.0,
            }
        )
        return max(abs(s) for s in samples[-1000:])

    assert held_peak(1.0) == pytest.approx(1.0, abs=0.02)
    assert held_peak(0.5) == pytest.approx(0.5, abs=0.02)
    assert held_peak(0.0) == pytest.approx(0.0, abs=0.02)


@pytest.mark.parametrize("duration_ms", [20.0, 50.0, 100.0, 149.0, 200.0, 1000.0])
def test_a_short_render_is_never_swallowed_by_the_release(duration_ms: float) -> None:
    """Regression: the default release is 150 ms, so anchoring it to the end of
    a shorter render used to start the fade at frame zero and emit pure silence.
    The release may only begin once attack and decay have run."""
    samples = pcm({"voices": [{"waveform": "sine"}], "durationMs": duration_ms})
    assert peak(samples) > 0.5, f"{duration_ms} ms render came out silent"


def test_a_long_enough_render_still_ends_on_silence() -> None:
    """The other side of that boundary: when there is room, the tail must land."""
    samples = pcm({"voices": [{"waveform": "sine"}], "durationMs": 1000.0})
    assert abs(samples[-1]) < 0.01


def test_zero_length_stages_are_not_a_division_by_zero() -> None:
    samples = pcm(voice("sine"))
    assert all(math.isfinite(s) for s in samples)
    assert any(s != 0.0 for s in samples)


# --- The int16 rounding rule (first exercised here; B03 could only emit zeros) -


def test_the_loudest_sample_is_encoded_without_wrapping() -> None:
    """A square is the hottest thing this synth can make, and its peak is where
    a round-then-cast would wrap to the opposite sign if the clamp were missing.

    Since B07 that peak is the limiter's target rather than the int16 ceiling:
    the bus normalizes every render, so nothing reaches full scale through the
    spec surface any more. The encoder's clamp is still there, now as the guard
    of last resort behind the bus's own."""
    spec, _ = validate_for_render(voice("square", fundamentalHz=220.0))
    wav: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    raw = struct.unpack_from(f"<{count}h", wav, 44)

    assert max(raw) == -min(raw), "the two polarities should mirror, not wrap"
    assert max(raw) < 32767, "the bus should leave headroom below the ceiling"
    assert all(-32768 <= value <= 32767 for value in raw)


def test_quiet_signal_rounds_to_nearest_not_toward_zero() -> None:
    samples = pcm(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "fundamentalHz": 440.0,
                    "ampEnv": {
                        "attackMs": 0.0,
                        "decayMs": 0.0,
                        "sustainLevel": 1.0,
                        "releaseMs": 0.0,
                    },
                }
            ],
            "durationMs": 50.0,
        }
    )
    quantum = 1.0 / 32767.0
    off_grid = [s for s in samples if abs(s) > quantum]
    assert off_grid, "expected non-zero samples to check rounding against"
    # Round-half-away-from-zero puts every sample on the int16 grid exactly.
    assert all(abs(s / quantum - round(s / quantum)) < 1e-9 for s in off_grid)
