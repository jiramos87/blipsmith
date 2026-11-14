"""Documented bounds for every numeric parameter in a SoundSpec.

This module is the single in-code source of truth for the limits the PRD calls
"documented ranges". Two consumers depend on it staying data rather than logic:
the clamp pass in `spec.py` walks it to normalize out-of-range input, and
`schema.py` publishes it so a driving agent can author a valid spec without
trial and error.

The distinction that runs through the whole contract: a numeric parameter
outside its range is a *clamp plus warning*, because the agent's intent is
recoverable. A value outside a discrete set (waveform, filter type, sample rate)
is a *typed error*, because guessing which one was meant would be a fabrication.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

# --- Structural limits --------------------------------------------------------
# Pinned in the backlog header; every later item agrees on these.

MAX_VOICES = 8
TRACK_COUNT = 5
SUPPORTED_SAMPLE_RATES = (8000, 11025, 16000, 22050, 44100)
SUPPORTED_CHANNELS = (1, 2)
SPEC_VERSION: Literal[1] = 1
LIMITER_TARGET_DBFS = -1.0

# The music mode (version 2) widens the composition: any number of tracks up to
# this, more voices, kit keys, shared effects, and the loop. Version 1 keeps the
# limits above, so every spec written before the music mode renders as it did.
MUSIC_SPEC_VERSION: Literal[2] = 2
MUSIC_MAX_VOICES = 64
MUSIC_MAX_TRACKS = 32
TRACK_NAME_MAX_LENGTH = 40
# The master chain is the shared room, run once per track so stems sum to the
# mix; only kinds that are linear in their input allow that.
MASTER_EFFECT_KINDS = ("delay", "reverb")
# Music mode, four-operator FM: exactly this many operators, in one of the
# eight classic algorithms. Each entry names, per operator, the operators that
# modulate it, and which operators are heard (the carriers). Operators run in
# order, so a modulator always comes before what it feeds. The core holds the
# same table; a test keeps the two equal.
FM4_OPERATORS = 4
FM4_ALGORITHMS: tuple[tuple[tuple[tuple[int, ...], ...], tuple[int, ...]], ...] = (
    (((), (1,), (2,), (3,)), (4,)),  # 0: 1 > 2 > 3 > 4
    (((), (), (1, 2), (3,)), (4,)),  # 1: (1 + 2) > 3 > 4
    (((), (), (2,), (1, 3)), (4,)),  # 2: (1 + (2 > 3)) > 4
    (((), (1,), (), (2, 3)), (4,)),  # 3: ((1 > 2) + 3) > 4
    (((), (1,), (), (3,)), (2, 4)),  # 4: (1 > 2) + (3 > 4)
    (((), (1,), (1,), (1,)), (2, 3, 4)),  # 5: 1 > 2, 1 > 3, 1 > 4
    (((), (1,), (), ()), (2, 3, 4)),  # 6: (1 > 2) + 3 + 4
    (((), (), (), ()), (1, 2, 3, 4)),  # 7: 1 + 2 + 3 + 4
)

# A filter cutoff has a second, render-time ceiling: a biquad's coefficients only
# stay well conditioned comfortably below Nyquist, and at Nyquist itself the
# corner has nowhere left to sit. The published `cutoffHz` range is absolute; a
# render caps it at this fraction of its own sample rate, which is why an 8 kHz
# render clamps harder than a 44.1 kHz one.
MAX_CUTOFF_FRACTION = 0.45


@dataclass(frozen=True)
class NumericRange:
    """An inclusive `[minimum, maximum]` bound with its default and meaning."""

    minimum: float
    maximum: float
    default: float
    unit: str = ""
    description: str = ""
    integer: bool = False

    def clamp(self, value: float) -> float:
        """Pull `value` to the nearest bound. Non-finite input is a caller error."""
        if not math.isfinite(value):
            raise ValueError(f"non-finite value: {value!r}")
        clamped = min(max(value, self.minimum), self.maximum)
        return round(clamped) if self.integer else float(clamped)

    def contains(self, value: float) -> bool:
        return math.isfinite(value) and self.minimum <= value <= self.maximum


# --- Per-parameter ranges -----------------------------------------------------
# Keyed by (model class name, field name) so the clamp walk can look a parameter
# up from the instance it is standing on, and report the full path it took.

RANGES: dict[tuple[str, str], NumericRange] = {
    # SoundSpec
    ("SoundSpec", "seed"): NumericRange(
        0, 4_294_967_295, 0, "", "PRNG seed; identical seeds render identical bytes", True
    ),
    ("SoundSpec", "durationMs"): NumericRange(
        10, 30_000, 1000, "ms", "one-shot render length (compositions allow longer)"
    ),
    # Master
    ("Master", "gainDb"): NumericRange(-60, 12, 0, "dB", "master bus gain before the limiter"),
    ("Limiter", "targetDbfs"): NumericRange(
        -24, -0.1, LIMITER_TARGET_DBFS, "dBFS", "peak the master bus normalizes to"
    ),
    # Voice
    ("Voice", "fundamentalHz"): NumericRange(20, 8000, 440, "Hz", "oscillator pitch in hertz"),
    ("Voice", "fundamentalMidi"): NumericRange(
        0, 127, 69, "", "oscillator pitch as a MIDI note; wins over fundamentalHz when set", True
    ),
    ("Voice", "pulseDuty"): NumericRange(
        0.01, 0.99, 0.5, "", "pulse width; only read when waveform is pulse"
    ),
    ("Voice", "pan"): NumericRange(-1, 1, 0, "", "-1 hard left, 0 centre, 1 hard right"),
    ("Voice", "mixDb"): NumericRange(-60, 12, 0, "dB", "voice level into the bus"),
    ("Voice", "track"): NumericRange(
        0, TRACK_COUNT - 1, 0, "", "mixer track this voice sits on", True
    ),
    ("Voice", "key"): NumericRange(
        0, 127, 36, "", "music mode: the MIDI note this voice answers to on a kit track", True
    ),
    # Adsr
    ("Adsr", "attackMs"): NumericRange(0, 10_000, 5, "ms", "silence to full amplitude"),
    ("Adsr", "decayMs"): NumericRange(0, 10_000, 100, "ms", "full amplitude to sustain level"),
    ("Adsr", "sustainLevel"): NumericRange(0, 1, 0.6, "", "held amplitude after decay"),
    ("Adsr", "releaseMs"): NumericRange(0, 10_000, 150, "ms", "sustain level back to silence"),
    # ModEnv
    ("ModEnv", "amount"): NumericRange(
        -1, 1, 0.5, "", "normalized depth; negative sweeps downward (the classic laser drop)"
    ),
    ("ModEnv", "attackMs"): NumericRange(0, 10_000, 0, "ms", "time to reach full modulation"),
    ("ModEnv", "decayMs"): NumericRange(0, 10_000, 120, "ms", "time to fall back to none"),
    # Lfo
    ("Lfo", "rateHz"): NumericRange(0.01, 100, 5, "Hz", "modulation speed"),
    ("Lfo", "depth"): NumericRange(0, 1, 0.5, "", "normalized modulation amount"),
    # Fm
    ("Fm", "ratio"): NumericRange(
        0.01, 24, 2.0, "", "modulator frequency as a multiple of carrier"
    ),
    ("Fm", "index"): NumericRange(
        0, 24, 3.0, "", "modulation depth; higher is brighter and clangier"
    ),
    # Am
    ("Am", "rateHz"): NumericRange(0.01, 5000, 100, "Hz", "modulator frequency"),
    ("Am", "depth"): NumericRange(0, 1, 0.5, "", "normalized modulation amount"),
    # Filter
    ("Filter", "cutoffHz"): NumericRange(
        20, 20_000, 8000, "Hz", "corner frequency; further clamped below Nyquist at render"
    ),
    ("Filter", "resonance"): NumericRange(0.1, 20, 0.7, "", "Q; higher rings more at the corner"),
    # LoFi
    ("LoFi", "bitDepth"): NumericRange(
        1, 16, 8, "bits", "quantization depth; lower is crunchier", True
    ),
    ("LoFi", "decimation"): NumericRange(
        1, 64, 1, "", "sample-and-hold factor; 1 is off, higher is grittier", True
    ),
    # Effect
    ("Effect", "drive"): NumericRange(0, 1, 0.5, "", "distortion and wavefold intensity"),
    ("Effect", "timeMs"): NumericRange(1, 2000, 120, "ms", "delay time"),
    ("Effect", "feedback"): NumericRange(
        0, 0.95, 0.35, "", "delay regeneration; capped below runaway"
    ),
    ("Effect", "mixWet"): NumericRange(0, 1, 0.3, "", "wet/dry balance for delay and reverb"),
    ("Effect", "roomSize"): NumericRange(0, 1, 0.5, "", "reverb tail length"),
    ("Effect", "damping"): NumericRange(0, 1, 0.5, "", "reverb high-frequency absorption"),
    # Touch (music mode): velocity shapes the tone, per note, around a pivot
    ("Touch", "pivot"): NumericRange(
        0, 1, 0.6, "", "the velocity that plays the voice exactly as authored"
    ),
    ("Touch", "fmIndex"): NumericRange(
        -24, 24, 0, "", "FM index added per unit of velocity above the pivot"
    ),
    ("Touch", "cutoffOctaves"): NumericRange(
        -8, 8, 0, "oct", "filter cutoff shift per unit of velocity above the pivot"
    ),
    ("Touch", "attackOctaves"): NumericRange(
        -8, 8, 0, "oct", "attack shortening per unit of velocity above the pivot"
    ),
    # Glide (music mode): the pitch slides from the previous note
    ("Glide", "timeMs"): NumericRange(0, 5000, 80, "ms", "time to slide to the note's pitch"),
    # Vibrato (music mode): a late vibrato that fades in on a held note
    ("Vibrato", "delayMs"): NumericRange(
        0, 10_000, 250, "ms", "time from the note's start before the vibrato begins"
    ),
    ("Vibrato", "fadeMs"): NumericRange(0, 10_000, 300, "ms", "time to fade in to full depth"),
    ("Vibrato", "rateHz"): NumericRange(0.1, 20, 5.5, "Hz", "vibrato speed"),
    ("Vibrato", "depthCents"): NumericRange(
        0, 200, 20, "cents", "pitch swing either side at full depth"
    ),
    # Fm4 (music mode): four sine operators in one of eight algorithms
    ("Fm4", "feedback"): NumericRange(
        0, 1, 0, "", "operator 1 feeding itself; 1 is pi radians, harsher and noisier"
    ),
    # Operator (one of an fm4 block's four)
    ("Operator", "ratio"): NumericRange(
        0.01, 24, 1, "", "frequency as a multiple of the voice's pitch"
    ),
    ("Operator", "fixedHz"): NumericRange(
        1, 20_000, 440, "Hz", "optional fixed frequency; null follows the voice's pitch"
    ),
    ("Operator", "detuneCents"): NumericRange(
        -100, 100, 0, "cents", "small offset from the ratio or fixed frequency"
    ),
    ("Operator", "level"): NumericRange(
        0, 1, 1, "", "loudness of a carrier; depth of a modulator (1 is 4 pi radians)"
    ),
    ("Operator", "attackMs"): NumericRange(0, 10_000, 0, "ms", "silence to full level"),
    ("Operator", "decayMs"): NumericRange(0, 10_000, 0, "ms", "full level to sustain"),
    ("Operator", "sustainLevel"): NumericRange(
        0, 1, 1, "", "level held after decay, to the end of the note's tail"
    ),
    # Composition
    ("Composition", "tempoBpm"): NumericRange(20, 300, 120, "BPM", "composition tempo"),
    ("Composition", "swing"): NumericRange(0, 0.75, 0, "", "offbeat delay as a fraction of a step"),
    # Track
    ("Track", "gainDb"): NumericRange(-60, 12, 0, "dB", "track level into the stereo bus"),
    ("Track", "pan"): NumericRange(-1, 1, 0, "", "-1 hard left, 0 centre, 1 hard right"),
    ("Track", "stepsPerBeat"): NumericRange(
        1, 16, 4, "", "step-grid resolution for this track", True
    ),
    # Note
    ("Note", "startBeat"): NumericRange(0, 10_000, 0, "beats", "onset, in beats from the start"),
    ("Note", "durationBeats"): NumericRange(0.01, 1000, 1, "beats", "how long the note is held"),
    ("Note", "midiNote"): NumericRange(
        0, 127, 60, "", "optional pitch; null plays the voice's own fundamental", True
    ),
    ("Note", "velocity"): NumericRange(0, 1, 0.8, "", "note loudness"),
    # Step
    ("Step", "index"): NumericRange(0, 4096, 0, "", "position on the track's step grid", True),
    ("Step", "velocity"): NumericRange(0, 1, 0.8, "", "step loudness"),
    ("Step", "midiNote"): NumericRange(
        0, 127, 60, "", "optional pitch; null plays the voice's own fundamental", True
    ),
}

# durationMs carries two documented maxima. The clamp pass swaps this in when the
# spec has a composition, so a 4-minute piece is not truncated to a one-shot.
DURATION_MS_COMPOSITION = NumericRange(10, 300_000, 1000, "ms", "composition render length", False)


def track_range_for(track_count: int) -> NumericRange:
    """`Voice.track` for a music-mode spec: any of the tracks it declares."""
    published = RANGES[("Voice", "track")]
    return NumericRange(
        0,
        max(track_count - 1, 0),
        published.default,
        published.unit,
        published.description,
        True,
    )


def cutoff_range_for(sample_rate: int) -> NumericRange:
    """The cutoff bound for one render: the published range, capped below Nyquist.

    The clamp pass swaps this in the way it swaps the composition duration, so a
    cutoff an agent authored for a 44.1 kHz render is pulled into range rather
    than rejected when the same spec is rendered at 8 kHz.
    """
    published = RANGES[("Filter", "cutoffHz")]
    return NumericRange(
        published.minimum,
        min(published.maximum, MAX_CUTOFF_FRACTION * sample_rate),
        published.default,
        published.unit,
        "corner frequency, capped below Nyquist for this render's sample rate",
    )
