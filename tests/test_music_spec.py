"""The music mode's contract in the spec: version 2 unlocks it, version 1 refuses it.

Version 1 is every spec written before the music mode, so these tests hold the
line that keeps their bytes: an unset music field is absent from every dump, and
a set one on a version 1 spec is a typed error rather than a silent change.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from blipsmith.ranges import MUSIC_MAX_TRACKS, MUSIC_MAX_VOICES
from blipsmith.result import SpecError
from blipsmith.schema import get_schema
from blipsmith.spec import parse_spec, to_canonical_json, validate_spec

MUSIC_KEYS = ("key", "loop", "name", "effects")


def music(**overrides: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "version": 2,
        "voices": [{"waveform": "sine"}],
        "composition": {"tracks": [{}]},
    }
    spec.update(overrides)
    return spec


def test_version_one_dumps_no_music_key() -> None:
    spec = parse_spec({"voices": [{"waveform": "sine"}], "composition": {"tracks": [{}] * 5}})
    canonical = json.loads(to_canonical_json(spec))
    assert "effects" not in canonical["master"]
    assert "loop" not in canonical["composition"]
    for track in canonical["composition"]["tracks"]:
        assert "name" not in track and "effects" not in track
    assert "key" not in canonical["voices"][0]


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"voices": [{"waveform": "sine", "key": 36}]}, "voices[0].key"),
        ({"voices": [{"waveform": "sine"}], "master": {"effects": []}}, "master.effects"),
        (
            {"voices": [{"waveform": "sine"}], "composition": {"loop": True}},
            "composition.loop",
        ),
        (
            {
                "voices": [{"waveform": "sine"}],
                "composition": {"tracks": [{"name": "kit"}, {}, {}, {}, {}]},
            },
            "composition.tracks[0].name",
        ),
    ],
)
def test_a_music_field_on_version_one_is_a_typed_error(payload: dict[str, Any], field: str) -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec(payload)
    assert caught.value.error.field == field
    assert "version to 2" in caught.value.error.message


def test_version_two_needs_a_composition() -> None:
    with pytest.raises(SpecError) as caught:
        parse_spec({"version": 2, "voices": [{"waveform": "sine"}]})
    assert caught.value.error.field == "composition"


@pytest.mark.parametrize("count", [1, 7, MUSIC_MAX_TRACKS])
def test_version_two_takes_any_track_count_up_to_the_limit(count: int) -> None:
    spec = parse_spec(music(composition={"tracks": [{}] * count}))
    assert spec.composition is not None
    assert len(spec.composition.tracks) == count


def test_version_two_refuses_more_tracks_than_the_limit() -> None:
    with pytest.raises(SpecError):
        parse_spec(music(composition={"tracks": [{}] * (MUSIC_MAX_TRACKS + 1)}))


def test_version_two_voice_limit() -> None:
    parse_spec(music(voices=[{"waveform": "sine"}] * MUSIC_MAX_VOICES))
    with pytest.raises(SpecError) as caught:
        parse_spec(music(voices=[{"waveform": "sine"}] * (MUSIC_MAX_VOICES + 1)))
    assert str(MUSIC_MAX_VOICES) in caught.value.error.message


def test_master_takes_only_linear_effects() -> None:
    parse_spec(music(master={"effects": [{"kind": "delay"}, {"kind": "reverb"}]}))
    with pytest.raises(SpecError) as caught:
        parse_spec(music(master={"effects": [{"kind": "wavefold"}]}))
    assert caught.value.error.validValues == ["delay", "reverb"]


def test_voice_track_clamps_to_the_declared_tracks() -> None:
    payload = music(
        voices=[{"waveform": "sine", "track": 9}],
        composition={"tracks": [{}, {}, {}]},
    )
    spec, warnings = validate_spec(payload)
    assert spec.voices[0].track == 2
    assert [w.param for w in warnings] == ["voices[0].track"]


def test_key_clamps_into_the_midi_range() -> None:
    spec, warnings = validate_spec(music(voices=[{"waveform": "sine", "key": 200}]))
    assert spec.voices[0].key == 127
    assert warnings[0].param == "voices[0].key"


def test_track_names_are_bounded() -> None:
    with pytest.raises(SpecError):
        parse_spec(music(composition={"tracks": [{"name": "x" * 41}]}))


def test_set_music_fields_reach_the_canonical_json() -> None:
    spec = parse_spec(
        music(
            voices=[{"waveform": "sine", "key": 38}],
            composition={
                "tracks": [{"name": "kit", "effects": [{"kind": "reverb"}]}],
                "loop": True,
            },
            master={"effects": [{"kind": "delay"}]},
        )
    )
    canonical = json.loads(to_canonical_json(spec))
    assert canonical["version"] == 2
    assert canonical["voices"][0]["key"] == 38
    assert canonical["composition"]["loop"] is True
    assert canonical["composition"]["tracks"][0]["name"] == "kit"
    assert canonical["composition"]["tracks"][0]["effects"][0]["kind"] == "reverb"
    assert canonical["master"]["effects"][0]["kind"] == "delay"


def test_schema_publishes_the_music_limits() -> None:
    schema = get_schema()
    assert schema["specVersions"] == [1, 2]
    assert schema["limits"]["music"]["maxTracks"] == MUSIC_MAX_TRACKS
    voice = schema["models"]["Voice"]["fields"]
    assert voice["key"]["musicMode"] is True
    assert "musicMode" not in voice["track"]
    assert all(key in json.dumps(schema["models"]) for key in MUSIC_KEYS)
