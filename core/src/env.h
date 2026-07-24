// The amplitude envelope.
//
// A one-shot has no key-up to release from, so the release is anchored to the
// end of the render: the envelope sustains until `releaseMs` before the last
// frame, then falls to silence exactly as the file ends. That way a spec's
// duration is the sound's duration, with no clipped tail and no dead air.
//
// Curves are algebraic rather than exponential. A true exponential needs exp(),
// which is banned from this path, and squaring the ramp gives the fast-then-slow
// fall that percussive material wants using only multiplication.

#pragma once

#include <cstdint>

#include "spec_parse.h"

namespace blipsmith {

class AmpEnvelope {
public:
    AmpEnvelope(const Adsr& adsr, std::uint32_t totalFrames, int sampleRate);

    // Gain in [0, 1] for the given frame.
    double at(std::uint32_t frame) const;

private:
    double sustained(std::uint32_t frame) const;

    std::uint32_t attackFrames_ = 0;
    std::uint32_t decayFrames_ = 0;
    std::uint32_t releaseFrames_ = 0;
    std::uint32_t releaseStart_ = 0;
    double sustainLevel_ = 1.0;
    double levelAtRelease_ = 1.0;
};

}  // namespace blipsmith
