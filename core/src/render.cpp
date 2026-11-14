#include "render.h"

#include <cstddef>
#include <vector>

#include "bus.h"
#include "env.h"
#include "fx.h"
#include "music.h"
#include "seq.h"
#include "spec_parse.h"
#include "voice_chain.h"
#include "wav.h"

namespace blipsmith {
namespace {

constexpr int kMusicVersion = 2;

// One run of a voice: the whole per-voice chain, rendered into the bus from
// `startFrame` for `frameCount` frames. A one-shot is a single run over the
// whole file; a composition is one run per note. Everything the run needs is a
// parameter, so a note can retune, re-level, and restart it without the chain
// itself knowing which of the two it is serving.
void render_run(const Spec& spec, const Voice& voice, int voiceIndex, double frequency,
                double velocity, const AmpEnvelope& envelope, std::uint32_t startFrame,
                std::uint32_t frameCount, const VoiceGains& gains, MasterBus& bus) {
    // Version 1 runs the voice's effects per note, inside the run: an echo or a
    // room ends with the note that made it.
    EffectChain effects(voice.effects, spec.sampleRate);
    run_voice_chain(spec, voice, voiceIndex, frequency, envelope, frameCount,
                    [&](std::uint32_t frame, double sample) {
                        if (!voice.effects.empty()) {
                            sample = effects.process(sample);
                        }
                        bus.add(startFrame + frame, sample * velocity, gains);
                    });
}

// A voice on a track answers to both: the levels add in decibels and the pans
// add across the image, so a voice can sit off-centre *within* a track that is
// itself placed off-centre. The bus clamps the sum back into the image.
VoiceGains gains_for_track(const Voice& voice, const Track& track, int channels) {
    return voice_gains(voice.pan + track.pan, voice.mixDb + track.gainDb, channels);
}

void render_one_shots(const Spec& spec, std::uint32_t frames, MasterBus& bus) {
    for (std::size_t index = 0; index < spec.voices.size(); ++index) {
        const Voice& voice = spec.voices[index];
        render_run(spec, voice, static_cast<int>(index), voice_frequency(voice), 1.0,
                   AmpEnvelope(voice.ampEnv, frames, spec.sampleRate), 0, frames,
                   voice_gains(voice.pan, voice.mixDb, spec.channels), bus);
    }
}

void render_composition(const Spec& spec, std::uint32_t frames, MasterBus& bus) {
    const std::vector<Track>& tracks = spec.composition.tracks;

    // Scheduled once per track rather than once per voice: two voices sharing a
    // track share its pattern, and the note times cannot be allowed to depend on
    // which voice is asking.
    std::vector<std::vector<ScheduledNote>> plan;
    plan.reserve(tracks.size());
    for (const Track& track : tracks) {
        plan.push_back(schedule_track(track, spec.composition.tempoBpm, spec.sampleRate));
    }

    for (std::size_t index = 0; index < spec.voices.size(); ++index) {
        const Voice& voice = spec.voices[index];
        if (voice.track < 0 || static_cast<std::size_t>(voice.track) >= tracks.size()) {
            continue;
        }
        const Track& track = tracks[static_cast<std::size_t>(voice.track)];
        const VoiceGains gains = gains_for_track(voice, track, spec.channels);

        for (const ScheduledNote& note : plan[static_cast<std::size_t>(voice.track)]) {
            if (note.startFrame >= frames) {
                continue;
            }
            const AmpEnvelope envelope =
                AmpEnvelope::gated(voice.ampEnv, note.heldFrames, spec.sampleRate);

            // A tail that would run past the end of the file is truncated there
            // rather than dropped: the note was audible, it just does not get to
            // finish ringing.
            std::uint32_t count = envelope.totalFrames();
            const std::uint32_t room = frames - note.startFrame;
            if (count > room) {
                count = room;
            }

            render_run(spec, voice, static_cast<int>(index),
                       trigger_frequency(voice, note.midiNote), note.velocity, envelope,
                       note.startFrame, count, gains, bus);
        }
    }
}

}  // namespace

RenderOutput render_spec_json(const std::string& specJson, bool wantStems) {
    const Spec spec = parse_spec(specJson);

    RenderOutput out;
    out.sampleRate = spec.sampleRate;
    out.channels = spec.channels;
    out.frames = ms_to_frames(spec.durationMs, spec.sampleRate);

    // Version 2 is the music mode, a path of its own; version 1 never enters it,
    // which is what keeps every sound rendered before it byte-identical.
    if (spec.version == kMusicVersion && spec.hasComposition) {
        MusicMix music = render_music(spec, out.frames, wantStems);
        out.features = measure(music.mix, spec.sampleRate, spec.channels);
        out.wav = encode_wav_pcm16(music.mix, spec.sampleRate, spec.channels);
        for (const std::vector<double>& stem : music.stems) {
            out.stems.push_back(encode_wav_pcm16(stem, spec.sampleRate, spec.channels));
        }
        out.stemClipped = music.stemClipped;
        return out;
    }

    MasterBus bus(out.frames, spec.channels);

    // With a composition, notes are the only thing that makes a voice sound. A
    // track nobody wrote notes for contributes silence, which is what lets an
    // agent build a piece one track at a time.
    if (spec.hasComposition) {
        render_composition(spec, out.frames, bus);
    } else {
        render_one_shots(spec, out.frames, bus);
    }

    // Features are measured on the bus output rather than on the encoded file:
    // same audio, without the int16 grid rounding every measurement.
    const std::vector<double> mixed = bus.finish(spec.master);
    out.features = measure(mixed, spec.sampleRate, spec.channels);
    out.wav = encode_wav_pcm16(mixed, spec.sampleRate, spec.channels);
    return out;
}

}  // namespace blipsmith
