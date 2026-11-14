// One run of a voice's chain, up to and including lo-fi, handed to a sink.
//
// Version 1 runs the voice's effects per note inside its sink; the music mode
// sums dry notes into a voice line and runs the effects once over the line.
// Both share this loop, so a note is the same arithmetic in either mode up to
// the point where they part.

#pragma once

#include <cstdint>

#include "env.h"
#include "filter.h"
#include "lofi.h"
#include "mod.h"
#include "noise.h"
#include "osc.h"
#include "spec_parse.h"

namespace blipsmith {

template <typename Sink>
void run_voice_chain(const Spec& spec, const Voice& voice, int voiceIndex, double frequency,
                     const AmpEnvelope& envelope, std::uint32_t frameCount, Sink&& sink) {
    Modulation modulation(voice, frequency, spec.sampleRate);
    NoiseSource noise(spec.seed, voiceIndex);
    LoFiStage lofi(voice.lofi);

    // A static cutoff needs its coefficients worked out once. A modulated one is
    // recomputed every frame, below.
    Biquad filter;
    if (voice.hasFilter) {
        filter.set(biquad_coefficients(voice.filter.type, voice.filter.cutoffHz,
                                       voice.filter.resonance, spec.sampleRate));
    }
    const bool sweepsCutoff = voice.hasFilter && modulation.modulatesCutoff();

    std::uint32_t phase = 0;
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

}  // namespace blipsmith
