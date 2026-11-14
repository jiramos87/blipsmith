#include "mod.h"

#include <cstdint>

#include "env.h"
#include "osc.h"
#include "tables.h"

namespace blipsmith {
namespace {

// Depth conventions, spelled out in mod.h.
constexpr double kModEnvPitchOctaves = 4.0;
constexpr double kLfoPitchOctaves = 2.0;
constexpr double kModEnvCutoffOctaves = 4.0;
constexpr double kLfoCutoffOctaves = 2.0;

// 1 / 2pi: FM's modulation index is stated in radians, and phase here is
// counted in turns.
constexpr double kTurnsPerRadian = 0.159154943091895335768883763372514;

Waveform waveform_of(LfoShape shape) {
    switch (shape) {
        case LfoShape::Triangle:
            return Waveform::Triangle;
        case LfoShape::Square:
            return Waveform::Square;
        case LfoShape::Saw:
            return Waveform::Saw;
        case LfoShape::Sine:
            break;
    }
    return Waveform::Sine;
}

// A bipolar modulator in [-1, 1] read from the shared oscillator table.
double modulator_sample(Waveform waveform, std::uint32_t phase) {
    return oscillator_sample(waveform, phase, 0.5);
}

// A bipolar modulator mapped to [0, 1], which is what a gain wants.
double unipolar(double bipolar) {
    return 0.5 * (1.0 + bipolar);
}

// Depth as a dry/wet blend, so depth 0 is exactly the dry signal: the
// multiplication by 1.0 leaves the carrier's bits untouched.
double blended_gain(double depth, double modulator) {
    return (1.0 - depth) + depth * modulator;
}

}  // namespace

ModEnvelope::ModEnvelope(const ModEnv& env, int sampleRate)
    : attackFrames_(ms_to_frames(env.attackMs, sampleRate)),
      decayFrames_(ms_to_frames(env.decayMs, sampleRate)) {}

double ModEnvelope::at(std::uint32_t frame) const {
    if (frame < attackFrames_) {
        return static_cast<double>(frame) / static_cast<double>(attackFrames_);
    }
    const std::uint32_t sinceAttack = frame - attackFrames_;
    if (sinceAttack >= decayFrames_) {
        return 0.0;
    }
    const double progress = static_cast<double>(sinceAttack) / static_cast<double>(decayFrames_);
    const double remaining = 1.0 - progress;
    return remaining * remaining;
}

Modulation::Modulation(const Voice& voice, double frequencyHz, int sampleRate,
                       const PitchExpression& expression)
    : hasModEnv_(voice.hasModEnv),
      hasLfo_(voice.hasLfo),
      hasFm_(voice.hasFm),
      hasAm_(voice.hasAm),
      modEnv_(voice.modEnv),
      lfo_(voice.lfo),
      fm_(voice.fm),
      am_(voice.am),
      modEnvelope_(voice.modEnv, sampleRate),
      expression_(expression),
      hasExpression_(expression.active()) {
    hasPitchModulation_ = (hasModEnv_ && modEnv_.target == ModEnvTarget::Pitch) ||
                          (hasLfo_ && lfo_.target == LfoTarget::Pitch);
    hasCutoffModulation_ = (hasModEnv_ && modEnv_.target == ModEnvTarget::Cutoff) ||
                           (hasLfo_ && lfo_.target == LfoTarget::Cutoff);

    baseTurns_ = sampleRate > 0 && frequencyHz > 0.0
                     ? frequencyHz / static_cast<double>(sampleRate)
                     : 0.0;
    baseIncrement_ = phase_increment(frequencyHz, sampleRate);
    carrierIncrement_ = baseIncrement_;

    lfoIncrement_ = hasLfo_ ? phase_increment(lfo_.rateHz, sampleRate) : 0;
    amIncrement_ = hasAm_ ? phase_increment(am_.rateHz, sampleRate) : 0;
}

double Modulation::pitchOctaves(double envelope) const {
    double octaves = 0.0;
    if (hasModEnv_ && modEnv_.target == ModEnvTarget::Pitch) {
        octaves -= modEnv_.amount * envelope * kModEnvPitchOctaves;
    }
    if (hasLfo_ && lfo_.target == LfoTarget::Pitch) {
        octaves += lfo_.depth * kLfoPitchOctaves *
                   modulator_sample(waveform_of(lfo_.shape), lfoPhase_);
    }
    return octaves;
}

double Modulation::cutoffOctaves(double envelope) const {
    double octaves = 0.0;
    if (hasModEnv_ && modEnv_.target == ModEnvTarget::Cutoff) {
        octaves -= modEnv_.amount * envelope * kModEnvCutoffOctaves;
    }
    if (hasLfo_ && lfo_.target == LfoTarget::Cutoff) {
        octaves += lfo_.depth * kLfoCutoffOctaves *
                   modulator_sample(waveform_of(lfo_.shape), lfoPhase_);
    }
    return octaves;
}

double Modulation::expressionOctaves(std::uint32_t frame) const {
    double octaves = 0.0;
    if (frame < expression_.glideFrames) {
        octaves += expression_.glideOctaves *
                   static_cast<double>(expression_.glideFrames - frame) /
                   static_cast<double>(expression_.glideFrames);
    }
    if (expression_.hasVibrato && frame >= expression_.vibratoDelayFrames) {
        const std::uint32_t since = frame - expression_.vibratoDelayFrames;
        double depth = expression_.vibratoOctaves;
        if (since < expression_.vibratoFadeFrames) {
            depth = depth * static_cast<double>(since) /
                    static_cast<double>(expression_.vibratoFadeFrames);
        }
        octaves += depth * modulator_sample(Waveform::Sine, vibratoPhase_);
    }
    return octaves;
}

void Modulation::step(std::uint32_t frame) {
    const double envelope = hasModEnv_ ? modEnvelope_.at(frame) : 0.0;

    // Pitch first: FM's modulator tracks the carrier, so it has to see the
    // frequency the carrier is actually running at this frame.
    double turns = baseTurns_;
    if (hasPitchModulation_) {
        double octaves = pitchOctaves(envelope);
        if (hasExpression_) {
            octaves += expressionOctaves(frame);
        }
        turns = baseTurns_ * octave_ratio(octaves);
        carrierIncrement_ = turns_to_increment(turns);
    } else if (hasExpression_) {
        // A note's glide and vibrato on an otherwise steady voice. Where they
        // add nothing (before the vibrato starts, after the glide lands) the
        // carrier runs at exactly the increment it has without them.
        const double octaves = expressionOctaves(frame);
        if (octaves != 0.0) {
            turns = baseTurns_ * octave_ratio(octaves);
            carrierIncrement_ = turns_to_increment(turns);
        } else {
            carrierIncrement_ = baseIncrement_;
        }
    }
    // The vibrato's phase starts where the vibrato does, so it fades in from a
    // zero crossing on every note.
    if (expression_.hasVibrato && frame >= expression_.vibratoDelayFrames) {
        vibratoPhase_ += expression_.vibratoIncrement;
    }

    if (hasFm_) {
        const double modulator = modulator_sample(Waveform::Sine, fmPhase_);
        fmPhase_ += turns_to_increment(turns * fm_.ratio);

        // The index is a depth in radians; fold whole turns away before the
        // cast so a deep index cannot overflow it. The signed-to-unsigned
        // conversion that follows is modular, which is exactly the wrap wanted.
        double offset = fm_.index * modulator * kTurnsPerRadian;
        offset -= static_cast<double>(static_cast<std::int64_t>(offset));
        fmPhaseOffset_ =
            static_cast<std::uint32_t>(static_cast<std::int64_t>(offset * kPhaseScale));
    }

    if (hasAm_) {
        const double modulator = modulator_sample(Waveform::Sine, amPhase_);
        amPhase_ += amIncrement_;
        // Ring modulation passes the modulator through bipolar, so the carrier
        // inverts every half cycle and the original pitch disappears into the
        // sum and difference tones. AM keeps it unipolar, which leaves the
        // carrier audible underneath.
        amGain_ = blended_gain(
            am_.depth, am_.mode == AmMode::Ring ? modulator : unipolar(modulator));
    }

    if (hasCutoffModulation_) {
        cutoffRatio_ = octave_ratio(cutoffOctaves(envelope));
    }

    if (hasLfo_) {
        if (lfo_.target == LfoTarget::Amplitude) {
            tremoloGain_ = blended_gain(
                lfo_.depth, unipolar(modulator_sample(waveform_of(lfo_.shape), lfoPhase_)));
        }
        lfoPhase_ += lfoIncrement_;
    }
}

}  // namespace blipsmith
