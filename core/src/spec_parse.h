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

struct Adsr {
    double attackMs = 5.0;
    double decayMs = 100.0;
    double sustainLevel = 0.6;
    double releaseMs = 150.0;
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
