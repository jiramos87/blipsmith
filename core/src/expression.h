// Expressive notes (music mode): what one note does beyond its pitch and level.
//
// Touch reshapes the voice for each note from its velocity: the FM index, the
// filter cutoff and the attack move around a pivot velocity, at which the
// voice plays exactly as authored. Level still follows velocity in the mix, as
// it always has, so touch changes the tone and leaves the loudness alone.
//
// Nothing here reaches for libm: octave shifts go through `octave_ratio`.

#pragma once

#include "spec_parse.h"

namespace blipsmith {

// The voice as one note of `velocity` plays it. Only the fields touch moves are
// rewritten, so `out` can be a copy of `voice` made once and reused per note.
void apply_touch(const Voice& voice, double velocity, Voice& out);

}  // namespace blipsmith
