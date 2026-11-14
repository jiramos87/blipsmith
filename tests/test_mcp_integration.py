"""B12: the MCP server, driven the way the agent drives it.

Every test here goes over the SDK's in-memory transport rather than calling the
session directly, because the contract being checked is the wire one: tool
names, published input schemas, and the shape of what comes back. A session
method that works but is not reachable as a tool is not the feature.

The scenarios read as sessions on purpose, several calls at a time. That is how
the instrument is actually played, and most of the interesting failures (a
refusal that quietly ate the previous edit, a setter that reset three fields it
was not asked about) only appear in sequence.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import Tool

from blipsmith.cli import main as cli_main
from blipsmith.mcp_server import build_server
from blipsmith.presets import preset_names
from blipsmith.schema import get_schema
from blipsmith.session import Session

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY = REPO_ROOT / "scripts" / "verify.sh"

SESSION_TOOLS = (
    "new_voice",
    "select_voice",
    "remove_voice",
    "set_waveform",
    "set_fundamental",
    "set_adsr",
    "set_mod_env",
    "set_lfo",
    "set_fm",
    "set_am",
    "set_filter",
    "set_lofi",
    "set_effects",
    "set_voice_output",
    "set_master",
    "set_tempo_swing",
    "set_track",
    "add_notes",
    "set_steps",
    "clear_track",
    # docs/prd/blipsmith-music-mode.md
    "add_track",
    "remove_track",
    "set_render_options",
    "render",
    "export_spec",
    "import_spec",
    "explain_session",
    # docs/prd/blipsmith-expressive-notes.md
    "set_touch",
    "set_glide",
    "set_vibrato",
)
STATELESS_TOOLS = ("render_spec", "get_schema", "list_presets", "load_preset", "explain_spec")
PINNED_TOOLS = (*SESSION_TOOLS, *STATELESS_TOOLS)


# --- Driving the server -------------------------------------------------------


class Mcp:
    """A connected client, plus the bookkeeping the coverage test needs."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self.called: set[str] = set()

    # The tool name is positional-only: several tools take a `name` argument of
    # their own, and a keyword parameter here would swallow it.
    async def call(self, tool: str, /, **arguments: Any) -> dict[str, Any]:
        result = await self._client.call_tool(tool, arguments)
        self.called.add(tool)
        assert not result.isError, f"{tool} failed at the transport: {result.content}"
        assert result.structuredContent is not None, f"{tool} returned no structured content"
        return dict(result.structuredContent)

    async def call_raw(self, tool: str, /, **arguments: Any) -> Any:
        self.called.add(tool)
        return await self._client.call_tool(tool, arguments)

    async def tools(self) -> list[Tool]:
        listing = await self._client.list_tools()
        return list(listing.tools)

    async def spec(self) -> dict[str, Any]:
        exported = await self.call("export_spec")
        return dict(exported["spec"])


def play(scenario: Callable[[Mcp], Awaitable[None]], session: Session | None = None) -> None:
    """Run one scenario against a fresh instrument."""

    async def go() -> None:
        server = build_server(session if session is not None else Session())
        async with create_connected_server_and_client_session(server) as client:
            await scenario(Mcp(client))

    asyncio.run(go())


async def a_playable_voice(mcp: Mcp) -> None:
    """The two calls every editing scenario starts with."""
    await mcp.call("new_voice", waveform="sine")
    await mcp.call("set_fundamental", hz=440.0)


# --- The published surface ----------------------------------------------------


def test_every_pinned_tool_is_published_with_a_schema() -> None:
    """The quality bar: an agent discovers this server entirely from list_tools,
    so a tool without a description or an input schema is unusable."""

    async def scenario(mcp: Mcp) -> None:
        published = {tool.name: tool for tool in await mcp.tools()}

        assert set(published) == set(PINNED_TOOLS)
        for name, tool in published.items():
            assert tool.inputSchema.get("type") == "object", f"{name} publishes no input schema"
            assert tool.description, f"{name} has no description"

    play(scenario)


def test_a_setter_publishes_its_parameters() -> None:
    """Spot-check that the schema carries the actual knobs rather than a blob."""

    async def scenario(mcp: Mcp) -> None:
        published = {tool.name: tool for tool in await mcp.tools()}
        adsr = published["set_adsr"].inputSchema["properties"]

        assert set(adsr) == {"attackMs", "decayMs", "sustainLevel", "releaseMs"}

    play(scenario)


# --- Reading the contract -----------------------------------------------------


def test_a_fresh_session_can_read_the_whole_contract() -> None:
    """`get_schema` is the first call an agent makes, and it has to be enough to
    author a valid spec without guessing."""

    async def scenario(mcp: Mcp) -> None:
        result = await mcp.call("get_schema")

        assert result["schema"] == json.loads(json.dumps(get_schema()))
        assert "SoundSpec" in result["schema"]["models"]

    play(scenario)


def test_the_preset_catalogue_comes_from_the_registry() -> None:
    async def scenario(mcp: Mcp) -> None:
        result = await mcp.call("list_presets")

        assert [entry["name"] for entry in result["presets"]] == preset_names()
        assert all(entry["description"] and entry["tags"] for entry in result["presets"])

    play(scenario)


# --- The main loop: load, edit, render ----------------------------------------


def test_a_preset_edited_and_rendered_comes_back_with_feedback(tmp_path: Path) -> None:
    """The acceptance path, end to end: an agent starts from an authored sound,
    turns four knob groups, and renders. What comes back has to be enough to
    decide the next move without hearing anything."""

    async def scenario(mcp: Mcp) -> None:
        assert (await mcp.call("load_preset", name="laser"))["status"] == "ok"
        await mcp.call("set_adsr", attackMs=0.0, decayMs=120.0)
        await mcp.call("set_fm", ratio=3.0, index=6.0)
        await mcp.call("set_filter", cutoffHz=3200.0)
        await mcp.call("set_lofi", bitDepth=6)

        result = await mcp.call("render", outDir=str(tmp_path))

        assert result["status"] == "rendered_ok"
        assert Path(result["wavPath"]).exists()
        assert Path(result["specPath"]).exists()
        assert result["explanation"]
        assert set(result["features"]) == {
            "durationMs",
            "peakDbfs",
            "rmsDbfs",
            "estimatedFundamentalHz",
            "spectralCentroidHz",
            "attackTimeMs",
            "integratedLufs",
            "truePeakDbtp",
        }
        assert all(value is not None for value in result["features"].values())

    play(scenario)


def test_edits_accumulate_across_calls(tmp_path: Path) -> None:
    """One session per process: the second call sees what the first one did."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        await mcp.call("set_adsr", attackMs=25.0)
        await mcp.call("set_adsr", releaseMs=90.0)

        voice = (await mcp.spec())["voices"][0]

        assert voice["ampEnv"]["attackMs"] == 25.0
        assert voice["ampEnv"]["releaseMs"] == 90.0
        assert voice["fundamentalHz"] == 440.0

    play(scenario)


def test_a_setter_moves_only_what_it_was_given() -> None:
    """Patch semantics. An agent adjusting the attack must not silently lose the
    decay it set three calls ago, and it cannot hear that it did."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        await mcp.call("set_adsr", attackMs=10.0, decayMs=200.0, sustainLevel=0.3, releaseMs=50.0)
        await mcp.call("set_adsr", attackMs=1.0)

        envelope = (await mcp.spec())["voices"][0]["ampEnv"]

        assert envelope == {
            "attackMs": 1.0,
            "decayMs": 200.0,
            "sustainLevel": 0.3,
            "releaseMs": 50.0,
        }

    play(scenario)


def test_two_servers_do_not_share_a_session() -> None:
    """One implicit session per server process, so a second instrument starts
    empty rather than inheriting the first one's patch."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        assert len((await mcp.spec())["voices"]) == 1

    play(scenario)

    async def fresh(mcp: Mcp) -> None:
        assert (await mcp.spec())["voices"] == []

    play(fresh)


# --- Clamping and refusal -----------------------------------------------------


def test_an_out_of_range_setter_clamps_and_says_so() -> None:
    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        result = await mcp.call("set_voice_output", pan=4.0)

        assert result["status"] == "ok"
        assert len(result["warnings"]) == 1
        warning = result["warnings"][0]
        assert warning["code"] == "clamped"
        assert warning["requested"] == 4.0
        assert warning["applied"] == 1.0
        assert (await mcp.spec())["voices"][0]["pan"] == 1.0

    play(scenario)


def test_an_in_range_setter_warns_about_nothing() -> None:
    """The other side of the bound: warnings mean something only if they are
    absent when nothing moved."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        result = await mcp.call("set_voice_output", pan=0.5)

        assert result["warnings"] == []

    play(scenario)


def test_an_unknown_enum_is_refused_and_changes_nothing() -> None:
    """A structural refusal has to leave the session exactly as it was, or an
    agent recovering from it would be editing a spec it cannot see."""

    async def scenario(mcp: Mcp) -> None:
        await mcp.call("new_voice", waveform="square")
        before = await mcp.spec()

        result = await mcp.call("set_waveform", waveform="kazoo")

        assert result["status"] == "invalid_spec"
        assert result["error"]["validValues"] is not None
        assert "sine" in result["error"]["validValues"]
        assert await mcp.spec() == before

    play(scenario)


def test_the_ninth_voice_is_refused_and_the_first_eight_survive() -> None:
    async def scenario(mcp: Mcp) -> None:
        for _ in range(8):
            assert (await mcp.call("new_voice", waveform="sine"))["status"] == "ok"

        result = await mcp.call("new_voice", waveform="sine")

        assert result["status"] == "invalid_spec"
        assert "8" in result["error"]["message"]
        assert len((await mcp.spec())["voices"]) == 8

    play(scenario)


def test_editing_with_no_voice_selected_is_a_typed_error() -> None:
    """And the other side: the same call works the moment a voice exists."""

    async def scenario(mcp: Mcp) -> None:
        refused = await mcp.call("set_adsr", attackMs=5.0)
        assert refused["status"] == "invalid_spec"
        assert "new_voice" in refused["error"]["message"]

        await mcp.call("new_voice", waveform="sine")
        assert (await mcp.call("set_adsr", attackMs=5.0))["status"] == "ok"

    play(scenario)


def test_a_block_needs_its_target_the_first_time_only() -> None:
    """A filter with no type has no default worth guessing, but once the voice
    has one, `set_filter` patches like every other setter."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)

        refused = await mcp.call("set_filter", cutoffHz=800.0)
        assert refused["status"] == "invalid_spec"
        assert "lowpass" in refused["error"]["validValues"]

        assert (await mcp.call("set_filter", type="lowpass", cutoffHz=800.0))["status"] == "ok"
        assert (await mcp.call("set_filter", resonance=4.0))["status"] == "ok"

        voice_filter = (await mcp.spec())["voices"][0]["filter"]
        assert voice_filter == {"type": "lowpass", "cutoffHz": 800.0, "resonance": 4.0}

    play(scenario)


def test_setting_pitch_one_way_clears_the_other() -> None:
    """A stale MIDI note would win over the hertz just set, and the agent would
    hear nothing change: it cannot hear at all."""

    async def scenario(mcp: Mcp) -> None:
        await mcp.call("new_voice", waveform="sine")
        await mcp.call("set_fundamental", midi=60)
        assert (await mcp.spec())["voices"][0]["fundamentalMidi"] == 60

        await mcp.call("set_fundamental", hz=880.0)
        voice = (await mcp.spec())["voices"][0]
        assert voice["fundamentalHz"] == 880.0
        assert voice["fundamentalMidi"] is None

        both = await mcp.call("set_fundamental", hz=440.0, midi=69)
        assert both["status"] == "invalid_spec"
        neither = await mcp.call("set_fundamental")
        assert neither["status"] == "invalid_spec"

    play(scenario)


def test_a_wrong_argument_type_is_an_error_at_the_transport() -> None:
    """The SDK validates against the published schema before the tool runs, so a
    string where a number belongs never reaches the spec layer."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        result = await mcp.call_raw("set_adsr", attackMs="quickly")

        assert result.isError

    play(scenario)


# --- Voice selection ----------------------------------------------------------


def test_the_selection_follows_the_voice_it_was_on() -> None:
    """Removing an earlier voice renumbers the others; the agent's selection has
    to survive that or its next edit lands on a different sound."""

    async def scenario(mcp: Mcp) -> None:
        for waveform in ("sine", "square", "saw"):
            await mcp.call("new_voice", waveform=waveform)
        await mcp.call("select_voice", index=2)

        await mcp.call("remove_voice", index=0)
        await mcp.call("set_waveform", waveform="triangle")

        waveforms = [voice["waveform"] for voice in (await mcp.spec())["voices"]]
        assert waveforms == ["square", "triangle"], "the saw was still the selected voice"

    play(scenario)


def test_selecting_a_voice_that_is_not_there_is_refused() -> None:
    async def scenario(mcp: Mcp) -> None:
        await mcp.call("new_voice", waveform="sine")

        assert (await mcp.call("select_voice", index=5))["status"] == "invalid_spec"
        assert (await mcp.call("select_voice", index=0))["status"] == "ok"

    play(scenario)


# --- Composition --------------------------------------------------------------


def test_starting_a_composition_switches_the_render_to_stereo() -> None:
    """The documented default for a composition, applied where an agent would
    otherwise have to know to ask for it."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        assert (await mcp.spec())["channels"] == 1

        await mcp.call("set_tempo_swing", tempoBpm=96.0, swing=0.25)
        assert (await mcp.spec())["channels"] == 2

        await mcp.call("set_render_options", channels=1)
        await mcp.call("set_tempo_swing", tempoBpm=100.0)
        assert (await mcp.spec())["channels"] == 1, "an explicit choice must stick"

    play(scenario)


def test_a_track_can_be_played_notes_painted_and_cleared() -> None:
    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        await mcp.call("set_tempo_swing", tempoBpm=120.0)
        await mcp.call("set_track", track=0, gainDb=-3.0, pan=-0.5)
        await mcp.call("add_notes", track=0, notes=[{"startBeat": 0.0, "midiNote": 60}])
        await mcp.call("add_notes", track=0, notes=[{"startBeat": 1.0, "midiNote": 64}])

        track = (await mcp.spec())["composition"]["tracks"][0]
        assert len(track["notes"]) == 2, "add_notes appends rather than replacing"
        assert track["gainDb"] == -3.0

        await mcp.call("set_steps", track=1, steps=[{"index": 0}, {"index": 2}], stepsPerBeat=4)
        assert len((await mcp.spec())["composition"]["tracks"][1]["steps"]) == 2

        await mcp.call("clear_track", track=0)
        assert (await mcp.spec())["composition"]["tracks"][0]["notes"] == []

    play(scenario)


def test_a_track_that_does_not_exist_is_refused() -> None:
    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)

        refused = await mcp.call("set_track", track=9, gainDb=0.0)
        assert refused["status"] == "invalid_spec"
        assert "5 tracks" in refused["error"]["message"]

        assert (await mcp.call("set_track", track=4, gainDb=0.0))["status"] == "ok"

    play(scenario)


def test_a_note_past_the_end_is_reported_by_the_render(tmp_path: Path) -> None:
    """The composition warnings reach the agent where it can act on them: in the
    render result, since that is the call that decides what got played."""

    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        await mcp.call("set_render_options", durationMs=1000.0, name="short")
        await mcp.call("set_tempo_swing", tempoBpm=120.0)
        await mcp.call("add_notes", track=0, notes=[{"startBeat": 0.0}, {"startBeat": 40.0}])

        result = await mcp.call("render", outDir=str(tmp_path))

        assert result["status"] == "rendered_with_warnings"
        assert [w["code"] for w in result["warnings"]] == ["note_beyond_end_dropped"]

    play(scenario)


# --- Export, import, explain --------------------------------------------------


def test_the_exported_spec_renders_the_same_bytes_through_the_cli(tmp_path: Path) -> None:
    """Lossless serialization, checked the way it will actually be used: the
    agent exports, a human commits the file and renders it later."""

    async def scenario(mcp: Mcp) -> None:
        await mcp.call("load_preset", name="kick")
        await mcp.call("set_adsr", decayMs=90.0)
        await mcp.call("set_fm", ratio=1.5, index=4.0)
        await mcp.call("set_render_options", name="thump")

        rendered = await mcp.call("render", outDir=str(tmp_path / "session"))
        exported = await mcp.call("export_spec")

        committed = tmp_path / "thump.spec.json"
        committed.write_text(exported["specJson"], encoding="utf-8")

        assert cli_main(["render", str(committed), "--out-dir", str(tmp_path / "cli")]) == 0
        assert (tmp_path / "cli" / "thump.wav").read_bytes() == Path(
            rendered["wavPath"]
        ).read_bytes()

    play(scenario)


def test_import_adopts_a_spec_as_an_object_or_as_text() -> None:
    """Both spellings an agent might reach for. JSON text arrives as an object
    when it parses (the SDK unwraps it) and as text when it does not, which is
    exactly the case that has to produce a typed error rather than a crash."""

    async def scenario(mcp: Mcp) -> None:
        spec = {
            "version": 1,
            "durationMs": 300.0,
            "voices": [{"waveform": "saw", "fundamentalHz": 110.0}],
        }

        assert (await mcp.call("import_spec", spec=spec))["status"] == "ok"
        assert (await mcp.spec())["voices"][0]["waveform"] == "saw"

        assert (await mcp.call("import_spec", spec=json.dumps(spec)))["status"] == "ok"
        assert (await mcp.spec())["durationMs"] == 300.0

    play(scenario)


@pytest.mark.parametrize(
    "value",
    [{"version": 2, "voices": []}, "{not json", {"voices": [{"waveform": "kazoo"}]}],
    ids=["unsupported-version", "malformed-json", "unknown-enum"],
)
def test_a_bad_import_leaves_the_session_alone(value: Any) -> None:
    async def scenario(mcp: Mcp) -> None:
        await mcp.call("new_voice", waveform="triangle")
        before = await mcp.spec()

        result = await mcp.call("import_spec", spec=value)

        assert result["status"] == "invalid_spec"
        assert await mcp.spec() == before

    play(scenario)


def test_the_session_explains_itself_without_rendering() -> None:
    async def scenario(mcp: Mcp) -> None:
        await mcp.call("new_voice", waveform="noise_pink")
        result = await mcp.call("explain_session")

        assert "pink noise" in result["explanation"]

    play(scenario)


def test_a_spec_can_be_explained_and_rendered_without_touching_the_session(
    tmp_path: Path,
) -> None:
    """The stateless half: an agent checking an idea must not lose its patch."""

    async def scenario(mcp: Mcp) -> None:
        await mcp.call("new_voice", waveform="square")
        before = await mcp.spec()

        other = {
            "version": 1,
            "durationMs": 120.0,
            "voices": [{"waveform": "saw"}],
            "meta": {"name": "aside"},
        }
        explained = await mcp.call("explain_spec", spec=other)
        rendered = await mcp.call("render_spec", spec=other, outDir=str(tmp_path))

        assert "bright saw" in explained["explanation"]
        assert rendered["status"] == "rendered_ok"
        assert Path(rendered["wavPath"]).name == "aside.wav"
        assert await mcp.spec() == before

    play(scenario)


def test_an_unknown_preset_lists_the_valid_names() -> None:
    async def scenario(mcp: Mcp) -> None:
        await mcp.call("new_voice", waveform="sine")
        before = await mcp.spec()

        result = await mcp.call("load_preset", name="lazer")

        assert result["status"] == "invalid_spec"
        assert result["error"]["validValues"] == preset_names()
        assert await mcp.spec() == before

    play(scenario)


def test_render_refuses_to_replace_a_file_then_agrees(tmp_path: Path) -> None:
    async def scenario(mcp: Mcp) -> None:
        await a_playable_voice(mcp)
        await mcp.call("set_render_options", name="once")

        assert (await mcp.call("render", outDir=str(tmp_path)))["status"] == "rendered_ok"

        refused = await mcp.call("render", outDir=str(tmp_path))
        assert refused["status"] == "render_failed"
        assert "refusing to overwrite" in refused["error"]["message"]

        again = await mcp.call("render", outDir=str(tmp_path), overwrite=True)
        assert again["status"] == "rendered_ok"

    play(scenario)


# --- Every pinned tool, once --------------------------------------------------


def test_every_pinned_tool_is_exercised(tmp_path: Path) -> None:
    """The quality bar asks for at least one integration test per tool. This is
    that sweep, and it doubles as the check that the whole surface still works
    in sequence rather than only in isolation."""

    async def scenario(mcp: Mcp) -> None:
        await mcp.call("get_schema")
        await mcp.call("list_presets")
        await mcp.call("load_preset", name="snare")
        await mcp.call("new_voice", waveform="pulse")
        await mcp.call("select_voice", index=0)
        await mcp.call("set_waveform", waveform="pulse", pulseDuty=0.3)
        await mcp.call("set_fundamental", midi=57)
        await mcp.call("set_adsr", attackMs=2.0, decayMs=140.0)
        await mcp.call("set_mod_env", target="pitch", amount=-0.4, decayMs=80.0)
        await mcp.call("set_lfo", target="amplitude", shape="triangle", rateHz=6.0, depth=0.3)
        await mcp.call("set_fm", ratio=2.0, index=4.0)
        await mcp.call("set_am", mode="ring", rateHz=90.0, depth=0.4)
        await mcp.call("set_filter", type="bandpass", cutoffHz=1500.0, resonance=2.0)
        await mcp.call("set_lofi", bitDepth=7, decimation=2)
        await mcp.call("set_effects", effects=[{"kind": "delay", "timeMs": 90.0}])
        await mcp.call("set_voice_output", pan=-0.3, mixDb=-4.0, track=1)
        await mcp.call("set_master", gainDb=-1.0, targetDbfs=-2.0)
        await mcp.call("set_render_options", durationMs=1500.0, seed=11, name="sweep")
        await mcp.call("set_tempo_swing", tempoBpm=110.0, swing=0.2)
        await mcp.call("set_track", track=1, gainDb=-2.0, pan=0.2)
        await mcp.call("add_notes", track=1, notes=[{"startBeat": 0.0, "midiNote": 60}])
        await mcp.call("set_steps", track=2, steps=[{"index": 0}], stepsPerBeat=4)
        await mcp.call("clear_track", track=2)
        await mcp.call("remove_voice", index=1)
        await mcp.call("set_render_options", version=2)
        added = await mcp.call("add_track")
        await mcp.call("remove_track", track=added["track"])
        await mcp.call("set_touch", cutoffOctaves=2.0)
        await mcp.call("set_glide", timeMs=60.0, mode="always")
        await mcp.call("set_vibrato", depthCents=15.0)
        await mcp.call("explain_session")
        await mcp.call("render", outDir=str(tmp_path))
        exported = await mcp.call("export_spec")
        await mcp.call("import_spec", spec=exported["spec"])
        await mcp.call("explain_spec", spec=exported["spec"])
        await mcp.call("render_spec", spec=exported["spec"], outDir=str(tmp_path), name="stateless")

        assert mcp.called == set(PINNED_TOOLS), f"never called: {set(PINNED_TOOLS) - mcp.called}"

    play(scenario)


# --- Booting the real process -------------------------------------------------


def test_the_boot_check_completes_a_handshake() -> None:
    """The verify gate's MCP step: the process starts, speaks MCP over stdio,
    and publishes its tools. Importing the module proves none of that."""
    result = subprocess.run(
        [sys.executable, "-m", "blipsmith.mcp_server", "--boot-check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "initialize ok" in result.stdout
    assert f"{len(PINNED_TOOLS)} tools" in result.stdout


def test_the_console_script_is_installed() -> None:
    assert shutil.which("blipsmith-mcp") is not None, "the pinned entry point is missing"


def test_the_verify_gate_boots_the_server() -> None:
    """B01 left this step conditional on the module existing; landing it turns
    the skip into a real handshake."""
    assert importlib.util.find_spec("blipsmith.mcp_server") is not None
    assert "python -m blipsmith.mcp_server --boot-check" in VERIFY.read_text()


# --- The music mode -----------------------------------------------------------


def test_a_music_session_builds_a_kit_track_with_a_room(tmp_path: Path) -> None:
    """The music mode played the way an agent would: switch it on, add a track,
    make a kit, give the track and the master a room, loop it, render stems."""

    async def scenario(mcp: Mcp) -> None:
        refused = await mcp.call("set_tempo_swing", loop=True)
        assert refused["status"] == "invalid_spec"
        assert "version=2" in refused["error"]["message"]

        await mcp.call("set_render_options", version=2, durationMs=2000.0, name="beat")
        added = await mcp.call("add_track")
        assert added["track"] == 5
        await mcp.call("new_voice", waveform="sine")
        await mcp.call("set_voice_output", track=5, key=36)
        await mcp.call("new_voice", waveform="noise_white")
        await mcp.call("set_voice_output", track=5, key=38)
        await mcp.call(
            "set_track", track=5, name="kit", effects=[{"kind": "reverb", "mixWet": 0.2}]
        )
        await mcp.call("set_master", effects=[{"kind": "delay", "timeMs": 250.0}])
        await mcp.call("set_tempo_swing", tempoBpm=120.0, loop=True)
        await mcp.call(
            "add_notes",
            track=5,
            notes=[{"startBeat": 0, "midiNote": 36}, {"startBeat": 1, "midiNote": 38}],
        )

        spec = await mcp.spec()
        assert spec["version"] == 2
        assert [v["key"] for v in spec["voices"]] == [36, 38]
        assert spec["composition"]["loop"] is True
        assert spec["composition"]["tracks"][5]["name"] == "kit"

        removal = await mcp.call("remove_track", track=5)
        assert removal["status"] == "invalid_spec"

        result = await mcp.call("render", outDir=str(tmp_path), stems=True)
        assert result["status"] == "rendered_ok"
        assert len(result["stems"]) == 6
        assert Path(result["stems"][5]["wavPath"]).name == "beat.stem-05-kit.wav"
        assert "Track 6 (kit)" in result["explanation"]

    play(scenario)
