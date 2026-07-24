#include "tables.h"

#include <array>
#include <vector>

namespace blipsmith {
namespace {

// The double nearest to pi, written as a literal so no platform routine is
// consulted for it.
constexpr double kTwoPi = 6.283185307179586476925286766559;

// sin(x) on [0, pi/2] as a fixed-length Taylor series in Horner form. The term
// count is fixed rather than convergence-driven, so the arithmetic is the same
// sequence of exactly-rounded operations everywhere. Truncating after x^17
// leaves an error near 1e-14, roughly 3e-10 of an int16 LSB.
double poly_sin(double x) {
    const double u = x * x;
    double p = 1.0 / 355687428096000.0;  // +1/17!
    p = p * u - 1.0 / 1307674368000.0;   // -1/15!
    p = p * u + 1.0 / 6227020800.0;      // +1/13!
    p = p * u - 1.0 / 39916800.0;        // -1/11!
    p = p * u + 1.0 / 362880.0;          // +1/9!
    p = p * u - 1.0 / 5040.0;            // -1/7!
    p = p * u + 1.0 / 120.0;             // +1/5!
    p = p * u - 1.0 / 6.0;               // -1/3!
    p = p * u + 1.0;
    return x * p;
}

// Quarter-turn symmetry keeps the polynomial argument inside [0, pi/2], where
// the fixed term count is most accurate.
double sine_of_turn(double turn) {
    if (turn <= 0.25) {
        return poly_sin(kTwoPi * turn);
    }
    if (turn <= 0.5) {
        return poly_sin(kTwoPi * (0.5 - turn));
    }
    if (turn <= 0.75) {
        return -poly_sin(kTwoPi * (turn - 0.5));
    }
    return -poly_sin(kTwoPi * (1.0 - turn));
}

std::vector<double> build_sine_table() {
    std::vector<double> table(kSineTableSize + 1);
    for (std::size_t i = 0; i < kSineTableSize; ++i) {
        table[i] = sine_of_turn(static_cast<double>(i) / static_cast<double>(kSineTableSize));
    }
    table[kSineTableSize] = table[0];
    return table;
}

// 2^(1/12): the equal-tempered semitone ratio, as a literal.
constexpr double kSemitoneRatio = 1.0594630943592952645618252949463;

std::array<double, 128> build_midi_table() {
    // Powers of the semitone ratio by repeated multiplication, and octaves by
    // exact doubling. Both avoid pow while staying a fixed operation sequence.
    std::array<double, 12> semitone{};
    semitone[0] = 1.0;
    for (int i = 1; i < 12; ++i) {
        semitone[i] = semitone[i - 1] * kSemitoneRatio;
    }

    std::array<double, 128> table{};
    for (int note = 0; note < 128; ++note) {
        int octave = (note - 69) / 12;
        int step = (note - 69) % 12;
        if (step < 0) {  // C++ truncates toward zero; we want a floor division
            step += 12;
            --octave;
        }
        double scale = 440.0 * semitone[static_cast<std::size_t>(step)];
        for (int i = 0; i < octave; ++i) {
            scale *= 2.0;
        }
        for (int i = 0; i > octave; --i) {
            scale *= 0.5;
        }
        table[static_cast<std::size_t>(note)] = scale;
    }
    return table;
}

}  // namespace

const double* sine_table() {
    static const std::vector<double> table = build_sine_table();
    return table.data();
}

double midi_to_hz(int note) {
    static const std::array<double, 128> table = build_midi_table();
    if (note < 0) {
        note = 0;
    }
    if (note > 127) {
        note = 127;
    }
    return table[static_cast<std::size_t>(note)];
}

}  // namespace blipsmith
