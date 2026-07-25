#include "filter.h"

#include <cstdint>

#include "osc.h"

namespace blipsmith {
namespace {

// Matches `ranges.MAX_CUTOFF_FRACTION` on the Python side.
constexpr double kMaxCutoffFraction = 0.45;
constexpr double kMinCutoffHz = 1.0;

}  // namespace

double usable_cutoff(double cutoffHz, int sampleRate) {
    if (sampleRate <= 0) {
        return kMinCutoffHz;
    }
    const double ceiling = kMaxCutoffFraction * static_cast<double>(sampleRate);
    if (!(cutoffHz > kMinCutoffHz)) {  // the negated form also catches NaN
        return kMinCutoffHz;
    }
    return cutoffHz > ceiling ? ceiling : cutoffHz;
}

BiquadCoefficients biquad_coefficients(FilterType type, double cutoffHz, double resonance,
                                       int sampleRate) {
    BiquadCoefficients pass_through;
    if (sampleRate <= 0 || !(resonance > 0.0)) {
        return pass_through;
    }

    // Half the corner angle, as a fraction of a turn. Reading the table here and
    // doubling below is what keeps `1 - cos` accurate at a low cutoff.
    const double halfTurn = usable_cutoff(cutoffHz, sampleRate) / (2.0 * sampleRate);
    const std::uint32_t phase = turns_to_increment(halfTurn);
    const double s = sine_at_phase(phase);                 // sin(w0/2)
    const double c = sine_at_phase(phase + kQuarterTurn);  // cos(w0/2)

    const double sinW = 2.0 * s * c;
    const double cosW = (c - s) * (c + s);
    const double oneMinusCos = 2.0 * s * s;
    const double onePlusCos = 2.0 * c * c;

    const double alpha = sinW / (2.0 * resonance);
    const double a0 = 1.0 + alpha;
    if (!(a0 > 0.0)) {
        return pass_through;
    }
    const double inverse = 1.0 / a0;

    BiquadCoefficients out;
    switch (type) {
        case FilterType::Highpass:
            out.b0 = 0.5 * onePlusCos * inverse;
            out.b1 = -onePlusCos * inverse;
            out.b2 = out.b0;
            break;
        case FilterType::Bandpass:
            // Constant peak gain: unity at the corner, falling either side.
            out.b0 = alpha * inverse;
            out.b1 = 0.0;
            out.b2 = -out.b0;
            break;
        case FilterType::Lowpass:
            out.b0 = 0.5 * oneMinusCos * inverse;
            out.b1 = oneMinusCos * inverse;
            out.b2 = out.b0;
            break;
    }
    out.a1 = -2.0 * cosW * inverse;
    out.a2 = (1.0 - alpha) * inverse;
    return out;
}

double Biquad::process(double sample) {
    const double out = coefficients_.b0 * sample + coefficients_.b1 * x1_ +
                       coefficients_.b2 * x2_ - coefficients_.a1 * y1_ -
                       coefficients_.a2 * y2_;
    x2_ = x1_;
    x1_ = sample;
    y2_ = y1_;
    y1_ = out;
    return out;
}

}  // namespace blipsmith
