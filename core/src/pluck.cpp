#include "pluck.h"

#include <cmath>
#include <cstdint>
#include <vector>

#include "osc.h"
#include "tables.h"

namespace blipsmith {

namespace {

// The lowest pitch the line is long enough for; a lower one plays at this.
constexpr double kMinHz = 20.0;
// The Lagrange read needs two samples either side of its point, and the loss
// filter one more, so a period is never shorter than this.
constexpr double kMinPeriod = 4.0;
// 60 dB as octaves of amplitude: three decades, 3 x log2(10).
constexpr double kDecayOctaves = 9.965784284662087;
// The loop gain's ceiling, so a string always dies away.
constexpr double kMaxLoopGain = 0.9999999;
// Matches the filters' own ceiling below Nyquist.
constexpr double kMaxCornerFraction = 0.45;
constexpr double kPluckResonance = 0.7071067811865476;
constexpr double kBodyResonance = 3.0;
constexpr double kBodyBoost = 2.0;

// A raised cosine across `width` samples, sampled at their centres.
double hammer(std::uint32_t n, std::uint32_t width) {
    const double turns = (static_cast<double>(n) + 0.5) / static_cast<double>(width);
    return 0.5 - 0.5 * sine_at_phase(turns_to_increment(turns) + kQuarterTurn);
}

}  // namespace

PluckedString::PluckedString(const String& string, int sampleRate)
    : string_(string), sampleRate_(sampleRate) {
    maxPeriod_ = static_cast<double>(sampleRate) / kMinHz;
    std::uint32_t size = 1;
    while (static_cast<double>(size) < maxPeriod_ + 8.0) {
        size <<= 1;
    }
    line_.assign(size, 0.0);
    mask_ = size - 1;
    loss_ = 0.25 * string.damping;
    hasBody_ = string.body > 0.0;
    if (hasBody_) {
        body_.set(biquad_coefficients(FilterType::Bandpass, string.bodyHz, kBodyResonance,
                                      sampleRate));
    }
}

double PluckedString::period_for(double turns) const {
    if (!(turns > 0.0)) {  // the negated form also catches NaN
        return maxPeriod_;
    }
    const double period = 1.0 / turns;
    if (period < kMinPeriod) {
        return kMinPeriod;
    }
    return period > maxPeriod_ ? maxPeriod_ : period;
}

// One period of the line: the pluck's noise through a lowpass, or what one
// hammer pulse leaves, both shaped by the same corner; then the comb of the place along the
// string, the mean taken out (a string has no DC to ring) and the level set to
// unit RMS, so a bright and a dull setting land alike.
void PluckedString::excite(double period, NoiseSource& noise) {
    std::uint32_t length = static_cast<std::uint32_t>(period + 0.5);
    const double pitchHz = static_cast<double>(sampleRate_) / period;
    const double corner = pitchHz * octave_ratio(kStringBrightnessOctaves * string_.brightness);
    const double ceiling = kMaxCornerFraction * static_cast<double>(sampleRate_);

    std::vector<double> burst(length, 0.0);
    if (string_.excitation == Excitation::Strike) {
        double width = static_cast<double>(sampleRate_) / corner;
        if (width < 2.0) {
            width = 2.0;
        }
        std::uint32_t samples = static_cast<std::uint32_t>(width + 0.5);
        if (samples > length) {
            samples = length;
        }
        double area = 0.0;
        for (std::uint32_t n = 0; n < samples; ++n) {
            burst[n] = hammer(n, samples);
            area += burst[n];
        }
        // A hammer gives the string a velocity, not a shape: the line holds its
        // integral, taken around the period with the mean out so it closes.
        const double mean = area / static_cast<double>(length);
        double displacement = 0.0;
        for (double& value : burst) {
            displacement += value - mean;
            value = displacement;
        }
    } else {
        for (double& value : burst) {
            value = noise.white();
        }
        if (corner < ceiling) {
            // Round the loop twice, keeping the second: the filter's start-up is
            // spent on the first, and the burst stays one seamless cycle.
            Biquad tone;
            tone.set(biquad_coefficients(FilterType::Lowpass, corner, kPluckResonance,
                                         sampleRate_));
            for (const double value : burst) {
                tone.process(value);
            }
            for (double& value : burst) {
                value = tone.process(value);
            }
        }
    }

    std::uint32_t offset = static_cast<std::uint32_t>(string_.position * period + 0.5);
    if (offset < 1) {
        offset = 1;
    }
    std::vector<double> shaped(length, 0.0);
    double sum = 0.0;
    for (std::uint32_t n = 0; n < length; ++n) {
        const std::uint32_t back = (n + length - offset % length) % length;
        shaped[n] = burst[n] - burst[back];
        sum += shaped[n];
    }
    const double mean = sum / static_cast<double>(length);
    double power = 0.0;
    for (double& value : shaped) {
        value -= mean;
        power += value * value;
    }
    const double scale =
        power > 0.0 ? 1.0 / std::sqrt(power / static_cast<double>(length)) : 0.0;
    for (const double value : shaped) {
        line_[write_ & mask_] = value * scale;
        ++write_;
    }
}

// The line `delay` samples back, 1 being the newest sample: a 4-point Lagrange
// interpolation between the two points either side.
double PluckedString::read(double delay) const {
    const std::uint32_t whole = static_cast<std::uint32_t>(delay);
    const double mu = delay - static_cast<double>(whole);
    const double before = line_[(write_ - (whole - 1)) & mask_];
    const double at = line_[(write_ - whole) & mask_];
    const double after = line_[(write_ - (whole + 1)) & mask_];
    const double far = line_[(write_ - (whole + 2)) & mask_];
    const double m1 = mu - 1.0;
    const double m2 = mu - 2.0;
    const double p1 = mu + 1.0;
    return -mu * m1 * m2 / 6.0 * before + p1 * m1 * m2 / 2.0 * at - p1 * mu * m2 / 2.0 * after +
           p1 * mu * m1 / 6.0 * far;
}

// The gain each trip round the loop, so the string falls 60 dB over its decay
// time; worked out again only when the period moves.
double PluckedString::loop_gain(double period) {
    if (period != gainPeriod_) {
        gainPeriod_ = period;
        const double seconds = string_.decayMs / 1000.0;
        gain_ = octave_ratio(-kDecayOctaves * period /
                             (static_cast<double>(sampleRate_) * seconds));
        if (gain_ > kMaxLoopGain) {
            gain_ = kMaxLoopGain;
        }
    }
    return gain_;
}

double PluckedString::sample(double turns, NoiseSource& noise) {
    const double period = period_for(turns);
    if (!excited_) {
        excite(period, noise);
        excited_ = true;
    }
    // The loss filter adds one sample, so the read goes one short of the period.
    const double fresh = read(period - 1.0);
    const double lost = loss_ * fresh + (1.0 - 2.0 * loss_) * read1_ + loss_ * read2_;
    read2_ = read1_;
    read1_ = fresh;
    const double out = loop_gain(period) * lost;
    line_[write_ & mask_] = out;
    ++write_;
    if (hasBody_) {
        return out + string_.body * kBodyBoost * body_.process(out);
    }
    return out;
}

}  // namespace blipsmith
