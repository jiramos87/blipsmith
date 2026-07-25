"""The human's surface: render, batch, vary, explain, verify-golden.

This is the reproducible backbone of the product. Everything an agent produces
over MCP lands as a committed `{name}.spec.json`, and this is what turns that
file back into the same bytes months later, on a machine that has never run an
agent. So the CLI deliberately holds no synthesis logic of its own: it reads
files, calls the same `blipsmith.render` orchestration the MCP server calls, and
prints what came back. A behaviour that existed only here could not be
reproduced from the other surface, which would break the promise.

Output is plain lines rather than a progress display: no spinners, no colour, no
timestamps. It is meant to be read in a terminal and grepped in a build log, and
two runs of the same command print the same thing.

Exit codes: 0 when everything asked for happened, 1 when any of it did not
(invalid spec, unwritable path, a single failure inside a batch, a golden hash
that moved). Usage errors keep argparse's own 2.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from blipsmith import _core
from blipsmith.explain import explain_spec
from blipsmith.presets import list_presets, load_preset
from blipsmith.ranges import RANGES
from blipsmith.render import render
from blipsmith.result import RenderResult, RenderStatus, SpecError
from blipsmith.spec import to_canonical_json, validate_for_render, validate_spec

EXIT_OK = 0
EXIT_FAILED = 1

SPEC_SUFFIX = ".spec.json"
DEFAULT_GOLDEN_DIR = Path("tests/golden")

# Seeds wrap rather than clamp when a variation walks off the top of the range:
# clamping would hand out the same seed twice and call them two variations.
SEED_MODULO = int(RANGES[("SoundSpec", "seed")].maximum) + 1


class CliError(Exception):
    """A problem the user can act on, reported as one line instead of a stack."""


# --- Reading and printing -----------------------------------------------------


def _read_json(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"cannot read {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise CliError(f"{path}: malformed JSON: {exc}") from exc


def _spec_stem(path: Path) -> str:
    """`laser.spec.json` -> `laser`, and `laser.json` -> `laser`."""
    name = path.name
    if name.endswith(SPEC_SUFFIX):
        return name[: -len(SPEC_SUFFIX)]
    return path.stem


def _number(value: float, places: int = 0) -> str:
    return f"{value:.{places}f}"


def _features_line(features: dict[str, float | None] | None) -> str:
    """The six measurements on one line, in the order an ear would ask for them:
    how long, how loud, how bright, how sudden."""
    if not features:
        return ""
    ordered = (
        ("", "durationMs", " ms", 0),
        ("peak ", "peakDbfs", " dBFS", 1),
        ("rms ", "rmsDbfs", " dBFS", 1),
        ("f0 ", "estimatedFundamentalHz", " Hz", 0),
        ("centroid ", "spectralCentroidHz", " Hz", 0),
        ("attack ", "attackTimeMs", " ms", 1),
    )
    parts = [
        f"{label}{_number(value, places)}{unit}"
        for label, key, unit, places in ordered
        if (value := features.get(key)) is not None
    ]
    return " | ".join(parts)


def _print_result(result: RenderResult) -> None:
    print(result.wavPath)
    print(result.specPath)
    line = _features_line(result.features)
    if line:
        print(f"  {line}")
    for warning in result.warnings:
        print(f"  warning  {warning.message}")


def _failed(result: RenderResult) -> bool:
    return result.status in {RenderStatus.INVALID_SPEC, RenderStatus.RENDER_FAILED}


def _reason(result: RenderResult) -> str:
    return result.error.message if result.error else "render failed"


# --- Commands -----------------------------------------------------------------


def cmd_render(args: argparse.Namespace) -> int:
    if (args.spec is None) == (args.preset is None):
        raise CliError("pass a spec file or --preset, not both and not neither")

    if args.preset is not None:
        # Straight through the same registry the MCP server uses, then treated as
        # any other spec: a preset is a starting point, not a second code path.
        data: Any = load_preset(args.preset).model_dump(mode="json")
    else:
        data = _read_json(args.spec)
    if args.seed is not None and isinstance(data, dict):
        data["seed"] = args.seed

    result = render(data, out_dir=args.out_dir, name=args.name, overwrite=args.overwrite)
    if _failed(result):
        raise CliError(_reason(result))
    _print_result(result)
    return EXIT_OK


def cmd_presets(args: argparse.Namespace) -> int:
    """The catalogue, one preset per line. Without this a human at a terminal has
    to know the file path inside the installed package to start from a preset."""
    presets = list_presets()
    tags = {preset.name: ",".join(preset.tags) for preset in presets}
    name_width = max(len(preset.name) for preset in presets)
    tag_width = max(len(value) for value in tags.values())
    for preset in presets:
        print(
            f"{preset.name:<{name_width}}  {tags[preset.name]:<{tag_width}}  {preset.description}"
        )
    print(f"{len(presets)} presets. Render one with: blipsmith render --preset {presets[0].name}")
    return EXIT_OK


def cmd_batch(args: argparse.Namespace) -> int:
    directory: Path = args.directory
    if not directory.is_dir():
        raise CliError(f"{directory} is not a directory")

    specs = sorted(directory.glob(f"*{SPEC_SUFFIX}"))
    if not specs:
        raise CliError(f"no *{SPEC_SUFFIX} files in {directory}")

    failures = 0
    for path in specs:
        try:
            result = render(_read_json(path), out_dir=args.out_dir, overwrite=args.overwrite)
        except CliError as exc:
            print(f"FAIL  {path.name}: {exc}")
            failures += 1
            continue
        if _failed(result):
            print(f"FAIL  {path.name}: {_reason(result)}")
            failures += 1
            continue
        print(f"ok    {path.name} -> {result.wavPath}")

    # The summary is the point of the command: a batch is run to find out which
    # of fifty specs still render, not to watch one of them succeed.
    rendered = len(specs) - failures
    print(f"{rendered} of {len(specs)} specs rendered, {failures} failed.")
    return EXIT_FAILED if failures else EXIT_OK


def cmd_vary(args: argparse.Namespace) -> int:
    if args.count < 1:
        raise CliError("--count must be at least 1")

    data = _read_json(args.spec)
    if not isinstance(data, dict):
        raise CliError(f"{args.spec}: a spec must be a JSON object")

    base_seed = data.get("seed", 0)
    if not isinstance(base_seed, int):
        base_seed = 0
    meta = data.get("meta")
    base_name = meta.get("name") if isinstance(meta, dict) else None
    stem = args.name or base_name or _spec_stem(args.spec)

    for index in range(1, args.count + 1):
        variant = copy.deepcopy(data)
        variant["seed"] = (base_seed + index) % SEED_MODULO
        # The name moves with the seed so each variation owns its own pair of
        # files and re-renders from its own sidecar with no extra arguments.
        # `meta.name` never reaches the core, so this changes no audio.
        variant.setdefault("meta", {})
        if isinstance(variant["meta"], dict):
            variant["meta"]["name"] = f"{stem}-{index}"

        result = render(variant, out_dir=args.out_dir, overwrite=args.overwrite)
        if _failed(result):
            raise CliError(_reason(result))
        print(f"{result.wavPath}  seed {variant['seed']}")

    print(f"{args.count} variations of {args.spec.name}.")
    return EXIT_OK


def cmd_explain(args: argparse.Namespace) -> int:
    spec, warnings = validate_spec(_read_json(args.spec))
    print(explain_spec(spec))
    for warning in warnings:
        print(f"  warning  {warning.message}")
    return EXIT_OK


def cmd_verify_golden(args: argparse.Namespace) -> int:
    golden: Path = args.golden_dir
    specs_dir = golden / "specs"
    hashes_path = golden / "hashes.json"
    if not specs_dir.is_dir():
        raise CliError(f"no golden specs at {specs_dir}")

    recorded = _read_json(hashes_path)
    if not isinstance(recorded, dict):
        raise CliError(f"{hashes_path}: expected an object mapping spec name to hash")

    specs = sorted(specs_dir.glob(f"*{SPEC_SUFFIX}"))
    matched = 0
    problems = 0
    for path in specs:
        try:
            spec, _ = validate_for_render(_read_json(path))
            digest = hashlib.sha256(_core.render(to_canonical_json(spec))["wav"]).hexdigest()
        except (CliError, SpecError) as exc:
            message = exc.error.message if isinstance(exc, SpecError) else str(exc)
            print(f"ERROR     {path.name}: {message}")
            problems += 1
            continue

        expected = recorded.get(path.name)
        if expected is None:
            print(f"UNKNOWN   {path.name}: no recorded hash")
            problems += 1
        elif expected == digest:
            print(f"match     {path.name}")
            matched += 1
        else:
            print(f"MISMATCH  {path.name}: recorded {expected[:12]}, rendered {digest[:12]}")
            problems += 1

    # A hash whose spec was deleted is never checked by anything, so it would sit
    # in the file looking like coverage forever.
    for orphan in sorted(set(recorded) - {path.name for path in specs}):
        print(f"ORPHAN    {orphan}: recorded hash with no spec")
        problems += 1

    print(f"{len(specs)} golden specs, {matched} match, {problems} to look at.")
    return EXIT_FAILED if problems else EXIT_OK


# --- Argument parsing ---------------------------------------------------------


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="where to write. Defaults to $BLIPSMITH_OUT_DIR, then ./blipsmith-out.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace files already at the target paths (refused by default).",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="blipsmith",
        description="Render lo-fi sound effects from a SoundSpec, deterministically.",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")

    render_cmd = commands.add_parser("render", help="render one spec file to WAV plus a sidecar")
    render_cmd.add_argument("spec", type=Path, nargs="?", help="a .spec.json file")
    render_cmd.add_argument(
        "--preset", default=None, help="render a shipped preset instead of a file"
    )
    render_cmd.add_argument("--seed", type=int, default=None, help="override the spec's seed")
    render_cmd.add_argument("--name", default=None, help="override the output file stem")
    _add_output_flags(render_cmd)
    render_cmd.set_defaults(handler=cmd_render)

    batch_cmd = commands.add_parser("batch", help="render every spec in a directory")
    batch_cmd.add_argument("directory", type=Path, help=f"a directory of *{SPEC_SUFFIX} files")
    _add_output_flags(batch_cmd)
    batch_cmd.set_defaults(handler=cmd_batch)

    vary_cmd = commands.add_parser("vary", help="emit N seeded variations of one spec")
    vary_cmd.add_argument("spec", type=Path, help="a .spec.json file")
    vary_cmd.add_argument(
        "-n", "--count", type=int, default=5, help="how many variations (default 5)"
    )
    vary_cmd.add_argument("--name", default=None, help="override the stem the variations share")
    _add_output_flags(vary_cmd)
    vary_cmd.set_defaults(handler=cmd_vary)

    presets_cmd = commands.add_parser("presets", help="list the shipped presets")
    presets_cmd.set_defaults(handler=cmd_presets)

    explain_cmd = commands.add_parser("explain", help="describe a spec in words, without rendering")
    explain_cmd.add_argument("spec", type=Path, help="a .spec.json file")
    explain_cmd.set_defaults(handler=cmd_explain)

    golden_cmd = commands.add_parser(
        "verify-golden", help="re-render the golden corpus and compare hashes"
    )
    golden_cmd.add_argument(
        "golden_dir",
        type=Path,
        nargs="?",
        default=DEFAULT_GOLDEN_DIR,
        help=f"the corpus directory (default {DEFAULT_GOLDEN_DIR})",
    )
    golden_cmd.set_defaults(handler=cmd_verify_golden)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exit_code: int = args.handler(args)
        return exit_code
    except CliError as exc:
        print(f"blipsmith: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except SpecError as exc:
        print(f"blipsmith: {exc.error.message}", file=sys.stderr)
        if exc.error.validValues:
            valid = ", ".join(str(value) for value in exc.error.validValues)
            print(f"  valid values: {valid}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover - exercised through the console script
    sys.exit(main())
