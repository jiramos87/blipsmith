"""B07: the master bus. Pan, mix level, master gain, limiter, clip guard.

This is the stage that makes a multi-voice spec renderable at all: before it,
voices summed at unit gain and a chord pinned itself against full scale. The
limiter is a safety gate rather than an effect, so most of these tests are about
what a caller *cannot* do to it.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.ranges import LIMITER_TARGET_DBFS
from blipsmith.result import ErrorCode, SpecError, WarningCode
from blipsmith.schema import get_schema
from blipsmith.spec import Limiter, SoundSpec, to_canonical_json, validate_for_render

GOLDEN = Path(__file__).resolve().parent / "golden"

FLAT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 1.0,
    "releaseMs": 0.0,
}

# The peak the bus normalizes to, as an int16 sample value. The tolerance is one
# quantization step: the bus works in doubles and the encoder rounds once.
TARGET_DBFS = LIMITER_TARGET_DBFS
PEAK_TOLERANCE_DB = 0.05

# Four voices at unit gain, which sums to roughly four times full scale.
CHORD_HZ = (220.0, 277.0, 330.0, 440.0)


# --- Rendering and measurement ------------------------------------------------


def raw_samples(payload: dict[str, Any]) -> tuple[int, ...]:
    spec, _ = validate_for_render(payload)
    wav: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def peak_dbfs(samples: tuple[int, ...] | list[int]) -> float:
    top = max(abs(value) for value in samples)
    return 20 * math.log10(top / 32767.0) if top else -math.inf


def chord(**overrides: Any) -> dict[str, Any]:
    voices: list[dict[str, Any]] = [
        {"waveform": "triangle", "fundamentalHz": hz, "ampEnv": dict(FLAT_ENV)} for hz in CHORD_HZ
    ]
    payload: dict[str, Any] = {"voices": voices, "durationMs": 200.0}
    payload.update(overrides)
    return payload


def one_voice(**voice_overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "waveform": "sine",
        "fundamentalHz": 440.0,
        "ampEnv": dict(FLAT_ENV),
    }
    body.update(voice_overrides)
    return {"voices": [body], "durationMs": 200.0}


def rms(values: list[int]) -> float:
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


# --- A hot sum is turned down, not squared off --------------------------------


def test_a_chord_that_sums_past_full_scale_does_not_clip() -> None:
    """Four voices at unit gain sum to about four times full scale. Before the
    bus this pinned roughly a tenth of its samples against the ceiling."""
    samples = raw_samples(chord())

    assert max(samples) < 32767, "the bus should leave headroom, not sit on the ceiling"
    assert min(samples) > -32768, "and nothing should wrap"
    assert peak_dbfs(samples) == pytest.approx(TARGET_DBFS, abs=PEAK_TOLERANCE_DB)


def test_a_hot_sum_keeps_its_shape_instead_of_being_flattened() -> None:
    """Turning a mix down and squaring it off both stop it clipping; only one of
    them still sounds like the mix. A clipped chord would sit at its ceiling for
    long runs of samples; a normalized one touches the peak and moves on."""
    samples = raw_samples(chord())
    top = max(abs(value) for value in samples)
    at_ceiling = sum(1 for value in samples if abs(value) >= top - 1)

    assert at_ceiling < len(samples) // 100, "the peak should be a peak, not a plateau"


@pytest.mark.parametrize("voice_count", [1, 2, 4, 8])
def test_any_number_of_voices_lands_on_the_target(voice_count: int) -> None:
    """The bus has to be the thing that sets the level, whatever is playing:
    eight voices is the pinned MAX_VOICES ceiling."""
    voices = [
        {"waveform": "saw", "fundamentalHz": 110.0 * (index + 1), "ampEnv": dict(FLAT_ENV)}
        for index in range(voice_count)
    ]
    samples = raw_samples({"voices": voices, "durationMs": 200.0})

    assert peak_dbfs(samples) == pytest.approx(TARGET_DBFS, abs=PEAK_TOLERANCE_DB)
    assert min(samples) > -32768


# --- ... and a quiet mix is brought up ----------------------------------------


@pytest.mark.parametrize("mix_db", [-6.0, -30.0, -60.0])
def test_a_quiet_spec_is_normalized_up_to_the_target(mix_db: float) -> None:
    """The other side of the limiter: it normalizes, it does not merely limit.
    A voice mixed 60 dB down still leaves at the target."""
    samples = raw_samples(one_voice(mixDb=mix_db))

    assert peak_dbfs(samples) == pytest.approx(TARGET_DBFS, abs=PEAK_TOLERANCE_DB)


def test_silence_stays_silent() -> None:
    """The one render with no peak to normalize to. Scaling it up would turn
    rounding noise into a full-scale hiss."""
    samples = raw_samples(
        one_voice(ampEnv={"attackMs": 0.0, "decayMs": 0.0, "sustainLevel": 0.0, "releaseMs": 0.0})
    )

    assert set(samples) == {0}


def test_the_limiter_target_is_what_sets_the_level() -> None:
    """The exposed loudness control, and it moves the peak by exactly what it
    says on both sides of the default."""
    for target in (-0.5, -6.0, -18.0):
        samples = raw_samples({**one_voice(), "master": {"limiter": {"targetDbfs": target}}})
        assert peak_dbfs(samples) == pytest.approx(target, abs=PEAK_TOLERANCE_DB)


def test_master_gain_cannot_move_the_finished_level() -> None:
    """A documented consequence of normalizing after the master gain: gainDb
    scales the sum and the limiter scales it straight back. `mixDb` is the
    control that still bites, because it changes the balance between voices,
    which normalization cannot undo. Pinned here so it is a known property
    rather than a surprise."""
    for gain_db in (-60.0, -6.0, 0.0, 12.0):
        samples = raw_samples({**one_voice(), "master": {"gainDb": gain_db}})
        assert peak_dbfs(samples) == pytest.approx(TARGET_DBFS, abs=PEAK_TOLERANCE_DB)


def test_mix_level_still_changes_the_balance_between_voices() -> None:
    even = raw_samples(
        {
            "voices": [
                {"waveform": "sine", "fundamentalHz": 440.0, "ampEnv": dict(FLAT_ENV)},
                {"waveform": "square", "fundamentalHz": 110.0, "ampEnv": dict(FLAT_ENV)},
            ],
            "durationMs": 200.0,
        }
    )
    tilted = raw_samples(
        {
            "voices": [
                {"waveform": "sine", "fundamentalHz": 440.0, "ampEnv": dict(FLAT_ENV)},
                {
                    "waveform": "square",
                    "fundamentalHz": 110.0,
                    "ampEnv": dict(FLAT_ENV),
                    "mixDb": -24.0,
                },
            ],
            "durationMs": 200.0,
        }
    )

    assert even != tilted


# --- Pan ----------------------------------------------------------------------


def channels_of(samples: tuple[int, ...]) -> tuple[list[int], list[int]]:
    return list(samples[0::2]), list(samples[1::2])


def test_hard_panned_voices_stay_on_their_own_side() -> None:
    """Two different waveforms, one hard left and one hard right: each side has
    to carry its own voice and nothing of the other's."""
    samples = raw_samples(
        {
            "voices": [
                {
                    "waveform": "sine",
                    "fundamentalHz": 440.0,
                    "ampEnv": dict(FLAT_ENV),
                    "pan": -1.0,
                },
                {
                    "waveform": "square",
                    "fundamentalHz": 110.0,
                    "ampEnv": dict(FLAT_ENV),
                    "pan": 1.0,
                },
            ],
            "durationMs": 200.0,
            "channels": 2,
        }
    )
    left, right = channels_of(samples)

    # The square is two-valued, so a right channel carrying only the square has
    # a tiny set of distinct values; a leaked sine would fill it in.
    assert len(set(right)) <= 4, "the right side should carry the square alone"
    assert len(set(left)) > 100, "the left side should carry the sine alone"
    assert left != right


def test_a_centred_voice_sits_equally_in_both_channels() -> None:
    left, right = channels_of(raw_samples({**one_voice(pan=0.0), "channels": 2}))
    assert left == right


@pytest.mark.parametrize(("pan", "louder_side"), [(-1.0, 0), (-0.5, 0), (0.5, 1), (1.0, 1)])
def test_pan_moves_energy_toward_the_side_it_names(pan: float, louder_side: int) -> None:
    """Both sides of centre, including the hard ends."""
    left, right = channels_of(raw_samples({**one_voice(pan=pan), "channels": 2}))
    sides = (rms(left), rms(right))

    assert sides[louder_side] > sides[1 - louder_side]


@pytest.mark.parametrize("pan", [-0.75, -0.5, 0.0, 0.5, 0.75])
def test_the_pan_law_is_constant_power(pan: float) -> None:
    """Read as the balance between the channels rather than as total energy.

    Constant power means the two gains square to one, which is what keeps a
    voice panned hard as loud as the same voice centred. That cannot be measured
    from a finished file, because the limiter normalizes every render to the
    same peak and rescales whatever the pan law did. The ratio between the
    channels survives normalization, and it is what separates this law from a
    linear one: at a pan of 0.5 the square-root law leaves the quiet side at
    0.577 of the loud one, where a linear law would leave it at 0.333.
    """
    left, right = channels_of(raw_samples({**one_voice(pan=pan), "channels": 2}))

    expected = math.sqrt((1.0 - pan) / (1.0 + pan))
    assert rms(left) / rms(right) == pytest.approx(expected, rel=0.01)


def test_pan_is_ignored_in_a_mono_render() -> None:
    """A mono file has no stereo image to place a voice in, so panning it must
    not quietly attenuate it instead."""
    assert raw_samples(one_voice(pan=-1.0)) == raw_samples(one_voice(pan=0.0))
    assert raw_samples(one_voice(pan=1.0)) == raw_samples(one_voice(pan=0.0))


# --- Clamping -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "field", "minimum", "maximum"),
    [("voice", "mixDb", -60.0, 12.0), ("master", "gainDb", -60.0, 12.0)],
)
@pytest.mark.parametrize("side", ["below", "above"])
def test_bus_levels_clamp_at_both_bounds(
    path: str, field: str, minimum: float, maximum: float, side: str
) -> None:
    bound = minimum if side == "below" else maximum
    requested = bound - 1.0 if side == "below" else bound + 1.0

    if path == "voice":
        payload = one_voice(**{field: requested})
        expected_param = f"voices[0].{field}"
    else:
        payload = {**one_voice(), "master": {field: requested}}
        expected_param = f"master.{field}"

    _, warnings = validate_for_render(payload)

    assert len(warnings) == 1
    assert warnings[0].code is WarningCode.CLAMPED
    assert warnings[0].param == expected_param
    assert warnings[0].requested == requested
    assert warnings[0].applied == bound


@pytest.mark.parametrize("side", ["below", "above"])
def test_the_limiter_target_clamps_at_both_bounds(side: str) -> None:
    bound = -24.0 if side == "below" else -0.1
    requested = bound - 1.0 if side == "below" else bound + 1.0

    _, warnings = validate_for_render(
        {**one_voice(), "master": {"limiter": {"targetDbfs": requested}}}
    )

    assert len(warnings) == 1
    assert warnings[0].param == "master.limiter.targetDbfs"
    assert warnings[0].applied == bound


@pytest.mark.parametrize("side", ["below", "above"])
def test_pan_clamps_at_both_bounds(side: str) -> None:
    bound = -1.0 if side == "below" else 1.0
    requested = bound - 1.0 if side == "below" else bound + 1.0

    _, warnings = validate_for_render(one_voice(pan=requested))

    assert len(warnings) == 1
    assert warnings[0].param == "voices[0].pan"
    assert warnings[0].applied == bound


def test_levels_inside_their_bounds_do_not_warn() -> None:
    _, warnings = validate_for_render(
        {**one_voice(mixDb=-12.0, pan=0.5), "master": {"gainDb": 3.0}}
    )
    assert warnings == []


# --- The limiter cannot be switched off ---------------------------------------


def test_the_limiter_has_no_bypass_field() -> None:
    """The safety gate is not a preference. The only thing a caller can say
    about the limiter is where to normalize to."""
    assert set(Limiter.model_fields) == {"targetDbfs"}


def test_the_spec_surface_carries_no_switches_at_all() -> None:
    """A stronger version of the same claim, taken from the published schema
    rather than from the model: nothing anywhere in the spec is a boolean, so
    there is no field that could turn a stage on or off."""
    schema = get_schema()
    switches = [
        f"{model}.{name}"
        for model, body in schema["models"].items()
        for name, field in body["fields"].items()
        if field["type"] == "boolean"
    ]

    assert switches == []


@pytest.mark.parametrize(
    "payload",
    [
        {"master": {"limiter": {"enabled": False, "targetDbfs": -1.0}}},
        {"master": {"limiter": {"bypass": True}}},
        {"master": {"clipGuard": False}},
    ],
    ids=["limiter-enabled", "limiter-bypass", "clip-guard"],
)
def test_inventing_a_bypass_field_is_a_typed_error(payload: dict[str, Any]) -> None:
    """And an agent that tries to add one is told so, rather than having the key
    silently ignored while it believes the limiter is off."""
    with pytest.raises(SpecError) as raised:
        validate_for_render({**one_voice(), **payload})

    assert raised.value.error.code is ErrorCode.INVALID_SPEC


def test_the_limiter_runs_even_on_a_spec_that_asks_for_nothing() -> None:
    """No master block at all: the defaults still put the limiter in the path."""
    spec, _ = validate_for_render(one_voice())

    assert spec.master.limiter.targetDbfs == TARGET_DBFS
    assert peak_dbfs(raw_samples(one_voice())) == pytest.approx(TARGET_DBFS, abs=PEAK_TOLERANCE_DB)


def test_the_default_spec_carries_the_pinned_target() -> None:
    assert SoundSpec().master.limiter.targetDbfs == LIMITER_TARGET_DBFS


# --- The whole corpus, now that the bus sits in front of it -------------------


def golden_cases() -> list[str]:
    return sorted(path.name for path in (GOLDEN / "specs").glob("*.spec.json"))


@pytest.mark.parametrize("name", golden_cases())
def test_every_golden_leaves_at_the_target_without_clipping(name: str) -> None:
    """The quality bar for the corpus: nothing clips, and every render lands on
    the normalization target."""
    payload = json.loads((GOLDEN / "specs" / name).read_text())
    samples = raw_samples(payload)
    target = payload.get("master", {}).get("limiter", {}).get("targetDbfs", TARGET_DBFS)

    assert min(samples) > -32768, f"{name} wrapped past negative full scale"
    assert max(samples) <= 32767
    assert peak_dbfs(samples) == pytest.approx(target, abs=PEAK_TOLERANCE_DB)


def test_the_corpus_covers_a_deliberately_hot_multi_voice_spec() -> None:
    assert "bus-hot-chord.spec.json" in golden_cases()
