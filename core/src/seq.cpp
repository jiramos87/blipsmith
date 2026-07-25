#include "seq.h"

#include "env.h"
#include "tables.h"

namespace blipsmith {
namespace {

constexpr double kMsPerMinute = 60000.0;

}  // namespace

std::vector<ScheduledNote> schedule_track(const Track& track, double tempoBpm, int sampleRate) {
    std::vector<ScheduledNote> scheduled;
    scheduled.reserve(track.notes.size());
    if (tempoBpm <= 0.0) {
        return scheduled;
    }

    const double beatMs = kMsPerMinute / tempoBpm;
    for (const Note& note : track.notes) {
        ScheduledNote event;
        event.startFrame = ms_to_frames(note.startBeat * beatMs, sampleRate);
        event.heldFrames = ms_to_frames(note.durationBeats * beatMs, sampleRate);
        event.midiNote = note.midiNote;
        event.velocity = note.velocity;
        scheduled.push_back(event);
    }
    return scheduled;
}

double voice_frequency(const Voice& voice) {
    return voice.fundamentalMidi >= 0 ? midi_to_hz(voice.fundamentalMidi) : voice.fundamentalHz;
}

double trigger_frequency(const Voice& voice, int midiNote) {
    return midiNote >= 0 ? midi_to_hz(midiNote) : voice_frequency(voice);
}

}  // namespace blipsmith
