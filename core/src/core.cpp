// blipsmith deterministic DSP core.
//
// Nothing in this module may reach a libm transcendental (sin, cos, exp, pow
// and friends): those are per-platform library routines that differ bit for
// bit, and byte-identical output across platforms is the product invariant.
// scripts/check_no_libm.py enforces this against the compiled binary.

#include <pybind11/pybind11.h>

#include <string>

#include "render.h"

#ifndef BLIPSMITH_CORE_VERSION
#define BLIPSMITH_CORE_VERSION "0.0.0+local"
#endif

namespace py = pybind11;

namespace {

// The five features that need spectral analysis land in B08; they are reported
// as null rather than as a plausible-looking zero, so a caller steering by
// numbers can tell "not measured yet" from "measured as silent".
py::dict render(const std::string& spec_json) {
    const blipsmith::RenderOutput output = blipsmith::render_spec_json(spec_json);

    py::dict features;
    features["durationMs"] = output.durationMs;
    features["peakDbfs"] = py::none();
    features["rmsDbfs"] = py::none();
    features["estimatedFundamentalHz"] = py::none();
    features["spectralCentroidHz"] = py::none();
    features["attackTimeMs"] = py::none();

    py::dict result;
    result["wav"] = py::bytes(output.wav);
    result["features"] = features;
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
        "Render canonical SoundSpec JSON. Returns {'wav': bytes, 'features': dict}.\n"
        "The JSON must already be validated, clamped, and defaults-filled by the\n"
        "Python layer: the core neither validates nor clamps.");
}
