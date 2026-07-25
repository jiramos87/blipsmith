#include "fx.h"

#include <cstdint>

#include "env.h"

namespace blipsmith {
namespace {

// How hard full drive pushes into each shaper. The clipper wants enough gain to
// square a sine off; the folder wants less, because every extra unit of gain
// adds another fold and the timbre gets thin rather than louder.
constexpr double kClipDriveGain = 24.0;
constexpr double kFoldDriveGain = 8.0;

// Past this the fold's turn count stops being meaningful, and it keeps the cast
// below inside the range where it is defined.
constexpr double kMaxFoldInput = 1000000.0;

// Freeverb's comb and allpass lengths, in samples at 44.1 kHz. Mutually prime,
// which is what stops the echoes from lining up into a ringing pitch.
constexpr int kCombLengths[] = {1116, 1188, 1277, 1356};
constexpr int kAllpassLengths[] = {556, 441};
constexpr double kReferenceRate = 44100.0;

// A comb's feedback, from the shortest tail that still reads as a room to the
// longest that still decays inside a game sound effect.
constexpr double kMinRoomFeedback = 0.70;
constexpr double kRoomFeedbackSpan = 0.28;

// Four combs summing in parallel multiply the input by roughly 1/(1 - feedback)
// each, so the wet path needs trimming to come back near unity.
constexpr double kReverbInputGain = 0.03;
constexpr double kAllpassGain = 0.5;

std::size_t scaled_length(int referenceSamples, int sampleRate) {
    const double scaled =
        (static_cast<double>(referenceSamples) * static_cast<double>(sampleRate)) / kReferenceRate;
    const std::int64_t rounded = static_cast<std::int64_t>(scaled + 0.5);
    return rounded < 1 ? std::size_t{1} : static_cast<std::size_t>(rounded);
}

double blend(double dry, double wet, double mixWet) {
    return (1.0 - mixWet) * dry + mixWet * wet;
}

}  // namespace

// --- Waveshapers --------------------------------------------------------------

double soft_clip(double sample) {
    if (sample >= 1.0) {
        return 1.0;
    }
    if (sample <= -1.0) {
        return -1.0;
    }
    // The cubic that meets +-1 with zero slope, so the knee is smooth and the
    // shaper never overshoots full scale.
    return sample * (1.5 - 0.5 * sample * sample);
}

double wave_fold(double sample) {
    double value = sample;
    if (!(value > -kMaxFoldInput)) {  // the negated form also catches NaN
        value = -kMaxFoldInput;
    }
    if (value > kMaxFoldInput) {
        value = kMaxFoldInput;
    }

    // Map to turns of a triangle with period 4, fold whole turns away, and read
    // the triangle back. On [-1, 1] this is the identity; past it the signal
    // reflects instead of clipping, which is the whole character of the effect.
    double turn = (value + 1.0) * 0.25;
    turn -= static_cast<double>(static_cast<std::int64_t>(turn));
    if (turn < 0.0) {
        turn += 1.0;
    }
    const double position = turn * 4.0;
    return position < 2.0 ? position - 1.0 : 3.0 - position;
}

// --- Delay --------------------------------------------------------------------

DelayLine::DelayLine(double timeMs, double feedback, double mixWet, int sampleRate)
    : feedback_(feedback), mixWet_(mixWet) {
    const std::uint32_t frames = ms_to_frames(timeMs, sampleRate);
    buffer_.assign(frames < 1U ? 1U : frames, 0.0);
}

double DelayLine::process(double sample) {
    const double delayed = buffer_[index_];
    buffer_[index_] = sample + delayed * feedback_;
    ++index_;
    if (index_ >= buffer_.size()) {
        index_ = 0;
    }
    return blend(sample, delayed, mixWet_);
}

// --- Reverb -------------------------------------------------------------------

Reverb::Reverb(double roomSize, double damping, double mixWet, int sampleRate)
    : feedback_(kMinRoomFeedback + kRoomFeedbackSpan * roomSize),
      damping_(damping),
      mixWet_(mixWet) {
    for (std::size_t i = 0; i < kCombs; ++i) {
        combs_[i].buffer.assign(scaled_length(kCombLengths[i], sampleRate), 0.0);
    }
    for (std::size_t i = 0; i < kAllpasses; ++i) {
        allpasses_[i].buffer.assign(scaled_length(kAllpassLengths[i], sampleRate), 0.0);
    }
}

double Reverb::process(double sample) {
    const double input = sample * kReverbInputGain;

    double wet = 0.0;
    for (Comb& comb : combs_) {
        const double out = comb.buffer[comb.index];
        // A one-pole lowpass inside the loop: each pass round the comb loses a
        // little more top end, which is what makes a tail sound like a room
        // rather than like a bank of echoes.
        comb.store = out * (1.0 - damping_) + comb.store * damping_;
        comb.buffer[comb.index] = input + comb.store * feedback_;
        ++comb.index;
        if (comb.index >= comb.buffer.size()) {
            comb.index = 0;
        }
        wet += out;
    }

    for (Allpass& allpass : allpasses_) {
        const double buffered = allpass.buffer[allpass.index];
        const double out = buffered - wet;
        allpass.buffer[allpass.index] = wet + buffered * kAllpassGain;
        ++allpass.index;
        if (allpass.index >= allpass.buffer.size()) {
            allpass.index = 0;
        }
        wet = out;
    }

    return blend(sample, wet, mixWet_);
}

// --- The chain ----------------------------------------------------------------

EffectChain::EffectChain(const std::vector<Effect>& effects, int sampleRate) {
    units_.reserve(effects.size());
    for (const Effect& effect : effects) {
        Unit unit;
        unit.kind = effect.kind;
        unit.drive = effect.drive;
        switch (effect.kind) {
            case EffectKind::Delay:
                unit.delay.emplace(effect.timeMs, effect.feedback, effect.mixWet, sampleRate);
                break;
            case EffectKind::Reverb:
                unit.reverb.emplace(effect.roomSize, effect.damping, effect.mixWet, sampleRate);
                break;
            case EffectKind::Distortion:
            case EffectKind::Wavefold:
                break;
        }
        units_.push_back(std::move(unit));
    }
}

double EffectChain::process(double sample) {
    double value = sample;
    for (Unit& unit : units_) {
        switch (unit.kind) {
            case EffectKind::Distortion:
                value = blend(value, soft_clip(value * (1.0 + unit.drive * kClipDriveGain)),
                              unit.drive);
                break;
            case EffectKind::Wavefold:
                value = blend(value, wave_fold(value * (1.0 + unit.drive * kFoldDriveGain)),
                              unit.drive);
                break;
            case EffectKind::Delay:
                value = unit.delay->process(value);
                break;
            case EffectKind::Reverb:
                value = unit.reverb->process(value);
                break;
        }
    }
    return value;
}

}  // namespace blipsmith
