"""What a spec sounds like, in words.

The features tell an agent what came out; this tells it what it asked for. The
two answer different questions, and an agent that cannot hear needs both: the
numbers say the sound is bright, the sentence says it is bright *because* the
FM index is high.

Deterministic by construction, and for the same reason as the audio: no
randomness, no phrasing choices, no model in the loop. The same spec produces
the same sentence forever, so an explanation can be committed beside a render
and diffed when the spec changes.

Written for someone skimming, not for a data sheet. It names what is switched
on and what character that gives, and stays quiet about every stage the spec
left alone: a list of twelve "off"s tells a reader nothing.
"""

from __future__ import annotations

from blipsmith.spec import (
    Adsr,
    AmMode,
    Effect,
    EffectKind,
    LfoTarget,
    SoundSpec,
    Voice,
    Waveform,
)

# How a waveform reads to someone who has to picture the sound.
_WAVEFORM_CHARACTER: dict[Waveform, str] = {
    Waveform.SINE: "a pure sine",
    Waveform.SQUARE: "a hollow square",
    Waveform.TRIANGLE: "a soft triangle",
    Waveform.SAW: "a bright saw",
    Waveform.PULSE: "a thin pulse",
    Waveform.NOISE_WHITE: "white noise",
    Waveform.NOISE_PINK: "pink noise",
}

_LFO_TARGET_NAME: dict[LfoTarget, str] = {
    LfoTarget.PITCH: "vibrato",
    LfoTarget.AMPLITUDE: "tremolo",
    LfoTarget.CUTOFF: "a filter wobble",
}

_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def _number(value: float) -> str:
    """Trim a float to something a person reads rather than parses."""
    rounded = round(value, 1)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def _note_name(midi: int) -> str:
    return f"{_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def _pitch_phrase(voice: Voice) -> str:
    """Empty for noise, which has no pitch to name and reads badly if given one."""
    if voice.waveform in (Waveform.NOISE_WHITE, Waveform.NOISE_PINK):
        return ""
    if voice.fundamentalMidi is not None:
        return f"at MIDI note {voice.fundamentalMidi} ({_note_name(voice.fundamentalMidi)})"
    return f"at {_number(voice.fundamentalHz)} Hz"


def _envelope_phrase(envelope: Adsr) -> str:
    """The envelope as a shape rather than as four numbers."""
    if envelope.attackMs >= 200:
        shape = "swells in"
    elif envelope.attackMs >= 30:
        shape = "eases in"
    else:
        shape = "starts instantly"

    if envelope.sustainLevel <= 0.05:
        tail = "and drops away" if envelope.decayMs < 200 else "and fades out"
    elif envelope.decayMs >= 400:
        tail = "and settles slowly"
    else:
        tail = "and holds"

    return f"{shape} {tail}"


def _effect_phrase(effect: Effect) -> str:
    if effect.kind is EffectKind.DISTORTION:
        return f"distortion at {_number(effect.drive * 100)}% drive"
    if effect.kind is EffectKind.WAVEFOLD:
        return f"wavefolding at {_number(effect.drive * 100)}% drive"
    if effect.kind is EffectKind.DELAY:
        return f"a {_number(effect.timeMs)} ms delay"
    return f"reverb on a {'large' if effect.roomSize >= 0.5 else 'small'} room"


def _stage_phrases(voice: Voice) -> list[str]:
    """Every stage this voice actually switched on, in signal-chain order."""
    stages: list[str] = []

    if voice.fm is not None:
        stages.append(
            f"FM at a {_number(voice.fm.ratio)}:1 ratio and index {_number(voice.fm.index)}"
        )
    if voice.am is not None:
        mode = "ring modulation" if voice.am.mode is AmMode.RING else "amplitude modulation"
        stages.append(f"{mode} at {_number(voice.am.rateHz)} Hz")
    if voice.modEnv is not None:
        direction = "down to" if voice.modEnv.amount < 0 else "up to"
        stages.append(
            f"a mod envelope sweeping {voice.modEnv.target.value} {direction} the fundamental "
            f"over {_number(voice.modEnv.decayMs)} ms"
        )
    if voice.lfo is not None:
        stages.append(
            f"{_LFO_TARGET_NAME[voice.lfo.target]} from a {_number(voice.lfo.rateHz)} Hz "
            f"{voice.lfo.shape.value} LFO"
        )
    if voice.filter is not None:
        stages.append(
            f"a {voice.filter.type.value} filter at {_number(voice.filter.cutoffHz)} Hz"
            + (" with resonance" if voice.filter.resonance >= 2.0 else "")
        )
    if voice.lofi is not None:
        crushed = voice.lofi.bitDepth < 16
        decimated = voice.lofi.decimation > 1
        if crushed and decimated:
            stages.append(
                f"a {voice.lofi.bitDepth}-bit crush and {voice.lofi.decimation}x decimation"
            )
        elif crushed:
            stages.append(f"a {voice.lofi.bitDepth}-bit crush")
        elif decimated:
            stages.append(f"{voice.lofi.decimation}x decimation")
    stages.extend(_effect_phrase(effect) for effect in voice.effects)

    return stages


def _join(parts: list[str]) -> str:
    if len(parts) == 1:
        return parts[0]
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _placement_phrase(voice: Voice, channels: int) -> str:
    if channels < 2 or voice.pan == 0:
        return ""
    side = "left" if voice.pan < 0 else "right"
    depth = "hard" if abs(voice.pan) >= 0.9 else "part-way"
    return f", placed {depth} {side}"


def explain_voice(voice: Voice, channels: int = 1) -> str:
    opening = " ".join(
        part for part in (_WAVEFORM_CHARACTER[voice.waveform], _pitch_phrase(voice)) if part
    )
    sentence = f"{opening} that {_envelope_phrase(voice.ampEnv)}"
    stages = _stage_phrases(voice)
    if stages:
        sentence += f", through {_join(stages)}"
    return sentence + _placement_phrase(voice, channels)


def explain_spec(spec: SoundSpec) -> str:
    """A plain-language description of what this spec will render.

    Deterministic: the same spec always produces the same text.
    """
    channels = int(spec.channels)
    header = (
        f"{_number(spec.durationMs)} ms, "
        f"{'stereo' if channels == 2 else 'mono'} at {int(spec.sampleRate)} Hz, "
        f"seed {spec.seed}."
    )

    if not spec.voices:
        return f"{header} No voices, so this renders silence."

    lines = [header]
    if spec.composition is not None:
        played = sum(1 for track in spec.composition.tracks if track.notes or track.steps)
        lines.append(
            f"A composition at {_number(spec.composition.tempoBpm)} BPM with "
            f"{played} of {len(spec.composition.tracks)} tracks playing."
        )

    for index, voice in enumerate(spec.voices):
        lines.append(f"Voice {index + 1}: {explain_voice(voice, channels)}.")

    lines.append(
        f"The master bus normalizes the mix to {_number(spec.master.limiter.targetDbfs)} dBFS."
    )
    return " ".join(lines)
