// The effects chain: distortion, wavefolding, delay, reverb, chorus.
//
// Effects apply in the order the spec lists them, each one carrying its own
// state, so two delays in a row are two delays and not one with a doubled time.
//
// Everything here is plain arithmetic over integer-length delay lines. The
// waveshapers are piecewise polynomials rather than the usual `tanh`, the delay
// taps land on whole samples rather than on an interpolated fraction, and the
// reverb is a Schroeder network whose comb and allpass lengths are integers
// scaled from the 44.1 kHz originals. Nothing is approximated per platform.
//
// `drive` is both the amount of gain into the shaper and the wet/dry balance, so
// a drive of 0 returns the input untouched, the same way an FM index of 0 or an
// LFO depth of 0 does. Delay and reverb take their balance from `mixWet`
// instead, per the published contract for those kinds.

#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <vector>

#include "spec_parse.h"

namespace blipsmith {

// Freeverb's stereo spread, in samples at 44.1 kHz: the right channel's combs
// and allpasses run this much longer, so a stereo room is wide rather than the
// same tail twice.
inline constexpr int kReverbStereoSpread = 23;

// How long an effect keeps sounding after its input stops, in frames: until it
// has fallen 96 dB (a factor of 2^-16). Distortion and wavefold have no tail.
// Worked out by repeated multiplication, so the bound is as exact as the audio.
std::uint32_t effect_tail_frames(const Effect& effect, int sampleRate);

// A chain's tail: the tails of its effects in series add up.
std::uint32_t chain_tail_frames(const std::vector<Effect>& effects, int sampleRate);

// Exposed for the shaping tests: the waveshapers with no dry blend.
double soft_clip(double sample);
double wave_fold(double sample);

class DelayLine {
public:
    DelayLine(double timeMs, double feedback, double mixWet, int sampleRate);

    double process(double sample);

private:
    std::vector<double> buffer_;
    std::size_t index_ = 0;
    double feedback_ = 0.0;
    double mixWet_ = 0.0;
};

// Four damped combs in parallel into two allpasses, the small Schroeder/Freeverb
// arrangement. Enough tail for a game sound effect without a per-voice cost that
// scales with the room.
class Reverb {
public:
    // `stereoSpread` lengthens every comb and allpass by that many samples at
    // 44.1 kHz; 0 is the mono room version 1 has always rendered.
    Reverb(double roomSize, double damping, double mixWet, int sampleRate, int stereoSpread = 0);

    double process(double sample);

private:
    static constexpr std::size_t kCombs = 4;
    static constexpr std::size_t kAllpasses = 2;

    struct Comb {
        std::vector<double> buffer;
        std::size_t index = 0;
        double store = 0.0;
    };

    struct Allpass {
        std::vector<double> buffer;
        std::size_t index = 0;
    };

    Comb combs_[kCombs];
    Allpass allpasses_[kAllpasses];
    double feedback_ = 0.0;
    double damping_ = 0.0;
    double mixWet_ = 0.0;
};

// Music mode: a chorus. One delay line read back at a delay that swings around
// its centre on a baked-sine LFO, through a 4-point Lagrange interpolation (the
// string's read), blended with the dry input. The read never comes closer than
// two samples to now. `quarterTurn` starts the LFO a quarter turn on: the right
// channel of a stereo track, so the two sides swing apart and the part widens.
class Chorus {
public:
    Chorus(double delayMs, double depthMs, double rateHz, double mixWet, int sampleRate,
           bool quarterTurn);

    double process(double sample);

private:
    double read(double delay) const;

    std::vector<double> buffer_;
    std::uint32_t mask_ = 0;
    std::uint32_t write_ = 0;
    double centre_ = 0.0;
    double depth_ = 0.0;
    std::uint32_t phase_ = 0;
    std::uint32_t increment_ = 0;
    double mixWet_ = 0.0;
};

class EffectChain {
public:
    EffectChain(const std::vector<Effect>& effects, int sampleRate, int stereoSpread = 0);

    double process(double sample);

private:
    struct Unit {
        EffectKind kind = EffectKind::Distortion;
        double drive = 0.0;
        std::optional<DelayLine> delay;
        std::optional<Reverb> reverb;
        std::optional<Chorus> chorus;
    };

    std::vector<Unit> units_;
};

}  // namespace blipsmith
