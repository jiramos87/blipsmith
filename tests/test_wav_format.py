"""B03: the bytes the core emits are a canonical PCM WAV and nothing more."""

from __future__ import annotations

import struct
from typing import Any

import pytest

import blipsmith
from blipsmith.spec import to_canonical_json, validate_for_render

HEADER_BYTES = 44


def render_bytes(**overrides: Any) -> bytes:
    payload: dict[str, Any] = {"voices": [{"waveform": "sine"}]}
    payload.update(overrides)
    spec, _ = validate_for_render(payload)
    result = blipsmith._core.render(to_canonical_json(spec))
    wav: bytes = result["wav"]
    return wav


def field(wav: bytes, fmt: str, offset: int) -> int:
    value: int = struct.unpack_from(fmt, wav, offset)[0]
    return value


def test_riff_wave_container() -> None:
    wav = render_bytes()
    assert wav[0:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert wav[12:16] == b"fmt "
    assert wav[36:40] == b"data"
    # RIFF size counts everything after the size field itself.
    assert field(wav, "<I", 4) == len(wav) - 8


def test_fmt_chunk_declares_uncompressed_pcm16() -> None:
    wav = render_bytes()
    assert field(wav, "<I", 16) == 16, "PCM fmt chunk is 16 bytes"
    assert field(wav, "<H", 20) == 1, "audio format 1 is uncompressed PCM"
    assert field(wav, "<H", 34) == 16, "16 bits per sample"


def test_header_is_exactly_44_bytes() -> None:
    """No LIST or INFO chunks: those carry timestamps and encoder names, and
    would make two renders of the same spec differ."""
    wav = render_bytes()
    assert field(wav, "<I", 40) == len(wav) - HEADER_BYTES


@pytest.mark.parametrize("channels", [1, 2])
@pytest.mark.parametrize("sample_rate", [8000, 11025, 16000, 22050, 44100])
def test_header_matches_the_requested_format(channels: int, sample_rate: int) -> None:
    wav = render_bytes(channels=channels, sampleRate=sample_rate, durationMs=250.0)

    assert field(wav, "<H", 22) == channels
    assert field(wav, "<I", 24) == sample_rate

    block_align = channels * 2
    assert field(wav, "<H", 32) == block_align
    assert field(wav, "<I", 28) == sample_rate * block_align, "byte rate"

    frames = int(250.0 * sample_rate / 1000.0)
    assert field(wav, "<I", 40) == frames * block_align


@pytest.mark.parametrize("duration_ms", [10.0, 250.0, 1000.0, 2500.0])
def test_data_chunk_length_matches_duration(duration_ms: float) -> None:
    wav = render_bytes(durationMs=duration_ms)
    frames = int(duration_ms * 22050 / 1000.0)
    assert field(wav, "<I", 40) == frames * 2
    assert len(wav) == HEADER_BYTES + frames * 2


def test_stereo_is_exactly_twice_the_mono_payload() -> None:
    mono = render_bytes(channels=1, durationMs=500.0)
    stereo = render_bytes(channels=2, durationMs=500.0)
    assert len(stereo) - HEADER_BYTES == 2 * (len(mono) - HEADER_BYTES)


def test_payload_carries_real_audio() -> None:
    """B03 rendered correct-shaped silence on purpose; from B04 the oscillators
    fill it in, so an all-zero payload now means something is broken."""
    wav = render_bytes(durationMs=100.0)
    assert set(wav[HEADER_BYTES:]) != {0}


def test_features_dict_carries_every_pinned_key() -> None:
    spec, _ = validate_for_render({"voices": [{"waveform": "sine"}]})
    features = blipsmith._core.render(to_canonical_json(spec))["features"]

    assert set(features) == {
        "durationMs",
        "peakDbfs",
        "rmsDbfs",
        "estimatedFundamentalHz",
        "spectralCentroidHz",
        "attackTimeMs",
    }
    assert features["durationMs"] == pytest.approx(1000.0)
    # B03 returned the other five as nulls, meaning "not measured yet". B08
    # measures them, so a null here now means a feature went missing rather
    # than a stage being unbuilt. What each one *means* is tested in
    # test_features.py; this only guards the bridge's shape.
    assert all(value is not None for value in features.values())


def test_core_render_is_byte_identical_across_calls() -> None:
    spec, _ = validate_for_render({"voices": [{"waveform": "saw"}], "seed": 7})
    canonical = to_canonical_json(spec)
    assert blipsmith._core.render(canonical)["wav"] == blipsmith._core.render(canonical)["wav"]


def test_core_rejects_unparseable_json() -> None:
    """The core trusts the Python layer, but must fail loudly rather than crash."""
    with pytest.raises(RuntimeError):
        blipsmith._core.render("{not json")
