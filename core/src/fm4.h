// Four-operator FM (music mode): four sine operators in place of the oscillator.
//
// Each operator is a phase accumulator reading the baked sine, with its own
// frequency (a ratio of the voice's pitch, or fixed), level and envelope. The
// algorithm says which operators modulate which and which are heard; the eight
// are the classic four-operator set, held here as data. A modulator adds its
// output to its targets' phase: at level 1 that is 4 pi radians at the peak.
// Operator 1 may feed itself back through the mean of its last two outputs,
// a one sample delay, which keeps the loop stable at any legal setting.
//
// Every phase starts at zero on each note, so a note renders the same wherever
// it sits. Nothing here reaches for libm: the sine is the table, detune goes
// through `octave_ratio`, and offsets fold whole turns before the cast exactly
// as the two-operator FM does.

#pragma once

#include <cstdint>

#include "spec_parse.h"

namespace blipsmith {

// The algorithm table: per algorithm, a bit per operator naming the operators
// that modulate it (bit 0 is operator 1), and a bit per carrier.
struct Fm4Algorithm {
    std::uint8_t modulators[kFm4Operators];
    std::uint8_t carriers;
};

inline constexpr int kFm4Algorithms = 8;

// The algorithm at `index`; out of range reads algorithm 0, though the spec
// never lets one through.
const Fm4Algorithm& fm4_algorithm(int index);

class FourOperator {
public:
    FourOperator(const Fm4& fm4, int sampleRate);

    // One sample of the summed carriers, given the voice's pitch this frame in
    // turns per sample. Call once per frame, in frame order.
    double sample(std::uint32_t frame, double turns);

private:
    struct Op {
        double frequencyScale = 1.0;
        bool fixed = false;
        std::uint32_t fixedIncrement = 0;
        double level = 1.0;
        double depthTurns = 0.0;
        std::uint32_t attackFrames = 0;
        std::uint32_t decayFrames = 0;
        double sustainLevel = 1.0;
        std::uint32_t phase = 0;
    };

    double envelope(const Op& op, std::uint32_t frame) const;

    Op ops_[kFm4Operators];
    Fm4Algorithm algorithm_{};
    double carrierScale_ = 1.0;
    double feedbackTurns_ = 0.0;
    double feedbackLast_ = 0.0;
    double feedbackBefore_ = 0.0;
};

}  // namespace blipsmith
