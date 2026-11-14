// Loudness the way a broadcast meter reads it, without libm.
//
// Integrated loudness follows ITU-R BS.1770: each channel through the
// K-weighting filters (a high shelf, then a high pass), mean squares over
// 400 ms blocks that step by 100 ms, an absolute gate at -70 LUFS and a
// relative one 10 LU below the gated mean. A file shorter than one block is
// measured as one block. True peak is the largest magnitude after 4x
// oversampling, so a peak that falls between two samples still counts.
//
// The filter and interpolator constants are baked for every supported sample
// rate (loudness_tables.h); the decibels come from the same exponent split as
// every other feature. These are measures only: no rendered byte depends on
// them.

#pragma once

#include <vector>

namespace blipsmith {

// -120 (silence) when nothing passes the gates.
double integrated_lufs(const std::vector<double>& interleaved, int sampleRate, int channels);

double true_peak_dbtp(const std::vector<double>& interleaved, int channels);

}  // namespace blipsmith
