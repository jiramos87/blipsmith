#include "fm4.h"

#include <cstdint>

#include "env.h"
#include "osc.h"
#include "tables.h"

namespace blipsmith {

namespace {

// The classic eight, operators numbered 1 to 4 (bits 0 to 3). Operators run in
// order, so every modulator is ready before the operator it feeds.
const Fm4Algorithm kFm4AlgorithmTable[kFm4Algorithms] = {
    {{0x0, 0x1, 0x2, 0x4}, 0x8},  // 0: 1 > 2 > 3 > 4
    {{0x0, 0x0, 0x3, 0x4}, 0x8},  // 1: (1 + 2) > 3 > 4
    {{0x0, 0x0, 0x2, 0x5}, 0x8},  // 2: (1 + (2 > 3)) > 4
    {{0x0, 0x1, 0x0, 0x6}, 0x8},  // 3: ((1 > 2) + 3) > 4
    {{0x0, 0x1, 0x0, 0x4}, 0xA},  // 4: (1 > 2) + (3 > 4)
    {{0x0, 0x1, 0x1, 0x1}, 0xE},  // 5: 1 > 2, 1 > 3, 1 > 4
    {{0x0, 0x1, 0x0, 0x0}, 0xE},  // 6: (1 > 2) + 3 + 4
    {{0x0, 0x0, 0x0, 0x0}, 0xF},  // 7: 1 + 2 + 3 + 4
};

constexpr double kCentsPerOctave = 1200.0;
// A modulator at level 1 swings its target by 4 pi radians: two turns.
constexpr double kDepthTurnsPerLevel = 2.0;
// Feedback 1 is pi radians: half a turn.
constexpr double kFeedbackTurns = 0.5;

// Whole turns folded away before the cast, so a deep offset cannot overflow
// it; the signed-to-unsigned conversion that follows wraps, as wanted.
std::uint32_t phase_offset(double turns) {
    turns -= static_cast<double>(static_cast<std::int64_t>(turns));
    return static_cast<std::uint32_t>(static_cast<std::int64_t>(turns * kPhaseScale));
}

}  // namespace

const Fm4Algorithm& fm4_algorithm(int index) {
    return kFm4AlgorithmTable[index < 0 || index >= kFm4Algorithms ? 0 : index];
}

FourOperator::FourOperator(const Fm4& fm4, int sampleRate) {
    algorithm_ = fm4_algorithm(fm4.algorithm);

    int carriers = 0;
    for (int i = 0; i < kFm4Operators; ++i) {
        const Operator& spec = fm4.operators[i];
        Op& op = ops_[i];
        const double detune =
            spec.detuneCents != 0.0 ? octave_ratio(spec.detuneCents / kCentsPerOctave) : 1.0;
        op.fixed = spec.fixedHz > 0.0;
        if (op.fixed) {
            op.fixedIncrement = phase_increment(spec.fixedHz * detune, sampleRate);
        } else {
            op.frequencyScale = spec.ratio * detune;
        }
        op.level = spec.level;
        op.depthTurns = spec.level * kDepthTurnsPerLevel;
        op.attackFrames = ms_to_frames(spec.attackMs, sampleRate);
        op.decayFrames = ms_to_frames(spec.decayMs, sampleRate);
        op.sustainLevel = spec.sustainLevel;
        if ((algorithm_.carriers >> i) & 1U) {
            ++carriers;
        }
    }
    // The carriers are summed and divided by their count, so a lone carrier at
    // level 1 plays at the level of a plain sine.
    carrierScale_ = 1.0 / static_cast<double>(carriers);
    feedbackTurns_ = fm4.feedback * kFeedbackTurns;
}

// Up over the attack, then a squared fall to the sustain level (fast, then
// slow, as a struck tone wants), held there to the end of the note's tail.
double FourOperator::envelope(const Op& op, std::uint32_t frame) const {
    if (frame < op.attackFrames) {
        return static_cast<double>(frame) / static_cast<double>(op.attackFrames);
    }
    const std::uint32_t sinceAttack = frame - op.attackFrames;
    if (sinceAttack < op.decayFrames) {
        const double remaining =
            1.0 - static_cast<double>(sinceAttack) / static_cast<double>(op.decayFrames);
        return op.sustainLevel + (1.0 - op.sustainLevel) * remaining * remaining;
    }
    return op.sustainLevel;
}

double FourOperator::sample(std::uint32_t frame, double turns) {
    double out[kFm4Operators];
    double sum = 0.0;
    for (int i = 0; i < kFm4Operators; ++i) {
        Op& op = ops_[i];
        double offset = 0.0;
        if (i == 0 && feedbackTurns_ != 0.0) {
            offset += feedbackTurns_ * 0.5 * (feedbackLast_ + feedbackBefore_);
        }
        const std::uint8_t feeds = algorithm_.modulators[i];
        for (int j = 0; j < i; ++j) {
            if ((feeds >> j) & 1U) {
                offset += out[j] * ops_[j].depthTurns;
            }
        }
        out[i] = sine_at_phase(op.phase + phase_offset(offset)) * envelope(op, frame);
        op.phase += op.fixed ? op.fixedIncrement : turns_to_increment(turns * op.frequencyScale);
        if ((algorithm_.carriers >> i) & 1U) {
            sum += out[i] * op.level;
        }
    }
    if (feedbackTurns_ != 0.0) {
        feedbackBefore_ = feedbackLast_;
        feedbackLast_ = out[0];
    }
    return sum * carrierScale_;
}

}  // namespace blipsmith
