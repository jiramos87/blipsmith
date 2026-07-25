#include "render.h"

#include <cstddef>
#include <vector>

#include "bus.h"
#include "env.h"
#include "filter.h"
#include "fx.h"
#include "lofi.h"
#include "mod.h"
#include "noise.h"
#include "osc.h"
#include "spec_parse.h"
#include "tables.h"
#include "wav.h"

namespace blipsmith {

RenderOutput render_spec_json(const std::string& specJson) {
    const Spec spec = parse_spec(specJson);

    RenderOutput out;
    out.sampleRate = spec.sampleRate;
    out.channels = spec.channels;
    out.frames = ms_to_frames(spec.durationMs, spec.sampleRate);

    MasterBus bus(out.frames, spec.channels);

    for (std::size_t index = 0; index < spec.voices.size(); ++index) {
        const Voice& voice = spec.voices[index];
        const VoiceGains gains = voice_gains(voice.pan, voice.mixDb, spec.channels);

        const double frequency = voice.fundamentalMidi >= 0
                                     ? midi_to_hz(voice.fundamentalMidi)
                                     : voice.fundamentalHz;
        const AmpEnvelope envelope(voice.ampEnv, out.frames, spec.sampleRate);
        Modulation modulation(voice, frequency, spec.sampleRate);
        NoiseSource noise(spec.seed, static_cast<int>(index));
        LoFiStage lofi(voice.lofi);
        EffectChain effects(voice.effects, spec.sampleRate);

        // A static cutoff needs its coefficients worked out once. A modulated
        // one is recomputed every frame, below.
        Biquad filter;
        if (voice.hasFilter) {
            filter.set(biquad_coefficients(voice.filter.type, voice.filter.cutoffHz,
                                           voice.filter.resonance, spec.sampleRate));
        }
        const bool sweepsCutoff = voice.hasFilter && modulation.modulatesCutoff();

        std::uint32_t phase = 0;
        for (std::uint32_t frame = 0; frame < out.frames; ++frame) {
            modulation.step(frame);

            // The chain runs oscillator -> FM -> AM -> envelope -> LFO. A voice
            // with no modulation multiplies by exactly 1.0 and adds a zero phase
            // offset, so its bytes are the ones B04 recorded.
            double sample;
            switch (voice.waveform) {
                case Waveform::NoiseWhite:
                    sample = noise.white();
                    break;
                case Waveform::NoisePink:
                    sample = noise.pink();
                    break;
                default:
                    sample = oscillator_sample(
                        voice.waveform, phase + modulation.fmPhaseOffset(), voice.pulseDuty);
                    phase += modulation.carrierIncrement();
                    break;
            }

            sample *= modulation.amGain();
            sample *= envelope.at(frame);
            sample *= modulation.tremoloGain();

            // ... then filter -> lo-fi -> effects. Each stage is skipped rather
            // than run with neutral settings, so a voice that asks for none of
            // them still renders the bytes B04 recorded.
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
            if (!voice.effects.empty()) {
                sample = effects.process(sample);
            }

            bus.add(frame, sample, gains);
        }
    }

    // Features are measured on the bus output rather than on the encoded file:
    // same audio, without the int16 grid rounding every measurement.
    const std::vector<double> mixed = bus.finish(spec.master);
    out.features = measure(mixed, spec.sampleRate, spec.channels);
    out.wav = encode_wav_pcm16(mixed, spec.sampleRate, spec.channels);
    return out;
}

}  // namespace blipsmith
