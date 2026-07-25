#include "lofi.h"

#include <cstdint>

namespace blipsmith {
namespace {

constexpr int kMaxBitDepth = 16;
constexpr int kMaxDecimation = 64;

// Steps either side of zero at the requested depth. Built by doubling so the
// value is exact, rather than by pow, which is banned from this path anyway.
double quantization_levels(int bitDepth) {
    int depth = bitDepth < 1 ? 1 : bitDepth;
    if (depth > kMaxBitDepth) {
        depth = kMaxBitDepth;
    }
    double levels = 1.0;
    for (int i = 1; i < depth; ++i) {
        levels *= 2.0;
    }
    return levels;
}

// Round half away from zero, the same rule the WAV encoder uses, so the two
// grids agree instead of drifting apart by an LSB.
double quantize(double sample, double levels, double inverseLevels) {
    const double scaled = sample * levels;
    const double biased = scaled >= 0.0 ? scaled + 0.5 : scaled - 0.5;
    return static_cast<double>(static_cast<std::int64_t>(biased)) * inverseLevels;
}

}  // namespace

LoFiStage::LoFiStage(const LoFi& lofi)
    : levels_(quantization_levels(lofi.bitDepth)) {
    inverseLevels_ = 1.0 / levels_;
    decimation_ = lofi.decimation < 1 ? 1 : lofi.decimation;
    if (decimation_ > kMaxDecimation) {
        decimation_ = kMaxDecimation;
    }
}

double LoFiStage::process(double sample) {
    // Quantize first, then hold: holding an already-quantized value gives the
    // same result as quantizing the held one, and this way the grid is applied
    // exactly once per frame.
    if (counter_ == 0) {
        held_ = quantize(sample, levels_, inverseLevels_);
    }
    ++counter_;
    if (counter_ >= decimation_) {
        counter_ = 0;
    }
    return held_;
}

}  // namespace blipsmith
