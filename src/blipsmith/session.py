"""The synth session: a `SoundSpec` an agent edits one knob group at a time.

The physical-synth metaphor made literal. A session holds one spec and one
selected voice, and every verb turns the smallest knob it can: set the envelope,
set the filter, place a note. Nothing accumulates outside the spec, so the
session serializes losslessly at any moment and the file it exports is the file
that renders.

Two rules make the editing safe for a caller that cannot hear what it is doing:

- **Every mutation goes through the B02 contract.** A change is applied to a
  plain dict copy of the spec, and that dict is validated and clamped as a whole
  before it becomes the new state. So a structurally invalid edit (unknown
  waveform, a thirteenth voice) raises and leaves the session exactly as it was,
  and an out-of-range number clamps with the same warning a render would give.
  There is no second validation path here to drift from the one in `spec.py`.
- **Setters patch rather than replace.** An agent adjusting one field of the
  envelope should not have to restate the other three, and silently resetting
  them would be a change it cannot hear. Only the arguments it passes move.

The exception is `set_effects`, which takes the whole chain: order is part of
the meaning there, so a patch would have nothing to patch against.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import Enum
from typing import Any

from blipsmith.presets import load_preset as read_preset
from blipsmith.ranges import FM4_OPERATORS, MUSIC_SPEC_VERSION, TRACK_COUNT
from blipsmith.result import SpecWarning, invalid_spec
from blipsmith.spec import (
    AmMode,
    Channels,
    FilterType,
    LfoTarget,
    ModEnvTarget,
    SoundSpec,
    validate_spec,
)
from blipsmith.wavetables import table_frames

SpecData = dict[str, Any]


def _given(**fields: Any) -> dict[str, Any]:
    """The arguments the caller actually passed. `None` means "leave it alone",
    which is what makes every setter a patch."""
    return {name: value for name, value in fields.items() if value is not None}


def _values(enum: type[Enum]) -> list[str | int]:
    """The valid values of a closed set, for the error that lists them."""
    return [member.value for member in enum]


class Session:
    """One editable spec. One per server process, per the MCP contract."""

    def __init__(self, spec: SoundSpec | None = None) -> None:
        self._spec = spec if spec is not None else SoundSpec()
        self._selected: int | None = 0 if self._spec.voices else None

    # --- State ----------------------------------------------------------------

    @property
    def spec(self) -> SoundSpec:
        """The current spec. Treat it as read-only: mutate through the verbs, so
        every change is validated and clamped."""
        return self._spec

    @property
    def selected_voice(self) -> int | None:
        return self._selected

    def _apply(self, mutate: Callable[[SpecData], None]) -> list[SpecWarning]:
        """Edit a copy, validate the result, then adopt it.

        The order is the whole safety story: nothing reaches `self._spec` that
        has not passed the same validation a rendered spec passes.
        """
        data: SpecData = self._spec.model_dump(mode="json")
        mutate(data)
        validated, warnings = validate_spec(data)
        self._spec = validated
        return warnings

    def _voice(self, data: SpecData) -> dict[str, Any]:
        if self._selected is None or self._selected >= len(data["voices"]):
            raise invalid_spec(
                "no voice is selected. Call new_voice to add one, or select_voice to pick "
                "an existing one.",
                field="voices",
            )
        selected: dict[str, Any] = data["voices"][self._selected]
        return selected

    def _composition(self, data: SpecData) -> dict[str, Any]:
        """The composition, started if this is the first composition verb.

        Starting one switches the render to stereo, which is the documented
        default for a composition: five tracks with pans are a stereo image, and
        an agent that cannot hear should not have to discover that its mix was
        folded down. `set_render_options` can move it back.
        """
        if data.get("composition") is None:
            data["composition"] = {"tracks": [{} for _ in range(TRACK_COUNT)]}
            data["channels"] = int(Channels.STEREO)
        composition: dict[str, Any] = data["composition"]
        return composition

    def _track(self, data: SpecData, index: int) -> dict[str, Any]:
        tracks = self._composition(data)["tracks"]
        if not 0 <= index < len(tracks):
            if data.get("version") == MUSIC_SPEC_VERSION:
                message = (
                    f"track {index} does not exist; there are {len(tracks)} tracks, numbered "
                    f"0 to {len(tracks) - 1}. add_track makes another."
                )
            else:
                message = (
                    f"track {index} does not exist; there are exactly {TRACK_COUNT} tracks, "
                    f"numbered 0 to {TRACK_COUNT - 1}."
                )
            raise invalid_spec(message, field="composition.tracks")
        track: dict[str, Any] = tracks[index]
        return track

    def _music(self, data: SpecData, what: str) -> None:
        if data.get("version") != MUSIC_SPEC_VERSION:
            raise invalid_spec(
                f"{what} belongs to the music mode: call set_render_options with "
                f"version={MUSIC_SPEC_VERSION} first.",
                field="version",
            )

    # --- Voices ---------------------------------------------------------------

    def new_voice(self, waveform: str) -> tuple[int, list[SpecWarning]]:
        """Add a voice and select it. The voice limit is enforced by the
        contract, so the existing voices survive a refused call."""
        index = len(self._spec.voices)

        def mutate(data: SpecData) -> None:
            data["voices"].append({"waveform": waveform})

        warnings = self._apply(mutate)
        self._selected = index
        return index, warnings

    def select_voice(self, index: int) -> None:
        if not 0 <= index < len(self._spec.voices):
            raise invalid_spec(
                f"voice {index} does not exist; the session has {len(self._spec.voices)}.",
                field="voices",
            )
        self._selected = index

    def remove_voice(self, index: int) -> list[SpecWarning]:
        if not 0 <= index < len(self._spec.voices):
            raise invalid_spec(
                f"voice {index} does not exist; the session has {len(self._spec.voices)}.",
                field="voices",
            )

        def mutate(data: SpecData) -> None:
            data["voices"].pop(index)

        warnings = self._apply(mutate)

        # The selection follows the voice it was on rather than the number:
        # removing voice 0 while voice 2 is selected leaves the same voice
        # selected, now numbered 1.
        remaining = len(self._spec.voices)
        if remaining == 0:
            self._selected = None
        elif self._selected is not None:
            if index < self._selected:
                self._selected -= 1
            elif index == self._selected:
                self._selected = min(index, remaining - 1)
        return warnings

    def set_waveform(self, waveform: str, pulseDuty: float | None = None) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            self._voice(data).update(_given(waveform=waveform, pulseDuty=pulseDuty))

        return self._apply(mutate)

    def set_fundamental(
        self, hz: float | None = None, midi: int | None = None
    ) -> list[SpecWarning]:
        """Pitch, in one unit or the other.

        Setting one clears the other, because a MIDI note wins over hertz in the
        core: leaving a stale note behind would make a hertz change inaudible,
        and inaudible is exactly what the caller cannot detect.
        """
        if (hz is None) == (midi is None):
            raise invalid_spec(
                "set_fundamental takes either hz or midi, not both and not neither.",
                field="voices.fundamentalHz",
            )

        def mutate(data: SpecData) -> None:
            voice = self._voice(data)
            if midi is not None:
                voice["fundamentalMidi"] = midi
            else:
                voice["fundamentalHz"] = hz
                voice["fundamentalMidi"] = None

        return self._apply(mutate)

    def set_adsr(
        self,
        attackMs: float | None = None,
        decayMs: float | None = None,
        sustainLevel: float | None = None,
        releaseMs: float | None = None,
    ) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            voice = self._voice(data)
            voice["ampEnv"] = {
                **voice.get("ampEnv", {}),
                **_given(
                    attackMs=attackMs,
                    decayMs=decayMs,
                    sustainLevel=sustainLevel,
                    releaseMs=releaseMs,
                ),
            }

        return self._apply(mutate)

    def _patch_block(
        self,
        key: str,
        required: str,
        required_value: Any,
        valid: list[str | int],
        fields: dict[str, Any],
    ) -> list[SpecWarning]:
        """Patch an optional per-voice block, creating it when it is the first
        time. The block's discriminator (a filter's type, an LFO's target) has no
        default that could be guessed, so creating one without it is refused."""

        def mutate(data: SpecData) -> None:
            voice = self._voice(data)
            current = voice.get(key)
            if current is None:
                if required_value is None:
                    raise invalid_spec(
                        f"this voice has no {key} yet, so {required} is required to add one.",
                        field=f"voices.{key}.{required}",
                        valid_values=valid,
                    )
                current = {}
            voice[key] = {**current, **_given(**{required: required_value}), **_given(**fields)}

        return self._apply(mutate)

    def set_mod_env(
        self,
        target: str | None = None,
        amount: float | None = None,
        attackMs: float | None = None,
        decayMs: float | None = None,
    ) -> list[SpecWarning]:
        return self._patch_block(
            "modEnv",
            "target",
            target,
            _values(ModEnvTarget),
            {"amount": amount, "attackMs": attackMs, "decayMs": decayMs},
        )

    def set_lfo(
        self,
        target: str | None = None,
        shape: str | None = None,
        rateHz: float | None = None,
        depth: float | None = None,
    ) -> list[SpecWarning]:
        return self._patch_block(
            "lfo",
            "target",
            target,
            _values(LfoTarget),
            {"shape": shape, "rateHz": rateHz, "depth": depth},
        )

    def set_fm(self, ratio: float | None = None, index: float | None = None) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            voice = self._voice(data)
            voice["fm"] = {**(voice.get("fm") or {}), **_given(ratio=ratio, index=index)}

        return self._apply(mutate)

    def set_am(
        self, mode: str | None = None, rateHz: float | None = None, depth: float | None = None
    ) -> list[SpecWarning]:
        return self._patch_block(
            "am", "mode", mode, _values(AmMode), {"rateHz": rateHz, "depth": depth}
        )

    def set_filter(
        self,
        type: str | None = None,
        cutoffHz: float | None = None,
        resonance: float | None = None,
    ) -> list[SpecWarning]:
        return self._patch_block(
            "filter",
            "type",
            type,
            _values(FilterType),
            {"cutoffHz": cutoffHz, "resonance": resonance},
        )

    def set_lofi(
        self, bitDepth: int | None = None, decimation: int | None = None
    ) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            voice = self._voice(data)
            voice["lofi"] = {
                **(voice.get("lofi") or {}),
                **_given(bitDepth=bitDepth, decimation=decimation),
            }

        return self._apply(mutate)

    def set_effects(self, effects: list[dict[str, Any]]) -> list[SpecWarning]:
        """The whole chain at once: effects apply in the order given, so the
        list is the meaning. An empty list clears it."""

        def mutate(data: SpecData) -> None:
            self._voice(data)["effects"] = list(effects)

        return self._apply(mutate)

    def set_voice_output(
        self,
        pan: float | None = None,
        mixDb: float | None = None,
        track: int | None = None,
        key: int | None = None,
    ) -> list[SpecWarning]:
        """`key` (music mode) makes the voice a kit piece; -1 clears it."""

        def mutate(data: SpecData) -> None:
            voice = self._voice(data)
            voice.update(_given(pan=pan, mixDb=mixDb, track=track))
            if key is not None:
                self._music(data, "a kit key")
                voice["key"] = None if key < 0 else key

        return self._apply(mutate)

    def _expression_block(
        self, key: str, what: str, clear: bool, fields: dict[str, Any]
    ) -> list[SpecWarning]:
        """Music mode: patch one of a voice's expression blocks, starting it from
        its defaults the first time; `clear` removes it."""

        def mutate(data: SpecData) -> None:
            self._music(data, what)
            voice = self._voice(data)
            if clear:
                voice[key] = None
                return
            voice[key] = {**(voice.get(key) or {}), **_given(**fields)}

        return self._apply(mutate)

    def set_touch(
        self,
        pivot: float | None = None,
        fmIndex: float | None = None,
        cutoffOctaves: float | None = None,
        attackOctaves: float | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        return self._expression_block(
            "touch",
            "touch",
            clear,
            {
                "pivot": pivot,
                "fmIndex": fmIndex,
                "cutoffOctaves": cutoffOctaves,
                "attackOctaves": attackOctaves,
            },
        )

    def set_glide(
        self, timeMs: float | None = None, mode: str | None = None, clear: bool = False
    ) -> list[SpecWarning]:
        return self._expression_block("glide", "glide", clear, {"timeMs": timeMs, "mode": mode})

    def set_fm4(
        self,
        algorithm: int | None = None,
        feedback: float | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        return self._expression_block(
            "fm4", "four-operator FM", clear, {"algorithm": algorithm, "feedback": feedback}
        )

    def set_operator(
        self,
        operator: int,
        ratio: float | None = None,
        fixedHz: float | None = None,
        followPitch: bool = False,
        detuneCents: float | None = None,
        level: float | None = None,
        attackMs: float | None = None,
        decayMs: float | None = None,
        sustainLevel: float | None = None,
    ) -> list[SpecWarning]:
        """Patch one of the four operators (numbered 1 to 4), starting the fm4
        block from its defaults if the voice has none. `followPitch` drops a
        fixed frequency so the operator follows the voice's pitch again."""

        def mutate(data: SpecData) -> None:
            self._music(data, "four-operator FM")
            if not 1 <= operator <= FM4_OPERATORS:
                raise invalid_spec(
                    f"operator {operator} does not exist; the operators are numbered 1 to "
                    f"{FM4_OPERATORS}.",
                    field="fm4.operators",
                )
            voice = self._voice(data)
            fm4 = voice.get("fm4") or {}
            operators = fm4.get("operators") or [{} for _ in range(FM4_OPERATORS)]
            patched = {
                **operators[operator - 1],
                **_given(
                    ratio=ratio,
                    fixedHz=fixedHz,
                    detuneCents=detuneCents,
                    level=level,
                    attackMs=attackMs,
                    decayMs=decayMs,
                    sustainLevel=sustainLevel,
                ),
            }
            if followPitch:
                patched.pop("fixedHz", None)
            operators[operator - 1] = patched
            voice["fm4"] = {**fm4, "operators": operators}

        return self._apply(mutate)

    def set_string(
        self,
        excitation: str | None = None,
        position: float | None = None,
        brightness: float | None = None,
        decayMs: float | None = None,
        damping: float | None = None,
        body: float | None = None,
        bodyHz: float | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        return self._expression_block(
            "string",
            "a string",
            clear,
            {
                "excitation": excitation,
                "position": position,
                "brightness": brightness,
                "decayMs": decayMs,
                "damping": damping,
                "body": body,
                "bodyHz": bodyHz,
            },
        )

    def set_modal(
        self,
        brightness: float | None = None,
        modes: list[dict[str, float]] | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        """Patch the voice's modal bank, starting it from its defaults the first
        time. `modes`, when given, replaces the whole bank (1 to 16 modes, each
        `{ratio, level, decayMs}`)."""
        return self._expression_block(
            "modal", "a modal bank", clear, {"brightness": brightness, "modes": modes}
        )

    def set_wavetable(
        self,
        table: str | None = None,
        frames: list[list[float]] | None = None,
        position: float | None = None,
        positionEnd: float | None = None,
        sweepMs: float | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        """Patch the voice's wavetable, starting it from its defaults the first
        time. `table` names a built-in table and `frames` gives one as harmonic
        amplitudes per frame; either replaces the whole set of frames."""
        if table is not None and frames is not None:
            raise invalid_spec(
                "set_wavetable: give a table name or frames, not both.", field="table"
            )
        given: list[dict[str, list[float]]] | None = None
        if table is not None:
            given = table_frames(table)
        elif frames is not None:
            given = [{"harmonics": list(frame)} for frame in frames]
        return self._expression_block(
            "wavetable",
            "a wavetable",
            clear,
            {
                "frames": given,
                "position": position,
                "positionEnd": positionEnd,
                "sweepMs": sweepMs,
            },
        )

    def set_additive(
        self,
        brightness: float | None = None,
        stretch: float | None = None,
        partials: list[dict[str, float]] | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        """Patch the voice's additive block, starting it from its defaults the
        first time. `partials`, when given, replaces the whole set (1 to 32, each
        `{ratio, level, decayMs}`)."""
        return self._expression_block(
            "additive",
            "an additive voice",
            clear,
            {"brightness": brightness, "stretch": stretch, "partials": partials},
        )

    def set_unison(
        self,
        voices: int | None = None,
        detuneCents: float | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        return self._expression_block(
            "unison", "unison", clear, {"voices": voices, "detuneCents": detuneCents}
        )

    def set_vibrato(
        self,
        delayMs: float | None = None,
        fadeMs: float | None = None,
        rateHz: float | None = None,
        depthCents: float | None = None,
        clear: bool = False,
    ) -> list[SpecWarning]:
        return self._expression_block(
            "vibrato",
            "a late vibrato",
            clear,
            {"delayMs": delayMs, "fadeMs": fadeMs, "rateHz": rateHz, "depthCents": depthCents},
        )

    # --- Master and render options -------------------------------------------

    def set_master(
        self,
        gainDb: float | None = None,
        targetDbfs: float | None = None,
        effects: list[dict[str, Any]] | None = None,
    ) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            master = data["master"]
            master.update(_given(gainDb=gainDb))
            if targetDbfs is not None:
                master["limiter"] = {**master.get("limiter", {}), "targetDbfs": targetDbfs}
            if effects is not None:
                self._music(data, "a master effect")
                master["effects"] = list(effects)

        return self._apply(mutate)

    def set_render_options(
        self,
        durationMs: float | None = None,
        sampleRate: int | None = None,
        channels: int | None = None,
        seed: int | None = None,
        name: str | None = None,
        version: int | None = None,
    ) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            data.update(
                _given(
                    durationMs=durationMs,
                    sampleRate=sampleRate,
                    channels=channels,
                    seed=seed,
                    version=version,
                )
            )
            if version == MUSIC_SPEC_VERSION:
                # The music mode is a composition mode.
                self._composition(data)
            if name is not None:
                data["meta"] = {**data.get("meta", {}), "name": name}

        return self._apply(mutate)

    # --- Composition ----------------------------------------------------------

    def set_tempo_swing(
        self, tempoBpm: float | None = None, swing: float | None = None, loop: bool | None = None
    ) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            composition = self._composition(data)
            composition.update(_given(tempoBpm=tempoBpm, swing=swing))
            if loop is not None:
                self._music(data, "the loop")
                composition["loop"] = loop

        return self._apply(mutate)

    def set_track(
        self,
        track: int,
        gainDb: float | None = None,
        pan: float | None = None,
        name: str | None = None,
        effects: list[dict[str, Any]] | None = None,
    ) -> list[SpecWarning]:
        """`name` and `effects` (the track's insert chain) are music mode."""

        def mutate(data: SpecData) -> None:
            entry = self._track(data, track)
            entry.update(_given(gainDb=gainDb, pan=pan))
            if name is not None:
                self._music(data, "a track name")
                entry["name"] = name or None
            if effects is not None:
                self._music(data, "a track effect")
                entry["effects"] = list(effects)

        return self._apply(mutate)

    def add_track(self) -> tuple[int, list[SpecWarning]]:
        """Music mode: append an empty track and return its index."""
        index = len(self._spec.composition.tracks) if self._spec.composition else TRACK_COUNT

        def mutate(data: SpecData) -> None:
            self._music(data, "adding a track")
            self._composition(data)["tracks"].append({})

        return index, self._apply(mutate)

    def remove_track(self, track: int) -> list[SpecWarning]:
        """Music mode: remove a track no voice plays on; the voices on later
        tracks move down with their tracks."""

        def mutate(data: SpecData) -> None:
            self._music(data, "removing a track")
            self._track(data, track)
            playing = [i for i, voice in enumerate(data["voices"]) if voice["track"] == track]
            if playing:
                raise invalid_spec(
                    f"voices {playing} play on track {track}; move them with "
                    "set_voice_output or remove them first.",
                    field="composition.tracks",
                )
            del data["composition"]["tracks"][track]
            for voice in data["voices"]:
                if voice["track"] > track:
                    voice["track"] -= 1

        return self._apply(mutate)

    def add_notes(self, track: int, notes: list[dict[str, Any]]) -> list[SpecWarning]:
        """Append notes to a track. Adding rather than replacing is what lets an
        agent build a part in passes."""

        def mutate(data: SpecData) -> None:
            entry = self._track(data, track)
            entry["notes"] = [*entry.get("notes", []), *notes]

        return self._apply(mutate)

    def set_steps(
        self, track: int, steps: list[dict[str, Any]], stepsPerBeat: int | None = None
    ) -> list[SpecWarning]:
        """Replace a track's step grid. A pattern is painted whole, so this one
        replaces where `add_notes` appends."""

        def mutate(data: SpecData) -> None:
            entry = self._track(data, track)
            entry["steps"] = list(steps)
            entry.update(_given(stepsPerBeat=stepsPerBeat))

        return self._apply(mutate)

    def clear_track(self, track: int) -> list[SpecWarning]:
        def mutate(data: SpecData) -> None:
            entry = self._track(data, track)
            entry["notes"] = []
            entry["steps"] = []

        return self._apply(mutate)

    # --- Whole-spec moves -----------------------------------------------------

    def adopt(self, data: Any) -> list[SpecWarning]:
        """Replace the session with another spec. Invalid input changes nothing,
        so a failed import leaves the work in progress intact."""
        validated, warnings = validate_spec(data)
        self._spec = validated
        self._selected = 0 if validated.voices else None
        return warnings

    def import_spec_json(self, text: str) -> list[SpecWarning]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise invalid_spec(f"malformed JSON: {exc}") from exc
        return self.adopt(data)

    def load_preset(self, name: str) -> list[SpecWarning]:
        """Start from an authored sound. Unknown names are refused by the
        registry, listing the valid ones, and the session is untouched."""
        return self.adopt(read_preset(name).model_dump(mode="json"))
