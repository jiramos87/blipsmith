#include "wav.h"

#include <cstddef>

namespace blipsmith {
namespace {

void put_u32(std::string& out, std::uint32_t value) {
    out.push_back(static_cast<char>(value & 0xFF));
    out.push_back(static_cast<char>((value >> 8) & 0xFF));
    out.push_back(static_cast<char>((value >> 16) & 0xFF));
    out.push_back(static_cast<char>((value >> 24) & 0xFF));
}

void put_u16(std::string& out, std::uint16_t value) {
    out.push_back(static_cast<char>(value & 0xFF));
    out.push_back(static_cast<char>((value >> 8) & 0xFF));
}

void put_tag(std::string& out, const char* tag) {
    out.append(tag, 4);
}

}  // namespace

std::int16_t to_pcm16(double sample) {
    const double scaled = sample * 32767.0;
    // A cast to an integer truncates toward zero, so the half-offset turns it
    // into round-half-away-from-zero without touching libm.
    const double biased = scaled >= 0.0 ? scaled + 0.5 : scaled - 0.5;
    if (biased >= 32767.0) {
        return 32767;
    }
    if (biased <= -32768.0) {
        return -32768;
    }
    return static_cast<std::int16_t>(static_cast<std::int32_t>(biased));
}

std::string encode_wav_pcm16(const std::vector<double>& interleaved, int sampleRate,
                             int channels) {
    const std::uint32_t sample_count = static_cast<std::uint32_t>(interleaved.size());
    const std::uint32_t data_bytes = sample_count * 2U;
    const std::uint16_t block_align = static_cast<std::uint16_t>(channels * 2);
    const std::uint32_t byte_rate = static_cast<std::uint32_t>(sampleRate) * block_align;

    std::string out;
    out.reserve(kWavHeaderBytes + data_bytes);

    put_tag(out, "RIFF");
    put_u32(out, 36U + data_bytes);  // everything after this field
    put_tag(out, "WAVE");

    put_tag(out, "fmt ");
    put_u32(out, 16U);                                  // PCM fmt chunk size
    put_u16(out, 1U);                                   // audio format: PCM
    put_u16(out, static_cast<std::uint16_t>(channels));
    put_u32(out, static_cast<std::uint32_t>(sampleRate));
    put_u32(out, byte_rate);
    put_u16(out, block_align);
    put_u16(out, 16U);  // bits per sample

    put_tag(out, "data");
    put_u32(out, data_bytes);

    for (const double sample : interleaved) {
        const std::int16_t value = to_pcm16(sample);
        put_u16(out, static_cast<std::uint16_t>(value));
    }

    return out;
}

}  // namespace blipsmith
