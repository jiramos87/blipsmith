// Seeded noise. Integer PRNG only: a platform rand() would break byte-identity
// on the first noise voice.
//
// The stream is derived from (spec seed, voice index), so re-rendering a spec
// reproduces the same noise exactly, while two noise voices in one spec still
// get uncorrelated streams instead of the same hiss twice.

#pragma once

#include <cstdint>

namespace blipsmith {

class NoiseSource {
public:
    NoiseSource(std::uint32_t seed, int voiceIndex);

    // Both return samples in [-1, 1).
    double white();
    double pink();

private:
    static constexpr int kPinkRows = 8;

    std::uint32_t next_u32();
    double next_bipolar();

    std::uint32_t state_;
    std::uint32_t counter_ = 0;
    double rows_[kPinkRows] = {};
    double running_sum_ = 0.0;
};

}  // namespace blipsmith
