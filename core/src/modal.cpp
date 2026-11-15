#include "modal.h"

#include <cstdint>
#include <vector>

#include "osc.h"
#include "tables.h"

namespace blipsmith {

namespace {

// 60 dB as octaves of amplitude: three decades, 3 x log2(10).
constexpr double kDecayOctaves = 9.965784284662087;
// The shrink's ceiling, so a mode always dies away.
constexpr double kMaxShrink = 0.9999999;
// Matches the filters' own ceiling below Nyquist.
constexpr double kMaxTurnsFraction = 0.45;

// A raised cosine across `width` samples, sampled at their centres.
double hammer(std::uint32_t n, std::uint32_t width) {
    const double turns = (static_cast<double>(n) + 0.5) / static_cast<double>(width);
    return 0.5 - 0.5 * sine_at_phase(turns_to_increment(turns) + kQuarterTurn);
}

}  // namespace

ModalBank::ModalBank(const Modal& modal, int sampleRate) : modal_(modal), sampleRate_(sampleRate) {
    rings_.reserve(modal.modes.size());
    for (const Mode& mode : modal.modes) {
        Ring ring;
        ring.ratio = mode.ratio;
        ring.level = mode.level;
        const double seconds = mode.decayMs / 1000.0;
        double shrink = 0.0;
        if (seconds > 0.0 && sampleRate > 0) {
            shrink = octave_ratio(-kDecayOctaves / (static_cast<double>(sampleRate) * seconds));
        }
        ring.shrink = shrink > kMaxShrink ? kMaxShrink : shrink;
        rings_.push_back(ring);
    }
}

// The angle of one frame at the mode's frequency, read from the baked sine at
// half the angle and doubled, as the filters do, so a low mode stays exact.
void ModalBank::turn_to(Ring& ring, double turns) const {
    double modeTurns = turns * ring.ratio;
    if (!(modeTurns > 0.0)) {  // the negated form also catches NaN
        modeTurns = 0.0;
    } else if (modeTurns > kMaxTurnsFraction) {
        modeTurns = kMaxTurnsFraction;
    }
    const std::uint32_t half = turns_to_increment(0.5 * modeTurns);
    const double s = sine_at_phase(half);
    const double c = sine_at_phase(half + kQuarterTurn);
    ring.sine = 2.0 * s * c;
    ring.cosine = (c - s) * (c + s);
}

// The pulse at the first frame's pitch, and which modes sound: one that starts
// at or above the ceiling would only alias, so it stays silent for the note.
void ModalBank::strike(double turns) {
    const double pitchTurns = turns > 0.0 ? turns : 0.0;
    double cornerTurns = pitchTurns * octave_ratio(kModalBrightnessOctaves * modal_.brightness);
    if (!(cornerTurns > 0.0) || cornerTurns > kMaxTurnsFraction) {
        cornerTurns = kMaxTurnsFraction;
    }
    double width = 1.0 / cornerTurns;
    if (width < 1.0) {
        width = 1.0;
    }
    const std::uint32_t samples = static_cast<std::uint32_t>(width + 0.5);
    pulse_.assign(samples, 0.0);
    double area = 0.0;
    for (std::uint32_t n = 0; n < samples; ++n) {
        pulse_[n] = hammer(n, samples);
        area += pulse_[n];
    }
    if (area > 0.0) {
        for (double& value : pulse_) {
            value /= area;
        }
    }
    for (Ring& ring : rings_) {
        ring.sounds = pitchTurns * ring.ratio < kMaxTurnsFraction && ring.level > 0.0;
    }
}

double ModalBank::sample(double turns) {
    if (!struck_) {
        strike(turns);
        struck_ = true;
    }
    if (turns != lastTurns_) {
        lastTurns_ = turns;
        for (Ring& ring : rings_) {
            turn_to(ring, turns);
        }
    }
    const double input = frame_ < pulse_.size() ? pulse_[frame_] : 0.0;
    ++frame_;
    double out = 0.0;
    for (Ring& ring : rings_) {
        if (!ring.sounds) {
            continue;
        }
        const double re = ring.shrink * (ring.cosine * ring.re - ring.sine * ring.im) + input;
        const double im = ring.shrink * (ring.sine * ring.re + ring.cosine * ring.im);
        ring.re = re;
        ring.im = im;
        out += ring.level * im;
    }
    return out;
}

}  // namespace blipsmith
