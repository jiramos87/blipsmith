"""B02: structural validation, the typed errors, and the canonical contract."""

from __future__ import annotations

import json
from typing import Any

import pytest

from blipsmith.ranges import MAX_VOICES, SUPPORTED_SAMPLE_RATES, TRACK_COUNT
from blipsmith.result import ErrorCode, RenderStatus, SpecError, WarningCode
from blipsmith.schema import get_schema
from blipsmith.spec import (
    AmMode,
    Composition,
    EffectKind,
    FilterType,
    LfoShape,
    LfoTarget,
    ModEnvTarget,
    SoundSpec,
    Voice,
    Waveform,
    clamp_spec,
    load_spec_json,
    parse_spec,
    to_canonical_json,
    validate_for_render,
    validate_spec,
)


def one_voice(**overrides: Any) -> dict[str, Any]:
    voice: dict[str, Any] = {"waveform": "sine"}
    voice.update(overrides)
    return {"voices": [voice]}


# --- The voice surface --------------------------------------------------------


def test_voice_surface_matches_prd() -> None:
    """The PRD enumerates exactly what a voice carries; drift here is a contract break."""
    assert set(Voice.model_fields) == {
        "waveform",
        "fundamentalHz",
        "fundamentalMidi",
        "pulseDuty",
        "ampEnv",
        "modEnv",
        "lfo",
        "fm",
        "am",
        "filter",
        "lofi",
        "effects",
        "pan",
        "mixDb",
        "track",
        # docs/prd/blipsmith-music-mode.md: the kit key, version 2 only.
        "key",
        # docs/prd/blipsmith-expressive-notes.md: per-note expression, version 2 only.
        "touch",
        "glide",
        "vibrato",
        # docs/prd/blipsmith-fm4.md: four-operator FM, version 2 only.
        "fm4",
    }


def test_closed_sets_match_prd() -> None:
    assert [w.value for w in Waveform] == [
        "sine",
        "square",
        "triangle",
        "saw",
        "pulse",
        "noise_white",
        "noise_pink",
    ]
    assert [f.value for f in FilterType] == ["lowpass", "highpass", "bandpass"]
    assert [t.value for t in LfoTarget] == ["pitch", "amplitude", "cutoff"]
    assert [t.value for t in ModEnvTarget] == ["pitch", "cutoff"]
    assert [m.value for m in AmMode] == ["am", "ring"]
    assert [k.value for k in EffectKind] == ["distortion", "wavefold", "delay", "reverb"]
    assert [s.value for s in LfoShape] == ["sine", "triangle", "square", "saw"]


def test_envelope_and_modulation_blocks_are_optional() -> None:
    spec = parse_spec(one_voice())
    voice = spec.voices[0]
    assert (voice.modEnv, voice.lfo, voice.fm, voice.am, voice.filter, voice.lofi) == (
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert voice.effects == []
    assert voice.ampEnv.attackMs >= 0


def test_limiter_cannot_be_disabled() -> None:
    """The master safety gate is an invariant: no field may switch it off."""
    spec = parse_spec(one_voice())
    limiter_fields = set(type(spec.master.limiter).model_fields)
    assert limiter_fields == {"targetDbfs"}
    with pytest.raises(SpecError):
        parse_spec({"voices": [{"waveform": "sine"}], "master": {"limiter": {"enabled": False}}})


# --- Unknown enums are typed errors, never guesses ----------------------------


@pytest.mark.parametrize(
    ("payload", "field", "expected_value"),
    [
        (one_voice(waveform="kazoo"), "voices[0].waveform", "sine"),
        (
            one_voice(filter={"type": "notch"}),
            "voices[0].filter.type",
            "lowpass",
        ),
        (
            one_voice(lfo={"target": "reverb"}),
            "voices[0].lfo.target",
            "pitch",
        ),
        (
            one_voice(lfo={"target": "pitch", "shape": "noise"}),
            "voices[0].lfo.shape",
            "sine",
        ),
        (
            one_voice(modEnv={"target": "resonance"}),
            "voices[0].modEnv.target",
            "pitch",
        ),
        (one_voice(am={"mode": "phase"}), "voices[0].am.mode", "am"),
        (
            one_voice(effects=[{"kind": "chorus"}]),
            "voices[0].effects[0].kind",
            "distortion",
        ),
        ({"sampleRate": 12345}, "sampleRate", 22050),
        ({"channels": 6}, "channels", 1),
    ],
)
def test_unknown_enum_is_invalid_spec(
    payload: dict[str, Any], field: str, expected_value: str | int
) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(payload)

    error = caught.value.error
    assert error.code is ErrorCode.INVALID_SPEC
    assert error.field == field
    assert error.validValues is not None
    assert expected_value in error.validValues
    # The message must be actionable on its own, not just via validValues.
    assert str(expected_value) in error.message


def test_error_result_envelope_reports_invalid_spec() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(one_voice(waveform="kazoo"))
    result = caught.value.as_result()
    assert result.status is RenderStatus.INVALID_SPEC
    assert result.wavPath is None
    assert result.error is not None


# --- Other structural failures ------------------------------------------------


def test_unsupported_version_names_the_supported_one() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"version": 3, **one_voice()})
    error = caught.value.error
    assert error.field == "version"
    # Version 2 is the music mode (docs/prd/blipsmith-music-mode.md).
    assert error.validValues == [1, 2]


def test_supported_version_is_accepted() -> None:
    assert parse_spec({"version": 1, **one_voice()}).version == 1


def test_malformed_json_is_invalid_spec() -> None:
    with pytest.raises(SpecError) as caught:
        load_spec_json('{"voices": [')
    assert "malformed JSON" in caught.value.error.message


def test_well_formed_json_is_accepted() -> None:
    spec = load_spec_json(json.dumps(one_voice()))
    assert spec.voices[0].waveform is Waveform.SINE


def test_json_nan_is_rejected() -> None:
    """json.loads accepts NaN by default; canonical JSON could never emit it."""
    with pytest.raises(SpecError):
        load_spec_json('{"durationMs": NaN, "voices": [{"waveform": "sine"}]}')


def test_missing_required_field_names_it() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{}]})
    assert caught.value.error.field == "voices[0].waveform"
    assert "required" in caught.value.error.message


def test_wrong_type_is_invalid_spec() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"durationMs": {"nested": 1}, **one_voice()})
    assert caught.value.error.field == "durationMs"


def test_unknown_field_lists_the_valid_ones() -> None:
    """A misspelled key must not be silently ignored: the agent cannot hear the difference."""
    with pytest.raises(SpecError) as caught:
        parse_spec(one_voice(attackMS=10))
    error = caught.value.error
    assert error.field == "voices[0].attackMS"
    assert error.validValues is not None
    assert "waveform" in error.validValues


# --- Render-time structural rules ---------------------------------------------


def test_zero_voices_rejected_for_render() -> None:
    with pytest.raises(SpecError) as caught:
        validate_for_render({"voices": []})
    assert caught.value.error.field == "voices"
    assert "at least one voice" in caught.value.error.message


def test_zero_voices_is_fine_outside_render() -> None:
    """A session starts empty; only rendering demands a voice."""
    spec, warnings = validate_spec({"voices": []})
    assert spec.voices == []
    assert warnings == []


def test_one_voice_renders() -> None:
    spec, _ = validate_for_render(one_voice())
    assert len(spec.voices) == 1


def test_max_voices_is_accepted() -> None:
    spec = parse_spec({"voices": [{"waveform": "sine"}] * MAX_VOICES})
    assert len(spec.voices) == MAX_VOICES


def test_one_voice_beyond_the_limit_is_rejected() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{"waveform": "sine"}] * (MAX_VOICES + 1)})
    error = caught.value.error
    assert error.field == "voices"
    assert str(MAX_VOICES) in error.message
    assert "unchanged" in error.message


def test_composition_requires_exactly_five_tracks() -> None:
    for count in (TRACK_COUNT - 1, TRACK_COUNT + 1):
        with pytest.raises(SpecError):
            parse_spec({**one_voice(), "composition": {"tracks": [{}] * count}})
    spec = parse_spec({**one_voice(), "composition": {"tracks": [{}] * TRACK_COUNT}})
    assert spec.composition is not None
    assert len(spec.composition.tracks) == TRACK_COUNT


def test_composition_defaults_to_five_tracks() -> None:
    assert len(Composition().tracks) == TRACK_COUNT


# --- Clamping in context ------------------------------------------------------


def test_clamp_warning_carries_the_full_path() -> None:
    _, warnings = validate_spec(one_voice(ampEnv={"attackMs": 999_999}))
    assert len(warnings) == 1
    warning = warnings[0]
    assert warning.param == "voices[0].ampEnv.attackMs"
    assert warning.code is WarningCode.CLAMPED
    assert warning.requested == 999_999
    assert warning.applied == 10_000


def test_composition_allows_a_longer_duration_than_a_one_shot() -> None:
    """The two documented maxima differ; a composition must not be cut to 30 s."""
    one_shot, warnings = validate_spec({**one_voice(), "durationMs": 120_000})
    assert one_shot.durationMs == 30_000
    assert warnings[0].param == "durationMs"

    composed, composed_warnings = validate_spec(
        {**one_voice(), "durationMs": 120_000, "composition": {}}
    )
    assert composed.durationMs == 120_000
    assert composed_warnings == []


def test_composition_duration_still_has_a_ceiling() -> None:
    spec, warnings = validate_spec({**one_voice(), "durationMs": 999_999, "composition": {}})
    assert spec.durationMs == 300_000
    assert len(warnings) == 1


def test_clamping_leaves_the_input_spec_untouched() -> None:
    original = parse_spec(one_voice(pan=5.0))
    clamped, warnings = clamp_spec(original)
    assert original.voices[0].pan == 5.0, "clamping mutated its input"
    assert clamped.voices[0].pan == 1.0
    assert warnings


def test_in_range_spec_produces_no_warnings() -> None:
    _, warnings = validate_spec(one_voice(pan=0.5, mixDb=-3.0))
    assert warnings == []


# --- Canonical JSON -----------------------------------------------------------


def test_canonical_json_round_trips() -> None:
    spec = parse_spec(
        {
            **one_voice(
                waveform="pulse",
                pulseDuty=0.25,
                fm={"ratio": 3.5, "index": 7.0},
                filter={"type": "bandpass", "cutoffHz": 2000.0},
                effects=[{"kind": "delay", "timeMs": 90.0}],
            ),
            "seed": 42,
            "meta": {"name": "blip", "tags": ["ui"], "description": "a blip"},
        }
    )
    restored = parse_spec(json.loads(to_canonical_json(spec)))
    assert restored == spec


def test_canonical_json_is_stable_and_sorted() -> None:
    spec = parse_spec(one_voice())
    first = to_canonical_json(spec)
    assert first == to_canonical_json(spec)

    payload = json.loads(first)
    assert list(payload) == sorted(payload)
    assert first == json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_canonical_json_materializes_defaults() -> None:
    """The core is handed a complete structure; it never fills a blank itself."""
    payload = json.loads(to_canonical_json(parse_spec(one_voice())))
    assert payload["version"] == 1
    assert payload["seed"] == 0
    assert payload["sampleRate"] == 22050
    assert payload["channels"] == 1
    assert payload["master"]["limiter"]["targetDbfs"] == -1.0
    assert payload["voices"][0]["ampEnv"]["sustainLevel"] >= 0
    assert payload["meta"]["name"] == "untitled"


def test_canonical_json_key_order_is_independent_of_input_order() -> None:
    forwards = parse_spec({"seed": 7, "durationMs": 500.0, **one_voice()})
    backwards = parse_spec({**one_voice(), "durationMs": 500.0, "seed": 7})
    assert to_canonical_json(forwards) == to_canonical_json(backwards)


def test_defaults_match_the_pinned_seams() -> None:
    spec = SoundSpec()
    assert spec.seed == 0
    assert spec.sampleRate == 22050
    assert spec.channels == 1
    assert spec.master.limiter.targetDbfs == -1.0
    assert 22050 in SUPPORTED_SAMPLE_RATES


# --- Published schema ---------------------------------------------------------


def test_schema_covers_every_field_with_type_range_and_default() -> None:
    schema = get_schema()
    models = schema["models"]
    assert schema["root"] == "SoundSpec"
    assert schema["specVersion"] == 1

    from blipsmith.ranges import RANGES

    for model_name, model in models.items():
        for field_name, described in model["fields"].items():
            label = f"{model_name}.{field_name}"
            assert described["type"], f"{label} has no type"
            # Every field states whether it is mandatory, and non-mandatory ones
            # carry the value used when omitted.
            assert "required" in described, f"{label} does not say if it is required"
            assert "default" in described, f"{label} has no default"
            if not described["required"]:
                assert described["default"] is not None or described["nullable"], label

            bounds = RANGES.get((model_name, field_name))
            if bounds is not None:
                assert described["minimum"] == bounds.minimum, label
                assert described["maximum"] == bounds.maximum, label


def test_schema_lists_every_model_reachable_from_the_root() -> None:
    models = get_schema()["models"]
    for name in (
        "SoundSpec",
        "Master",
        "Limiter",
        "Voice",
        "Adsr",
        "ModEnv",
        "Lfo",
        "Fm",
        "Am",
        "Filter",
        "LoFi",
        "Effect",
        "Composition",
        "Track",
        "Note",
        "Step",
        "Meta",
    ):
        assert name in models, f"{name} missing from the published schema"


def test_schema_publishes_closed_sets_and_limits() -> None:
    schema = get_schema()
    voice_fields = schema["models"]["Voice"]["fields"]
    assert voice_fields["waveform"]["enum"] == [w.value for w in Waveform]
    assert voice_fields["waveform"]["required"] is True

    spec_fields = schema["models"]["SoundSpec"]["fields"]
    assert spec_fields["sampleRate"]["enum"] == list(SUPPORTED_SAMPLE_RATES)
    assert spec_fields["voices"]["type"] == "array"
    assert spec_fields["voices"]["items"] == "Voice"
    assert spec_fields["voices"]["maxItems"] == MAX_VOICES

    limits = schema["limits"]
    assert limits["maxVoices"] == MAX_VOICES
    assert limits["trackCount"] == TRACK_COUNT
    assert limits["sampleRates"] == list(SUPPORTED_SAMPLE_RATES)


def test_schema_is_json_serializable() -> None:
    """It travels over MCP as JSON; anything unserializable is a broken contract."""
    assert json.loads(json.dumps(get_schema()))["root"] == "SoundSpec"
