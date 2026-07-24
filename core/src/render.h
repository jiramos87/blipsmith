// The render entry point: canonical spec JSON in, WAV bytes plus measured
// features out. This is the whole of what the Python layer asks the core to do.

#pragma once

#include <cstdint>
#include <string>

namespace blipsmith {

struct RenderOutput {
    std::string wav;
    std::uint32_t frames = 0;
    int sampleRate = 22050;
    int channels = 1;
    // Measured from the rendered PCM rather than restated from the spec, so it
    // reflects the audio that actually exists.
    double durationMs = 0.0;
};

RenderOutput render_spec_json(const std::string& specJson);

}  // namespace blipsmith
