// The master bus: where voices become a file.
//
// Every voice arrives here as a mono stream and leaves as part of one interleaved
// mix. The bus does four things, in this order: places each voice with pan and
// mix level, applies the master gain, normalizes the sum to the limiter's target
// headroom, and clamps whatever is left to full scale.
//
// The limiter is a safety gate, not an effect, and there is deliberately no way
// to switch it off: the spec has no bypass field and this class has no bypass
// path. It normalizes rather than merely limits, so a mix that sums past full
// scale is turned *down* cleanly instead of being squared off, and a mix that
// never gets near full scale is brought *up* to the same target. Every render
// therefore leaves at the same peak, and loudness is set by the limiter target
// rather than by how many voices happened to be playing.
//
// One consequence worth knowing: because normalization runs after it,
// `master.gainDb` cannot change the level of the finished file. It scales the
// sum, and the normalizer scales it straight back. Per-voice `mixDb` is the
// control that still matters, because it changes the balance *between* voices,
// which normalization cannot undo.
//
// The pan law is constant power: a voice panned hard to one side is as loud as
// the same voice in the middle. `sqrt` is the only function involved, and
// IEEE-754 requires it to be exactly rounded everywhere, so it is as
// deterministic as multiplication.

#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "spec_parse.h"

namespace blipsmith {

struct VoiceGains {
    double left = 1.0;
    double right = 1.0;
};

// Pan is a stereo-image control, so a mono render ignores it rather than
// attenuating a centred voice by 3 dB into a picture that does not exist.
VoiceGains voice_gains(double pan, double mixDb, int channels);

class MasterBus {
public:
    MasterBus(std::uint32_t frames, int channels);

    void add(std::uint32_t frame, double sample, const VoiceGains& gains);

    // Master gain, then normalization to the limiter target, then the clip
    // guard. A silent mix stays silent: there is no peak to normalize to, and
    // inventing one would turn rounding noise into a full-scale hiss.
    std::vector<double> finish(const Master& master);

private:
    std::vector<double> mix_;
    int channels_;
};

}  // namespace blipsmith
