// A deterministic resonant biquad: lowpass, highpass, bandpass.
//
// The coefficients are the standard bilinear-transform (RBJ cookbook) forms,
// which need sin(w0) and cos(w0). Both come from the same baked sine table the
// oscillators read, because even a once-per-render `sin` call would put a
// per-platform routine into the rendered bytes: coefficients are not a
// side-channel, they are the sound.
//
// They are read at the *half* angle and combined through the double-angle
// identities, which costs nothing and keeps the small-angle terms accurate.
// Taking `1 - cos(w0)` directly would cancel four digits away at a low cutoff,
// where `2 sin^2(w0/2)` stays exact to the table's own precision.
//
// Direct Form I, deliberately: when an LFO or the mod envelope moves the cutoff,
// the coefficients change every frame, and DF1 keeps its history in the signal
// rather than in a state that a coefficient change would reinterpret.

#pragma once

#include "spec_parse.h"

namespace blipsmith {

struct BiquadCoefficients {
    double b0 = 1.0;
    double b1 = 0.0;
    double b2 = 0.0;
    double a1 = 0.0;
    double a2 = 0.0;
};

// The cutoff a render can actually use: positive, and below Nyquist with the
// margin a biquad needs. The Python layer applies the same ceiling to the spec
// and reports it as a `clamped` warning (`ranges.MAX_CUTOFF_FRACTION` is the
// source of truth); this is the safety net for a cutoff that modulation moved
// after validation, where there is no caller left to warn.
double usable_cutoff(double cutoffHz, int sampleRate);

BiquadCoefficients biquad_coefficients(FilterType type, double cutoffHz, double resonance,
                                       int sampleRate);

class Biquad {
public:
    void set(const BiquadCoefficients& coefficients) { coefficients_ = coefficients; }

    double process(double sample);

private:
    BiquadCoefficients coefficients_;
    double x1_ = 0.0;
    double x2_ = 0.0;
    double y1_ = 0.0;
    double y2_ = 0.0;
};

}  // namespace blipsmith
