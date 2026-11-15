// Additive voices (music mode): a tone summed from sine partials, in place of
// the oscillator. One engine serves two blocks. A wavetable gives harmonic
// frames and a position that moves over the note, its levels crossfaded between
// two frames; an additive block gives partials at any ratio, each with its own
// decay. Each partial is a phase accumulator reading the baked sine at its
// ratio of the voice's pitch, worked out every frame, so glide, vibrato, the
// LFO and the pitch envelope move every partial together.
//
// Band limiting is per partial and per frame: a partial sounds in full below
// 0.35 turns per sample, fades linearly to silence at 0.45 (the filters' own
// ceiling) and stays silent above, so no partial folds back at any note and a
// glide across the ceiling fades rather than clicks.
//
// Nothing here reaches for libm: the sine is the table, a decay goes through
// `octave_ratio`, the levels through `sqrt`, which IEEE 754 rounds exactly.

#pragma once

#include <cstdint>
#include <vector>

#include "spec_parse.h"

namespace blipsmith {

// How far touch moves a wavetable's position: `cutoffOctaves` over this span of
// octaves crosses the whole table.
inline constexpr double kWavetableTouchOctaves = 4.0;
// The octaves an additive voice's brightness spans, as a string's does.
inline constexpr double kAdditiveBrightnessOctaves = 7.0;

class AdditiveSource {
public:
    // `startTurns` is where the fundamental's cycle starts, in turns; each
    // partial starts at the same moment of its own cycle, so a unison copy is
    // the same tone shifted in time.
    AdditiveSource(const Wavetable& wavetable, int sampleRate, double startTurns);
    AdditiveSource(const Additive& additive, int sampleRate, double startTurns);

    // One sample, given the voice's pitch this frame in turns per sample. Call
    // once per frame, in frame order.
    double sample(double turns);

private:
    struct Tone {
        double ratio = 1.0;
        double level = 0.0;
        double shrink = 1.0;
        double decay = 1.0;
        double band = 1.0;
        std::uint32_t phase = 0;
        std::uint32_t increment = 0;
    };

    void start_phases(double startTurns);
    void tune(double turns);
    void place(double position);

    std::vector<Tone> tones_;
    // A wavetable's frames, each scaled to one sine's loudness and as long as
    // the longest; empty for an additive block.
    std::vector<std::vector<double>> frames_;
    double positionStart_ = 0.0;
    double positionEnd_ = 0.0;
    std::uint32_t sweepFrames_ = 0;
    double placedAt_ = -1.0;
    double lastTurns_ = -1.0;
    std::uint32_t frame_ = 0;
};

}  // namespace blipsmith
