"""The library call and the structured CLI output a program reads instead of text."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith import render_sound
from blipsmith.cli import main
from blipsmith.render import render, stem_filename
from blipsmith.result import SpecError
from blipsmith.spec import parse_spec, to_canonical_json, validate_for_render

GOLDEN = Path(__file__).resolve().parent / "golden" / "specs"


def piece() -> dict[str, Any]:
    return {
        "version": 2,
        "sampleRate": 22050,
        "durationMs": 1000,
        "meta": {"name": "piece"},
        "voices": [
            {"waveform": "sine", "fundamentalHz": 55, "key": 36, "track": 0},
            {"waveform": "saw", "track": 1},
        ],
        "composition": {
            "loop": True,
            "tracks": [
                {"name": "kit", "notes": [{"startBeat": 0, "midiNote": 36}]},
                {"notes": [{"startBeat": 1, "midiNote": 60}]},
            ],
        },
    }


def test_render_sound_matches_the_core_byte_for_byte() -> None:
    payload = json.loads((GOLDEN / "composition-five-track.spec.json").read_text())
    spec, _ = validate_for_render(payload)
    assert render_sound(payload).wav == blipsmith._core.render(to_canonical_json(spec))["wav"]


def test_render_sound_takes_a_model_too() -> None:
    model = parse_spec(piece())
    assert render_sound(model).wav == render_sound(piece()).wav


def test_render_sound_returns_named_stems() -> None:
    sound = render_sound(piece(), stems=True)
    assert [(s.track, s.name) for s in sound.stems] == [(0, "kit"), (1, None)]
    assert all(len(s.wav) == len(sound.wav) for s in sound.stems)
    assert "integratedLufs" in sound.features


def test_render_sound_raises_on_an_invalid_spec() -> None:
    with pytest.raises(SpecError) as caught:
        render_sound({"voices": [{"waveform": "kazoo"}]})
    assert caught.value.error.field == "voices[0].waveform"


def test_stems_need_the_music_mode() -> None:
    with pytest.raises(SpecError) as caught:
        render_sound({"voices": [{"waveform": "sine"}]}, stems=True)
    assert caught.value.error.field == "version"


def test_stem_files_land_beside_the_mix(tmp_path: Path) -> None:
    result = render(piece(), out_dir=tmp_path, stems=True)
    assert [Path(s.wavPath).name for s in result.stems] == [
        "piece.stem-00-kit.wav",
        "piece.stem-01.wav",
    ]
    assert all(Path(s.wavPath).exists() for s in result.stems)


def test_stems_refused_on_version_one_touch_nothing(tmp_path: Path) -> None:
    out = tmp_path / "never"
    result = render({"voices": [{"waveform": "sine"}]}, out_dir=out, stems=True)
    assert result.status == "invalid_spec"
    assert not out.exists()


def test_stem_names_are_safe_filenames() -> None:
    assert stem_filename("a", 3, "kit / drums") == "a.stem-03-kit-drums.wav"
    assert stem_filename("a", 12, "../..") == "a.stem-12.wav"


def test_cli_json_is_one_object(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_file = tmp_path / "in.spec.json"
    spec_file.write_text(json.dumps(piece()))
    out = tmp_path / "out"
    code = main(["render", str(spec_file), "--out-dir", str(out), "--stems", "--json"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 0
    assert printed["status"] == "rendered_ok"
    assert len(printed["stems"]) == 2
    assert printed["features"]["truePeakDbtp"] <= 0.5


def test_cli_json_reports_a_failure_as_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_file = tmp_path / "in.spec.json"
    spec_file.write_text(json.dumps({"voices": [{"waveform": "sine"}]}))
    code = main(["render", str(spec_file), "--out-dir", str(tmp_path), "--stems", "--json"])
    printed = json.loads(capsys.readouterr().out)
    assert code == 1
    assert printed["error"]["field"] == "version"
