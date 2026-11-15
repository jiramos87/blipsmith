// One run of a voice's chain, up to and including lo-fi, handed to a sink.
//
// Version 1 runs the voice's effects per note inside its sink; the music mode
// sums dry notes into a voice line and runs the effects once over the line.
// Both share this loop, so a note is the same arithmetic in either mode up to
// the point where they part.

#pragma once

#include <cstdint>
#include <optional>

#include "additive.h"
#include "env.h"
#include "expression.h"
#include "filter.h"
#include "fm4.h"
#include "lofi.h"
#include "modal.h"
#include "mod.h"
#include "noise.h"
#include "osc.h"
#include "pluck.h"
#include "spec_parse.h"

namespace blipsmith {

// One copy of a voice in a unison stack: where its cycle starts and which noise
// stream it draws. The plain voice is one copy at phase zero on its own stream.
struct VoiceCopy {
    std::uint32_t startPhase = 0;
    // -1 means the voice's own stream.
    int noiseStream = -1;
};

template <typename Sink>
void run_voice_chain(const Spec& spec, const Voice& voice, int voiceIndex, double frequency,
                     const AmpEnvelope& envelope, const PitchExpression& expression,
                     const VoiceCopy& copy, std::uint32_t frameCount, Sink&& sink) {
    Modulation modulation(voice, frequency, spec.sampleRate, expression);
    NoiseSource noise(spec.seed, copy.noiseStream < 0 ? voiceIndex : copy.noiseStream);
    LoFiStage lofi(voice.lofi);
    const double startTurns = static_cast<double>(copy.startPhase) / kPhaseScale;
    // Four-operator FM replaces the oscillator; its phases start on the note.
    std::optional<FourOperator> operators;
    if (voice.hasFm4) {
        operators.emplace(voice.fm4, spec.sampleRate, startTurns);
    }
    // So does a string; its line is filled on the note's first frame.
    std::optional<PluckedString> string;
    if (voice.hasString) {
        string.emplace(voice.string, spec.sampleRate);
    }
    // And a modal bank; it is struck on the note's first frame.
    std::optional<ModalBank> modal;
    if (voice.hasModal) {
        modal.emplace(voice.modal, spec.sampleRate);
    }
    // And a wavetable or an additive block, summed from sine partials.
    std::optional<AdditiveSource> additive;
    if (voice.hasWavetable) {
        additive.emplace(voice.wavetable, spec.sampleRate, startTurns);
    } else if (voice.hasAdditive) {
        additive.emplace(voice.additive, spec.sampleRate, startTurns);
    }

    // A static cutoff needs its coefficients worked out once. A modulated one is
    // recomputed every frame, below.
    Biquad filter;
    if (voice.hasFilter) {
        filter.set(biquad_coefficients(voice.filter.type, voice.filter.cutoffHz,
                                       voice.filter.resonance, spec.sampleRate));
    }
    const bool sweepsCutoff = voice.hasFilter && modulation.modulatesCutoff();

    std::uint32_t phase = copy.startPhase;
    for (std::uint32_t frame = 0; frame < frameCount; ++frame) {
        modulation.step(frame);

        // The chain runs oscillator -> FM -> AM -> envelope -> LFO. A voice with
        // no modulation multiplies by exactly 1.0 and adds a zero phase offset,
        // so its bytes are the ones B04 recorded.
        double sample;
        switch (voice.waveform) {
            case Waveform::NoiseWhite:
                sample = noise.white();
                break;
            case Waveform::NoisePink:
                sample = noise.pink();
                break;
            default:
                if (operators) {
                    sample = operators->sample(frame, modulation.carrierTurns());
                    break;
                }
                if (string) {
                    sample = string->sample(modulation.carrierTurns(), noise);
                    break;
                }
                if (modal) {
                    sample = modal->sample(modulation.carrierTurns());
                    break;
                }
                if (additive) {
                    sample = additive->sample(modulation.carrierTurns());
                    break;
                }
                sample = oscillator_sample(voice.waveform, phase + modulation.fmPhaseOffset(),
                                           voice.pulseDuty);
                phase += modulation.carrierIncrement();
                break;
        }

        sample *= modulation.amGain();
        sample *= envelope.at(frame);
        sample *= modulation.tremoloGain();

        // ... then filter -> lo-fi. Each stage is skipped rather than run with
        // neutral settings, so a voice that asks for neither still renders the
        // bytes B04 recorded.
        if (voice.hasFilter) {
            if (sweepsCutoff) {
                filter.set(biquad_coefficients(
                    voice.filter.type, voice.filter.cutoffHz * modulation.cutoffRatio(),
                    voice.filter.resonance, spec.sampleRate));
            }
            sample = filter.process(sample);
        }
        if (voice.hasLoFi) {
            sample = lofi.process(sample);
        }

        sink(frame, sample);
    }
}

// A note as one copy of the voice: every voice without unison.
template <typename Sink>
void run_voice_chain(const Spec& spec, const Voice& voice, int voiceIndex, double frequency,
                     const AmpEnvelope& envelope, const PitchExpression& expression,
                     std::uint32_t frameCount, Sink&& sink) {
    run_voice_chain(spec, voice, voiceIndex, frequency, envelope, expression, VoiceCopy{},
                    frameCount, static_cast<Sink&&>(sink));
}

// A note with no expression: version 1, and a music voice with none set.
template <typename Sink>
void run_voice_chain(const Spec& spec, const Voice& voice, int voiceIndex, double frequency,
                     const AmpEnvelope& envelope, std::uint32_t frameCount, Sink&& sink) {
    run_voice_chain(spec, voice, voiceIndex, frequency, envelope, PitchExpression{}, frameCount,
                    static_cast<Sink&&>(sink));
}

}  // namespace blipsmith
