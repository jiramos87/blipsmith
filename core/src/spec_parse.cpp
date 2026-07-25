#include "spec_parse.h"

#include <cstddef>
#include <locale>
#include <sstream>
#include <stdexcept>
#include <utility>

namespace blipsmith {
namespace {

constexpr int kMaxDepth = 64;

struct JsonValue {
    enum class Kind { Null, Bool, Number, String, Array, Object };

    Kind kind = Kind::Null;
    bool boolean = false;
    double number = 0.0;
    std::string text;
    std::vector<JsonValue> items;
    std::vector<std::pair<std::string, JsonValue>> members;

    const JsonValue* find(const char* key) const {
        for (const auto& member : members) {
            if (member.first == key) {
                return &member.second;
            }
        }
        return nullptr;
    }
};

// Number conversion goes through a classic-locale stream rather than strtod.
// strtod honours LC_NUMERIC, so in a comma-decimal locale it would read "1.5"
// as 1 and silently render the wrong sound.
double parse_number(const std::string& token) {
    std::istringstream stream(token);
    stream.imbue(std::locale::classic());
    double value = 0.0;
    stream >> value;
    if (stream.fail()) {
        throw std::runtime_error("invalid JSON number: " + token);
    }
    return value;
}

void encode_utf8(unsigned int code_point, std::string& out) {
    if (code_point < 0x80) {
        out.push_back(static_cast<char>(code_point));
    } else if (code_point < 0x800) {
        out.push_back(static_cast<char>(0xC0 | (code_point >> 6)));
        out.push_back(static_cast<char>(0x80 | (code_point & 0x3F)));
    } else if (code_point < 0x10000) {
        out.push_back(static_cast<char>(0xE0 | (code_point >> 12)));
        out.push_back(static_cast<char>(0x80 | ((code_point >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (code_point & 0x3F)));
    } else {
        out.push_back(static_cast<char>(0xF0 | (code_point >> 18)));
        out.push_back(static_cast<char>(0x80 | ((code_point >> 12) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | ((code_point >> 6) & 0x3F)));
        out.push_back(static_cast<char>(0x80 | (code_point & 0x3F)));
    }
}

class Parser {
public:
    explicit Parser(const std::string& text) : text_(text) {}

    JsonValue parse() {
        skip_whitespace();
        JsonValue root = parse_value(0);
        skip_whitespace();
        if (pos_ != text_.size()) {
            fail("trailing characters after the top-level value");
        }
        return root;
    }

private:
    const std::string& text_;
    std::size_t pos_ = 0;

    [[noreturn]] void fail(const std::string& why) const {
        throw std::runtime_error("spec JSON parse error at offset " + std::to_string(pos_) +
                                 ": " + why);
    }

    char peek() const {
        if (pos_ >= text_.size()) {
            throw std::runtime_error("spec JSON parse error: unexpected end of input");
        }
        return text_[pos_];
    }

    void expect(char expected) {
        if (peek() != expected) {
            fail(std::string("expected '") + expected + "'");
        }
        ++pos_;
    }

    void skip_whitespace() {
        while (pos_ < text_.size()) {
            const char c = text_[pos_];
            if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
                ++pos_;
            } else {
                break;
            }
        }
    }

    bool literal(const char* word) {
        const std::size_t length = std::char_traits<char>::length(word);
        if (text_.compare(pos_, length, word) == 0) {
            pos_ += length;
            return true;
        }
        return false;
    }

    JsonValue parse_value(int depth) {
        if (depth > kMaxDepth) {
            fail("nesting is too deep");
        }
        switch (peek()) {
            case '{':
                return parse_object(depth);
            case '[':
                return parse_array(depth);
            case '"': {
                JsonValue value;
                value.kind = JsonValue::Kind::String;
                value.text = parse_string();
                return value;
            }
            case 't': {
                if (!literal("true")) fail("expected 'true'");
                JsonValue value;
                value.kind = JsonValue::Kind::Bool;
                value.boolean = true;
                return value;
            }
            case 'f': {
                if (!literal("false")) fail("expected 'false'");
                JsonValue value;
                value.kind = JsonValue::Kind::Bool;
                value.boolean = false;
                return value;
            }
            case 'n': {
                if (!literal("null")) fail("expected 'null'");
                return JsonValue{};
            }
            default:
                return parse_number_value();
        }
    }

    JsonValue parse_object(int depth) {
        expect('{');
        JsonValue value;
        value.kind = JsonValue::Kind::Object;
        skip_whitespace();
        if (peek() == '}') {
            ++pos_;
            return value;
        }
        while (true) {
            skip_whitespace();
            std::string key = parse_string();
            skip_whitespace();
            expect(':');
            skip_whitespace();
            value.members.emplace_back(std::move(key), parse_value(depth + 1));
            skip_whitespace();
            if (peek() == ',') {
                ++pos_;
                continue;
            }
            expect('}');
            return value;
        }
    }

    JsonValue parse_array(int depth) {
        expect('[');
        JsonValue value;
        value.kind = JsonValue::Kind::Array;
        skip_whitespace();
        if (peek() == ']') {
            ++pos_;
            return value;
        }
        while (true) {
            skip_whitespace();
            value.items.push_back(parse_value(depth + 1));
            skip_whitespace();
            if (peek() == ',') {
                ++pos_;
                continue;
            }
            expect(']');
            return value;
        }
    }

    std::string parse_string() {
        expect('"');
        std::string out;
        while (true) {
            if (pos_ >= text_.size()) {
                fail("unterminated string");
            }
            const char c = text_[pos_++];
            if (c == '"') {
                return out;
            }
            if (c != '\\') {
                out.push_back(c);
                continue;
            }
            if (pos_ >= text_.size()) {
                fail("unterminated escape");
            }
            const char escape = text_[pos_++];
            switch (escape) {
                case '"': out.push_back('"'); break;
                case '\\': out.push_back('\\'); break;
                case '/': out.push_back('/'); break;
                case 'b': out.push_back('\b'); break;
                case 'f': out.push_back('\f'); break;
                case 'n': out.push_back('\n'); break;
                case 'r': out.push_back('\r'); break;
                case 't': out.push_back('\t'); break;
                case 'u': {
                    unsigned int code_point = parse_hex4();
                    // Python's json.dumps escapes non-ASCII, so surrogate pairs
                    // arrive here for anything outside the BMP.
                    if (code_point >= 0xD800 && code_point <= 0xDBFF && pos_ + 1 < text_.size() &&
                        text_[pos_] == '\\' && text_[pos_ + 1] == 'u') {
                        pos_ += 2;
                        const unsigned int low = parse_hex4();
                        code_point = 0x10000 + ((code_point - 0xD800) << 10) + (low - 0xDC00);
                    }
                    encode_utf8(code_point, out);
                    break;
                }
                default:
                    fail("unknown string escape");
            }
        }
    }

    unsigned int parse_hex4() {
        if (pos_ + 4 > text_.size()) {
            fail("truncated \\u escape");
        }
        unsigned int value = 0;
        for (int i = 0; i < 4; ++i) {
            const char c = text_[pos_++];
            value <<= 4;
            if (c >= '0' && c <= '9') {
                value |= static_cast<unsigned int>(c - '0');
            } else if (c >= 'a' && c <= 'f') {
                value |= static_cast<unsigned int>(c - 'a' + 10);
            } else if (c >= 'A' && c <= 'F') {
                value |= static_cast<unsigned int>(c - 'A' + 10);
            } else {
                fail("bad hex digit in \\u escape");
            }
        }
        return value;
    }

    JsonValue parse_number_value() {
        const std::size_t start = pos_;
        if (pos_ < text_.size() && (text_[pos_] == '-' || text_[pos_] == '+')) {
            ++pos_;
        }
        while (pos_ < text_.size()) {
            const char c = text_[pos_];
            const bool numeric = (c >= '0' && c <= '9') || c == '.' || c == 'e' || c == 'E' ||
                                 c == '+' || c == '-';
            if (!numeric) {
                break;
            }
            ++pos_;
        }
        if (start == pos_) {
            fail("expected a value");
        }
        JsonValue value;
        value.kind = JsonValue::Kind::Number;
        value.number = parse_number(text_.substr(start, pos_ - start));
        return value;
    }
};

// --- Field readers ------------------------------------------------------------

double number_or(const JsonValue& object, const char* key, double fallback) {
    const JsonValue* found = object.find(key);
    if (found == nullptr || found->kind != JsonValue::Kind::Number) {
        return fallback;
    }
    return found->number;
}

int int_or(const JsonValue& object, const char* key, int fallback) {
    const JsonValue* found = object.find(key);
    if (found == nullptr || found->kind != JsonValue::Kind::Number) {
        return fallback;
    }
    return static_cast<int>(found->number);
}

const JsonValue* object_at(const JsonValue& object, const char* key) {
    const JsonValue* found = object.find(key);
    if (found == nullptr || found->kind != JsonValue::Kind::Object) {
        return nullptr;
    }
    return found;
}

Waveform waveform_from(const JsonValue& voice) {
    const JsonValue* found = voice.find("waveform");
    if (found == nullptr || found->kind != JsonValue::Kind::String) {
        return Waveform::Sine;
    }
    const std::string& name = found->text;
    if (name == "square") return Waveform::Square;
    if (name == "triangle") return Waveform::Triangle;
    if (name == "saw") return Waveform::Saw;
    if (name == "pulse") return Waveform::Pulse;
    if (name == "noise_white") return Waveform::NoiseWhite;
    if (name == "noise_pink") return Waveform::NoisePink;
    return Waveform::Sine;
}

// Enum readers mirror waveform_from: the Python layer has already rejected any
// value outside the closed set, so an unrecognized string here means the two
// layers have drifted apart, and falling back to the documented default is the
// least surprising way to degrade.
LfoShape lfo_shape_from(const JsonValue& block) {
    const JsonValue* found = block.find("shape");
    if (found == nullptr || found->kind != JsonValue::Kind::String) {
        return LfoShape::Sine;
    }
    if (found->text == "triangle") return LfoShape::Triangle;
    if (found->text == "square") return LfoShape::Square;
    if (found->text == "saw") return LfoShape::Saw;
    return LfoShape::Sine;
}

LfoTarget lfo_target_from(const JsonValue& block) {
    const JsonValue* found = block.find("target");
    if (found == nullptr || found->kind != JsonValue::Kind::String) {
        return LfoTarget::Pitch;
    }
    if (found->text == "amplitude") return LfoTarget::Amplitude;
    if (found->text == "cutoff") return LfoTarget::Cutoff;
    return LfoTarget::Pitch;
}

ModEnvTarget mod_env_target_from(const JsonValue& block) {
    const JsonValue* found = block.find("target");
    if (found == nullptr || found->kind != JsonValue::Kind::String) {
        return ModEnvTarget::Pitch;
    }
    return found->text == "cutoff" ? ModEnvTarget::Cutoff : ModEnvTarget::Pitch;
}

AmMode am_mode_from(const JsonValue& block) {
    const JsonValue* found = block.find("mode");
    if (found == nullptr || found->kind != JsonValue::Kind::String) {
        return AmMode::Am;
    }
    return found->text == "ring" ? AmMode::Ring : AmMode::Am;
}

FilterType filter_type_from(const JsonValue& block) {
    const JsonValue* found = block.find("type");
    if (found == nullptr || found->kind != JsonValue::Kind::String) {
        return FilterType::Lowpass;
    }
    if (found->text == "highpass") return FilterType::Highpass;
    if (found->text == "bandpass") return FilterType::Bandpass;
    return FilterType::Lowpass;
}

EffectKind effect_kind_from(const JsonValue& block) {
    const JsonValue* found = block.find("kind");
    if (found == nullptr || found->kind != JsonValue::Kind::String) {
        return EffectKind::Distortion;
    }
    if (found->text == "wavefold") return EffectKind::Wavefold;
    if (found->text == "delay") return EffectKind::Delay;
    if (found->text == "reverb") return EffectKind::Reverb;
    return EffectKind::Distortion;
}

std::vector<Effect> effects_from(const JsonValue& voice) {
    std::vector<Effect> effects;
    const JsonValue* found = voice.find("effects");
    if (found == nullptr || found->kind != JsonValue::Kind::Array) {
        return effects;
    }
    for (const JsonValue& entry : found->items) {
        if (entry.kind != JsonValue::Kind::Object) {
            continue;
        }
        Effect effect;
        effect.kind = effect_kind_from(entry);
        effect.drive = number_or(entry, "drive", effect.drive);
        effect.timeMs = number_or(entry, "timeMs", effect.timeMs);
        effect.feedback = number_or(entry, "feedback", effect.feedback);
        effect.mixWet = number_or(entry, "mixWet", effect.mixWet);
        effect.roomSize = number_or(entry, "roomSize", effect.roomSize);
        effect.damping = number_or(entry, "damping", effect.damping);
        effects.push_back(effect);
    }
    return effects;
}

Composition composition_from(const JsonValue& block) {
    Composition composition;
    composition.tempoBpm = number_or(block, "tempoBpm", composition.tempoBpm);

    const JsonValue* tracks = block.find("tracks");
    if (tracks == nullptr || tracks->kind != JsonValue::Kind::Array) {
        return composition;
    }
    for (const JsonValue& entry : tracks->items) {
        Track track;
        if (entry.kind == JsonValue::Kind::Object) {
            track.gainDb = number_or(entry, "gainDb", track.gainDb);
            track.pan = number_or(entry, "pan", track.pan);
            const JsonValue* notes = entry.find("notes");
            if (notes != nullptr && notes->kind == JsonValue::Kind::Array) {
                for (const JsonValue& item : notes->items) {
                    if (item.kind != JsonValue::Kind::Object) {
                        continue;
                    }
                    Note note;
                    note.startBeat = number_or(item, "startBeat", note.startBeat);
                    note.durationBeats = number_or(item, "durationBeats", note.durationBeats);
                    // Canonical JSON spells "no pitch of its own" as null, which
                    // is not a number, so the fallback is what carries it.
                    note.midiNote = int_or(item, "midiNote", -1);
                    note.velocity = number_or(item, "velocity", note.velocity);
                    track.notes.push_back(note);
                }
            }
        }
        composition.tracks.push_back(track);
    }
    return composition;
}

Adsr adsr_from(const JsonValue* block) {
    Adsr envelope;
    if (block == nullptr) {
        return envelope;
    }
    envelope.attackMs = number_or(*block, "attackMs", envelope.attackMs);
    envelope.decayMs = number_or(*block, "decayMs", envelope.decayMs);
    envelope.sustainLevel = number_or(*block, "sustainLevel", envelope.sustainLevel);
    envelope.releaseMs = number_or(*block, "releaseMs", envelope.releaseMs);
    return envelope;
}

}  // namespace

Spec parse_spec(const std::string& json) {
    Parser parser(json);
    const JsonValue root = parser.parse();
    if (root.kind != JsonValue::Kind::Object) {
        throw std::runtime_error("spec JSON must be an object");
    }

    Spec spec;
    spec.version = int_or(root, "version", spec.version);
    spec.seed = static_cast<std::uint32_t>(number_or(root, "seed", 0.0));
    spec.sampleRate = int_or(root, "sampleRate", spec.sampleRate);
    spec.channels = int_or(root, "channels", spec.channels);
    spec.durationMs = number_or(root, "durationMs", spec.durationMs);

    if (const JsonValue* master = object_at(root, "master")) {
        spec.master.gainDb = number_or(*master, "gainDb", spec.master.gainDb);
        if (const JsonValue* limiter = object_at(*master, "limiter")) {
            spec.master.limiter.targetDbfs =
                number_or(*limiter, "targetDbfs", spec.master.limiter.targetDbfs);
        }
    }

    const JsonValue* composition = root.find("composition");
    spec.hasComposition = composition != nullptr && composition->kind == JsonValue::Kind::Object;
    if (spec.hasComposition) {
        spec.composition = composition_from(*composition);
    }

    if (const JsonValue* voices = root.find("voices")) {
        if (voices->kind == JsonValue::Kind::Array) {
            for (const JsonValue& entry : voices->items) {
                if (entry.kind != JsonValue::Kind::Object) {
                    continue;
                }
                Voice voice;
                voice.waveform = waveform_from(entry);
                voice.fundamentalHz = number_or(entry, "fundamentalHz", voice.fundamentalHz);
                voice.fundamentalMidi = int_or(entry, "fundamentalMidi", -1);
                voice.pulseDuty = number_or(entry, "pulseDuty", voice.pulseDuty);
                voice.ampEnv = adsr_from(object_at(entry, "ampEnv"));

                if (const JsonValue* block = object_at(entry, "modEnv")) {
                    voice.hasModEnv = true;
                    voice.modEnv.target = mod_env_target_from(*block);
                    voice.modEnv.amount = number_or(*block, "amount", voice.modEnv.amount);
                    voice.modEnv.attackMs = number_or(*block, "attackMs", voice.modEnv.attackMs);
                    voice.modEnv.decayMs = number_or(*block, "decayMs", voice.modEnv.decayMs);
                }
                if (const JsonValue* block = object_at(entry, "lfo")) {
                    voice.hasLfo = true;
                    voice.lfo.target = lfo_target_from(*block);
                    voice.lfo.shape = lfo_shape_from(*block);
                    voice.lfo.rateHz = number_or(*block, "rateHz", voice.lfo.rateHz);
                    voice.lfo.depth = number_or(*block, "depth", voice.lfo.depth);
                }
                if (const JsonValue* block = object_at(entry, "fm")) {
                    voice.hasFm = true;
                    voice.fm.ratio = number_or(*block, "ratio", voice.fm.ratio);
                    voice.fm.index = number_or(*block, "index", voice.fm.index);
                }
                if (const JsonValue* block = object_at(entry, "am")) {
                    voice.hasAm = true;
                    voice.am.mode = am_mode_from(*block);
                    voice.am.rateHz = number_or(*block, "rateHz", voice.am.rateHz);
                    voice.am.depth = number_or(*block, "depth", voice.am.depth);
                }

                if (const JsonValue* block = object_at(entry, "filter")) {
                    voice.hasFilter = true;
                    voice.filter.type = filter_type_from(*block);
                    voice.filter.cutoffHz = number_or(*block, "cutoffHz", voice.filter.cutoffHz);
                    voice.filter.resonance =
                        number_or(*block, "resonance", voice.filter.resonance);
                }
                if (const JsonValue* block = object_at(entry, "lofi")) {
                    voice.hasLoFi = true;
                    voice.lofi.bitDepth = int_or(*block, "bitDepth", voice.lofi.bitDepth);
                    voice.lofi.decimation = int_or(*block, "decimation", voice.lofi.decimation);
                }
                voice.effects = effects_from(entry);

                voice.pan = number_or(entry, "pan", voice.pan);
                voice.mixDb = number_or(entry, "mixDb", voice.mixDb);
                voice.track = int_or(entry, "track", voice.track);
                spec.voices.push_back(voice);
            }
        }
    }

    return spec;
}

}  // namespace blipsmith
