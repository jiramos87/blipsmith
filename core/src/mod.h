// Modulation: FM, AM/ring, the LFO, and the mod envelope.
//
// All four live in the same fixed-point phase domain as the oscillators. FM and
// LFO-to-pitch move the carrier's phase increment, AM/ring and LFO-to-amplitude
// scale the sample, and anything routed to cutoff becomes a per-sample control
// signal the filter reads.
//
// Depth conventions, fixed here because the spec expresses them as normalized
// amounts and something has to say what "full depth" means:
//
//  - `modEnv.amount` is the direction the pitch (or cutoff) *travels over time*,
//    which is how the published schema describes it: negative sweeps downward.
//    The envelope contour starts at full and returns to none, so the sound
//    starts displaced in the opposite direction and arrives at the fundamental.
//    An amount of -1 starts four octaves up and falls: the classic laser drop.
//  - `lfo.depth` of 1 swings pitch by +-2 octaves (a siren) and cutoff likewise.
//    Amplitude is a plain tremolo: full depth dips to silence and back.
//
// Nothing here reaches for libm. The pitch multiplier goes through
// `octave_ratio`, and the FM operator is a phase offset added to an unsigned
// accumulator, so it wraps by overflow rather than by any comparison.

#pragma once

#include <cstdint>

#include "spec_parse.h"

namespace blipsmith {

// The mod envelope's contour: silence to full over `attackMs`, then back to
// none over `decayMs`, and none thereafter. The fall is squared for the same
// reason the amplitude envelope's is: percussive material wants fast-then-slow,
// and squaring gets it with a multiply instead of an exponential.
class ModEnvelope {
public:
    ModEnvelope(const ModEnv& env, int sampleRate);

    // Contour in [0, 1], before `amount` decides depth and direction.
    double at(std::uint32_t frame) const;

private:
    std::uint32_t attackFrames_ = 0;
    std::uint32_t decayFrames_ = 0;
};

// One voice's modulation, assembled once and stepped one frame at a time.
class Modulation {
public:
    Modulation(const Voice& voice, double frequencyHz, int sampleRate);

    // Advance every modulator by one frame. Call once per frame, before the
    // accessors below are read.
    void step(std::uint32_t frame);

    // The carrier's phase increment for this frame, after pitch modulation.
    std::uint32_t carrierIncrement() const { return carrierIncrement_; }

    // FM: what to add to the carrier phase for this frame's sample.
    std::uint32_t fmPhaseOffset() const { return fmPhaseOffset_; }

    // AM/ring as a gain on the carrier, applied before the amplitude envelope.
    double amGain() const { return amGain_; }

    // LFO-to-amplitude, applied after the envelope. 1.0 when unrouted.
    double tremoloGain() const { return tremoloGain_; }

    // What to multiply the filter cutoff by this frame; 1.0 when nothing is
    // routed there. The filter is the consumer, so a voice with no filter on it
    // renders as if the routing were not there at all.
    double cutoffRatio() const { return cutoffRatio_; }

    // Whether that ratio moves. The filter recomputes its coefficients every
    // frame when it does, and only once when it does not.
    bool modulatesCutoff() const { return hasCutoffModulation_; }

private:
    double pitchOctaves(double envelope) const;
    double cutoffOctaves(double envelope) const;

    bool hasModEnv_ = false;
    bool hasLfo_ = false;
    bool hasFm_ = false;
    bool hasAm_ = false;
    bool hasPitchModulation_ = false;
    bool hasCutoffModulation_ = false;

    ModEnv modEnv_;
    Lfo lfo_;
    Fm fm_;
    Am am_;
    ModEnvelope modEnvelope_;

    double baseTurns_ = 0.0;
    std::uint32_t baseIncrement_ = 0;

    std::uint32_t lfoPhase_ = 0;
    std::uint32_t lfoIncrement_ = 0;
    std::uint32_t amPhase_ = 0;
    std::uint32_t amIncrement_ = 0;
    std::uint32_t fmPhase_ = 0;

    std::uint32_t carrierIncrement_ = 0;
    std::uint32_t fmPhaseOffset_ = 0;
    double amGain_ = 1.0;
    double tremoloGain_ = 1.0;
    double cutoffRatio_ = 1.0;
};

}  // namespace blipsmith
