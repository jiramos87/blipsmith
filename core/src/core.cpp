// blipsmith deterministic DSP core.
//
// Nothing in this module may reach a libm transcendental (sin, cos, exp, pow
// and friends): those are per-platform library routines that differ bit for
// bit, and byte-identical output across platforms is the product invariant.
// scripts/check_no_libm.py enforces this against the compiled binary.

#include <pybind11/pybind11.h>

#include <cstddef>
#include <string>

#include "render.h"

#ifndef BLIPSMITH_CORE_VERSION
#define BLIPSMITH_CORE_VERSION "0.0.0+local"
#endif

namespace py = pybind11;

namespace {

// All six features are measured from the finished audio. The driving agent
// cannot hear, so these are how it checks whether the change it made did what
// it wanted.
py::dict render(const std::string& spec_json, bool stems) {
    const blipsmith::RenderOutput output = blipsmith::render_spec_json(spec_json, stems);

    py::dict features;
    features["durationMs"] = output.features.durationMs;
    features["peakDbfs"] = output.features.peakDbfs;
    features["rmsDbfs"] = output.features.rmsDbfs;
    features["estimatedFundamentalHz"] = output.features.estimatedFundamentalHz;
    features["spectralCentroidHz"] = output.features.spectralCentroidHz;
    features["attackTimeMs"] = output.features.attackTimeMs;

    py::dict result;
    result["wav"] = py::bytes(output.wav);
    result["features"] = features;
    if (stems) {
        py::list stemWavs;
        py::list stemClipped;
        for (std::size_t i = 0; i < output.stems.size(); ++i) {
            stemWavs.append(py::bytes(output.stems[i]));
            stemClipped.append(static_cast<bool>(output.stemClipped[i]));
        }
        result["stems"] = stemWavs;
        result["stemClipped"] = stemClipped;
    }
    return result;
}

}  // namespace

PYBIND11_MODULE(_core, m) {
    m.doc() = "blipsmith native DSP core";

    m.def(
        "ping",
        []() { return std::string("pong"); },
        "Liveness probe: returns 'pong' when the compiled core is loaded.");

    m.def(
        "core_version",
        []() { return std::string(BLIPSMITH_CORE_VERSION); },
        "Version the core was compiled with; matches the Python package version.");

    m.def(
        "render",
        &render,
        py::arg("spec_json"),
        py::arg("stems") = false,
        "Render canonical SoundSpec JSON. Returns {'wav': bytes, 'features': dict}.\n"
        "With stems=True a music-mode spec also returns 'stems' (one WAV per track)\n"
        "and 'stemClipped'.\n"
        "The JSON must already be validated, clamped, and defaults-filled by the\n"
        "Python layer: the core neither validates nor clamps.");
}
