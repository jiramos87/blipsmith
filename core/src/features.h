// What the render sounded like, in numbers.
//
// The driving agent cannot hear. Every render therefore comes back with these
// six measurements taken from the finished audio, so an agent that wanted a
// brighter sound can check whether it got one instead of guessing. They are
// measured, not restated from the spec: a spec asking for 440 Hz through a
// pitch envelope does not produce a 440 Hz sound, and the number that helps is
// the one that came out.
//
// Measured on the post-bus samples, before the int16 encoder, so they describe
// the audio the file contains at full precision.
//
// Determinism applies here too. A feature is something an agent steers by, so
// it has to be as reproducible as the PCM it measures: the FFT twiddles come
// from the same baked sine table as everything else, and the decibel conversion
// from the same exponent split. `libm` is no more available to analysis than it
// is to synthesis.

#pragma once

#include <cstdint>
#include <vector>

namespace blipsmith {

struct Features {
    double durationMs = 0.0;
    double peakDbfs = 0.0;
    double rmsDbfs = 0.0;
    // 0 when the render is too short, or too noisy, to hold a pitch.
    double estimatedFundamentalHz = 0.0;
    double spectralCentroidHz = 0.0;
    double attackTimeMs = 0.0;
};

// `interleaved` is the bus output: channel-interleaved samples in [-1, 1].
// Stereo is measured as the mono sum, since these describe the sound rather
// than its placement.
Features measure(const std::vector<double>& interleaved, int sampleRate, int channels);

}  // namespace blipsmith
