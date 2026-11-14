// The render entry point: canonical spec JSON in, WAV bytes plus measured
// features out. This is the whole of what the Python layer asks the core to do.

#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "features.h"

namespace blipsmith {

struct RenderOutput {
    std::string wav;
    std::uint32_t frames = 0;
    int sampleRate = 22050;
    int channels = 1;
    // Measured from the rendered PCM rather than restated from the spec, so
    // they reflect the audio that actually exists.
    Features features;
    // Music mode with stems asked for: one WAV per track, in track order, and
    // whether the clip guard had to touch it.
    std::vector<std::string> stems;
    std::vector<bool> stemClipped;
};

RenderOutput render_spec_json(const std::string& specJson, bool wantStems = false);

}  // namespace blipsmith
