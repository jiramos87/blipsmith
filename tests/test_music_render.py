"""The music mode's render: the kit, effects with tails, the loop, stems.

Each test renders through the same validate-compile-core path the product uses
and reads the PCM back, because what the contract promises is audio: a keyed
voice that stays quiet, a room that rings on, a file that is exactly the loop.
"""

from __future__ import annotations

import copy
import struct
from typing import Any

import blipsmith
from blipsmith.composition import compile_composition
from blipsmith.result import WarningCode
from blipsmith.spec import to_canonical_json, validate_for_render

RATE = 22050
TEMPO = 120.0  # half a second a beat
FRAMES_PER_BEAT = RATE // 2


def kick(**overrides: Any) -> dict[str, Any]:
    voice: dict[str, Any] = {
        "waveform": "sine",
        "fundamentalHz": 55.0,
        "key": 36,
        "ampEnv": {"attackMs": 1, "decayMs": 150, "sustainLevel": 0, "releaseMs": 20},
    }
    voice.update(overrides)
    return voice


def piece(voices: list[dict[str, Any]], tracks: list[dict[str, Any]], **top: Any) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "version": 2,
        "seed": 7,
        "sampleRate": RATE,
        "durationMs": 2000,
        "voices": voices,
        "composition": {"tempoBpm": TEMPO, "tracks": tracks},
    }
    for key, value in top.items():
        if key == "loop":
            spec["composition"]["loop"] = value
        else:
            spec[key] = value
    return spec


def render(spec: dict[str, Any], stems: bool = False) -> dict[str, Any]:
    validated, _ = validate_for_render(spec)
    result: dict[str, Any] = blipsmith._core.render(to_canonical_json(validated), stems)
    return result


def samples(wav: bytes) -> tuple[int, ...]:
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def left(wav: bytes) -> tuple[int, ...]:
    return samples(wav)[0::2]


def note(beat: float, midi: int | None, length: float = 0.5) -> dict[str, Any]:
    return {"startBeat": beat, "midiNote": midi, "durationBeats": length}


# --- The kit ------------------------------------------------------------------


def test_a_keyed_voice_plays_only_its_key() -> None:
    snare = {"waveform": "noise_white", "key": 38, "ampEnv": {"releaseMs": 20}}
    notes = [note(0, 36), note(1, 36)]
    both = piece([kick(), snare], [{"notes": notes}])
    alone = piece([kick()], [{"notes": notes}])
    assert render(both)["wav"] == render(alone)["wav"]


def test_several_voices_share_a_key() -> None:
    body = kick(fundamentalHz=180.0)
    one = render(piece([kick()], [{"notes": [note(0, 36)]}]))["wav"]
    two = render(piece([kick(), body], [{"notes": [note(0, 36)]}]))["wav"]
    assert one != two


def test_a_keyed_voice_keeps_its_own_pitch() -> None:
    tone = kick(
        fundamentalHz=220.0,
        ampEnv={"attackMs": 1, "decayMs": 1, "sustainLevel": 1, "releaseMs": 1},
    )
    played = render(piece([tone], [{"notes": [note(0, 36, 3.5)]}]))
    assert abs(played["features"]["estimatedFundamentalHz"] - 220.0) < 5.0


def test_a_keyless_voice_follows_the_note() -> None:
    tone = {"waveform": "sine", "ampEnv": {"sustainLevel": 1, "releaseMs": 1}}
    played = render(piece([tone], [{"notes": [note(0, 57, 3.5)]}]))
    assert abs(played["features"]["estimatedFundamentalHz"] - 220.0) < 5.0


def test_a_note_no_voice_plays_warns() -> None:
    spec, _ = validate_for_render(piece([kick()], [{"notes": [note(0, 36), note(1, 40)]}]))
    _, warnings = compile_composition(spec)
    assert [w.code for w in warnings] == [WarningCode.NOTE_UNPLAYED]
    assert "beat 1.0" in warnings[0].message


# --- Effects with tails -------------------------------------------------------


def test_a_voice_delay_rings_past_its_note() -> None:
    echo = kick(effects=[{"kind": "delay", "timeMs": 400, "feedback": 0.5, "mixWet": 0.5}])
    wav = render(piece([echo], [{"notes": [note(0, 36)]}]))["wav"]
    after = left(wav)[FRAMES_PER_BEAT * 2 :]  # a second after a 170 ms hit
    assert max(abs(s) for s in after) > 30


def test_a_track_room_rings_past_the_notes() -> None:
    tracks = [
        {"effects": [{"kind": "reverb", "roomSize": 0.8, "mixWet": 0.5}], "notes": [note(0, 36)]}
    ]
    wav = render(piece([kick()], tracks))["wav"]
    tail = left(wav)[FRAMES_PER_BEAT : FRAMES_PER_BEAT * 2]
    assert max(abs(s) for s in tail) > 30


def test_a_track_room_is_wide() -> None:
    tracks = [
        {"effects": [{"kind": "reverb", "roomSize": 0.8, "mixWet": 0.6}], "notes": [note(0, 36)]}
    ]
    pcm = samples(render(piece([kick()], tracks))["wav"])
    assert pcm[0::2] != pcm[1::2]


def test_any_number_of_tracks() -> None:
    voices = [kick(track=index) for index in range(9)]
    tracks = [{"notes": [note(index * 0.25, 36)]} for index in range(9)]
    result = render(piece(voices, tracks), stems=True)
    assert len(result["stems"]) == 9


# --- The loop -----------------------------------------------------------------


def test_the_loop_is_exactly_the_duration() -> None:
    spec = piece([kick()], [{"notes": [note(3.5, 36)]}], loop=True)
    assert len(left(render(spec)["wav"])) == RATE * 2


def test_the_loop_wraps_the_tail_onto_the_start() -> None:
    long = kick(ampEnv={"attackMs": 1, "decayMs": 50, "sustainLevel": 0.8, "releaseMs": 600})
    tracks = [{"notes": [note(3.5, 36)]}]  # held to the end, released past it
    wrapped = left(render(piece([long], tracks, loop=True))["wav"])
    cut = left(render(piece([long], tracks))["wav"])
    assert max(abs(s) for s in cut[:FRAMES_PER_BEAT]) == 0
    assert max(abs(s) for s in wrapped[:FRAMES_PER_BEAT]) > 30


def test_the_loop_wraps_a_room_longer_than_the_loop() -> None:
    master = {"effects": [{"kind": "reverb", "roomSize": 1.0, "mixWet": 0.6}]}
    spec = piece([kick()], [{"notes": [note(3, 36)]}], loop=True, master=master)
    spec["durationMs"] = 500
    spec["composition"]["tracks"][0]["notes"] = [note(0.5, 36)]
    wav = left(render(spec)["wav"])
    assert len(wav) == RATE // 2
    assert max(abs(s) for s in wav[: RATE // 4]) > 30


# --- Stems --------------------------------------------------------------------


def three_tracks() -> dict[str, Any]:
    voices = [
        kick(track=0),
        {"waveform": "saw", "track": 1, "pan": -0.5, "mixDb": -6},
        {"waveform": "triangle", "track": 2, "effects": [{"kind": "delay", "timeMs": 200}]},
    ]
    tracks: list[dict[str, Any]] = [
        {"notes": [note(0, 36), note(2, 36)]},
        {"effects": [{"kind": "reverb"}], "notes": [note(0, 45, 2)]},
        {"pan": 0.4, "notes": [note(1, 72), note(3.5, 76)]},
    ]
    master = {"effects": [{"kind": "reverb", "roomSize": 0.4, "mixWet": 0.2}]}
    return piece(voices, tracks, loop=True, master=master)


def test_stems_sum_to_the_mix_within_a_step_per_track() -> None:
    result = render(three_tracks(), stems=True)
    mix = samples(result["wav"])
    stems = [samples(stem) for stem in result["stems"]]
    assert len(stems) == 3
    worst = max(abs(sum(stem[i] for stem in stems) - mix[i]) for i in range(len(mix)))
    assert worst <= len(stems)
    assert result["stemClipped"] == [False, False, False]


def test_asking_for_stems_leaves_the_mix_alone() -> None:
    spec = three_tracks()
    assert render(spec, stems=True)["wav"] == render(spec)["wav"]


def test_the_music_mode_is_deterministic() -> None:
    spec = three_tracks()
    again = copy.deepcopy(spec)
    assert render(spec, stems=True)["stems"] == render(again, stems=True)["stems"]
