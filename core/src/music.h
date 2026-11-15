// The music mode (spec version 2): a whole piece in one render.
//
// Version 1 places every note straight on the master bus and normalizes. The
// music mode builds the piece the way a mixing desk does, one track at a time:
//
//   per voice   its notes, dry, summed into a mono line; the voice's effects run
//               once over the line, so an echo rings past the note that made it
//   per track   each line panned and levelled into the track's stereo line; the
//               track's effects; the master effects (delay and reverb, which are
//               linear, so running them per track equals one shared room and
//               lets the stems add up to the mix); the loop fold
//   the mix     the tracks summed in order, then the master gain and ONE scale
//               that puts the peak on the limiter target, then the clip guard
//
// Every step is a fixed order of additions and multiplications, so the order
// above is part of the bytes.
//
// The loop: with `composition.loop`, the render runs past the end until every
// tail has fallen 96 dB (at most kMaxTailMs), and everything past the end is
// added back onto the start, as many times as it overruns. The file is then
// exactly the loop and plays round without a seam. Without it, tails past the
// end are cut, as in version 1.

#pragma once

#include <cstdint>
#include <vector>

#include "spec_parse.h"
#include "voice_chain.h"

namespace blipsmith {

inline constexpr double kMaxTailMs = 60000.0;

struct MusicMix {
    // Interleaved, finished: scaled to the limiter target and clip-guarded.
    std::vector<double> mix;
    // One per track when asked for, scaled by the same gain as the mix.
    std::vector<std::vector<double>> stems;
    std::vector<bool> stemClipped;
};

MusicMix render_music(const Spec& spec, std::uint32_t frames, bool wantStems);

// Frames rendered past the end before the fold, for a looped spec.
std::uint32_t music_tail_frames(const Spec& spec, std::uint32_t frames);

// One copy of a unison stack: its pitch over the note's, its level, and where
// it starts. Copies spread evenly across the detune, each at one over the root
// of the count, so the stack sounds about as loud as one copy.
struct UnisonCopy {
    double ratio = 1.0;
    double gain = 1.0;
    VoiceCopy copy;
};

std::vector<UnisonCopy> unison_copies(const Unison& unison, std::uint32_t seed, int voiceIndex);

// Whether `voice` plays a note of `midiNote` (-1 for "no pitch of its own"): a
// keyless voice plays every note of its track, a keyed one only its key.
bool voice_plays(const Voice& voice, int midiNote);

}  // namespace blipsmith
