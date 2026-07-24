#include "env.h"

namespace blipsmith {
namespace {

std::uint32_t ms_to_frames(double ms, int sampleRate) {
    if (ms <= 0.0 || sampleRate <= 0) {
        return 0;
    }
    const double frames = (ms * static_cast<double>(sampleRate)) / 1000.0;
    return static_cast<std::uint32_t>(frames);
}

}  // namespace

AmpEnvelope::AmpEnvelope(const Adsr& adsr, std::uint32_t totalFrames, int sampleRate)
    : attackFrames_(ms_to_frames(adsr.attackMs, sampleRate)),
      decayFrames_(ms_to_frames(adsr.decayMs, sampleRate)),
      releaseFrames_(ms_to_frames(adsr.releaseMs, sampleRate)),
      sustainLevel_(adsr.sustainLevel) {
    releaseStart_ = totalFrames > releaseFrames_ ? totalFrames - releaseFrames_ : 0;

    // The release is never allowed to start before the attack and decay have
    // run. Without this, any render shorter than releaseMs would begin its
    // fade-out at frame zero, where the level is still silence, and the whole
    // file would come out silent: a short blip with a long default release is
    // exactly the case an agent would hit first.
    const std::uint32_t earliest = attackFrames_ + decayFrames_;
    if (releaseStart_ < earliest) {
        releaseStart_ = earliest;
    }
    if (releaseStart_ > totalFrames) {
        releaseStart_ = totalFrames;
    }

    // Whatever room is left is the release, so the tail still lands on silence
    // exactly at the end of the file.
    releaseFrames_ = totalFrames - releaseStart_;
    levelAtRelease_ = sustained(releaseStart_);
}

double AmpEnvelope::sustained(std::uint32_t frame) const {
    if (frame < attackFrames_) {
        return static_cast<double>(frame) / static_cast<double>(attackFrames_);
    }
    const std::uint32_t sinceAttack = frame - attackFrames_;
    if (sinceAttack < decayFrames_) {
        const double progress =
            static_cast<double>(sinceAttack) / static_cast<double>(decayFrames_);
        return 1.0 - (1.0 - sustainLevel_) * progress * progress;
    }
    return sustainLevel_;
}

double AmpEnvelope::at(std::uint32_t frame) const {
    if (frame < releaseStart_) {
        return sustained(frame);
    }
    if (releaseFrames_ == 0) {
        return sustained(frame);
    }
    const double progress =
        static_cast<double>(frame - releaseStart_) / static_cast<double>(releaseFrames_);
    const double remaining = 1.0 - progress;
    return levelAtRelease_ * remaining * remaining;
}

}  // namespace blipsmith
