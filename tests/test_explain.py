"""B08: the plain-language explanation of a spec.

The features say what came out; this says what was asked for. It has to be
deterministic for the same reason the audio is, and it has to actually name the
stages that are switched on, since an agent that cannot hear has no other way to
confirm the spec it built is the spec it meant.
"""

from __future__ import annotations

from typing import Any

import pytest

from blipsmith.explain import explain_spec
from blipsmith.render import render
from blipsmith.spec import SoundSpec, validate_for_render

FLAT_ENV: dict[str, float] = {
    "attackMs": 0.0,
    "decayMs": 0.0,
    "sustainLevel": 1.0,
    "releaseMs": 0.0,
}


def explained(payload: dict[str, Any]) -> str:
    spec, _ = validate_for_render(payload)
    return explain_spec(spec)


def voice(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"waveform": "sine", "fundamentalHz": 440.0, "ampEnv": dict(FLAT_ENV)}
    body.update(overrides)
    return {"voices": [body], "durationMs": 500.0}


# --- Deterministic ------------------------------------------------------------


def test_the_same_spec_always_explains_the_same_way() -> None:
    payload = voice(fm={"ratio": 3.0, "index": 4.0}, filter={"type": "lowpass", "cutoffHz": 900.0})
    assert explained(payload) == explained(payload)


def test_two_equal_specs_explain_identically() -> None:
    """Key order in the incoming JSON must not reach the text."""
    forwards = explained({"durationMs": 500.0, "voices": [{"waveform": "saw"}]})
    backwards = explained({"voices": [{"waveform": "saw"}], "durationMs": 500.0})
    assert forwards == backwards


def test_a_different_spec_explains_differently() -> None:
    """The other side of determinism: stable text is only useful if it still
    tracks the spec."""
    assert explained(voice(waveform="saw")) != explained(voice(waveform="sine"))
    assert explained(voice(fundamentalHz=440.0)) != explained(voice(fundamentalHz=880.0))


# --- It names what it should --------------------------------------------------


@pytest.mark.parametrize(
    ("waveform", "word"),
    [
        ("sine", "sine"),
        ("square", "square"),
        ("triangle", "triangle"),
        ("saw", "saw"),
        ("pulse", "pulse"),
        ("noise_white", "white noise"),
        ("noise_pink", "pink noise"),
    ],
)
def test_the_waveform_is_named(waveform: str, word: str) -> None:
    assert word in explained(voice(waveform=waveform))


def test_pitch_is_named_in_hertz_or_as_a_note() -> None:
    assert "440 Hz" in explained(voice(fundamentalHz=440.0))
    assert "MIDI note 60" in explained(voice(fundamentalMidi=60))
    assert "C4" in explained(voice(fundamentalMidi=60))


def test_noise_is_not_given_a_pitch_it_does_not_have() -> None:
    text = explained(voice(waveform="noise_white", fundamentalHz=440.0))
    assert "440 Hz" not in text
    assert "white noise that" in text


@pytest.mark.parametrize(
    ("envelope", "phrase"),
    [
        ({"attackMs": 0.0, "decayMs": 20.0, "sustainLevel": 0.0, "releaseMs": 0.0}, "instantly"),
        ({"attackMs": 60.0, "decayMs": 100.0, "sustainLevel": 0.5, "releaseMs": 50.0}, "eases in"),
        ({"attackMs": 400.0, "decayMs": 100.0, "sustainLevel": 0.8, "releaseMs": 50.0}, "swells"),
    ],
)
def test_the_envelope_is_described_as_a_shape(envelope: dict[str, float], phrase: str) -> None:
    """Four numbers tell a reader nothing; "swells in" tells them what to expect."""
    assert phrase in explained(voice(ampEnv=envelope))


@pytest.mark.parametrize(
    ("block", "word"),
    [
        ({"fm": {"ratio": 2.0, "index": 5.0}}, "FM"),
        ({"am": {"mode": "ring", "rateHz": 200.0}}, "ring modulation"),
        ({"am": {"mode": "am", "rateHz": 200.0}}, "amplitude modulation"),
        ({"lfo": {"target": "pitch", "rateHz": 5.0}}, "vibrato"),
        ({"lfo": {"target": "amplitude", "rateHz": 5.0}}, "tremolo"),
        ({"modEnv": {"target": "pitch", "amount": -0.5}}, "mod envelope"),
        ({"filter": {"type": "lowpass", "cutoffHz": 800.0}}, "lowpass filter"),
        ({"lofi": {"bitDepth": 4, "decimation": 1}}, "4-bit crush"),
        ({"lofi": {"bitDepth": 16, "decimation": 8}}, "8x decimation"),
        ({"effects": [{"kind": "distortion", "drive": 0.5}]}, "distortion"),
        ({"effects": [{"kind": "wavefold", "drive": 0.5}]}, "wavefolding"),
        ({"effects": [{"kind": "delay", "timeMs": 120.0}]}, "delay"),
        ({"effects": [{"kind": "reverb", "roomSize": 0.8}]}, "reverb"),
    ],
)
def test_every_active_stage_is_named(block: dict[str, Any], word: str) -> None:
    assert word in explained(voice(**block))


@pytest.mark.parametrize(
    "stage",
    ["FM", "ring modulation", "vibrato", "mod envelope", "filter", "crush", "delay", "reverb"],
)
def test_a_stage_that_is_off_is_not_mentioned(stage: str) -> None:
    """The other side of the same claim. A list of twelve "off"s buries the two
    things that are actually on."""
    assert stage not in explained(voice())


def test_the_stages_are_listed_in_signal_chain_order() -> None:
    """So a reader can follow the sound through, rather than reassembling it."""
    text = explained(
        voice(
            fm={"ratio": 2.0, "index": 4.0},
            filter={"type": "lowpass", "cutoffHz": 900.0},
            lofi={"bitDepth": 6, "decimation": 1},
            effects=[{"kind": "delay", "timeMs": 100.0}],
        )
    )

    assert text.index("FM") < text.index("filter") < text.index("crush") < text.index("delay")


def test_the_render_settings_are_stated() -> None:
    text = explained({**voice(), "sampleRate": 8000, "channels": 2, "seed": 99})

    assert "500 ms" in text
    assert "stereo" in text
    assert "8000 Hz" in text
    assert "seed 99" in text


def test_pan_is_described_only_when_there_is_an_image_to_place_it_in() -> None:
    assert "hard left" in explained({**voice(pan=-1.0), "channels": 2})
    assert "left" not in explained(voice(pan=-1.0)), "a mono render has no sides"


def test_every_voice_gets_its_own_line() -> None:
    text = explained(
        {
            "voices": [
                {"waveform": "saw", "fundamentalHz": 110.0},
                {"waveform": "noise_white"},
            ],
            "durationMs": 400.0,
        }
    )

    assert "Voice 1:" in text
    assert "Voice 2:" in text
    assert "saw" in text
    assert "white noise" in text


def test_the_limiter_is_mentioned_because_it_always_runs() -> None:
    assert "normalizes" in explained(voice())


def test_a_spec_with_no_voices_says_so_rather_than_describing_nothing() -> None:
    """`validate_for_render` refuses this, but `explain_spec` is also reached
    from a session that is still being built up."""
    assert "silence" in explain_spec(SoundSpec())


# --- It reaches the caller ----------------------------------------------------


def test_a_render_result_carries_the_explanation(tmp_path: Any) -> None:
    result = render(voice(), out_dir=tmp_path, name="explained")

    assert result.explanation is not None
    assert "sine" in result.explanation
    assert result.explanation == explained(voice())


def test_the_explanation_travels_with_the_features(tmp_path: Any) -> None:
    """The pair is the point: the text says what was asked for, the numbers say
    what came out."""
    result = render(
        voice(filter={"type": "lowpass", "cutoffHz": 600.0}), out_dir=tmp_path, name="pair"
    )

    assert result.features is not None
    assert result.explanation is not None
    assert "lowpass filter at 600 Hz" in result.explanation
    assert result.features["spectralCentroidHz"] is not None
