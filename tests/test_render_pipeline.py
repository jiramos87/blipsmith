"""B03: the orchestration around the audio, which is final even though the
audio itself is still silence."""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path
from typing import Any

import pytest

from blipsmith.render import (
    DEFAULT_OUT_DIR,
    OUT_DIR_ENV,
    render,
    resolve_out_dir,
    to_sidecar_json,
)
from blipsmith.result import ErrorCode, RenderStatus
from blipsmith.spec import parse_spec, to_canonical_json


def spec_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "voices": [{"waveform": "sine"}],
        "meta": {"name": "blip"},
    }
    payload.update(overrides)
    return payload


# --- Happy path ---------------------------------------------------------------


def test_render_writes_wav_and_sidecar(tmp_path: Path) -> None:
    result = render(spec_payload(), out_dir=tmp_path)

    assert result.status is RenderStatus.RENDERED_OK
    assert result.error is None
    assert result.wavPath == str(tmp_path / "blip.wav")
    assert result.specPath == str(tmp_path / "blip.spec.json")
    assert (tmp_path / "blip.wav").exists()
    assert (tmp_path / "blip.spec.json").exists()


def test_rendering_twice_is_byte_identical(tmp_path: Path) -> None:
    first = render(spec_payload(seed=99), out_dir=tmp_path / "a")
    second = render(spec_payload(seed=99), out_dir=tmp_path / "b")

    assert first.wavPath is not None
    assert second.wavPath is not None
    assert Path(first.wavPath).read_bytes() == Path(second.wavPath).read_bytes()


def test_different_specs_are_not_conflated(tmp_path: Path) -> None:
    short = render(spec_payload(durationMs=100.0), out_dir=tmp_path / "short")
    long_ = render(spec_payload(durationMs=200.0), out_dir=tmp_path / "long")

    assert short.wavPath is not None
    assert long_.wavPath is not None
    assert Path(short.wavPath).read_bytes() != Path(long_.wavPath).read_bytes()


def test_defaults_are_mono_22050_16bit(tmp_path: Path) -> None:
    result = render(spec_payload(), out_dir=tmp_path)
    assert result.wavPath is not None
    wav = Path(result.wavPath).read_bytes()

    assert struct.unpack_from("<H", wav, 22)[0] == 1, "mono"
    assert struct.unpack_from("<I", wav, 24)[0] == 22050
    assert struct.unpack_from("<H", wav, 34)[0] == 16
    assert struct.unpack_from("<I", wav, 40)[0] == 22050 * 2, "one second of frames"


def test_result_carries_the_feature_block(tmp_path: Path) -> None:
    result = render(spec_payload(), out_dir=tmp_path)
    assert result.features is not None
    assert set(result.features) >= {"durationMs", "peakDbfs", "attackTimeMs"}


def test_explicit_name_overrides_meta_name(tmp_path: Path) -> None:
    result = render(spec_payload(), out_dir=tmp_path, name="override")
    assert result.wavPath == str(tmp_path / "override.wav")
    assert (tmp_path / "override.spec.json").exists()


# --- The sidecar round trip ---------------------------------------------------


def test_sidecar_reparses_to_the_same_canonical_spec(tmp_path: Path) -> None:
    """The PRD's core promise: the committed spec regenerates the asset exactly."""
    payload = spec_payload(seed=3, durationMs=750.0)
    result = render(payload, out_dir=tmp_path)
    assert result.specPath is not None

    original = parse_spec(payload)
    restored = parse_spec(json.loads(Path(result.specPath).read_text()))

    assert to_canonical_json(restored) == to_canonical_json(original)


def test_rendering_the_sidecar_reproduces_the_bytes(tmp_path: Path) -> None:
    first = render(spec_payload(), out_dir=tmp_path / "one")
    assert first.specPath is not None and first.wavPath is not None

    from_sidecar = json.loads(Path(first.specPath).read_text())
    second = render(from_sidecar, out_dir=tmp_path / "two")

    assert second.wavPath is not None
    assert Path(second.wavPath).read_bytes() == Path(first.wavPath).read_bytes()


def test_sidecar_is_human_editable(tmp_path: Path) -> None:
    """The PRD has humans hand-editing this file, so it is indented and sorted."""
    result = render(spec_payload(), out_dir=tmp_path)
    assert result.specPath is not None
    text = Path(result.specPath).read_text()

    assert text.endswith("\n")
    assert "\n  " in text, "sidecar should be indented, not minified"
    payload = json.loads(text)
    assert list(payload) == sorted(payload)


def test_sidecar_json_is_stable() -> None:
    spec = parse_spec(spec_payload())
    assert to_sidecar_json(spec) == to_sidecar_json(spec)


# --- Output directory resolution ----------------------------------------------


def test_missing_output_directory_is_created(tmp_path: Path) -> None:
    nested = tmp_path / "deeply" / "nested" / "out"
    assert not nested.exists()

    result = render(spec_payload(), out_dir=nested)

    assert result.status is RenderStatus.RENDERED_OK
    assert (nested / "blip.wav").exists()


def test_env_var_supplies_the_default_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OUT_DIR_ENV, str(tmp_path / "from-env"))
    assert resolve_out_dir() == tmp_path / "from-env"

    result = render(spec_payload())
    assert result.wavPath == str(tmp_path / "from-env" / "blip.wav")


def test_explicit_directory_beats_the_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OUT_DIR_ENV, str(tmp_path / "from-env"))
    assert resolve_out_dir(tmp_path / "explicit") == tmp_path / "explicit"


def test_falls_back_to_the_default_directory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(OUT_DIR_ENV, raising=False)
    assert resolve_out_dir() == Path(DEFAULT_OUT_DIR)


# --- Refusals -----------------------------------------------------------------


def test_existing_file_is_not_silently_replaced(tmp_path: Path) -> None:
    first = render(spec_payload(), out_dir=tmp_path)
    assert first.status is RenderStatus.RENDERED_OK
    original = (tmp_path / "blip.wav").read_bytes()

    blocked = render(spec_payload(durationMs=500.0), out_dir=tmp_path)

    assert blocked.status is RenderStatus.RENDER_FAILED
    assert blocked.error is not None
    assert blocked.error.code is ErrorCode.RENDER_FAILED
    assert "blip.wav" in blocked.error.message
    assert "overwrite" in blocked.error.message
    assert (tmp_path / "blip.wav").read_bytes() == original, "the asset was replaced anyway"


def test_overwrite_flag_replaces_the_asset(tmp_path: Path) -> None:
    render(spec_payload(), out_dir=tmp_path)
    original = (tmp_path / "blip.wav").read_bytes()

    result = render(spec_payload(durationMs=500.0), out_dir=tmp_path, overwrite=True)

    assert result.status is RenderStatus.RENDERED_OK
    assert (tmp_path / "blip.wav").read_bytes() != original


def test_an_existing_sidecar_alone_also_blocks(tmp_path: Path) -> None:
    """Both halves are assets; neither may be clobbered without the flag."""
    (tmp_path / "blip.spec.json").write_text("{}")

    result = render(spec_payload(), out_dir=tmp_path)

    assert result.status is RenderStatus.RENDER_FAILED
    assert result.error is not None
    assert "blip.spec.json" in result.error.message
    assert not (tmp_path / "blip.wav").exists(), "partial output left behind"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_unwritable_directory_fails_with_an_actionable_message(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        result = render(spec_payload(), out_dir=locked)

        assert result.status is RenderStatus.RENDER_FAILED
        assert result.error is not None
        assert "permission" in result.error.message.lower()
        assert list(locked.iterdir()) == [], "no partial files"
    finally:
        locked.chmod(0o700)


def test_invalid_spec_writes_nothing(tmp_path: Path) -> None:
    result = render({"voices": [{"waveform": "kazoo"}]}, out_dir=tmp_path)

    assert result.status is RenderStatus.INVALID_SPEC
    assert result.wavPath is None
    assert result.error is not None
    assert result.error.validValues is not None
    assert list(tmp_path.iterdir()) == []


def test_voiceless_spec_writes_nothing(tmp_path: Path) -> None:
    result = render({"voices": []}, out_dir=tmp_path)

    assert result.status is RenderStatus.INVALID_SPEC
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape", "sub/dir", "", ".", ".."])
def test_a_name_cannot_escape_the_output_directory(tmp_path: Path, name: str) -> None:
    """meta.name is agent-controlled, so it must stay a plain filename."""
    result = render(spec_payload(), out_dir=tmp_path, name=name)

    assert result.status is RenderStatus.RENDER_FAILED
    assert result.error is not None
    assert "plain filename" in result.error.message
    assert list(tmp_path.iterdir()) == []


# --- Warnings ride along with a successful render -----------------------------


def test_clamped_spec_renders_with_warnings(tmp_path: Path) -> None:
    result = render(spec_payload(voices=[{"waveform": "sine", "pan": 12.0}]), out_dir=tmp_path)

    assert result.status is RenderStatus.RENDERED_WITH_WARNINGS
    assert result.wavPath is not None
    assert Path(result.wavPath).exists(), "a clamp must not prevent the render"
    assert len(result.warnings) == 1
    assert result.warnings[0].param == "voices[0].pan"
    assert result.warnings[0].applied == 1.0


def test_in_range_spec_renders_clean(tmp_path: Path) -> None:
    result = render(spec_payload(voices=[{"waveform": "sine", "pan": 0.5}]), out_dir=tmp_path)
    assert result.status is RenderStatus.RENDERED_OK
    assert result.warnings == []
