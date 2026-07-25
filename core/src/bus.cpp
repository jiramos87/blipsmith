#include "bus.h"

#include <cmath>

#include "tables.h"

namespace blipsmith {
namespace {

constexpr double kFullScale = 1.0;

double absolute(double value) {
    return value < 0.0 ? -value : value;
}

}  // namespace

VoiceGains voice_gains(double pan, double mixDb, int channels) {
    const double level = db_to_linear(mixDb);
    VoiceGains gains;
    if (channels < 2) {
        gains.left = level;
        gains.right = level;
        return gains;
    }

    double position = pan;
    if (!(position > -1.0)) {  // the negated form also catches NaN
        position = -1.0;
    }
    if (position > 1.0) {
        position = 1.0;
    }

    // The square-root pan law: the two gains square to 1, so power is constant
    // across the image and a centred voice sits at -3 dB per side.
    gains.left = level * std::sqrt((1.0 - position) * 0.5);
    gains.right = level * std::sqrt((1.0 + position) * 0.5);
    return gains;
}

MasterBus::MasterBus(std::uint32_t frames, int channels)
    : mix_(static_cast<std::size_t>(frames) * static_cast<std::size_t>(channels < 1 ? 1 : channels),
           0.0),
      channels_(channels < 1 ? 1 : channels) {}

void MasterBus::add(std::uint32_t frame, double sample, const VoiceGains& gains) {
    const std::size_t base =
        static_cast<std::size_t>(frame) * static_cast<std::size_t>(channels_);
    if (base >= mix_.size()) {
        return;
    }
    mix_[base] += sample * gains.left;
    if (channels_ > 1) {
        mix_[base + 1] += sample * gains.right;
    }
}

std::vector<double> MasterBus::finish(const Master& master) {
    const double masterGain = db_to_linear(master.gainDb);
    double peak = 0.0;
    for (double& sample : mix_) {
        sample *= masterGain;
        const double magnitude = absolute(sample);
        if (magnitude > peak) {
            peak = magnitude;
        }
    }

    if (peak > 0.0) {
        const double scale = db_to_linear(master.limiter.targetDbfs) / peak;
        for (double& sample : mix_) {
            sample *= scale;
        }
    }

    // Defense in depth. Normalization already put the peak on target, so this
    // has nothing left to catch through the spec surface; it is here so that no
    // future stage can put an out-of-range sample into the encoder.
    for (double& sample : mix_) {
        if (sample > kFullScale) {
            sample = kFullScale;
        } else if (sample < -kFullScale) {
            sample = -kFullScale;
        }
    }

    return std::move(mix_);
}

}  // namespace blipsmith
