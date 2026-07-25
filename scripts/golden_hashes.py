#!/usr/bin/env python3
"""Print the golden corpus as a JSON manifest of spec name to SHA-256 of its WAV.

This exists for the two-platform determinism gate. Each CI platform job runs it
and uploads the result; a join job downloads both manifests and diffs them. Two
machines that agree on every hash have proven the invariant this whole project is
built around, and the diff names the exact spec when they do not.

    python scripts/golden_hashes.py [corpus-dir] > manifest.json

Deliberately not a `blipsmith` subcommand: `verify-golden` answers "did the bytes
move?" for a human, and its output is prose. This answers "what are the bytes?"
for a machine, and its output has to be diffable.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from blipsmith import _core
from blipsmith.spec import to_canonical_json, validate_for_render

DEFAULT_CORPUS = Path(__file__).resolve().parents[1] / "tests" / "golden"
SPEC_SUFFIX = ".spec.json"


def corpus_hashes(corpus: Path = DEFAULT_CORPUS) -> dict[str, str]:
    """Render every spec in `corpus/specs` and hash the WAV bytes.

    Renders through the same validate-canonicalize-core path the product uses, so
    a manifest cannot agree with a render nobody could reproduce.
    """
    specs = sorted((corpus / "specs").glob(f"*{SPEC_SUFFIX}"))
    if not specs:
        raise SystemExit(f"golden_hashes: no specs at {corpus / 'specs'}")

    manifest = {}
    for path in specs:
        spec, _ = validate_for_render(json.loads(path.read_text(encoding="utf-8")))
        wav: bytes = _core.render(to_canonical_json(spec))["wav"]
        manifest[path.name] = hashlib.sha256(wav).hexdigest()
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    corpus = Path(args[0]) if args else DEFAULT_CORPUS
    # Sorted keys and a trailing newline: the join job diffs these as text.
    print(json.dumps(corpus_hashes(corpus), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
