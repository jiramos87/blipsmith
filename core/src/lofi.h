// The lo-fi stage: bit-depth reduction and sample-rate decimation.
//
// Both are integer operations by nature, which is the whole point: this is the
// one place where the crunch an agent asks for is exactly the crunch a fixed
// grid produces, on every platform, with no rounding to argue about.
//
// The two are neutral at their documented boundaries. A decimation factor of 1
// holds every sample, so it returns the input untouched, and 16 bits quantizes
// onto a grid finer than the int16 file itself.

#pragma once

#include "spec_parse.h"

namespace blipsmith {

class LoFiStage {
public:
    explicit LoFiStage(const LoFi& lofi);

    double process(double sample);

private:
    double levels_ = 1.0;
    double inverseLevels_ = 1.0;
    int decimation_ = 1;
    int counter_ = 0;
    double held_ = 0.0;
};

}  // namespace blipsmith
