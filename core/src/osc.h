// Oscillators over a 32-bit fixed-point phase accumulator.
//
// Phase is an unsigned 32-bit counter spanning one full turn, so it wraps by
// overflow rather than by a floating-point comparison that could drift. Every
// waveform except sine is a closed-form function of that counter, which makes
// them exact; sine reads the baked table with linear interpolation.
//
// The shapes are deliberately naive: no band-limiting, so they alias just like
// the chips this instrument is imitating.

#pragma once

#include <cstdint>

#include "spec_parse.h"

namespace blipsmith {

// How far the phase advances per frame. Frequencies at or above the sample rate
// fold rather than overflow, so no input can produce undefined behaviour.
std::uint32_t phase_increment(double frequencyHz, int sampleRate);

// Returns a sample in [-1, 1]. Noise waveforms return 0 here: they carry state
// and live in NoiseSource.
double oscillator_sample(Waveform waveform, std::uint32_t phase, double pulseDuty);

bool is_noise(Waveform waveform);

}  // namespace blipsmith
