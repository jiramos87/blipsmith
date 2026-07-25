// Baked tables: the sine wavetable and the MIDI-note-to-hertz map.
//
// Both exist because the obvious implementations reach for libm. `sin` and
// `pow` are per-platform routines whose last bits differ between glibc, Apple's
// libm, and WASM, so calling either even once at setup time would make the
// rendered bytes platform-dependent. Everything here is built from literal
// constants and IEEE-754-exact arithmetic instead, which the standard requires
// every platform to round identically.

#pragma once

#include <cstddef>

namespace blipsmith {

inline constexpr int kSineTableBits = 11;
inline constexpr std::size_t kSineTableSize = std::size_t{1} << kSineTableBits;

// kSineTableSize + 1 entries: the extra guard point repeats entry 0 so linear
// interpolation near the wrap needs no branch.
const double* sine_table();

// 440 Hz at note 69, equal temperament. Notes outside 0-127 clamp to the ends.
double midi_to_hz(int note);

// 2^octaves, the pitch multiplier for a modulation depth expressed in octaves.
// This is what `pow` or `exp2` would be asked for; both are per-platform, so it
// is built here from an exact integer power of two times a fixed-length series
// for the fraction. The argument saturates at +-24 octaves, well past hearing.
double octave_ratio(double octaves);

// A gain in decibels as a plain multiplier. `10^(db/20)` is `pow` twice over, so
// it goes through `octave_ratio` instead: an octave of amplitude is 6.02 dB, and
// that is a conversion, not an approximation.
double db_to_linear(double db);

// Silence has no decibel value. Reporting it as negative infinity would be
// honest and useless: it does not serialize to JSON and it cannot be compared.
// A floor two dozen dB below what 16-bit audio can even represent says the same
// thing and stays a number.
inline constexpr double kSilenceDbfs = -120.0;

// The inverse of `db_to_linear`, and banned for the same reason: `log10` is a
// per-platform routine. Built from an exact exponent split and a fixed-length
// series for what is left, so a feature an agent steers by is as reproducible
// as the audio it measures. Zero and anything negative report `kSilenceDbfs`.
double linear_to_db(double linear);

}  // namespace blipsmith
