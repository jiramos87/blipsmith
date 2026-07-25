"""B11: the command line.

The CLI is the half of the product that has to still work when nobody is
driving. Its job is to turn a committed spec back into the same bytes, so the
tests that matter most here are the round trips: render a spec, render the
sidecar it emitted, compare. Everything else is about failing legibly, since a
human reading a terminal cannot ask the tool what it meant.

Most tests call `main()` in process, which is the same code path the console
script wraps. Two do not: the entry point itself and the missing-core case both
have to be observed from outside the interpreter that owns them.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from blipsmith.cli import build_parser, main
from blipsmith.presets import list_presets, load_preset
from blipsmith.render import render

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN = REPO_ROOT / "tests" / "golden"
VERIFY = REPO_ROOT / "scripts" / "verify.sh"

COMMANDS = ("render", "batch", "vary", "explain", "presets", "verify-golden")

# `verify-golden` defaults its corpus directory and `presets` takes nothing, so
# neither has a positional to supply when the parser is exercised generically.
COMMANDS_WITHOUT_A_POSITIONAL = ("presets", "verify-golden")


# --- Fixtures and helpers -----------------------------------------------------


def spec_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "durationMs": 200.0,
        "seed": 7,
        "voices": [{"waveform": "noise_white", "fundamentalHz": 440.0}],
        "meta": {"name": "hiss", "tags": ["test"], "description": "A test hiss."},
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "hiss.spec.json"
    path.write_text(json.dumps(spec_payload(), indent=2), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def out_dir_is_never_the_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every command falls back to `$BLIPSMITH_OUT_DIR`, so point it somewhere
    disposable: a test that forgets `--out-dir` must not write into the repo."""
    monkeypatch.setenv("BLIPSMITH_OUT_DIR", str(tmp_path / "default-out"))


def samples_of(path: Path) -> tuple[int, ...]:
    wav = path.read_bytes()
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


# --- The spec round trip ------------------------------------------------------


def test_a_committed_sidecar_re_renders_the_same_bytes(spec_file: Path, tmp_path: Path) -> None:
    """The product's central promise: what the agent rendered, the human
    re-renders byte for byte from the file in the repository."""
    first = tmp_path / "first"
    again = tmp_path / "again"

    assert main(["render", str(spec_file), "--out-dir", str(first)]) == 0
    assert main(["render", str(first / "hiss.spec.json"), "--out-dir", str(again)]) == 0

    assert (first / "hiss.wav").read_bytes() == (again / "hiss.wav").read_bytes()


def test_the_cli_renders_through_the_shared_pipeline(spec_file: Path, tmp_path: Path) -> None:
    """No synthesis logic lives only here: the same spec through the library
    gives the same file, so the MCP surface cannot drift from this one."""
    through_cli = tmp_path / "cli"
    through_api = tmp_path / "api"

    assert main(["render", str(spec_file), "--out-dir", str(through_cli)]) == 0
    render(spec_payload(), out_dir=through_api)

    assert (through_cli / "hiss.wav").read_bytes() == (through_api / "hiss.wav").read_bytes()


# --- render flags -------------------------------------------------------------


def test_out_dir_flag_places_the_files(spec_file: Path, tmp_path: Path) -> None:
    target = tmp_path / "somewhere" / "deeper"

    assert main(["render", str(spec_file), "--out-dir", str(target)]) == 0

    assert (target / "hiss.wav").exists()
    assert (target / "hiss.spec.json").exists()


def test_the_env_var_is_the_fallback_out_dir(spec_file: Path, tmp_path: Path) -> None:
    """The pinned resolution order, with the explicit flag left off."""
    assert main(["render", str(spec_file)]) == 0

    assert (tmp_path / "default-out" / "hiss.wav").exists()


def test_seed_flag_overrides_the_spec(spec_file: Path, tmp_path: Path) -> None:
    """A noise voice, so a different seed is a different file, and the sidecar
    records the seed that was actually used."""
    default = tmp_path / "default"
    seeded = tmp_path / "seeded"

    assert main(["render", str(spec_file), "--out-dir", str(default)]) == 0
    assert main(["render", str(spec_file), "--seed", "12345", "--out-dir", str(seeded)]) == 0

    assert samples_of(default / "hiss.wav") != samples_of(seeded / "hiss.wav")
    assert json.loads((seeded / "hiss.spec.json").read_text())["seed"] == 12345


def test_name_flag_sets_the_output_stem(spec_file: Path, tmp_path: Path) -> None:
    assert main(["render", str(spec_file), "--name", "custom", "--out-dir", str(tmp_path)]) == 0

    assert (tmp_path / "custom.wav").exists()
    assert not (tmp_path / "hiss.wav").exists()


def test_rendering_twice_refuses_then_overwrites(
    spec_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Both sides of the overwrite flag. An asset already on disk is somebody's
    committed sound effect until they say otherwise."""
    out_dir = str(tmp_path / "out")
    assert main(["render", str(spec_file), "--out-dir", out_dir]) == 0

    assert main(["render", str(spec_file), "--out-dir", out_dir]) == 1
    assert "refusing to overwrite" in capsys.readouterr().err

    assert main(["render", str(spec_file), "--out-dir", out_dir, "--overwrite"]) == 0


def test_render_prints_both_paths_and_the_features(
    spec_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The agent steers by features and the human needs the path; a render that
    printed neither would make the caller go looking."""
    out_dir = tmp_path / "out"
    main(["render", str(spec_file), "--out-dir", str(out_dir)])
    out = capsys.readouterr().out

    assert str(out_dir / "hiss.wav") in out
    assert str(out_dir / "hiss.spec.json") in out
    for label in ("peak", "rms", "f0", "centroid", "attack"):
        assert label in out


def test_a_clamp_warning_is_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A clamped render still succeeds, so the only way the caller learns their
    value moved is this line."""
    path = tmp_path / "loud.spec.json"
    path.write_text(json.dumps(spec_payload(voices=[{"waveform": "sine", "pan": 4.0}])))

    assert main(["render", str(path), "--out-dir", str(tmp_path)]) == 0
    assert "warning" in capsys.readouterr().out


# --- Failures are messages, not tracebacks ------------------------------------


def test_an_invalid_spec_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "bad.spec.json"
    path.write_text(json.dumps(spec_payload(voices=[{"waveform": "kazoo"}])))

    assert main(["render", str(path), "--out-dir", str(tmp_path)]) == 1

    captured = capsys.readouterr()
    assert "kazoo" in captured.err
    assert "sine" in captured.err, "the valid values belong in the message"
    assert not list(tmp_path.glob("*.wav"))


def test_malformed_json_is_a_message_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "broken.spec.json"
    path.write_text("{not json")

    assert main(["render", str(path), "--out-dir", str(tmp_path)]) == 1

    error = capsys.readouterr().err
    assert "malformed JSON" in error
    assert "Traceback" not in error


def test_a_missing_file_is_a_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["render", str(tmp_path / "nope.spec.json")]) == 1
    assert "cannot read" in capsys.readouterr().err


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unwritable_out_dir_exits_nonzero(
    spec_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert main(["render", str(spec_file), "--out-dir", str(locked)]) == 1
        assert "permission" in capsys.readouterr().err.lower()
    finally:
        locked.chmod(0o700)


# --- batch --------------------------------------------------------------------


@pytest.fixture
def batch_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "specs"
    folder.mkdir()
    for name in ("one", "two"):
        (folder / f"{name}.spec.json").write_text(
            json.dumps(spec_payload(meta={"name": name})), encoding="utf-8"
        )
    return folder


def test_batch_renders_every_valid_spec_and_reports_the_broken_one(
    batch_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """One bad file must not cost the caller the other forty-nine renders."""
    (batch_dir / "broken.spec.json").write_text(
        json.dumps(spec_payload(voices=[{"waveform": "kazoo"}], meta={"name": "broken"}))
    )
    out_dir = tmp_path / "out"

    assert main(["batch", str(batch_dir), "--out-dir", str(out_dir)]) == 1

    printed = capsys.readouterr().out
    assert (out_dir / "one.wav").exists()
    assert (out_dir / "two.wav").exists()
    assert not (out_dir / "broken.wav").exists()
    assert "FAIL  broken.spec.json" in printed
    assert "ok    one.spec.json" in printed
    assert "2 of 3 specs rendered, 1 failed." in printed


def test_a_clean_batch_exits_zero(
    batch_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["batch", str(batch_dir), "--out-dir", str(tmp_path / "out")]) == 0
    assert "0 failed" in capsys.readouterr().out


def test_an_empty_batch_folder_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Rendering nothing successfully is the failure mode a build script would
    never notice."""
    empty = tmp_path / "empty"
    empty.mkdir()

    assert main(["batch", str(empty)]) == 1
    assert "no *.spec.json files" in capsys.readouterr().err


def test_batch_needs_a_directory(spec_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["batch", str(spec_file)]) == 1
    assert "not a directory" in capsys.readouterr().err


# --- vary ---------------------------------------------------------------------


def test_vary_emits_a_spec_and_a_wav_per_variation(spec_file: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"

    assert main(["vary", str(spec_file), "-n", "5", "--out-dir", str(out_dir)]) == 0

    assert sorted(p.name for p in out_dir.glob("*.wav")) == [f"hiss-{i}.wav" for i in range(1, 6)]
    assert len(list(out_dir.glob("*.spec.json"))) == 5


def test_variations_differ_only_in_seed_and_name(spec_file: Path, tmp_path: Path) -> None:
    """A variation is the same patch under a different seed. `meta.name` moves
    with it so each one owns its files, and the core never reads `meta`, so the
    audio still differs by seed alone."""
    out_dir = tmp_path / "out"
    main(["vary", str(spec_file), "-n", "3", "--out-dir", str(out_dir)])

    def without_identity(spec: dict[str, Any]) -> dict[str, Any]:
        stripped = {key: value for key, value in spec.items() if key != "seed"}
        stripped["meta"] = {k: v for k, v in stripped["meta"].items() if k != "name"}
        return stripped

    loaded = [
        json.loads((out_dir / f"hiss-{index}.spec.json").read_text()) for index in range(1, 4)
    ]
    seeds = [spec["seed"] for spec in loaded]

    assert seeds == [8, 9, 10], "seeds walk up from the spec's own seed of 7"
    assert len({json.dumps(without_identity(spec), sort_keys=True) for spec in loaded}) == 1


def test_each_variation_re_renders_from_its_own_sidecar(spec_file: Path, tmp_path: Path) -> None:
    """Each variation is a committed asset in its own right, so its sidecar has
    to regenerate it with no arguments beyond the file."""
    out_dir = tmp_path / "out"
    again = tmp_path / "again"
    main(["vary", str(spec_file), "-n", "3", "--out-dir", str(out_dir)])

    for index in range(1, 4):
        sidecar = out_dir / f"hiss-{index}.spec.json"
        assert main(["render", str(sidecar), "--out-dir", str(again)]) == 0

        original = (out_dir / f"hiss-{index}.wav").read_bytes()
        assert (again / f"hiss-{index}.wav").read_bytes() == original


def test_variations_are_different_sounds(spec_file: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    main(["vary", str(spec_file), "-n", "4", "--out-dir", str(out_dir)])

    rendered = {samples_of(out_dir / f"hiss-{index}.wav") for index in range(1, 5)}

    assert len(rendered) == 4, "four variations should be four sounds"


def test_vary_needs_at_least_one_variation(
    spec_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["vary", str(spec_file), "-n", "0"]) == 1
    assert "at least 1" in capsys.readouterr().err


def test_vary_defaults_to_five(spec_file: Path, tmp_path: Path) -> None:
    assert main(["vary", str(spec_file), "--out-dir", str(tmp_path / "out")]) == 0
    assert len(list((tmp_path / "out").glob("*.wav"))) == 5


# --- explain ------------------------------------------------------------------


def test_explain_prints_the_explanation(
    spec_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["explain", str(spec_file)]) == 0

    printed = capsys.readouterr().out
    assert "white noise" in printed
    assert "200 ms" in printed


def test_explain_writes_no_audio(spec_file: Path, tmp_path: Path) -> None:
    """It describes what the spec asks for, which needs no render at all."""
    assert main(["explain", str(spec_file)]) == 0

    assert not (tmp_path / "default-out").exists()
    assert not list(tmp_path.rglob("*.wav"))


def test_explain_is_deterministic(spec_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["explain", str(spec_file)])
    first = capsys.readouterr().out
    main(["explain", str(spec_file)])

    assert capsys.readouterr().out == first


# --- presets ------------------------------------------------------------------
#
# Added in B13, on the note B11 left: the library was reachable from Python and
# from MCP, but a human at a terminal had to know the path inside the installed
# package to start from one. The README documents this surface, so it ships.


def test_presets_lists_the_whole_catalogue(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["presets"]) == 0

    printed = capsys.readouterr().out
    for preset in list_presets():
        assert preset.name in printed
        assert preset.description in printed


def test_presets_shows_both_families(capsys: pytest.CaptureFixture[str]) -> None:
    """A catalogue that lost its drum kit should not read as complete."""
    main(["presets"])
    printed = capsys.readouterr().out

    assert "sfx" in printed
    assert "drum" in printed


def test_render_from_a_preset_writes_the_same_bytes_as_the_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--preset laser` has to be the shipped laser, not a CLI-local copy of it."""
    out = tmp_path / "out"
    assert main(["render", "--preset", "laser", "--out-dir", str(out)]) == 0
    capsys.readouterr()

    direct = render(load_preset("laser").model_dump(mode="json"), out_dir=tmp_path / "direct")

    assert direct.wavPath is not None
    assert (out / "laser.wav").read_bytes() == Path(direct.wavPath).read_bytes()


def test_a_preset_render_re_renders_from_its_own_sidecar(tmp_path: Path) -> None:
    out = tmp_path / "out"
    main(["render", "--preset", "kick", "--out-dir", str(out)])

    again = tmp_path / "again"
    assert main(["render", str(out / "kick.spec.json"), "--out-dir", str(again)]) == 0
    assert (out / "kick.wav").read_bytes() == (again / "kick.wav").read_bytes()


def test_a_preset_render_still_honours_the_seed_override(tmp_path: Path) -> None:
    seeded = tmp_path / "seeded"
    plain = tmp_path / "plain"
    main(["render", "--preset", "snare", "--out-dir", str(plain)])
    main(["render", "--preset", "snare", "--seed", "99", "--out-dir", str(seeded)])

    # The snare is noise, so a different seed has to reach the audio.
    assert (plain / "snare.wav").read_bytes() != (seeded / "snare.wav").read_bytes()


def test_an_unknown_preset_names_the_valid_ones(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["render", "--preset", "trombone"]) == 1

    printed = capsys.readouterr().err
    assert "trombone" in printed
    assert "laser" in printed


def test_a_preset_and_a_spec_file_together_are_refused(
    spec_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two sources of truth for one render is the ambiguity worth refusing:
    silently picking one would render something the caller did not ask for."""
    assert main(["render", str(spec_file), "--preset", "laser"]) == 1
    assert "--preset" in capsys.readouterr().err


def test_render_with_neither_a_spec_nor_a_preset_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["render"]) == 1
    assert "--preset" in capsys.readouterr().err


# --- verify-golden ------------------------------------------------------------


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    copy = tmp_path / "golden"
    shutil.copytree(GOLDEN, copy)
    return copy


def test_verify_golden_passes_on_the_committed_corpus(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Against the real corpus, not a copy: this is the command a maintainer
    runs before a release."""
    assert main(["verify-golden", str(GOLDEN)]) == 0

    printed = capsys.readouterr().out
    assert "0 to look at" in printed
    assert "MISMATCH" not in printed


def test_verify_golden_fails_on_a_tampered_hash(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hashes = json.loads((corpus / "hashes.json").read_text())
    hashes["sine-440.spec.json"] = "0" * 64
    (corpus / "hashes.json").write_text(json.dumps(hashes, indent=2, sort_keys=True))

    assert main(["verify-golden", str(corpus)]) == 1

    printed = capsys.readouterr().out
    assert "MISMATCH  sine-440.spec.json" in printed
    assert "match     saw-110.spec.json" in printed, "the others still report per file"


def test_verify_golden_fails_on_a_spec_with_no_recorded_hash(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(corpus / "specs" / "sine-440.spec.json", corpus / "specs" / "newcomer.spec.json")

    assert main(["verify-golden", str(corpus)]) == 1
    assert "UNKNOWN   newcomer.spec.json" in capsys.readouterr().out


def test_verify_golden_reports_a_hash_whose_spec_is_gone(
    corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A hash with no spec is never checked by anything, so it sits in the file
    looking like coverage."""
    (corpus / "specs" / "sine-440.spec.json").unlink()

    assert main(["verify-golden", str(corpus)]) == 1
    assert "ORPHAN    sine-440.spec.json" in capsys.readouterr().out


def test_verify_golden_needs_a_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["verify-golden", str(tmp_path)]) == 1
    assert "no golden specs" in capsys.readouterr().err


# --- The command surface itself -----------------------------------------------


def test_help_exits_zero_and_lists_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    """`blipsmith --help` is the verify gate's boot check, so a nonzero exit
    here fails the whole gate."""
    with pytest.raises(SystemExit) as raised:
        main(["--help"])

    assert raised.value.code == 0
    printed = capsys.readouterr().out
    for command in COMMANDS:
        assert command in printed


def test_every_command_is_wired_to_a_handler() -> None:
    for command in COMMANDS:
        positional = [] if command in COMMANDS_WITHOUT_A_POSITIONAL else ["x"]
        args = build_parser().parse_args([command, *positional])
        assert callable(args.handler)


def test_no_command_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as raised:
        main([])

    assert raised.value.code == 2


def test_the_console_script_is_installed() -> None:
    """In process the CLI is just a function; the entry point is what a user
    actually types, and it can break on its own."""
    executable = shutil.which("blipsmith")
    if executable is None:
        pytest.skip("console script not on PATH in this environment")

    result = subprocess.run([executable, "--help"], capture_output=True, text=True, check=False)

    assert result.returncode == 0
    assert "verify-golden" in result.stdout


def test_the_verify_gate_boots_the_cli() -> None:
    """B01 left the gate's CLI step conditional on this module existing. Landing
    it is what turns that skip into a real check."""
    assert importlib.util.find_spec("blipsmith.cli") is not None
    assert "blipsmith --help" in VERIFY.read_text()


# --- No core, no fallback -----------------------------------------------------


_BLOCK_CORE = """
import sys
from importlib.abc import MetaPathFinder


class _BlockCore(MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "blipsmith._core":
            raise ModuleNotFoundError("simulated: core not built", name="blipsmith._core")
        return None


sys.meta_path.insert(0, _BlockCore())

from blipsmith.cli import main

raise SystemExit(main(["--help"]))
"""


def test_the_cli_fails_fast_without_the_native_core() -> None:
    """Every command, including the ones that do not render: there is no build
    of this tool that works without the core, and pretending otherwise would
    hand someone a WAV that is not the one their spec describes."""
    result = subprocess.run(
        [sys.executable, "-c", _BLOCK_CORE], capture_output=True, text=True, check=False
    )

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "uv sync --reinstall-package blipsmith" in combined
    assert "no pure-Python fallback" in combined
