#include "noise.h"

namespace blipsmith {
namespace {

// SplitMix64 finalizer. Mixing the voice index in through an avalanche step
// rather than adding it keeps adjacent voices from producing visibly related
// streams.
std::uint32_t derive_state(std::uint32_t seed, int voiceIndex) {
    std::uint64_t z = (static_cast<std::uint64_t>(seed) << 32) ^ 0x9E3779B97F4A7C15ULL;
    z += static_cast<std::uint64_t>(voiceIndex + 1) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    z = z ^ (z >> 31);
    const std::uint32_t state = static_cast<std::uint32_t>(z ^ (z >> 32));
    // xorshift is stuck forever at zero, so it is the one state to avoid.
    return state == 0U ? 0x6D2B79F5U : state;
}

}  // namespace

NoiseSource::NoiseSource(std::uint32_t seed, int voiceIndex)
    : state_(derive_state(seed, voiceIndex)) {
    for (int row = 0; row < kPinkRows; ++row) {
        rows_[row] = next_bipolar();
        running_sum_ += rows_[row];
    }
}

std::uint32_t NoiseSource::next_u32() {
    // xorshift32. Unsigned overflow and shifts are fully defined, so this is
    // the same sequence of bits on every platform.
    state_ ^= state_ << 13;
    state_ ^= state_ >> 17;
    state_ ^= state_ << 5;
    return state_;
}

double NoiseSource::next_bipolar() {
    // Unsigned-to-double conversion only: casting a large uint32 to int32 would
    // be implementation-defined before C++20.
    return (static_cast<double>(next_u32()) / 4294967296.0) * 2.0 - 1.0;
}

double NoiseSource::white() {
    return next_bipolar();
}

double NoiseSource::pink() {
    // Voss-McCartney: each row is refreshed half as often as the one before it,
    // so summing them stacks equal energy per octave into a 1/f slope. The row
    // to refresh is the number of trailing zeros in the sample counter.
    ++counter_;
    std::uint32_t remaining = counter_;
    int row = 0;
    while (row < kPinkRows && (remaining & 1U) == 0U) {
        remaining >>= 1;
        ++row;
    }
    if (row < kPinkRows) {
        running_sum_ -= rows_[row];
        rows_[row] = next_bipolar();
        running_sum_ += rows_[row];
    }
    // Dividing by the row count plus the per-sample white row keeps the result
    // inside [-1, 1) without a peak-tracking pass.
    return (running_sum_ + next_bipolar()) / static_cast<double>(kPinkRows + 1);
}

}  // namespace blipsmith
