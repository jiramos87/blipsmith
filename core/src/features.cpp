#include "features.h"

#include <cmath>
#include <cstddef>

#include "osc.h"
#include "tables.h"

namespace blipsmith {
namespace {

// A power of two, and no larger than the sine table, so every twiddle below is
// an exact table entry rather than an interpolation between two of them.
constexpr std::size_t kFftSize = 1024;
constexpr std::size_t kFftBits = 10;
constexpr std::uint32_t kFftPhaseStep = static_cast<std::uint32_t>(0x100000000ULL / kFftSize);

// The window the pitch estimator looks at. Long enough to hold several cycles
// of the lowest pitch the synth can make, short enough to stay cheap.
constexpr std::size_t kPitchWindow = 4096;
constexpr std::size_t kMinPitchWindow = 64;

// The pitch search range, as the frequencies the oscillators themselves cover.
constexpr double kMinPitchHz = 20.0;
constexpr double kMaxPitchHz = 8000.0;

// How close to the peak counts as "arrived", when timing the attack.
constexpr double kAttackThreshold = 0.99;

double magnitude_of(double real, double imaginary) {
    return std::sqrt(real * real + imaginary * imaginary);
}

// --- The transform ------------------------------------------------------------

// Iterative radix-2 Cooley-Tukey, in place.
//
// This is where the backlog item called for vendored kissfft. kissfft builds
// its twiddles with `cos` and `sin` from the host libm, which the determinism
// invariant bars and `scripts/check_no_libm.py` would reject outright. The
// transform itself is only butterflies, so the part worth borrowing is small,
// and reading twiddles from the baked table makes them exact at this size
// instead of merely close.
void fft(double* real, double* imaginary) {
    // Bit-reversal permutation.
    for (std::size_t i = 1, j = 0; i < kFftSize; ++i) {
        std::size_t bit = kFftSize >> 1;
        for (; (j & bit) != 0; bit >>= 1) {
            j ^= bit;
        }
        j ^= bit;
        if (i < j) {
            const double swapReal = real[i];
            real[i] = real[j];
            real[j] = swapReal;
            const double swapImaginary = imaginary[i];
            imaginary[i] = imaginary[j];
            imaginary[j] = swapImaginary;
        }
    }

    for (std::size_t stage = 1; stage <= kFftBits; ++stage) {
        const std::size_t span = std::size_t{1} << stage;
        const std::size_t half = span >> 1;
        const std::uint32_t step = kFftPhaseStep * static_cast<std::uint32_t>(kFftSize / span);

        for (std::size_t start = 0; start < kFftSize; start += span) {
            std::uint32_t phase = 0;
            for (std::size_t k = 0; k < half; ++k) {
                // e^(-2i*pi*k/span): cosine on the real axis, negated sine on
                // the imaginary one.
                const double twiddleReal = sine_at_phase(phase + kQuarterTurn);
                const double twiddleImaginary = -sine_at_phase(phase);
                phase += step;

                const std::size_t even = start + k;
                const std::size_t odd = even + half;
                const double oddReal =
                    real[odd] * twiddleReal - imaginary[odd] * twiddleImaginary;
                const double oddImaginary =
                    real[odd] * twiddleImaginary + imaginary[odd] * twiddleReal;

                real[odd] = real[even] - oddReal;
                imaginary[odd] = imaginary[even] - oddImaginary;
                real[even] += oddReal;
                imaginary[even] += oddImaginary;
            }
        }
    }
}

// --- Measurements -------------------------------------------------------------

std::vector<double> to_mono(const std::vector<double>& interleaved, int channels) {
    if (channels < 2) {
        return interleaved;
    }
    const std::size_t frames = interleaved.size() / static_cast<std::size_t>(channels);
    std::vector<double> mono(frames, 0.0);
    for (std::size_t frame = 0; frame < frames; ++frame) {
        double sum = 0.0;
        for (int channel = 0; channel < channels; ++channel) {
            sum += interleaved[frame * static_cast<std::size_t>(channels) +
                               static_cast<std::size_t>(channel)];
        }
        mono[frame] = sum / static_cast<double>(channels);
    }
    return mono;
}

// Time from the first sample to the first one that reaches the render's peak.
// The plain "time to peak" reading rather than a 10-90% rise time, because an
// agent that asked for a 50 ms attack wants to be told 50 ms.
double attack_time_ms(const std::vector<double>& mono, double peak, int sampleRate) {
    if (peak <= 0.0 || sampleRate <= 0) {
        return 0.0;
    }
    const double threshold = peak * kAttackThreshold;
    for (std::size_t i = 0; i < mono.size(); ++i) {
        const double magnitude = mono[i] < 0.0 ? -mono[i] : mono[i];
        if (magnitude >= threshold) {
            return (static_cast<double>(i) * 1000.0) / static_cast<double>(sampleRate);
        }
    }
    return 0.0;
}

// Autocorrelation, read past the first dip.
//
// Taking the highest peak outright would answer lag zero, where every signal
// correlates perfectly with itself. Walking down the initial slope first, then
// taking the best peak after it, finds the period instead. The parabola through
// the winning lag and its neighbours recovers the fraction of a sample between
// them, which at 440 Hz is the difference between a 2% error and a rounding one.
double estimate_fundamental_hz(const std::vector<double>& mono, double peak, int sampleRate) {
    if (peak <= 0.0 || sampleRate <= 0) {
        return 0.0;
    }

    // Analyse from the loudest point onward: that is where the sound is most
    // itself, and where a decaying one still has something to measure.
    std::size_t start = 0;
    double loudest = 0.0;
    for (std::size_t i = 0; i < mono.size(); ++i) {
        const double magnitude = mono[i] < 0.0 ? -mono[i] : mono[i];
        if (magnitude > loudest) {
            loudest = magnitude;
            start = i;
        }
    }
    if (mono.size() - start < kMinPitchWindow) {
        start = 0;
    }

    const std::size_t length =
        mono.size() - start < kPitchWindow ? mono.size() - start : kPitchWindow;
    if (length < kMinPitchWindow) {
        return 0.0;
    }

    // A constant offset correlates with itself at every lag, so it would drown
    // out the periodicity. Remove it first.
    double mean = 0.0;
    for (std::size_t i = 0; i < length; ++i) {
        mean += mono[start + i];
    }
    mean /= static_cast<double>(length);

    std::vector<double> window(length);
    for (std::size_t i = 0; i < length; ++i) {
        window[i] = mono[start + i] - mean;
    }

    std::size_t minLag = static_cast<std::size_t>(static_cast<double>(sampleRate) / kMaxPitchHz);
    if (minLag < 2) {
        minLag = 2;
    }
    std::size_t maxLag = static_cast<std::size_t>(static_cast<double>(sampleRate) / kMinPitchHz);
    if (maxLag > length / 2) {
        maxLag = length / 2;
    }
    if (maxLag <= minLag + 1) {
        return 0.0;
    }

    // Normalized square difference rather than raw autocorrelation. A raw sum
    // has fewer terms at a long lag than at a short one, so every peak leans
    // downhill and the parabola below slides off the true period. Dividing by
    // the overlap count instead over-corrects: at long lags there is little
    // signal left to average, the noise inflates, and the estimator answers
    // with a sub-octave. Dividing by the energy actually in the overlap is
    // bounded either way, which is McLeod's normalization.
    std::vector<double> correlation(maxLag + 1, 0.0);
    for (std::size_t lag = 0; lag <= maxLag; ++lag) {
        double product = 0.0;
        double energy = 0.0;
        for (std::size_t i = 0; i + lag < length; ++i) {
            product += window[i] * window[i + lag];
            energy += window[i] * window[i] + window[i + lag] * window[i + lag];
        }
        correlation[lag] = energy > 0.0 ? (2.0 * product) / energy : 0.0;
    }

    std::size_t lag = minLag;
    while (lag + 1 < maxLag && correlation[lag + 1] < correlation[lag]) {
        ++lag;
    }

    std::size_t best = lag;
    for (std::size_t k = lag; k <= maxLag; ++k) {
        if (correlation[k] > correlation[best]) {
            best = k;
        }
    }
    if (correlation[best] <= 0.0 || best == 0) {
        return 0.0;
    }

    // Every multiple of the period correlates about as well as the period does,
    // and once normalized they are within a hair of each other, so taking the
    // highest peak outright reports an arbitrary octave down. The fundamental
    // is the *first* peak that comes close to the best one.
    const double threshold = 0.75 * correlation[best];
    for (std::size_t k = lag + 1; k + 1 <= maxLag; ++k) {
        if (correlation[k] >= threshold && correlation[k] >= correlation[k - 1] &&
            correlation[k] >= correlation[k + 1]) {
            best = k;
            break;
        }
    }

    double refined = static_cast<double>(best);
    if (best >= 1 && best + 1 <= maxLag) {
        const double before = correlation[best - 1];
        const double at = correlation[best];
        const double after = correlation[best + 1];
        const double curvature = before - 2.0 * at + after;
        if (curvature != 0.0) {
            refined += 0.5 * (before - after) / curvature;
        }
    }
    if (!(refined > 0.0)) {
        return 0.0;
    }
    return static_cast<double>(sampleRate) / refined;
}

// The centre of mass of the spectrum: the one number that says "bright" or
// "dark". Averaged over every full window of the render, so a sound that opens
// up as it goes is described by all of itself rather than by its first 46 ms.
double spectral_centroid_hz(const std::vector<double>& mono, int sampleRate) {
    if (mono.empty() || sampleRate <= 0) {
        return 0.0;
    }

    // Hann, from the same table as everything else. Windowing matters here:
    // a rectangular window smears every partial across the spectrum and drags
    // the centroid upward by more than the difference being measured.
    static const std::vector<double> window = [] {
        std::vector<double> shape(kFftSize);
        const std::uint32_t step = static_cast<std::uint32_t>(0x100000000ULL / kFftSize);
        std::uint32_t phase = 0;
        for (std::size_t i = 0; i < kFftSize; ++i) {
            shape[i] = 0.5 - 0.5 * sine_at_phase(phase + kQuarterTurn);
            phase += step;
        }
        return shape;
    }();

    std::vector<double> spectrum(kFftSize / 2 + 1, 0.0);
    std::vector<double> real(kFftSize);
    std::vector<double> imaginary(kFftSize);

    std::size_t windows = 0;
    for (std::size_t offset = 0; offset + kFftSize <= mono.size(); offset += kFftSize) {
        for (std::size_t i = 0; i < kFftSize; ++i) {
            real[i] = mono[offset + i] * window[i];
            imaginary[i] = 0.0;
        }
        fft(real.data(), imaginary.data());
        for (std::size_t bin = 0; bin <= kFftSize / 2; ++bin) {
            spectrum[bin] += magnitude_of(real[bin], imaginary[bin]);
        }
        ++windows;
    }

    if (windows == 0) {
        // Shorter than one window: zero-pad rather than report nothing.
        for (std::size_t i = 0; i < kFftSize; ++i) {
            real[i] = i < mono.size() ? mono[i] * window[i] : 0.0;
            imaginary[i] = 0.0;
        }
        fft(real.data(), imaginary.data());
        for (std::size_t bin = 0; bin <= kFftSize / 2; ++bin) {
            spectrum[bin] = magnitude_of(real[bin], imaginary[bin]);
        }
    }

    const double binHz = static_cast<double>(sampleRate) / static_cast<double>(kFftSize);
    double weighted = 0.0;
    double total = 0.0;
    // From bin 1: bin 0 is DC, which a pulse wave has plenty of and which is
    // not part of what anyone means by brightness.
    for (std::size_t bin = 1; bin <= kFftSize / 2; ++bin) {
        weighted += static_cast<double>(bin) * binHz * spectrum[bin];
        total += spectrum[bin];
    }
    return total > 0.0 ? weighted / total : 0.0;
}

}  // namespace

Features measure(const std::vector<double>& interleaved, int sampleRate, int channels) {
    Features features;
    if (sampleRate <= 0 || interleaved.empty()) {
        features.peakDbfs = kSilenceDbfs;
        features.rmsDbfs = kSilenceDbfs;
        return features;
    }

    const std::vector<double> mono = to_mono(interleaved, channels);
    features.durationMs =
        (static_cast<double>(mono.size()) * 1000.0) / static_cast<double>(sampleRate);

    double peak = 0.0;
    double sumOfSquares = 0.0;
    for (const double sample : mono) {
        const double magnitude = sample < 0.0 ? -sample : sample;
        if (magnitude > peak) {
            peak = magnitude;
        }
        sumOfSquares += sample * sample;
    }

    features.peakDbfs = linear_to_db(peak);
    features.rmsDbfs = linear_to_db(std::sqrt(sumOfSquares / static_cast<double>(mono.size())));
    features.attackTimeMs = attack_time_ms(mono, peak, sampleRate);
    features.estimatedFundamentalHz = estimate_fundamental_hz(mono, peak, sampleRate);
    features.spectralCentroidHz = spectral_centroid_hz(mono, sampleRate);
    return features;
}

}  // namespace blipsmith
