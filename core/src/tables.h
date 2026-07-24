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

}  // namespace blipsmith
