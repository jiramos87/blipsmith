#include "music.h"

#include <cstddef>
#include <utility>

#include "bus.h"
#include "env.h"
#include "expression.h"
#include "fx.h"
#include "seq.h"
#include "tables.h"
#include "voice_chain.h"

namespace blipsmith {
namespace {

constexpr double kFullScale = 1.0;

double absolute(double value) {
    return value < 0.0 ? -value : value;
}

// The pitch a voice sounds for a note it plays: a keyed voice is a drum and
// keeps its own; a keyless one follows the note, as in version 1.
double note_frequency(const Voice& voice, int midiNote) {
    return voice.key >= 0 ? voice_frequency(voice) : trigger_frequency(voice, midiNote);
}

// One effect chain per channel. The right channel's reverb is spread, so a
// stereo room is wide; a mono render has one plain chain.
void run_stereo_chain(const std::vector<Effect>& effects, int sampleRate, int channels,
                      std::vector<double>& line) {
    if (effects.empty()) {
        return;
    }
    for (int channel = 0; channel < channels; ++channel) {
        EffectChain chain(effects, sampleRate, channel == 1 ? kReverbStereoSpread : 0);
        const std::size_t step = static_cast<std::size_t>(channels);
        for (std::size_t index = static_cast<std::size_t>(channel); index < line.size();
             index += step) {
            line[index] = chain.process(line[index]);
        }
    }
}

// Everything at or past `frames` is added back onto the start, frame by frame
// in order, so a tail longer than the loop wraps more than once.
void fold(std::vector<double>& line, std::uint32_t frames, int channels) {
    const std::size_t width = static_cast<std::size_t>(channels);
    const std::size_t loop = static_cast<std::size_t>(frames) * width;
    if (loop == 0) {
        return;
    }
    for (std::size_t index = loop; index < line.size(); ++index) {
        line[index % loop] += line[index];
    }
    line.resize(loop);
}

}  // namespace

bool voice_plays(const Voice& voice, int midiNote) {
    return voice.key < 0 || voice.key == midiNote;
}

std::uint32_t music_tail_frames(const Spec& spec, std::uint32_t frames) {
    const std::vector<Track>& tracks = spec.composition.tracks;
    std::uint64_t noteTail = 0;
    std::uint32_t voiceTail = 0;
    for (const Voice& voice : spec.voices) {
        if (voice.track < 0 || static_cast<std::size_t>(voice.track) >= tracks.size()) {
            continue;
        }
        const std::uint32_t own = chain_tail_frames(voice.effects, spec.sampleRate);
        voiceTail = own > voiceTail ? own : voiceTail;
        const Track& track = tracks[static_cast<std::size_t>(voice.track)];
        for (const ScheduledNote& note :
             schedule_track(track, spec.composition.tempoBpm, spec.sampleRate)) {
            if (note.startFrame >= frames || !voice_plays(voice, note.midiNote)) {
                continue;
            }
            const AmpEnvelope envelope =
                AmpEnvelope::gated(voice.ampEnv, note.heldFrames, spec.sampleRate);
            const std::uint64_t end = std::uint64_t{note.startFrame} + envelope.totalFrames();
            if (end > frames && end - frames > noteTail) {
                noteTail = end - frames;
            }
        }
    }
    std::uint32_t trackTail = 0;
    for (const Track& track : tracks) {
        const std::uint32_t own = chain_tail_frames(track.effects, spec.sampleRate);
        trackTail = own > trackTail ? own : trackTail;
    }
    const std::uint64_t total = noteTail + voiceTail + trackTail +
                                chain_tail_frames(spec.master.effects, spec.sampleRate);
    const std::uint64_t cap = ms_to_frames(kMaxTailMs, spec.sampleRate);
    return static_cast<std::uint32_t>(total < cap ? total : cap);
}

MusicMix render_music(const Spec& spec, std::uint32_t frames, bool wantStems) {
    const std::vector<Track>& tracks = spec.composition.tracks;
    const int channels = spec.channels < 1 ? 1 : spec.channels;
    const std::size_t width = static_cast<std::size_t>(channels);
    const bool loop = spec.composition.loop;
    const std::uint32_t span = loop ? frames + music_tail_frames(spec, frames) : frames;

    MusicMix out;
    out.mix.assign(static_cast<std::size_t>(frames) * width, 0.0);
    std::vector<double> voiceLine;

    for (std::size_t trackIndex = 0; trackIndex < tracks.size(); ++trackIndex) {
        const Track& track = tracks[trackIndex];
        const std::vector<ScheduledNote> plan =
            schedule_track(track, spec.composition.tempoBpm, spec.sampleRate);
        std::vector<double> trackLine(static_cast<std::size_t>(span) * width, 0.0);

        for (std::size_t voiceIndex = 0; voiceIndex < spec.voices.size(); ++voiceIndex) {
            const Voice& voice = spec.voices[voiceIndex];
            if (voice.track != static_cast<int>(trackIndex)) {
                continue;
            }

            voiceLine.assign(span, 0.0);
            // A voice with touch plays each note through its own copy, reshaped by
            // the note's velocity; one without it plays the voice as written.
            Voice touched;
            if (voice.hasTouch) {
                touched = voice;
            }
            for (const ScheduledNote& note : plan) {
                if (note.startFrame >= frames || !voice_plays(voice, note.midiNote)) {
                    continue;
                }
                if (voice.hasTouch) {
                    apply_touch(voice, note.velocity, touched);
                }
                const Voice& played = voice.hasTouch ? touched : voice;
                const AmpEnvelope envelope =
                    AmpEnvelope::gated(played.ampEnv, note.heldFrames, spec.sampleRate);
                std::uint32_t count = envelope.totalFrames();
                const std::uint32_t room = span - note.startFrame;
                if (count > room) {
                    count = room;
                }
                const double velocity = note.velocity;
                double* start = voiceLine.data() + note.startFrame;
                run_voice_chain(spec, played, static_cast<int>(voiceIndex),
                                note_frequency(voice, note.midiNote), envelope, count,
                                [&](std::uint32_t frame, double sample) {
                                    start[frame] += sample * velocity;
                                });
            }

            if (!voice.effects.empty()) {
                EffectChain chain(voice.effects, spec.sampleRate);
                for (double& sample : voiceLine) {
                    sample = chain.process(sample);
                }
            }

            const VoiceGains gains =
                voice_gains(voice.pan + track.pan, voice.mixDb + track.gainDb, channels);
            for (std::size_t frame = 0; frame < span; ++frame) {
                const double sample = voiceLine[frame];
                trackLine[frame * width] += sample * gains.left;
                if (channels > 1) {
                    trackLine[frame * width + 1] += sample * gains.right;
                }
            }
        }

        run_stereo_chain(track.effects, spec.sampleRate, channels, trackLine);
        run_stereo_chain(spec.master.effects, spec.sampleRate, channels, trackLine);
        if (loop) {
            fold(trackLine, frames, channels);
        }

        for (std::size_t index = 0; index < out.mix.size(); ++index) {
            out.mix[index] += trackLine[index];
        }
        if (wantStems) {
            trackLine.resize(out.mix.size());
            out.stems.push_back(std::move(trackLine));
        }
    }

    // One gain for the whole render: master gain, then the scale that puts the
    // mix's peak on the limiter target. The stems take the same gain, which is
    // what keeps their balance and lets them add up to the mix.
    const double masterGain = db_to_linear(spec.master.gainDb);
    double peak = 0.0;
    for (double& sample : out.mix) {
        sample *= masterGain;
        const double magnitude = absolute(sample);
        if (magnitude > peak) {
            peak = magnitude;
        }
    }
    double scale = 1.0;
    if (peak > 0.0) {
        scale = db_to_linear(spec.master.limiter.targetDbfs) / peak;
        for (double& sample : out.mix) {
            sample *= scale;
        }
    }
    for (double& sample : out.mix) {
        if (sample > kFullScale) {
            sample = kFullScale;
        } else if (sample < -kFullScale) {
            sample = -kFullScale;
        }
    }

    for (std::vector<double>& stem : out.stems) {
        bool clipped = false;
        for (double& sample : stem) {
            sample *= masterGain;
            if (peak > 0.0) {
                sample *= scale;
            }
            if (sample > kFullScale) {
                sample = kFullScale;
                clipped = true;
            } else if (sample < -kFullScale) {
                sample = -kFullScale;
                clipped = true;
            }
        }
        out.stemClipped.push_back(clipped);
    }
    return out;
}

}  // namespace blipsmith
