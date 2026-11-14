#include "expression.h"

#include "env.h"
#include "osc.h"
#include "tables.h"

namespace blipsmith {
namespace {

// The published bounds of the fields touch moves.
constexpr double kMaxFmIndex = 24.0;
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
