#include "expression.h"

#include "tables.h"

namespace blipsmith {
namespace {

// The published bounds of the fields touch moves.
constexpr double kMaxFmIndex = 24.0;
constexpr double kMinCutoffHz = 20.0;
constexpr double kMaxAttackMs = 10000.0;

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

}  // namespace blipsmith
