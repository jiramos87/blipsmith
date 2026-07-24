#include "osc.h"

#include <cstddef>

#include "tables.h"

namespace blipsmith {
namespace {

constexpr double kPhaseScale = 4294967296.0;  // 2^32
constexpr std::uint32_t kHalfTurn = 0x80000000U;

// Phase as a fraction of a turn, in [0, 1).
double turn_of(std::uint32_t phase) {
    return static_cast<double>(phase) / kPhaseScale;
}

double interpolated_sine(std::uint32_t phase) {
    const double* table = sine_table();
    constexpr int kFractionBits = 32 - kSineTableBits;
    const std::uint32_t index = phase >> kFractionBits;
    const std::uint32_t fraction = phase & ((1U << kFractionBits) - 1U);
    const double weight = static_cast<double>(fraction) / static_cast<double>(1U << kFractionBits);
    const double a = table[index];
    const double b = table[index + 1];
    return a + (b - a) * weight;
}

}  // namespace

std::uint32_t phase_increment(double frequencyHz, int sampleRate) {
    if (sampleRate <= 0 || frequencyHz <= 0.0) {
        return 0;
    }
    double turns = frequencyHz / static_cast<double>(sampleRate);
    // Fold whole turns away before the cast: a frequency at or above the sample
    // rate would otherwise overflow the conversion, which is undefined.
    turns -= static_cast<double>(static_cast<std::int64_t>(turns));
    if (turns < 0.0) {
        turns += 1.0;
    }
    return static_cast<std::uint32_t>(turns * kPhaseScale);
}

bool is_noise(Waveform waveform) {
    return waveform == Waveform::NoiseWhite || waveform == Waveform::NoisePink;
}

double oscillator_sample(Waveform waveform, std::uint32_t phase, double pulseDuty) {
    switch (waveform) {
        case Waveform::Sine:
            return interpolated_sine(phase);

        case Waveform::Square:
            return phase < kHalfTurn ? 1.0 : -1.0;

        case Waveform::Saw:
            return 2.0 * turn_of(phase) - 1.0;

        case Waveform::Triangle: {
            const double turn = turn_of(phase);
            return turn < 0.5 ? (4.0 * turn - 1.0) : (3.0 - 4.0 * turn);
        }

        case Waveform::Pulse: {
            const std::uint32_t threshold = static_cast<std::uint32_t>(pulseDuty * kPhaseScale);
            return phase < threshold ? 1.0 : -1.0;
        }

        case Waveform::NoiseWhite:
        case Waveform::NoisePink:
            return 0.0;
    }
    return 0.0;
}

}  // namespace blipsmith
