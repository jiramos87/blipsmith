#include "env.h"

namespace blipsmith {

std::uint32_t ms_to_frames(double ms, int sampleRate) {
    if (ms <= 0.0 || sampleRate <= 0) {
        return 0;
    }
    const double frames = (ms * static_cast<double>(sampleRate)) / 1000.0;
    return static_cast<std::uint32_t>(frames);
}

AmpEnvelope::AmpEnvelope(const Adsr& adsr, std::uint32_t totalFrames, int sampleRate)
    : totalFrames_(totalFrames),
      attackFrames_(ms_to_frames(adsr.attackMs, sampleRate)),
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

AmpEnvelope AmpEnvelope::gated(const Adsr& adsr, std::uint32_t heldFrames, int sampleRate) {
    AmpEnvelope envelope;
    envelope.attackFrames_ = ms_to_frames(adsr.attackMs, sampleRate);
    envelope.decayFrames_ = ms_to_frames(adsr.decayMs, sampleRate);
    envelope.sustainLevel_ = adsr.sustainLevel;

    // The key-up is where the note says it is, even if the attack never
    // finished: a sixteenth note through a 200 ms attack is meant to be a
    // clipped stab, not a full one.
    envelope.releaseStart_ = heldFrames;
    envelope.releaseFrames_ = ms_to_frames(adsr.releaseMs, sampleRate);
    envelope.totalFrames_ = heldFrames + envelope.releaseFrames_;
    envelope.levelAtRelease_ = envelope.sustained(heldFrames);
    return envelope;
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
    // Past the tail there is nothing left. A one-shot never asks (its buffer
    // ends with the envelope), but a note's caller may, and squaring a negative
    // remaining fraction would grow instead of fade.
    if (frame >= totalFrames_) {
        return 0.0;
    }
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
