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

// 2^-16: a tail is over once it has fallen this far, 96 dB, below 16-bit audio.
constexpr double kTailFloor = 1.0 / 65536.0;
constexpr std::uint32_t kMaxTailPasses = 100000;

// Allpasses ring at their own gain per pass whatever the room.
constexpr double kAllpassTailGain = kAllpassGain;

std::uint32_t saturate(std::uint64_t frames) {
    return frames > 0xFFFFFFFFULL ? 0xFFFFFFFFU : static_cast<std::uint32_t>(frames);
}

std::uint32_t passes_until_floor(double gainPerPass) {
    double level = 1.0;
    std::uint32_t passes = 1;
    while (level * gainPerPass > kTailFloor && passes < kMaxTailPasses) {
        level *= gainPerPass;
        ++passes;
    }
    return passes;
}

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

Reverb::Reverb(double roomSize, double damping, double mixWet, int sampleRate, int stereoSpread)
    : feedback_(kMinRoomFeedback + kRoomFeedbackSpan * roomSize),
      damping_(damping),
      mixWet_(mixWet) {
    for (std::size_t i = 0; i < kCombs; ++i) {
        combs_[i].buffer.assign(scaled_length(kCombLengths[i] + stereoSpread, sampleRate), 0.0);
    }
    for (std::size_t i = 0; i < kAllpasses; ++i) {
        allpasses_[i].buffer.assign(scaled_length(kAllpassLengths[i] + stereoSpread, sampleRate),
                                    0.0);
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

EffectChain::EffectChain(const std::vector<Effect>& effects, int sampleRate, int stereoSpread) {
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
                unit.reverb.emplace(effect.roomSize, effect.damping, effect.mixWet, sampleRate,
                                    stereoSpread);
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

// --- Tails --------------------------------------------------------------------

std::uint32_t effect_tail_frames(const Effect& effect, int sampleRate) {
    switch (effect.kind) {
        case EffectKind::Delay: {
            std::uint32_t length = ms_to_frames(effect.timeMs, sampleRate);
            if (length < 1U) {
                length = 1U;
            }
            return saturate(std::uint64_t{length} * passes_until_floor(effect.feedback));
        }
        case EffectKind::Reverb: {
            // The longest comb, at the right channel's spread, sets the pace; the
            // allpasses add their own ringing on top.
            const double feedback = kMinRoomFeedback + kRoomFeedbackSpan * effect.roomSize;
            const std::size_t comb =
                scaled_length(kCombLengths[3] + kReverbStereoSpread, sampleRate);
            std::size_t allpass = 0;
            for (const int length : kAllpassLengths) {
                allpass += scaled_length(length + kReverbStereoSpread, sampleRate);
            }
            return saturate(std::uint64_t{comb} * passes_until_floor(feedback) +
                            std::uint64_t{allpass} * passes_until_floor(kAllpassTailGain));
        }
        case EffectKind::Distortion:
        case EffectKind::Wavefold:
            break;
    }
    return 0;
}

std::uint32_t chain_tail_frames(const std::vector<Effect>& effects, int sampleRate) {
    std::uint64_t total = 0;
    for (const Effect& effect : effects) {
        total += effect_tail_frames(effect, sampleRate);
    }
    return saturate(total);
}

}  // namespace blipsmith
