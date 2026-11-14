// Expressive notes (music mode): what one note does beyond its pitch and level.
//
// Touch reshapes the voice for each note from its velocity: the FM index, the
// filter cutoff and the attack move around a pivot velocity, at which the
// voice plays exactly as authored. Level still follows velocity in the mix, as
// it always has, so touch changes the tone and leaves the loudness alone.
//
// Glide and late vibrato move the pitch while the note plays. Both are worked
// out per note from the note and its voice, never from time or the order a
// container happens to hold things in, so a note renders the same wherever it
// sits. The pitch offsets they produce join the modulation's pitch path.
//
// Nothing here reaches for libm: octave shifts go through `octave_ratio`, the
// vibrato reads the baked sine, and a glide's distance comes from MIDI numbers.

#pragma once

#include <cstdint>

#include "seq.h"
#include "spec_parse.h"

namespace blipsmith {

// The voice as one note of `velocity` plays it. Only the fields touch moves are
// rewritten, so `out` can be a copy of `voice` made once and reused per note.
void apply_touch(const Voice& voice, double velocity, Voice& out);

// What moves one note's pitch while it plays. Empty, it moves nothing, and the
// modulation it is handed runs exactly the code it ran before notes had any.
struct PitchExpression {
    // Glide: the note starts `glideOctaves` from its own pitch and arrives,
    // linearly in octaves, over `glideFrames`.
    double glideOctaves = 0.0;
    std::uint32_t glideFrames = 0;
    // Late vibrato: nothing for `vibratoDelayFrames`, then a sine whose depth
    // grows linearly to `vibratoOctaves` over `vibratoFadeFrames`.
    bool hasVibrato = false;
    std::uint32_t vibratoDelayFrames = 0;
    std::uint32_t vibratoFadeFrames = 0;
    std::uint32_t vibratoIncrement = 0;
    double vibratoOctaves = 0.0;

    bool hasGlide() const { return glideFrames > 0 && glideOctaves != 0.0; }
    bool active() const { return hasGlide() || hasVibrato; }
};

// The voice's vibrato, the same for every note it plays. Empty without one, or
// with no depth.
PitchExpression vibrato_expression(const Voice& voice, int sampleRate);

// Adds the glide into `expression` for `note`, coming from `previous` (null when
// the note is the voice's first). No glide without a previous note, without a
// MIDI pitch on either, or, in legato mode, when the previous one was released
// before this one starts.
void add_glide(const Voice& voice, const ScheduledNote* previous, const ScheduledNote& note,
               int sampleRate, PitchExpression& expression);

}  // namespace blipsmith
