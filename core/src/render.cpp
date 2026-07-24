#include "render.h"

#include <cstddef>
#include <vector>

#include "env.h"
#include "noise.h"
#include "osc.h"
#include "spec_parse.h"
#include "tables.h"
#include "wav.h"

namespace blipsmith {
namespace {

// Frame count truncates rather than rounds, so the mapping from durationMs to
// samples is one fixed rule with no tie-breaking to disagree about.
std::uint32_t frame_count(double durationMs, int sampleRate) {
    if (durationMs <= 0.0 || sampleRate <= 0) {
        return 0;
    }
    const double frames = (durationMs * static_cast<double>(sampleRate)) / 1000.0;
    return static_cast<std::uint32_t>(frames);
}

}  // namespace

RenderOutput render_spec_json(const std::string& specJson) {
    const Spec spec = parse_spec(specJson);

    RenderOutput out;
    out.sampleRate = spec.sampleRate;
    out.channels = spec.channels;
    out.frames = frame_count(spec.durationMs, spec.sampleRate);

    const std::size_t sample_count =
        static_cast<std::size_t>(out.frames) * static_cast<std::size_t>(spec.channels);
    std::vector<double> mix(sample_count, 0.0);

    // Voices sum straight into the mix at unit gain. Per-voice pan and mix
    // level, and the master limiter that keeps a hot sum in range, arrive with
    // the bus in B07; the per-voice modulation and filter chain in B05/B06.
    for (std::size_t index = 0; index < spec.voices.size(); ++index) {
        const Voice& voice = spec.voices[index];

        const double frequency = voice.fundamentalMidi >= 0
                                     ? midi_to_hz(voice.fundamentalMidi)
                                     : voice.fundamentalHz;
        const std::uint32_t increment = phase_increment(frequency, spec.sampleRate);
        const AmpEnvelope envelope(voice.ampEnv, out.frames, spec.sampleRate);
        NoiseSource noise(spec.seed, static_cast<int>(index));

        std::uint32_t phase = 0;
        for (std::uint32_t frame = 0; frame < out.frames; ++frame) {
            double sample;
            switch (voice.waveform) {
                case Waveform::NoiseWhite:
                    sample = noise.white();
                    break;
                case Waveform::NoisePink:
                    sample = noise.pink();
                    break;
                default:
                    sample = oscillator_sample(voice.waveform, phase, voice.pulseDuty);
                    phase += increment;
                    break;
            }

            sample *= envelope.at(frame);

            const std::size_t base =
                static_cast<std::size_t>(frame) * static_cast<std::size_t>(spec.channels);
            for (int channel = 0; channel < spec.channels; ++channel) {
                mix[base + static_cast<std::size_t>(channel)] += sample;
            }
        }
    }

    out.wav = encode_wav_pcm16(mix, spec.sampleRate, spec.channels);
    out.durationMs = spec.sampleRate > 0
                         ? (static_cast<double>(out.frames) * 1000.0) /
                               static_cast<double>(spec.sampleRate)
                         : 0.0;
    return out;
}

}  // namespace blipsmith
