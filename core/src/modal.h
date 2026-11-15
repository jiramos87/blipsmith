// A modal bank (music mode): tuned resonators struck once, in place of the
// oscillator. A drum skin, a cymbal, a wood block or a bar rings as a handful of
// modes, each at its own frequency and pace; this rings them.
//
// Each mode is a complex one-pole resonator: a point turned by the mode's angle
// and shrunk by its decay every frame, the strike added to it, its imaginary part
// heard. A unit impulse rings it at amplitude 1, starting from zero. A turn keeps
// the point's size, so a mode's frequency can move every frame (a conga's pitch
// drop, a glide, vibrato) without its level jumping. The shrink is 2 to a
// negative power, held below 1, so every mode dies away at every legal setting.
//
// The strike is one raised-cosine pulse of unit area, as wide as one cycle of a
// corner set by the brightness: a soft mallet rolls off the upper modes, a hard
// stick rings them all. Nothing here reaches for libm: the decay goes through
// `octave_ratio`, the angles and the pulse read the baked sine.

#pragma once

#include <cstdint>
#include <vector>

#include "spec_parse.h"

namespace blipsmith {

// The octaves a strike's brightness spans: its corner sits from the pitch (0)
// to this many octaves above it (1). Touch moves it in octaves.
inline constexpr double kModalBrightnessOctaves = 7.0;

class ModalBank {
public:
    ModalBank(const Modal& modal, int sampleRate);

    // One sample of the bank, given the voice's pitch this frame in turns per
    // sample. The first call sets the strike from that frame's pitch and decides
    // which modes sound. Call once per frame, in frame order.
    double sample(double turns);

private:
    struct Ring {
        double ratio = 1.0;
        double level = 0.0;
        double shrink = 0.0;
        double re = 0.0;
        double im = 0.0;
        double cosine = 1.0;
        double sine = 0.0;
        bool sounds = true;
    };

    void strike(double turns);
    void turn_to(Ring& ring, double turns) const;

    Modal modal_;
    int sampleRate_;
    std::vector<Ring> rings_;
    std::vector<double> pulse_;
    std::uint32_t frame_ = 0;
    bool struck_ = false;
    double lastTurns_ = -1.0;
};

}  // namespace blipsmith
