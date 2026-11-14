// Plucked and struck strings (music mode): a string in place of the oscillator.
//
// A Karplus-Strong loop in the shape Jaffe and Smith gave it: one period of a
// delay line, read back a fraction of a sample at a time, through a loss filter
// and a loop gain, and written in again. The pluck or hammer fills the line once
// at the note's start; from then on the string rings on its own.
//
// Every part of the loop has a gain of at most 1: the 4-point Lagrange read is
// centred between its middle points, the loss filter is [c, 1 - 2c, c] with c at
// most a quarter, and the loop gain is 2 to a negative power, held below 1. So a
// string decays at every legal setting. The loss filter is symmetric, a delay
// of exactly one sample at every frequency, which keeps the tuning to the read.
//
// The period comes from the voice's pitch every frame, so glide, vibrato and the
// pitch modulators move the string. The excitation's noise is the voice's own
// seeded stream, fresh on each note, so a note renders the same wherever it
// sits. Nothing here reaches for libm: the decay goes through `octave_ratio`,
// the hammer and the filters read the baked sine, and the level uses sqrt.

#pragma once

#include <cstdint>
#include <vector>

#include "filter.h"
#include "noise.h"
#include "spec_parse.h"

namespace blipsmith {

// The octaves a string's brightness spans: its excitation's corner sits from
// the pitch (0) to this many octaves above it (1). Touch moves it in octaves.
inline constexpr double kStringBrightnessOctaves = 7.0;

class PluckedString {
public:
    PluckedString(const String& string, int sampleRate);

    // One sample of the string, given the voice's pitch this frame in turns per
    // sample. The first call fills the line from `noise` (a pluck) or a hammer
    // (a strike) at that frame's pitch. Call once per frame, in frame order.
    double sample(double turns, NoiseSource& noise);

private:
    double period_for(double turns) const;
    void excite(double period, NoiseSource& noise);
    double read(double delay) const;
    double loop_gain(double period);

    String string_;
    int sampleRate_;
    std::vector<double> line_;
    std::uint32_t mask_ = 0;
    std::uint32_t write_ = 0;
    double maxPeriod_ = 0.0;
    bool excited_ = false;
    double loss_ = 0.0;
    double read1_ = 0.0;
    double read2_ = 0.0;
    double gainPeriod_ = -1.0;
    double gain_ = 0.0;
    bool hasBody_ = false;
    Biquad body_;
};

}  // namespace blipsmith
