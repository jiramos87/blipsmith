"""Wavetables, partials, unison and chorus in the spec.

All four are additive to version 2. A spec that names none of them dumps exactly
as it did, a version 1 spec that names one is a typed error, a wavetable or an
additive voice replaces the oscillator, and a chorus's three fields stay out of
the dump of every other effect.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from blipsmith.explain import explain_spec
from blipsmith.result import SpecError
from blipsmith.schema import get_schema
from blipsmith.session import Session
from blipsmith.spec import parse_spec, to_canonical_json, validate_spec
from blipsmith.wavetables import NAMED_TABLES, table_frames


def music(*voices: dict[str, Any], track: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "version": 2,
        "voices": list(voices) or [{"waveform": "sine"}],
        "composition": {"tracks": [track or {}]},
    }


def dumped_voice(data: dict[str, Any]) -> dict[str, Any]:
    voice: dict[str, Any] = json.loads(to_canonical_json(parse_spec(data)))["voices"][0]
    return voice


@pytest.mark.parametrize("block", ["wavetable", "additive", "unison"])
def test_an_unset_block_is_left_out_of_the_dump(block: str) -> None:
    assert block not in dumped_voice(music())


@pytest.mark.parametrize("block", ["wavetable", "additive", "unison"])
def test_a_block_on_version_one_is_a_typed_error(block: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{"waveform": "sine", block: {}}]})
    assert caught.value.error.field == f"voices[0].{block}"
    assert "version to 2" in caught.value.error.message


def test_a_wavetable_materializes_its_defaults() -> None:
    voice = dumped_voice(music({"waveform": "sine", "wavetable": {}}))
    assert voice["wavetable"] == {
        "frames": [{"harmonics": [1.0]}],
        "position": 0.0,
        "sweepMs": 1000.0,
    }


def test_a_sweep_end_is_dumped_when_set() -> None:
    voice = dumped_voice(music({"waveform": "sine", "wavetable": {"positionEnd": 1}}))
    assert voice["wavetable"]["positionEnd"] == 1.0


def test_an_additive_voice_materializes_its_defaults() -> None:
    voice = dumped_voice(music({"waveform": "sine", "additive": {}}))
    assert voice["additive"] == {
        "brightness": 1.0,
        "stretch": 0.0,
        "partials": [{"ratio": 1.0, "level": 1.0, "decayMs": 0.0}],
    }


def test_unison_materializes_its_defaults() -> None:
    voice = dumped_voice(music({"waveform": "saw", "unison": {}}))
    assert voice["unison"] == {"voices": 2, "detuneCents": 12.0}


@pytest.mark.parametrize(
    ("block", "field", "count"),
    [
        ("wavetable", "frames", 0),
        ("wavetable", "frames", 9),
        ("additive", "partials", 0),
        ("additive", "partials", 33),
    ],
)
def test_list_lengths_are_bounded(block: str, field: str, count: int) -> None:
    entry: dict[str, Any] = {"harmonics": [1.0]} if field == "frames" else {"ratio": 1}
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", block: {field: [entry] * count}}))
    assert caught.value.error.field == f"voices[0].{block}.{field}"


def test_a_frame_holds_one_to_sixty_four_harmonics() -> None:
    with pytest.raises(SpecError):
        parse_spec(music({"waveform": "sine", "wavetable": {"frames": [{"harmonics": []}]}}))
    with pytest.raises(SpecError):
        parse_spec(
            music({"waveform": "sine", "wavetable": {"frames": [{"harmonics": [0.1] * 65}]}})
        )
    parse_spec(music({"waveform": "sine", "wavetable": {"frames": [{"harmonics": [0.1] * 64}]}}))


def test_harmonics_clamp_one_by_one_with_a_warning() -> None:
    frames = [{"harmonics": [1.0, 3.0, -2.0]}]
    spec, warnings = validate_spec(music({"waveform": "sine", "wavetable": {"frames": frames}}))
    wavetable = spec.voices[0].wavetable
    assert wavetable is not None
    assert wavetable.frames[0].harmonics == [1.0, 1.0, -1.0]
    params = [w.param for w in warnings]
    assert "voices[0].wavetable.frames[0].harmonics[1]" in params
    assert "voices[0].wavetable.frames[0].harmonics[2]" in params


def test_unison_counts_clamp() -> None:
    spec, warnings = validate_spec(music({"waveform": "saw", "unison": {"voices": 12}}))
    assert spec.voices[0].unison is not None
    assert spec.voices[0].unison.voices == 8
    assert warnings


@pytest.mark.parametrize("block", ["wavetable", "additive"])
@pytest.mark.parametrize("other", ["fm", "fm4", "string", "modal"])
def test_a_new_source_beside_another_is_a_typed_error(block: str, other: str) -> None:
    with pytest.raises(SpecError):
        parse_spec(music({"waveform": "sine", other: {}, block: {}}))


def test_a_wavetable_and_an_additive_voice_do_not_mix() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "sine", "wavetable": {}, "additive": {}}))
    assert caught.value.error.field == "voices[0].wavetable"


@pytest.mark.parametrize("block", ["wavetable", "additive"])
def test_a_new_source_needs_a_sine_waveform(block: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": "saw", block: {}}))
    assert caught.value.error.field == "voices[0].waveform"


@pytest.mark.parametrize("noise", ["noise_white", "noise_pink"])
def test_unison_on_noise_is_a_typed_error(noise: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(music({"waveform": noise, "unison": {}}))
    assert caught.value.error.field == "voices[0].unison"


@pytest.mark.parametrize("source", ["fm", "fm4", "string", "modal", "wavetable", "additive"])
def test_unison_rides_on_every_pitched_source(source: str) -> None:
    parse_spec(music({"waveform": "sine", source: {}, "unison": {"voices": 3}}))


def test_other_effects_dump_without_the_chorus_fields() -> None:
    effects = [{"kind": "delay"}, {"kind": "reverb"}, {"kind": "distortion"}]
    voice = dumped_voice(music({"waveform": "sine", "effects": effects}))
    for effect in voice["effects"]:
        assert not {"delayMs", "depthMs", "rateHz"} & set(effect)


def test_a_chorus_fills_its_fields() -> None:
    voice = dumped_voice(music({"waveform": "sine", "effects": [{"kind": "chorus"}]}))
    chorus = voice["effects"][0]
    assert chorus["delayMs"] == 12.0
    assert chorus["depthMs"] == 2.0
    assert chorus["rateHz"] == 0.8


def test_a_chorus_on_a_track_parses() -> None:
    spec = parse_spec(music(track={"effects": [{"kind": "chorus", "depthMs": 3}]}))
    assert spec.composition is not None
    effects = spec.composition.tracks[0].effects
    assert effects is not None
    assert effects[0].depthMs == 3.0


def test_a_chorus_on_version_one_is_a_typed_error() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"voices": [{"waveform": "sine", "effects": [{"kind": "chorus"}]}]})
    assert caught.value.error.field == "voices[0].effects[0]"


def test_a_chorus_field_on_version_one_is_a_typed_error() -> None:
    with pytest.raises(SpecError):
        parse_spec({"voices": [{"waveform": "sine", "effects": [{"kind": "delay", "rateHz": 1}]}]})


def test_a_chorus_cannot_sit_on_the_master() -> None:
    data = music()
    data["master"] = {"effects": [{"kind": "chorus"}]}
    with pytest.raises(SpecError) as caught:
        parse_spec(data)
    assert caught.value.error.field == "master.effects[0].kind"


def test_chorus_fields_clamp() -> None:
    spec, warnings = validate_spec(
        music({"waveform": "sine", "effects": [{"kind": "chorus", "depthMs": 50}]})
    )
    assert spec.voices[0].effects[0].depthMs == 10.0
    assert warnings


@pytest.mark.parametrize("name", list(NAMED_TABLES))
def test_named_tables_expand_into_valid_frames(name: str) -> None:
    frames = table_frames(name)
    spec, warnings = validate_spec(music({"waveform": "sine", "wavetable": {"frames": frames}}))
    assert warnings == []
    wavetable = spec.voices[0].wavetable
    assert wavetable is not None
    assert len(wavetable.frames) == len(frames) >= 3


def test_an_unknown_table_is_a_typed_error() -> None:
    with pytest.raises(SpecError) as caught:
        table_frames("kazoo")
    assert "bright" in caught.value.error.message


def test_the_schema_publishes_the_new_blocks_as_music_mode() -> None:
    models = get_schema()["models"]
    for block in ("wavetable", "additive", "unison"):
        assert models["Voice"]["fields"][block]["musicMode"] is True
    assert "chorus" in models["Effect"]["fields"]["kind"]["enum"]
    assert models["Effect"]["fields"]["rateHz"]["musicMode"] is True
    assert models["Frame"]["fields"]["harmonics"]["maximum"] == 1
    assert models["Partial"]["fields"]["decayMs"]["maximum"] == 30_000


# --- The session verbs and the explanation ----------------------------------------------


def music_session() -> Session:
    session = Session()
    session.new_voice("sine")
    session.set_render_options(version=2)
    return session


def test_set_wavetable_takes_a_named_table_and_patches_it() -> None:
    session = music_session()
    session.set_wavetable(table="bright", position=0.25)
    session.set_wavetable(positionEnd=0.75, sweepMs=500)
    wavetable = session.spec.voices[0].wavetable
    assert wavetable is not None
    assert len(wavetable.frames) == 4
    assert (wavetable.position, wavetable.positionEnd, wavetable.sweepMs) == (0.25, 0.75, 500)
    session.set_wavetable(frames=[[1.0, 0.5]])
    wavetable = session.spec.voices[0].wavetable
    assert wavetable is not None
    assert wavetable.frames[0].harmonics == [1.0, 0.5]
    session.set_wavetable(clear=True)
    assert session.spec.voices[0].wavetable is None


def test_set_wavetable_refuses_a_name_and_frames_together() -> None:
    session = music_session()
    with pytest.raises(SpecError):
        session.set_wavetable(table="organ", frames=[[1.0]])
    assert session.spec.voices[0].wavetable is None


def test_set_additive_and_set_unison_patch_their_blocks() -> None:
    session = music_session()
    session.set_additive(partials=[{"ratio": 1.0}, {"ratio": 2.0, "decayMs": 300.0}])
    session.set_additive(stretch=0.001)
    session.set_unison(voices=3)
    voice = session.spec.voices[0]
    assert voice.additive is not None
    assert [(p.ratio, p.decayMs) for p in voice.additive.partials] == [(1.0, 0.0), (2.0, 300.0)]
    assert voice.additive.stretch == 0.001
    assert voice.unison is not None
    assert (voice.unison.voices, voice.unison.detuneCents) == (3, 12.0)


def test_the_new_verbs_are_refused_on_version_one() -> None:
    session = Session()
    session.new_voice("sine")
    for verb in (session.set_wavetable, session.set_additive, session.set_unison):
        with pytest.raises(SpecError) as caught:
            verb()
        assert caught.value.error.field == "version"


def test_the_explanation_names_each_block() -> None:
    spec = parse_spec(
        music(
            {
                "waveform": "sine",
                "wavetable": {
                    "frames": table_frames("vowel"),
                    "position": 0.1,
                    "positionEnd": 0.9,
                    "sweepMs": 800,
                },
                "unison": {"voices": 3, "detuneCents": 8},
                "touch": {"cutoffOctaves": 2},
            },
            {
                "waveform": "sine",
                "additive": {"partials": [{"ratio": 1}, {"ratio": 2, "decayMs": 300}]},
                "effects": [{"kind": "chorus"}],
            },
        )
    )
    text = explain_spec(spec)
    assert "a wavetable tone" in text
    assert "a wavetable of 4 frames up to harmonic 14, swept from 0.1 to 0.9 over 800 ms" in text
    assert "3 unison copies spread 8 cents" in text
    assert "touch moving the table position" in text
    assert "an additive tone" in text
    assert "2 partials at 1x, 2x the pitch, some fading and some held" in text
    assert "a chorus swinging 2 ms around 12 ms at 0.8 Hz" in text
