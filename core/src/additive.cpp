#include "additive.h"

#include <cmath>
#include <cstdint>
#include <vector>

#include "env.h"
#include "osc.h"
#include "tables.h"

namespace blipsmith {

namespace {

// 60 dB as octaves of amplitude: three decades, 3 x log2(10).
constexpr double kDecayOctaves = 9.965784284662087;
// The band limit: full level below the first, silent from the second.
constexpr double kBandFull = 0.35;
constexpr double kBandSilent = 0.45;
// Below this a decaying partial is silent for good, so a long note does not
// spend its frames on numbers too small to hear.
constexpr double kDecayFloor = 1e-9;

double clamp_unit(double value) {
    if (!(value > 0.0)) {  // the negated form also catches NaN
        return 0.0;
    }
    return value > 1.0 ? 1.0 : value;
}

// One over the root of the summed squares, so the set sounds as loud as one
// full sine; silence stays silence.
double unit_rms_scale(const std::vector<double>& levels) {
    double power = 0.0;
    for (const double level : levels) {
        power += level * level;
    }
    return power > 0.0 ? 1.0 / std::sqrt(power) : 0.0;
}

double band_gain(double partialTurns) {
    if (partialTurns <= kBandFull) {
        return 1.0;
    }
    if (partialTurns >= kBandSilent) {
        return 0.0;
    }
    return (kBandSilent - partialTurns) / (kBandSilent - kBandFull);
}

}  // namespace

AdditiveSource::AdditiveSource(const Wavetable& wavetable, int sampleRate, double startTurns) {
    std::size_t harmonics = 1;
    for (const std::vector<double>& frame : wavetable.frames) {
        harmonics = frame.size() > harmonics ? frame.size() : harmonics;
    }
    for (const std::vector<double>& frame : wavetable.frames) {
        std::vector<double> scaled(harmonics, 0.0);
        const double scale = unit_rms_scale(frame);
        for (std::size_t h = 0; h < frame.size(); ++h) {
            scaled[h] = frame[h] * scale;
        }
        frames_.push_back(scaled);
    }
    if (frames_.empty()) {
        frames_.push_back(std::vector<double>(harmonics, 0.0));
        frames_[0][0] = 1.0;
    }
    tones_.resize(harmonics);
    for (std::size_t h = 0; h < harmonics; ++h) {
        tones_[h].ratio = static_cast<double>(h + 1);
    }
    positionStart_ = clamp_unit(wavetable.position);
    positionEnd_ = wavetable.positionEnd < 0.0 ? positionStart_ : clamp_unit(wavetable.positionEnd);
    sweepFrames_ = ms_to_frames(wavetable.sweepMs, sampleRate);
    start_phases(startTurns);
    place(positionStart_);
}

AdditiveSource::AdditiveSource(const Additive& additive, int sampleRate, double startTurns) {
    std::vector<double> levels;
    for (const Partial& partial : additive.partials) {
        levels.push_back(partial.level);
    }
    const double scale = unit_rms_scale(levels);
    // The roll-off's corner, in ratios of the pitch; at brightness 1 it sits so
    // far up that every partial keeps its level.
    const double corner =
        octave_ratio(kAdditiveBrightnessOctaves * clamp_unit(additive.brightness));
    const bool rollsOff = additive.brightness < 1.0;
    for (const Partial& partial : additive.partials) {
        Tone tone;
        tone.ratio = partial.ratio;
        if (additive.stretch > 0.0) {
            tone.ratio = partial.ratio * std::sqrt(1.0 + additive.stretch * partial.ratio *
                                                             partial.ratio);
        }
        double rolloff = 1.0;
        if (rollsOff) {
            const double above = tone.ratio / corner;
            const double squared = above * above;
            rolloff = 1.0 / (1.0 + squared * squared);
        }
        tone.level = partial.level * scale * rolloff;
        if (partial.decayMs > 0.0 && sampleRate > 0) {
            const double frames = static_cast<double>(sampleRate) * partial.decayMs / 1000.0;
            tone.shrink = octave_ratio(-kDecayOctaves / frames);
        }
        tones_.push_back(tone);
    }
    start_phases(startTurns);
}

void AdditiveSource::start_phases(double startTurns) {
    if (startTurns == 0.0) {
        return;
    }
    for (Tone& tone : tones_) {
        tone.phase = turns_to_phase(startTurns * tone.ratio);
    }
}

// Each partial's step and band gain at this frame's pitch; worked out again
// only when the pitch moves.
void AdditiveSource::tune(double turns) {
    lastTurns_ = turns;
    for (Tone& tone : tones_) {
        double partialTurns = turns * tone.ratio;
        if (!(partialTurns > 0.0)) {
            partialTurns = 0.0;
        }
        tone.band = band_gain(partialTurns);
        tone.increment = turns_to_increment(partialTurns);
    }
}

// A wavetable's levels at a read position: the two frames either side,
// crossfaded.
void AdditiveSource::place(double position) {
    placedAt_ = position;
    const std::size_t last = frames_.size() - 1;
    const double at = position * static_cast<double>(last);
    std::size_t below = static_cast<std::size_t>(at);
    double mix = at - static_cast<double>(below);
    if (below >= last) {
        below = last;
        mix = 0.0;
    }
    const std::vector<double>& from = frames_[below];
    const std::vector<double>& to = frames_[below < last ? below + 1 : last];
    for (std::size_t h = 0; h < tones_.size(); ++h) {
        tones_[h].level = mix == 0.0 ? from[h] : from[h] + (to[h] - from[h]) * mix;
    }
}

double AdditiveSource::sample(double turns) {
    if (turns != lastTurns_) {
        tune(turns);
    }
    if (!frames_.empty() && positionEnd_ != positionStart_) {
        double position = positionEnd_;
        if (frame_ < sweepFrames_) {
            const double progress = static_cast<double>(frame_) / static_cast<double>(sweepFrames_);
            position = positionStart_ + (positionEnd_ - positionStart_) * progress;
        }
        if (position != placedAt_) {
            place(position);
        }
    }
    ++frame_;

    double out = 0.0;
    for (Tone& tone : tones_) {
        if (tone.level != 0.0 && tone.band > 0.0 && tone.decay > 0.0) {
            out += tone.level * tone.band * tone.decay * sine_at_phase(tone.phase);
        }
        tone.phase += tone.increment;
        if (tone.shrink < 1.0 && tone.decay > 0.0) {
            tone.decay *= tone.shrink;
            if (tone.decay < kDecayFloor) {
                tone.decay = 0.0;
            }
        }
    }
    return out;
}

}  // namespace blipsmith
