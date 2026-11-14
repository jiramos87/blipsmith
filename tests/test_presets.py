"""B10: the preset library.

A preset is a plain spec file, so most of what could go wrong here is not
audible: a name that does not match its file, a description that says nothing, a
patch that clamps on load, two entries that are secretly the same sound. Those
are what this file checks, plus the one thing that matters to the driving agent
above all: every listed preset actually loads and actually makes a sound.

Sound design cannot be asserted, only characterized. The archetype checks below
pin the property each preset's description claims (a laser falls, a jump rises,
a closed hat is over before an open one has started) rather than trying to
express taste as an assertion.
"""

from __future__ import annotations

import itertools
import json
import math
import struct
from pathlib import Path
from typing import Any

import pytest

import blipsmith
from blipsmith.presets import PRESET_DIR, PRESET_SUFFIX, list_presets, load_preset, preset_names
from blipsmith.ranges import LIMITER_TARGET_DBFS
from blipsmith.render import render
from blipsmith.result import ErrorCode, RenderStatus, SpecError
from blipsmith.spec import to_canonical_json, validate_for_render

GOLDEN = Path(__file__).resolve().parent / "golden"

PEAK_TOLERANCE_DB = 0.05

# The archetypes the backlog names. Splitting them here rather than reading the
# tags back means a preset cannot satisfy the coverage check by relabelling
# itself.
GAME_SFX = ("laser", "jump", "coin", "explosion", "hit", "powerup", "ui-blip")
DRUM_KIT = ("kick", "snare", "hat-closed", "hat-open", "clap", "tom")

ALL_PRESETS = (*GAME_SFX, *DRUM_KIT)


# --- Rendering and measurement ------------------------------------------------


def samples_of(name: str) -> tuple[int, ...]:
    spec = load_preset(name)
    wav: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    count = struct.unpack_from("<I", wav, 40)[0] // 2
    return struct.unpack_from(f"<{count}h", wav, 44)


def features_of(name: str) -> dict[str, float]:
    spec = load_preset(name)
    measured: dict[str, float] = blipsmith._core.render(to_canonical_json(spec))["features"]
    return measured


def peak_dbfs(samples: tuple[int, ...]) -> float:
    top = max(abs(value) for value in samples)
    return 20 * math.log10(top / 32767.0) if top else -math.inf


def pitch_hz(chunk: tuple[int, ...] | list[int], sample_rate: int) -> float:
    """A crude pitch read from zero crossings.

    Enough to see which way a sweep is going, which is all the archetype checks
    need, and blind to the octave errors a real estimator would argue about.
    """
    crossings = sum(1 for a, b in itertools.pairwise(chunk) if (a < 0) != (b < 0))
    return crossings * sample_rate / (2 * len(chunk))


def window_peak(samples: tuple[int, ...], start_ms: float, end_ms: float, rate: int) -> int:
    first = int(start_ms * rate / 1000)
    last = int(end_ms * rate / 1000)
    window = samples[first:last]
    return max(abs(value) for value in window) if window else 0


# --- The catalogue ------------------------------------------------------------


def test_every_preset_is_listed_with_what_it_needs() -> None:
    """An agent chooses from this listing alone, so every field has to carry
    something. A nameless or undescribed preset is one it cannot pick."""
    for info in list_presets():
        assert info.name, "a preset needs a name"
        assert info.tags, f"{info.name} has no tags to search by"
        assert info.description, f"{info.name} has no description"


def test_a_description_is_one_line() -> None:
    """One line, as the acceptance says: this goes into a tool result the agent
    reads at a glance, not into documentation."""
    for info in list_presets():
        assert "\n" not in info.description
        assert len(info.description) <= 120, f"{info.name}: {len(info.description)} characters"
        assert info.description.endswith("."), f"{info.name} should read as a sentence"


def test_the_listing_covers_game_sfx_and_a_drum_kit() -> None:
    """The two families the PRD asks for, taken from the tags an agent would
    actually filter on."""
    families = {info.name: set(info.tags) for info in list_presets()}

    sfx = {name for name, tags in families.items() if "sfx" in tags}
    drums = {name for name, tags in families.items() if "drum" in tags}

    assert sfx == set(GAME_SFX)
    assert drums == set(DRUM_KIT)
    assert sfx | drums == set(families), "every preset should declare a family"


def test_the_library_covers_the_archetypes_the_backlog_names() -> None:
    assert set(preset_names()) == set(ALL_PRESETS)


def test_the_catalogue_is_stable() -> None:
    """Sorted, so a caller that diffs two listings sees real changes only."""
    assert [info.name for info in list_presets()] == sorted(ALL_PRESETS)


# --- Loading ------------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_every_listed_name_loads(name: str) -> None:
    spec = load_preset(name)

    assert spec.voices, f"{name} would render silence"
    assert spec.version == 1


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_a_preset_is_named_after_its_file(name: str) -> None:
    """`meta.name` is what a render writes to disk, so the file an agent asked
    for is the file it gets."""
    assert load_preset(name).meta.name == name


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_a_preset_is_authored_in_range(name: str) -> None:
    """A preset that clamps on load would be teaching the agent a value it is
    not allowed to use."""
    _, warnings = validate_for_render(
        json.loads((PRESET_DIR / f"{name}{PRESET_SUFFIX}").read_text())
    )

    assert warnings == []


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_a_preset_ships_with_the_default_seed(name: str) -> None:
    """The acceptance renders every preset at seed 0, and the golden hashes are
    recorded there."""
    assert load_preset(name).seed == 0


def test_loading_twice_returns_independent_specs() -> None:
    """A preset is a starting point, so the first thing anyone does is edit it.
    That must not reach the next caller."""
    first = load_preset("laser")
    first.voices[0].fundamentalHz = 20.0
    first.meta.name = "mine"

    second = load_preset("laser")

    assert second.voices[0].fundamentalHz != 20.0
    assert second.meta.name == "laser"


def test_an_unknown_preset_names_the_valid_ones() -> None:
    with pytest.raises(SpecError) as raised:
        load_preset("laserr")

    error = raised.value.error
    assert error.code is ErrorCode.INVALID_SPEC
    assert error.validValues == sorted(ALL_PRESETS)
    assert "laser" in error.message


@pytest.mark.parametrize("name", ["", "LASER", "laser.spec.json", "../spec", "kit/kick"])
def test_a_name_that_is_not_a_preset_is_refused(name: str) -> None:
    """Including the ones that look like near-misses: a path, an extension, the
    wrong case. The registry answers to exactly the published names."""
    with pytest.raises(SpecError):
        load_preset(name)


def test_a_failed_load_leaves_the_library_untouched() -> None:
    before = list_presets()

    with pytest.raises(SpecError):
        load_preset("nope")

    assert list_presets() == before


def test_presets_ship_beside_the_package() -> None:
    """They are package data, not test fixtures: an installed wheel has to carry
    them or `load_preset` fails for every user who did not clone the repo."""
    assert PRESET_DIR.name == "presets"
    assert (PRESET_DIR / "__init__.py").exists()
    assert len(list(PRESET_DIR.glob(f"*{PRESET_SUFFIX}"))) == len(ALL_PRESETS)


# --- Rendering ----------------------------------------------------------------


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_a_preset_renders_without_clipping(name: str) -> None:
    samples = samples_of(name)

    assert any(value != 0 for value in samples), f"{name} rendered silence"
    assert min(samples) > -32768, f"{name} wrapped past negative full scale"
    assert peak_dbfs(samples) == pytest.approx(LIMITER_TARGET_DBFS, abs=PEAK_TOLERANCE_DB)


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_a_preset_reports_a_full_set_of_features(name: str) -> None:
    """The agent steers by these, and it loaded this preset precisely because it
    could not hear what it was choosing."""
    measured = features_of(name)

    assert set(measured) == {
        "durationMs",
        "peakDbfs",
        "rmsDbfs",
        "estimatedFundamentalHz",
        "spectralCentroidHz",
        "attackTimeMs",
        # docs/prd/blipsmith-music-mode.md: loudness and true peak, on every render.
        "integratedLufs",
        "truePeakDbtp",
    }
    assert all(value is not None for value in measured.values())
    assert measured["durationMs"] == pytest.approx(load_preset(name).durationMs, abs=1.0)


def test_no_two_presets_render_the_same_bytes() -> None:
    """Thirteen names have to be thirteen sounds."""
    rendered = {name: samples_of(name) for name in ALL_PRESETS}

    assert len(set(rendered.values())) == len(ALL_PRESETS)


def test_a_preset_renders_through_the_normal_pipeline(tmp_path: Path) -> None:
    """The registry hands back an ordinary spec, so it goes through the same
    `render` every other spec does, warnings and sidecar and all."""
    result = render(load_preset("kick").model_dump(mode="json"), out_dir=tmp_path)

    assert result.status is RenderStatus.RENDERED_OK
    assert result.wavPath is not None and Path(result.wavPath).name == "kick.wav"
    assert result.specPath is not None and Path(result.specPath).exists()
    assert result.explanation


# --- What each archetype claims to be -----------------------------------------


@pytest.mark.parametrize(
    ("name", "falls"),
    [("laser", True), ("kick", True), ("tom", True), ("jump", False)],
)
def test_the_pitch_sweeps_the_way_its_description_says(name: str, falls: bool) -> None:
    """The mod-envelope presets are the ones whose direction is easy to get
    backwards, and impossible to notice without listening."""
    samples = samples_of(name)
    rate = int(load_preset(name).sampleRate)
    fifth = len(samples) // 5

    head = pitch_hz(samples[:fifth], rate)
    next_fifth = pitch_hz(samples[fifth : 2 * fifth], rate)

    if falls:
        assert head > next_fifth * 1.2, f"{name} should be falling in pitch"
    else:
        assert next_fifth > head * 1.2, f"{name} should be rising in pitch"


def test_a_closed_hat_is_over_before_an_open_one_is() -> None:
    """The pair only earns two entries if they differ in the one way their
    names promise."""
    closed = load_preset("hat-closed")
    open_hat = load_preset("hat-open")

    assert closed.durationMs < open_hat.durationMs
    assert closed.voices[0].ampEnv.decayMs < open_hat.voices[0].ampEnv.decayMs

    rate = int(closed.sampleRate)
    assert window_peak(samples_of("hat-closed"), 60.0, 110.0, rate) == 0, "a closed hat should stop"
    assert window_peak(samples_of("hat-open"), 300.0, 400.0, rate) > 0, "an open hat should ring"


def test_a_clap_is_several_bursts_and_not_one() -> None:
    """What the delay is doing in that preset: the first burst is followed by
    quieter repeats rather than by silence."""
    samples = samples_of("clap")
    rate = int(load_preset("clap").sampleRate)
    bursts = [window_peak(samples, start, start + 12.0, rate) for start in (0.0, 12.0, 24.0, 36.0)]

    assert all(value > 0 for value in bursts), "every early window should carry a burst"
    assert bursts[3] < bursts[0], "and they should be dying away, not building"


def test_a_powerup_climbs_in_steps() -> None:
    """Four notes, so four onsets, each higher than the last."""
    spec = load_preset("powerup")
    assert spec.composition is not None
    pitches = [note.midiNote for note in spec.composition.tracks[0].notes]

    assert len(pitches) == 4
    assert pitches == sorted(p for p in pitches if p is not None)
    assert pitches[-1] is not None and pitches[0] is not None
    assert pitches[-1] - pitches[0] == 12, "an octave, as the description says"


def test_the_noisy_presets_are_brighter_than_the_tuned_ones() -> None:
    """A one-line sanity check on the whole library's spectral spread, which is
    the number the agent will reach for first when it wants a darker hit."""
    centroid = {name: features_of(name)["spectralCentroidHz"] for name in ALL_PRESETS}

    assert centroid["hat-closed"] > centroid["snare"] > centroid["kick"]
    assert centroid["kick"] < 200.0, "a kick has almost nothing above its fundamental"


# --- The golden corpus --------------------------------------------------------


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_the_golden_copy_matches_the_preset_it_was_taken_from(name: str) -> None:
    """The corpus freezes bytes, so its copy of a preset has to be that preset.
    Editing a preset without re-recording its golden fails here, which is the
    point: the hash below would otherwise be guarding a file nobody ships."""
    shipped = (PRESET_DIR / f"{name}{PRESET_SUFFIX}").read_bytes()
    frozen = (GOLDEN / "specs" / f"preset-{name}{PRESET_SUFFIX}").read_bytes()

    assert shipped == frozen


@pytest.mark.parametrize("name", ALL_PRESETS)
def test_every_preset_has_a_golden_entry(name: str) -> None:
    recorded = json.loads((GOLDEN / "hashes.json").read_text())

    assert f"preset-{name}{PRESET_SUFFIX}" in recorded


def golden_preset_specs() -> list[str]:
    return sorted(path.name for path in (GOLDEN / "specs").glob(f"preset-*{PRESET_SUFFIX}"))


def test_the_corpus_holds_no_golden_for_a_preset_that_no_longer_exists() -> None:
    expected = sorted(f"preset-{name}{PRESET_SUFFIX}" for name in ALL_PRESETS)

    assert golden_preset_specs() == expected


def test_hashes_are_taken_from_the_seed_the_acceptance_names() -> None:
    """A noise preset renders differently under a different seed, which is what
    makes "rendered with seed 0" load-bearing rather than incidental."""
    name = "snare"
    at_zero = samples_of(name)
    payload: dict[str, Any] = json.loads((PRESET_DIR / f"{name}{PRESET_SUFFIX}").read_text())
    payload["seed"] = 1
    spec, _ = validate_for_render(payload)
    at_one: bytes = blipsmith._core.render(to_canonical_json(spec))["wav"]
    count = struct.unpack_from("<I", at_one, 40)[0] // 2

    assert struct.unpack_from(f"<{count}h", at_one, 44) != at_zero
