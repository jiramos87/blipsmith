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
};

struct Limiter {
    double targetDbfs = -1.0;
};

struct Master {
    double gainDb = 0.0;
    Limiter limiter;
};

struct Spec {
    int version = 1;
    std::uint32_t seed = 0;
    int sampleRate = 22050;
    int channels = 1;
    double durationMs = 1000.0;
    Master master;
    std::vector<Voice> voices;
    bool hasComposition = false;
};

// Throws std::runtime_error when the text is not parseable JSON.
Spec parse_spec(const std::string& json);

}  // namespace blipsmith
