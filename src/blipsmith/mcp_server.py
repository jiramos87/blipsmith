"""The agent's surface: blipsmith as an instrument over MCP.

The driving agent plays this the way a person plays a synthesizer in front of
them: it does not describe a sound and receive one, it turns knobs. One implicit
session per server process holds a `SoundSpec`, the grouped setters move one
block of it at a time, and `render` prints the result to disk. Nothing here
decides how a sound should be made; the agent supplies that, and this supplies
the instrument.

Two consequences shape every tool result:

- **The agent cannot hear.** Every render comes back with the six acoustic
  features and a plain-language explanation, so the next move can be reasoned
  about numerically. A tool that changed something silently would be useless.
- **A refused call must be legible.** Every tool returns a `status`, plus
  `warnings` for values that were clamped and `error` (with `validValues` where
  the field is a closed set) for what was refused. Refusals leave the session
  exactly as it was, so the agent can retry from a known state rather than
  guessing what survived.

The tools split in two. Session verbs edit and render the in-memory spec;
stateless verbs (`get_schema`, `list_presets`, `render_spec`, `explain_spec`)
answer questions and never touch it.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP

from blipsmith.explain import explain_spec as explain_text
from blipsmith.presets import list_presets as preset_catalogue
from blipsmith.render import render as render_to_files
from blipsmith.render import to_sidecar_json
from blipsmith.result import SpecError, SpecWarning
from blipsmith.schema import get_schema as schema_payload
from blipsmith.session import Session
from blipsmith.spec import parse_spec

SERVER_NAME = "blipsmith"

INSTRUCTIONS = """\
blipsmith is a deterministic lo-fi synthesizer you play like hardware: the same
spec and seed always render the same bytes, and there is no model inside it.

Start with get_schema (every field, its range, its default) or list_presets, then
either load_preset or new_voice. Grouped setters edit the selected voice one
block at a time; set_tempo_swing, add_notes, and set_steps build a five-track
composition. render writes a WAV plus the spec that regenerates it, and returns
acoustic features so you can check what you actually got. export_spec hands back
a file a human can commit and re-render byte for byte.

Out-of-range numbers clamp and tell you so in `warnings`. Unknown enum values are
refused with `validValues`, and leave the session unchanged."""


def _warnings(warnings: list[SpecWarning]) -> list[dict[str, Any]]:
    return [warning.model_dump(mode="json") for warning in warnings]


def _ok(warnings: list[SpecWarning], **extra: Any) -> dict[str, Any]:
    return {"status": "ok", "warnings": _warnings(warnings), "error": None, **extra}


def _refused(exc: SpecError) -> dict[str, Any]:
    return {
        "status": exc.error.code.value,
        "warnings": [],
        "error": exc.error.model_dump(mode="json"),
    }


def _guarded(action: Callable[[], list[SpecWarning]], **extra: Any) -> dict[str, Any]:
    """Run one session edit. A refusal becomes a typed result rather than a
    raised error, so the agent reads `validValues` instead of a stack trace."""
    try:
        warnings = action()
    except SpecError as exc:
        return _refused(exc)
    return _ok(warnings, **extra)


def build_server(session: Session | None = None) -> FastMCP:
    """The server and its one session. Taking the session as an argument is what
    lets the tests drive a fresh instrument per scenario."""
    state = session if session is not None else Session()
    server = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)

    # --- Voices ---------------------------------------------------------------

    @server.tool()
    def new_voice(waveform: str) -> dict[str, Any]:
        """Add a voice and select it. Up to 8 voices (64 in the music mode); one
        more is refused."""
        try:
            index, warnings = state.new_voice(waveform)
        except SpecError as exc:
            return _refused(exc)
        return _ok(warnings, voiceIndex=index)

    @server.tool()
    def select_voice(index: int) -> dict[str, Any]:
        """Choose which voice the setters below edit."""
        try:
            state.select_voice(index)
        except SpecError as exc:
            return _refused(exc)
        return _ok([], voiceIndex=index)

    @server.tool()
    def remove_voice(index: int) -> dict[str, Any]:
        """Delete a voice. The selection follows the voice it was on."""
        return _guarded(lambda: state.remove_voice(index), voiceIndex=state.selected_voice)

    @server.tool()
    def set_waveform(waveform: str, pulseDuty: float | None = None) -> dict[str, Any]:
        """sine, square, triangle, saw, pulse, noise_white, or noise_pink.
        `pulseDuty` is only read by pulse."""
        return _guarded(lambda: state.set_waveform(waveform, pulseDuty))

    @server.tool()
    def set_fundamental(hz: float | None = None, midi: int | None = None) -> dict[str, Any]:
        """Pitch, as hertz or as a MIDI note. Give exactly one: setting either
        clears the other, since a MIDI note wins over hertz when rendering."""
        return _guarded(lambda: state.set_fundamental(hz, midi))

    @server.tool()
    def set_adsr(
        attackMs: float | None = None,
        decayMs: float | None = None,
        sustainLevel: float | None = None,
        releaseMs: float | None = None,
    ) -> dict[str, Any]:
        """The amplitude envelope. Omitted fields keep their current value."""
        return _guarded(lambda: state.set_adsr(attackMs, decayMs, sustainLevel, releaseMs))

    @server.tool()
    def set_mod_env(
        target: str | None = None,
        amount: float | None = None,
        attackMs: float | None = None,
        decayMs: float | None = None,
    ) -> dict[str, Any]:
        """A modulation envelope routed to pitch or cutoff. A negative `amount`
        sweeps downward: -1 with a short decay is the classic laser drop.
        `target` is required the first time."""
        return _guarded(lambda: state.set_mod_env(target, amount, attackMs, decayMs))

    @server.tool()
    def set_lfo(
        target: str | None = None,
        shape: str | None = None,
        rateHz: float | None = None,
        depth: float | None = None,
    ) -> dict[str, Any]:
        """A low-frequency oscillator on pitch (vibrato), amplitude (tremolo), or
        cutoff. `target` is required the first time."""
        return _guarded(lambda: state.set_lfo(target, shape, rateHz, depth))

    @server.tool()
    def set_fm(ratio: float | None = None, index: float | None = None) -> dict[str, Any]:
        """Two-operator FM. `ratio` places the modulator against the carrier,
        `index` sets how much: higher is brighter and clangier."""
        return _guarded(lambda: state.set_fm(ratio, index))

    @server.tool()
    def set_am(
        mode: str | None = None, rateHz: float | None = None, depth: float | None = None
    ) -> dict[str, Any]:
        """Amplitude or ring modulation. `mode` is required the first time."""
        return _guarded(lambda: state.set_am(mode, rateHz, depth))

    @server.tool()
    def set_filter(
        type: str | None = None,
        cutoffHz: float | None = None,
        resonance: float | None = None,
    ) -> dict[str, Any]:
        """A resonant lowpass, highpass, or bandpass. The cutoff is capped below
        Nyquist for the render's sample rate. `type` is required the first time."""
        return _guarded(lambda: state.set_filter(type, cutoffHz, resonance))

    @server.tool()
    def set_lofi(bitDepth: int | None = None, decimation: int | None = None) -> dict[str, Any]:
        """Bit-depth crush and sample-and-hold decimation. 16 bits and a factor
        of 1 are neutral."""
        return _guarded(lambda: state.set_lofi(bitDepth, decimation))

    @server.tool()
    def set_effects(effects: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace the effect chain, in order. Each entry needs a `kind`:
        distortion or wavefold (read `drive`), delay (`timeMs`, `feedback`,
        `mixWet`), reverb (`roomSize`, `damping`, `mixWet`). An empty list
        clears the chain."""
        return _guarded(lambda: state.set_effects(effects))

    @server.tool()
    def set_voice_output(
        pan: float | None = None,
        mixDb: float | None = None,
        track: int | None = None,
        key: int | None = None,
    ) -> dict[str, Any]:
        """Where this voice sits: stereo position, level into the bus, and which
        mixer track it plays on. Music mode: `key` (a MIDI note) makes it a kit
        piece that plays only notes of that key, at its own pitch; -1 clears it."""
        return _guarded(lambda: state.set_voice_output(pan, mixDb, track, key))

    # --- Expressive notes (music mode) ------------------------------------------

    @server.tool()
    def set_touch(
        pivot: float | None = None,
        fmIndex: float | None = None,
        cutoffOctaves: float | None = None,
        attackOctaves: float | None = None,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Music mode: velocity changes this voice's tone, not only its level. At
        `pivot` the voice plays as written; per unit of velocity above it the FM
        index moves by `fmIndex`, the cutoff by `cutoffOctaves`, and the attack
        shortens by `attackOctaves` (softer notes move the other way).
        `clear` removes it."""
        return _guarded(
            lambda: state.set_touch(pivot, fmIndex, cutoffOctaves, attackOctaves, clear)
        )

    @server.tool()
    def set_glide(
        timeMs: float | None = None, mode: str | None = None, clear: bool = False
    ) -> dict[str, Any]:
        """Music mode: each note slides in from the previous note's pitch over
        `timeMs`. `mode` legato glides only when the previous note is still held,
        always from any previous note. Not on a kit voice. `clear` removes it."""
        return _guarded(lambda: state.set_glide(timeMs, mode, clear))

    @server.tool()
    def set_fm4(
        algorithm: int | None = None, feedback: float | None = None, clear: bool = False
    ) -> dict[str, Any]:
        """Music mode: four sine operators replace this voice's oscillator (the
        waveform must be sine, and the voice cannot also have fm). `algorithm`
        0 to 7 says how they feed each other: 0 one stack 1 > 2 > 3 > 4, 1 (1 +
        2) > 3 > 4, 2 (1 + (2 > 3)) > 4, 3 ((1 > 2) + 3) > 4, 4 two pairs (1 > 2)
        + (3 > 4), 5 1 into 2, 3 and 4, 6 (1 > 2) + 3 + 4, 7 four carriers.
        `feedback` 0 to 1 feeds operator 1 into itself (harsher). Tune each
        operator with set_operator. `clear` removes it."""
        return _guarded(lambda: state.set_fm4(algorithm, feedback, clear))

    @server.tool()
    def set_operator(
        operator: int,
        ratio: float | None = None,
        fixedHz: float | None = None,
        followPitch: bool = False,
        detuneCents: float | None = None,
        level: float | None = None,
        attackMs: float | None = None,
        decayMs: float | None = None,
        sustainLevel: float | None = None,
    ) -> dict[str, Any]:
        """Music mode: one of the four FM operators (1 to 4), starting fm4 if the
        voice has none. It runs at `ratio` times the note's pitch, or at
        `fixedHz` (`followPitch` undoes that). `level` is loudness for a carrier
        and depth for a modulator (1 is very bright; 0.1 to 0.4 is usual). Its
        envelope rises over `attackMs` and falls to `sustainLevel` over
        `decayMs`; a modulator that decays makes a struck, darkening tone."""
        return _guarded(
            lambda: state.set_operator(
                operator,
                ratio,
                fixedHz,
                followPitch,
                detuneCents,
                level,
                attackMs,
                decayMs,
                sustainLevel,
            )
        )

    @server.tool()
    def set_vibrato(
        delayMs: float | None = None,
        fadeMs: float | None = None,
        rateHz: float | None = None,
        depthCents: float | None = None,
        clear: bool = False,
    ) -> dict[str, Any]:
        """Music mode: a late vibrato. Nothing for `delayMs` from each note's
        start, then it fades in over `fadeMs` to `depthCents` either side at
        `rateHz`, so a held note blooms. `clear` removes it."""
        return _guarded(lambda: state.set_vibrato(delayMs, fadeMs, rateHz, depthCents, clear))

    # --- Master and render options -------------------------------------------

    @server.tool()
    def set_master(
        gainDb: float | None = None,
        targetDbfs: float | None = None,
        effects: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """The master bus. `targetDbfs` is the peak every render normalizes to,
        and is the control that actually sets loudness: the limiter runs after
        `gainDb` and cannot be switched off. Music mode: `effects` is the shared
        room every track goes through, delay and reverb only."""
        return _guarded(lambda: state.set_master(gainDb, targetDbfs, effects))

    @server.tool()
    def set_render_options(
        durationMs: float | None = None,
        sampleRate: int | None = None,
        channels: int | None = None,
        seed: int | None = None,
        name: str | None = None,
        version: int | None = None,
    ) -> dict[str, Any]:
        """Length, format, seed, and the filename stem the render writes to.
        `version` 2 turns on the music mode (any number of tracks, kit keys,
        track and master effects with tails, the loop, stems)."""
        return _guarded(
            lambda: state.set_render_options(durationMs, sampleRate, channels, seed, name, version)
        )

    # --- Composition ----------------------------------------------------------

    @server.tool()
    def set_tempo_swing(
        tempoBpm: float | None = None, swing: float | None = None, loop: bool | None = None
    ) -> dict[str, Any]:
        """Tempo and shuffle for the composition, starting one if there is none.
        `swing` delays every offbeat position on a track's grid by that fraction
        of a step. Starting a composition switches the render to stereo, its
        documented default; set_render_options can change that back. Music
        mode: `loop` makes the file exactly the loop, every tail wrapped onto
        its start."""
        return _guarded(lambda: state.set_tempo_swing(tempoBpm, swing, loop))

    @server.tool()
    def set_track(
        track: int,
        gainDb: float | None = None,
        pan: float | None = None,
        name: str | None = None,
        effects: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Level and stereo position for one mixer track (five, 0 to 4, unless
        the music mode added more). Music mode: `name` labels its stem, and
        `effects` is its own insert chain, run once over all it plays."""
        return _guarded(lambda: state.set_track(track, gainDb, pan, name, effects))

    @server.tool()
    def add_track() -> dict[str, Any]:
        """Music mode: add an empty track at the end. Returns its index."""
        try:
            index, warnings = state.add_track()
        except SpecError as exc:
            return _refused(exc)
        return _ok(warnings, track=index)

    @server.tool()
    def remove_track(track: int) -> dict[str, Any]:
        """Music mode: remove a track no voice plays on. Voices on later tracks
        move down with them."""
        return _guarded(lambda: state.remove_track(track))

    @server.tool()
    def add_notes(track: int, notes: list[dict[str, Any]]) -> dict[str, Any]:
        """Append notes to a track. Each note takes `startBeat`, an optional
        `midiNote` (null plays the voice's own pitch), `durationBeats`, and
        `velocity`. Notes starting past the render's end are dropped with a
        warning, and an exact duplicate is dropped rather than doubled."""
        return _guarded(lambda: state.add_notes(track, notes))

    @server.tool()
    def set_steps(
        track: int, steps: list[dict[str, Any]], stepsPerBeat: int | None = None
    ) -> dict[str, Any]:
        """Paint a track's step grid, replacing what was there. Each step takes
        an `index` on the grid, a `velocity`, and an optional `midiNote`. A grid
        renders exactly like the note list it stands for."""
        return _guarded(lambda: state.set_steps(track, steps, stepsPerBeat))

    @server.tool()
    def clear_track(track: int) -> dict[str, Any]:
        """Remove every note and step from a track."""
        return _guarded(lambda: state.clear_track(track))

    # --- Output ---------------------------------------------------------------

    @server.tool()
    def render(
        outDir: str | None = None,
        name: str | None = None,
        overwrite: bool = False,
        stems: bool = False,
    ) -> dict[str, Any]:
        """Render the session to a WAV plus the spec that regenerates it.

        Returns both paths, the acoustic features measured from the finished
        audio (loudness and true peak included), a plain-language explanation,
        and any clamp warnings. Refuses to replace an existing file unless
        `overwrite` is set. Music mode: `stems` also writes one WAV per track."""
        result = render_to_files(
            state.spec.model_dump(mode="json"),
            out_dir=outDir,
            name=name,
            overwrite=overwrite,
            stems=stems,
        )
        return dict(result.model_dump(mode="json"))

    @server.tool()
    def export_spec() -> dict[str, Any]:
        """The session as a file. `specJson` is exactly what a render writes
        beside its WAV, so committing it lets anyone reproduce these bytes."""
        return _ok(
            [],
            spec=state.spec.model_dump(mode="json"),
            specJson=to_sidecar_json(state.spec),
        )

    @server.tool()
    def import_spec(spec: dict[str, Any] | str) -> dict[str, Any]:
        """Adopt a spec, given either as an object or as the JSON text
        `export_spec` produced. Invalid input is refused and the session in
        progress survives untouched."""
        if isinstance(spec, str):
            return _guarded(lambda: state.import_spec_json(spec))
        return _guarded(lambda: state.adopt(spec))

    @server.tool()
    def explain_session() -> dict[str, Any]:
        """What the session will render, in words."""
        return _ok([], explanation=explain_text(state.spec))

    # --- Stateless ------------------------------------------------------------

    @server.tool()
    def get_schema() -> dict[str, Any]:
        """Every field of a SoundSpec with its type, range, default, and meaning:
        enough to author a valid spec without trial and error."""
        return _ok([], schema=schema_payload())

    @server.tool()
    def list_presets() -> dict[str, Any]:
        """The authored starting points: game sound effects and a lo-fi drum
        kit, each with tags and a one-line description."""
        return _ok([], presets=[info.model_dump(mode="json") for info in preset_catalogue()])

    @server.tool()
    def load_preset(name: str) -> dict[str, Any]:
        """Load a preset into the session, replacing what is there. An unknown
        name is refused with the valid ones listed, and changes nothing."""
        return _guarded(lambda: state.load_preset(name))

    @server.tool()
    def render_spec(
        spec: dict[str, Any],
        outDir: str | None = None,
        name: str | None = None,
        overwrite: bool = False,
        stems: bool = False,
    ) -> dict[str, Any]:
        """Render a spec passed in directly, without touching the session.
        Music mode: `stems` also writes one WAV per track."""
        result = render_to_files(spec, out_dir=outDir, name=name, overwrite=overwrite, stems=stems)
        return dict(result.model_dump(mode="json"))

    @server.tool()
    def explain_spec(spec: dict[str, Any]) -> dict[str, Any]:
        """Describe a spec passed in directly, without rendering it."""
        try:
            parsed = parse_spec(spec)
        except SpecError as exc:
            return _refused(exc)
        return _ok([], explanation=explain_text(parsed))

    return server


# --- Process entry point ------------------------------------------------------


def _server_command() -> list[str]:
    """How to launch this server as a subprocess: the console script when it is
    installed, the module otherwise. Both take no arguments."""
    console = shutil.which("blipsmith-mcp")
    if console is not None:
        return [console]
    return [sys.executable, "-m", "blipsmith.mcp_server"]


async def _handshake() -> int:
    """Start the real server over stdio and complete an initialize plus
    list_tools round trip. This is the verify gate's boot check: it proves the
    process starts, speaks MCP, and publishes its tools, which importing the
    module alone would not."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command, *arguments = _server_command()
    parameters = StdioServerParameters(command=command, args=arguments)
    async with (
        stdio_client(parameters) as (read, write),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        tools = await client.list_tools()
        print(f"blipsmith-mcp: initialize ok, {len(tools.tools)} tools published")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the server on stdio, or self-test with --boot-check."""
    arguments = sys.argv[1:] if argv is None else argv
    if "--boot-check" in arguments:
        import anyio

        return int(anyio.run(_handshake))

    build_server().run()
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the boot check
    sys.exit(main())
