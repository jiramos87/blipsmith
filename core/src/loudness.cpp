#include "loudness.h"

#include <cmath>
#include <cstddef>

#include "loudness_tables.h"
#include "tables.h"

namespace blipsmith {
namespace {

constexpr double kBlockMs = 400.0;
constexpr double kStepMs = 100.0;
constexpr double kLoudnessOffset = -0.691;
constexpr double kAbsoluteGateLufs = -70.0;
constexpr double kRelativeGateLu = -10.0;

const KWeighting* weighting_for(int sampleRate) {
    for (const KWeighting& entry : kKWeighting) {
        if (entry.sampleRate == sampleRate) {
            return &entry;
        }
    }
    return nullptr;
}

// Direct form I, coefficients as {b0, b1, b2, a1, a2}.
class Stage {
public:
    explicit Stage(const double* c) : c_(c) {}

    double process(double x) {
        const double y = c_[0] * x + c_[1] * x1_ + c_[2] * x2_ - c_[3] * y1_ - c_[4] * y2_;
        x2_ = x1_;
        x1_ = x;
        y2_ = y1_;
        y1_ = y;
        return y;
    }

private:
    const double* c_;
    double x1_ = 0.0;
    double x2_ = 0.0;
    double y1_ = 0.0;
    double y2_ = 0.0;
};

// 10 * log10(power), as 20 * log10 of its square root, which is exact.
double power_to_lufs(double power) {
    return kLoudnessOffset + linear_to_db(std::sqrt(power));
}

}  // namespace

double integrated_lufs(const std::vector<double>& interleaved, int sampleRate, int channels) {
    const KWeighting* weighting = weighting_for(sampleRate);
    const std::size_t width = static_cast<std::size_t>(channels < 1 ? 1 : channels);
    const std::size_t frames = interleaved.size() / width;
    if (weighting == nullptr || frames == 0) {
        return kSilenceDbfs;
    }

    // Squared K-weighted samples summed over the channels, each weighted 1:
    // BS.1770 gives left and right (and mono) the same weight.
    std::vector<double> squared(frames, 0.0);
    for (std::size_t channel = 0; channel < width; ++channel) {
        Stage shelf(weighting->shelf);
        Stage highpass(weighting->highpass);
        for (std::size_t frame = 0; frame < frames; ++frame) {
            const double y = highpass.process(shelf.process(interleaved[frame * width + channel]));
            squared[frame] += y * y;
        }
    }

    const std::size_t block = static_cast<std::size_t>(
        kBlockMs * static_cast<double>(sampleRate) / 1000.0);
    const std::size_t step = static_cast<std::size_t>(
        kStepMs * static_cast<double>(sampleRate) / 1000.0);
    std::vector<double> powers;
    if (frames < block) {
        double sum = 0.0;
        for (const double value : squared) {
            sum += value;
        }
        powers.push_back(sum / static_cast<double>(frames));
    } else {
        for (std::size_t start = 0; start + block <= frames; start += step) {
            double sum = 0.0;
            for (std::size_t i = start; i < start + block; ++i) {
                sum += squared[i];
            }
            powers.push_back(sum / static_cast<double>(block));
        }
    }

    double gatedSum = 0.0;
    std::size_t gatedCount = 0;
    for (const double power : powers) {
        if (power > 0.0 && power_to_lufs(power) > kAbsoluteGateLufs) {
            gatedSum += power;
            ++gatedCount;
        }
    }
    if (gatedCount == 0) {
        return kSilenceDbfs;
    }
    const double relativeGate =
        power_to_lufs(gatedSum / static_cast<double>(gatedCount)) + kRelativeGateLu;

    double sum = 0.0;
    std::size_t count = 0;
    for (const double power : powers) {
        if (power > 0.0) {
            const double lufs = power_to_lufs(power);
            if (lufs > kAbsoluteGateLufs && lufs > relativeGate) {
                sum += power;
                ++count;
            }
        }
    }
    return count == 0 ? kSilenceDbfs : power_to_lufs(sum / static_cast<double>(count));
}

double true_peak_dbtp(const std::vector<double>& interleaved, int channels) {
    const std::size_t width = static_cast<std::size_t>(channels < 1 ? 1 : channels);
    const std::size_t frames = interleaved.size() / width;
    double peak = 0.0;
    for (std::size_t channel = 0; channel < width; ++channel) {
        for (std::size_t frame = 0; frame < frames; ++frame) {
            const double own = interleaved[frame * width + channel];
            double magnitude = own < 0.0 ? -own : own;
            if (magnitude > peak) {
                peak = magnitude;
            }
            for (int phase = 0; phase < kTruePeakPhases; ++phase) {
                double value = 0.0;
                for (int tap = 0; tap < kTruePeakTaps; ++tap) {
                    const std::ptrdiff_t at = static_cast<std::ptrdiff_t>(frame) +
                                              kTruePeakFirstTap + tap;
                    if (at < 0 || static_cast<std::size_t>(at) >= frames) {
                        continue;
                    }
                    value += interleaved[static_cast<std::size_t>(at) * width + channel] *
                             kTruePeakInterpolator[phase][tap];
                }
                magnitude = value < 0.0 ? -value : value;
                if (magnitude > peak) {
                    peak = magnitude;
                }
            }
        }
    }
    return linear_to_db(peak);
}

}  // namespace blipsmith
