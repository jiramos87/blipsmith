// Canonical SoundSpec JSON -> plain numeric struct.
//
// The Python layer has already validated, clamped, and materialized every
// default before the core sees a byte, so this parser does no validation and no
// clamping: a field that is absent here is a bug upstream, not user input to be
// forgiven. Missing fields fall back to the same defaults the Python contract
// declares, purely so a malformed call degrades predictably instead of crashing.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace blipsmith {

enum class Waveform : int {
    Sine = 0,
    Square,
    Triangle,
    Saw,
    Pulse,
    NoiseWhite,
    NoisePink,
};

enum class LfoShape : int {
    Sine = 0,
    Triangle,
    Square,
    Saw,
};

enum class LfoTarget : int {
    Pitch = 0,
    Amplitude,
    Cutoff,
};

enum class ModEnvTarget : int {
    Pitch = 0,
    Cutoff,
};

enum class AmMode : int {
    Am = 0,
    Ring,
};

enum class FilterType : int {
    Lowpass = 0,
    Highpass,
    Bandpass,
};

enum class GlideMode : int {
    Legato = 0,
    Always,
};

enum class Excitation : int {
    Pluck = 0,
    Strike = 1,
};

enum class EffectKind : int {
    Distortion = 0,
    Wavefold,
    Delay,
    Reverb,
};

struct Adsr {
    double attackMs = 5.0;
    double decayMs = 100.0;
    double sustainLevel = 0.6;
    double releaseMs = 150.0;
};

struct ModEnv {
    ModEnvTarget target = ModEnvTarget::Pitch;
    double amount = 0.5;
    double attackMs = 0.0;
    double decayMs = 120.0;
};

struct Lfo {
    LfoTarget target = LfoTarget::Pitch;
    LfoShape shape = LfoShape::Sine;
    double rateHz = 5.0;
    double depth = 0.5;
};

struct Fm {
    double ratio = 2.0;
    double index = 3.0;
};

struct Am {
    AmMode mode = AmMode::Am;
    double rateHz = 100.0;
    double depth = 0.5;
};

struct Filter {
    FilterType type = FilterType::Lowpass;
    double cutoffHz = 8000.0;
    double resonance = 0.7;
};

struct LoFi {
    int bitDepth = 8;
    int decimation = 1;
};

// Music mode, expressive notes. Each is read per note, in the music path only.
struct Touch {
    double pivot = 0.6;
    double fmIndex = 0.0;
    double cutoffOctaves = 0.0;
    double attackOctaves = 0.0;
};

struct Glide {
    double timeMs = 80.0;
    GlideMode mode = GlideMode::Legato;
};

struct Vibrato {
    double delayMs = 250.0;
    double fadeMs = 300.0;
    double rateHz = 5.5;
    double depthCents = 20.0;
};

// Music mode, four-operator FM. One sine operator: its frequency, its level
// (loudness as a carrier, depth as a modulator) and its envelope.
struct Operator {
    double ratio = 1.0;
    // 0 means "follows the voice's pitch"; above 0, a fixed frequency in Hz.
    double fixedHz = 0.0;
    double detuneCents = 0.0;
    double level = 1.0;
    double attackMs = 0.0;
    double decayMs = 0.0;
    double sustainLevel = 1.0;
};

inline constexpr int kFm4Operators = 4;

struct Fm4 {
    int algorithm = 0;
    double feedback = 0.0;
    Operator operators[kFm4Operators];
};

// Music mode, a plucked or struck string in place of the oscillator.
struct String {
    Excitation excitation = Excitation::Pluck;
    double position = 0.2;
    double brightness = 0.6;
    double decayMs = 2500.0;
    double damping = 0.5;
    double body = 0.0;
    double bodyHz = 200.0;
};

// Music mode, one mode of a modal bank.
struct Mode {
    double ratio = 1.0;
    double level = 1.0;
    double decayMs = 500.0;
};

// Music mode, a bank of tuned resonators struck once in place of the oscillator.
struct Modal {
    double brightness = 0.6;
    std::vector<Mode> modes;
};

// One flat struct per the published contract: each kind reads the parameters
// that apply to it and ignores the rest.
struct Effect {
    EffectKind kind = EffectKind::Distortion;
    double drive = 0.5;
    double timeMs = 120.0;
    double feedback = 0.35;
    double mixWet = 0.3;
    double roomSize = 0.5;
    double damping = 0.5;
};

struct Voice {
    Waveform waveform = Waveform::Sine;
    double fundamentalHz = 440.0;
    // -1 means "not set". The note-to-hertz conversion belongs in the core from a
    // baked table: 2**((n-69)/12) through a host libm would make the rendered
    // bytes platform-dependent.
    int fundamentalMidi = -1;
    double pulseDuty = 0.5;
    Adsr ampEnv;
    // Every modulation block is optional, and canonical JSON spells "absent" as
    // null rather than omitting the key, so each carries its own present flag.
    bool hasModEnv = false;
    ModEnv modEnv;
    bool hasLfo = false;
    Lfo lfo;
    bool hasFm = false;
    Fm fm;
    bool hasAm = false;
    Am am;
    bool hasFilter = false;
    Filter filter;
    bool hasLoFi = false;
    LoFi lofi;
    std::vector<Effect> effects;
    double pan = 0.0;
    double mixDb = 0.0;
    int track = 0;
    // Music mode: the MIDI note this voice answers to on a kit track; -1 means
    // it plays every note of its track, as in version 1.
    int key = -1;
    // Music mode: expressive notes, each optional.
    bool hasTouch = false;
    Touch touch;
    bool hasGlide = false;
    Glide glide;
    bool hasVibrato = false;
    Vibrato vibrato;
    // Music mode: four-operator FM in place of the oscillator.
    bool hasFm4 = false;
    Fm4 fm4;
    // Music mode: a plucked or struck string in place of the oscillator.
    bool hasString = false;
    String string;
    // Music mode: a bank of tuned resonators in place of the oscillator.
    bool hasModal = false;
    Modal modal;
};

// One scheduled event. The Python compiler has already expanded painted steps
// into notes and baked swing into the start times, so the core sees one
// representation and never has to know a step grid existed.
struct Note {
    double startBeat = 0.0;
    double durationBeats = 1.0;
    // -1 means "no pitch of its own": the voice plays at its own fundamental,
    // which is what a drum hit wants.
    int midiNote = -1;
    double velocity = 0.8;
};

// `stepsPerBeat` and the composition's `swing` are deliberately not read here.
// They describe how a pattern was authored, and the compiler has already spent
// them; carrying them into the renderer would be a second chance to disagree.
struct Track {
    double gainDb = 0.0;
    double pan = 0.0;
    std::vector<Note> notes;
    // Music mode: the track's stereo insert chain.
    std::vector<Effect> effects;
};

struct Composition {
    double tempoBpm = 120.0;
    std::vector<Track> tracks;
    // Music mode: wrap everything past the end back onto the start.
    bool loop = false;
};

struct Limiter {
    double targetDbfs = -1.0;
};

struct Master {
    double gainDb = 0.0;
    Limiter limiter;
    // Music mode: the shared room (delay and reverb), run once per track.
    std::vector<Effect> effects;
};

struct Spec {
    int version = 1;
    std::uint32_t seed = 0;
    int sampleRate = 22050;
    int channels = 1;
    double durationMs = 1000.0;
    Master master;
    std::vector<Voice> voices;
    // With a composition, voices are triggered by notes and nothing else: a
    // track with no notes contributes silence rather than a held one-shot.
    bool hasComposition = false;
    Composition composition;
};

// Throws std::runtime_error when the text is not parseable JSON.
Spec parse_spec(const std::string& json);

}  // namespace blipsmith
