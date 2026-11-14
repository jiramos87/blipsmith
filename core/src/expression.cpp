#include "expression.h"

#include "env.h"
#include "fm4.h"
#include "osc.h"
#include "pluck.h"
#include "tables.h"

namespace blipsmith {
namespace {

// The published bounds of the fields touch moves.
constexpr double kMaxFmIndex = 24.0;
// A four-operator modulator at level 1 is 4 pi radians deep, so a level is a
// depth in radians times this, and the index bound is this level.
constexpr double kLevelPerRadian = 0.0795774715459476678844418816862571;
constexpr double kMaxModulatorLevel = kMaxFmIndex * kLevelPerRadian;
constexpr double kMinCutoffHz = 20.0;
constexpr double kMaxAttackMs = 10000.0;

constexpr double kCentsPerOctave = 1200.0;
constexpr double kSemitonesPerOctave = 12.0;

}  // namespace

void apply_touch(const Voice& voice, double velocity, Voice& out) {
    const Touch& touch = voice.touch;
    const double t = velocity - touch.pivot;

    if (voice.hasFm && touch.fmIndex != 0.0) {
        double index = voice.fm.index + touch.fmIndex * t;
        if (index < 0.0) {
            index = 0.0;
        } else if (index > kMaxFmIndex) {
            index = kMaxFmIndex;
        }
        out.fm.index = index;
    }
    // On four operators the index moves every modulator in proportion to its
    // level: one at level 0 stays silent, and the carriers are left alone, since
    // level already follows velocity.
    if (voice.hasFm4 && touch.fmIndex != 0.0) {
        const Fm4Algorithm& algorithm = fm4_algorithm(voice.fm4.algorithm);
        std::uint8_t modulators = 0;
        for (int i = 0; i < kFm4Operators; ++i) {
            modulators |= algorithm.modulators[i];
        }
        for (int i = 0; i < kFm4Operators; ++i) {
            if (((modulators >> i) & 1U) == 0) {
                continue;
            }
            const double level = voice.fm4.operators[i].level;
            double touched = level + touch.fmIndex * t * level * kLevelPerRadian;
            if (touched < 0.0) {
                touched = 0.0;
            } else if (touched > kMaxModulatorLevel) {
                touched = kMaxModulatorLevel;
            }
            out.fm4.operators[i].level = touched;
        }
    }
    // On a string the same octaves move the pluck's or hammer's corner.
    if (voice.hasString && touch.cutoffOctaves != 0.0) {
        double brightness = voice.string.brightness + touch.cutoffOctaves * t / kStringBrightnessOctaves;
        if (brightness < 0.0) {
            brightness = 0.0;
        } else if (brightness > 1.0) {
            brightness = 1.0;
        }
        out.string.brightness = brightness;
    }
    // The ceiling below Nyquist is the filter's own, applied where it designs.
    if (voice.hasFilter && touch.cutoffOctaves != 0.0) {
        const double cutoff = voice.filter.cutoffHz * octave_ratio(touch.cutoffOctaves * t);
        out.filter.cutoffHz = cutoff < kMinCutoffHz ? kMinCutoffHz : cutoff;
    }
    // A harder hit attacks faster, so the shift runs against the velocity.
    if (touch.attackOctaves != 0.0) {
        const double attack = voice.ampEnv.attackMs * octave_ratio(-touch.attackOctaves * t);
        out.ampEnv.attackMs = attack > kMaxAttackMs ? kMaxAttackMs : attack;
    }
}

PitchExpression vibrato_expression(const Voice& voice, int sampleRate) {
    PitchExpression expression;
    if (!voice.hasVibrato || !(voice.vibrato.depthCents > 0.0)) {
        return expression;
    }
    expression.hasVibrato = true;
    expression.vibratoDelayFrames = ms_to_frames(voice.vibrato.delayMs, sampleRate);
    expression.vibratoFadeFrames = ms_to_frames(voice.vibrato.fadeMs, sampleRate);
    expression.vibratoIncrement = phase_increment(voice.vibrato.rateHz, sampleRate);
    expression.vibratoOctaves = voice.vibrato.depthCents / kCentsPerOctave;
    return expression;
}

void add_glide(const Voice& voice, const ScheduledNote* previous, const ScheduledNote& note,
               int sampleRate, PitchExpression& expression) {
    if (!voice.hasGlide || previous == nullptr || previous->midiNote < 0 || note.midiNote < 0) {
        return;
    }
    if (voice.glide.mode == GlideMode::Legato) {
        const std::uint64_t releasedAt =
            std::uint64_t{previous->startFrame} + previous->heldFrames;
        if (releasedAt < note.startFrame) {
            return;
        }
    }
    expression.glideFrames = ms_to_frames(voice.glide.timeMs, sampleRate);
    expression.glideOctaves =
        static_cast<double>(previous->midiNote - note.midiNote) / kSemitonesPerOctave;
}

}  // namespace blipsmith
