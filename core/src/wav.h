// Canonical PCM WAV encoding, written by us rather than by libsndfile so the
// output bytes stay under our control. The header is a fixed 44 bytes: RIFF,
// fmt (16-byte PCM), data. No LIST/INFO chunks, which is deliberate as much as
// minimal, since those conventionally carry timestamps or encoder names and
// would break byte-identity between two renders of the same spec.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace blipsmith {

inline constexpr std::size_t kWavHeaderBytes = 44;

// The one rounding rule for the whole project: scale by 32767, round half away
// from zero, then clamp to the int16 range. Uses only IEEE-754-exact operations
// and a truncating cast, so it produces identical bytes on every platform.
std::int16_t to_pcm16(double sample);

// `interleaved` holds frames * channels samples nominally in [-1, 1]; anything
// beyond is clamped by to_pcm16 rather than wrapping.
std::string encode_wav_pcm16(const std::vector<double>& interleaved, int sampleRate, int channels);

}  // namespace blipsmith
