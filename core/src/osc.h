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

// One full turn of the phase accumulator, as a double: 2^32.
inline constexpr double kPhaseScale = 4294967296.0;

// A quarter turn: the offset that turns a sine lookup into a cosine.
inline constexpr std::uint32_t kQuarterTurn = 0x40000000U;

// The baked sine at a phase, which is every cosine and sine this core is
// allowed to ask for. Filter coefficients and FFT twiddles read it too, not
// just the oscillators.
double sine_at_phase(std::uint32_t phase);

// How far the phase advances per frame. Frequencies at or above the sample rate
// fold rather than overflow, so no input can produce undefined behaviour.
std::uint32_t phase_increment(double frequencyHz, int sampleRate);

// The same conversion from a pitch already expressed in turns per sample.
// Modulation recomputes this every frame, since vibrato and a pitch envelope
// move the increment while the sound plays.
std::uint32_t turns_to_increment(double turnsPerSample);

// A point in a cycle given in turns, as a phase: whole turns fold away. A
// unison copy starts its partials and operators here.
std::uint32_t turns_to_phase(double turns);

// Returns a sample in [-1, 1]. Noise waveforms return 0 here: they carry state
// and live in NoiseSource.
double oscillator_sample(Waveform waveform, std::uint32_t phase, double pulseDuty);

bool is_noise(Waveform waveform);

}  // namespace blipsmith
