"""B13: the README, executed rather than proof-read.

The acceptance is "followed verbatim by a new user, both loops complete". Prose
rots quietly: a flag gets renamed, a tool gets dropped, and the README keeps
looking right for a year. So the CLI example is lifted out of the file and run,
its printed output compared against the block the README promises, and every MCP
tool the transcript names is checked against the server's published list.

What this cannot test is the shape of a session, which is why the transcript
stays a transcript. The names in it are real, and that is the part that breaks.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from blipsmith.cli import build_parser, main
from blipsmith.mcp_server import build_server
from blipsmith.presets import preset_names

README = Path(__file__).resolve().parents[1] / "README.md"


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def documented_spec() -> str:
    """The spec the README tells a new user to write, taken from its heredoc."""
    block = re.search(r"<<'JSON'\n(.*?)\nJSON\n", readme_text(), re.S)
    assert block is not None, "the CLI loop should still write its spec with a heredoc"
    return block.group(1)


def documented_output() -> list[str]:
    """The lines the README promises `blipsmith render` prints back."""
    block = re.search(r"```\n(blipsmith-out/blip\.wav\n.*?)```", readme_text(), re.S)
    assert block is not None, "the CLI loop should still show what the render prints"
    return block.group(1).strip().splitlines()


def published_tools() -> set[str]:
    return {tool.name for tool in asyncio.run(build_server().list_tools())}


# --- Loop 2, run verbatim -----------------------------------------------------


def test_the_documented_spec_is_valid_json() -> None:
    parsed = json.loads(documented_spec())

    assert parsed["version"] == 1


def test_the_cli_loop_runs_exactly_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Write the file the README writes, run the command it runs, from a fresh
    directory with no environment set: what a new user has."""
    monkeypatch.delenv("BLIPSMITH_OUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "blip.spec.json").write_text(documented_spec(), encoding="utf-8")

    assert main(["render", "blip.spec.json"]) == 0

    printed = capsys.readouterr().out.strip().splitlines()
    assert printed == documented_output(), "the README no longer shows what the tool prints"


def test_the_documented_render_lands_where_the_readme_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("BLIPSMITH_OUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "blip.spec.json").write_text(documented_spec(), encoding="utf-8")

    main(["render", "blip.spec.json"])
    capsys.readouterr()

    assert (tmp_path / "blipsmith-out" / "blip.wav").is_file()
    assert (tmp_path / "blipsmith-out" / "blip.spec.json").is_file()


def test_the_sidecar_the_readme_promises_reproduces_the_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The README's central claim about the CLI: render the sidecar and you get
    the same WAV back, byte for byte."""
    monkeypatch.delenv("BLIPSMITH_OUT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "blip.spec.json").write_text(documented_spec(), encoding="utf-8")
    main(["render", "blip.spec.json"])

    main(["render", "blipsmith-out/blip.spec.json", "--out-dir", "again"])
    capsys.readouterr()

    assert (tmp_path / "blipsmith-out" / "blip.wav").read_bytes() == (
        tmp_path / "again" / "blip.wav"
    ).read_bytes()


DOCUMENTED_COMMANDS = [
    ["presets"],
    ["render", "--preset", "kick"],
    ["vary", "blip.spec.json", "-n", "5"],
    ["batch", "sounds/"],
    ["explain", "blip.spec.json"],
    ["verify-golden"],
]


@pytest.mark.parametrize("argv", DOCUMENTED_COMMANDS, ids=lambda argv: str(argv[0]))
def test_every_command_the_readme_lists_still_parses(argv: list[str]) -> None:
    """The command table is the second thing a reader copies. A flag renamed out
    from under it fails here rather than in their terminal."""
    assert f"blipsmith {' '.join(argv)}" in readme_text()

    assert callable(build_parser().parse_args(argv).handler)


# --- Loop 1, checked where it can be ------------------------------------------


def documented_tools() -> set[str]:
    """Every `tool_name(` in the transcript block. A renamed tool has to show up
    here as a failure, not as a reader's confusion."""
    transcript = re.search(r"```\n(list_presets\(\).*?)```", readme_text(), re.S)
    assert transcript is not None, "the MCP loop should still show a transcript"
    return set(re.findall(r"([a-z_]+)\(", transcript.group(1)))


def test_every_tool_the_transcript_names_is_published() -> None:
    published = published_tools()

    assert documented_tools() <= published, documented_tools() - published


def test_the_readme_reports_the_real_tool_count() -> None:
    quoted = re.search(r"(\d+) tools", readme_text())

    assert quoted is not None, "the README should say how big the control surface is"
    assert int(quoted.group(1)) == len(published_tools())


def test_the_readme_reports_the_real_preset_count() -> None:
    quoted = re.findall(r"(\d+) presets", readme_text())

    assert quoted, "the README should say how many presets ship"
    assert {int(value) for value in quoted} == {len(preset_names())}


def test_the_readme_names_the_preset_the_transcript_loads() -> None:
    assert "laser" in preset_names()


# --- Install and license claims -----------------------------------------------


def test_the_install_instructions_name_the_real_commands() -> None:
    text = readme_text()

    assert "uv sync" in text
    assert "uv sync --reinstall-package blipsmith" in text
    assert "./scripts/verify.sh" in text


def test_the_license_section_lists_what_is_actually_shipped() -> None:
    """CLAUDE.md and the PRD both say "all deps MIT/BSD", which stopped being
    true when the MCP SDK arrived. The README is the public claim, so it has to
    name the licenses that are really in the tree."""
    text = readme_text().lower()

    for dependency in ("pydantic", "mcp", "certifi", "python-multipart", "typing-extensions"):
        assert dependency in text
    for licence in ("mit", "mpl-2.0", "apache-2.0", "psf-2.0", "bsd-3"):
        assert licence in text


def test_the_readme_states_the_determinism_contract() -> None:
    text = readme_text()

    assert "linux x86_64" in text.lower()
    assert "macos arm64" in text.lower()
    assert "libm" in text
