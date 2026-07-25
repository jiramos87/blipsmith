// The sequencer: notes in beats become voice triggers in frames.
//
// Everything musical about a composition has already been decided by the time
// it reaches here. Steps are notes, swing is baked into the start times, and
// duplicates and unreachable notes are gone. What is left is arithmetic: at
// this tempo and this sample rate, which frame does each note start on, and how
// long is it held?
//
// Polyphony falls out of that. A note is a trigger, not a voice, so two notes
// overlapping on one track render the same voice twice into the same frames and
// the bus sums them. Each trigger starts from a clean slate (fresh phase,
// filter state, and noise stream), which is why a hi-hat sounds like itself on
// every hit instead of drifting through the pattern.

#pragma once

#include <cstdint>
#include <vector>

#include "spec_parse.h"

namespace blipsmith {

struct ScheduledNote {
    std::uint32_t startFrame = 0;
    std::uint32_t heldFrames = 0;
    // -1 keeps the voice's own fundamental; anything else overrides it.
    int midiNote = -1;
    double velocity = 1.0;
};

// One track's notes placed on the render's timeline. Beat-to-frame conversion
// goes through the same truncating rule the envelopes use, so a note's onset
// and its envelope agree about where frame zero is.
std::vector<ScheduledNote> schedule_track(const Track& track, double tempoBpm, int sampleRate);

// The pitch a voice plays when nothing overrides it: its MIDI note if it has
// one, otherwise its frequency in hertz.
double voice_frequency(const Voice& voice);

// The pitch a trigger plays: the note's own, or the voice's when it has none.
double trigger_frequency(const Voice& voice, int midiNote);

}  // namespace blipsmith
