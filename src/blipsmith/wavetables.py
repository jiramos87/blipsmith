"""Named wavetables: frames an agent can ask for by name.

A spec only ever holds frames, the harmonic amplitudes of each single-cycle
shape; a name is a shorthand the MCP verb and the session expand into them, so
the contract stays plain data. Every table runs dark to bright, which is what
lets touch read a brighter frame for a harder note.
"""

from __future__ import annotations

from blipsmith.result import invalid_spec

_HARMONICS = 32


def _round(values: list[float]) -> list[float]:
    return [round(v, 6) for v in values]


def _triangle() -> list[float]:
    out = []
    for h in range(1, _HARMONICS + 1):
        if h % 2 == 0:
            out.append(0.0)
        else:
            sign = 1.0 if (h // 2) % 2 == 0 else -1.0
            out.append(sign / (h * h))
    return _round(out)


def _square() -> list[float]:
    return _round([0.0 if h % 2 == 0 else 1.0 / h for h in range(1, _HARMONICS + 1)])


def _saw() -> list[float]:
    return _round([1.0 / h for h in range(1, _HARMONICS + 1)])


NAMED_TABLES: dict[str, tuple[str, list[list[float]]]] = {
    "bright": (
        "sine, triangle, square, saw: the classic shapes from dark to bright",
        [[1.0], _triangle(), _square(), _saw()],
    ),
    "organ": (
        "drawbar registrations on the harmonic bars, from a soft flute to full organ",
        [
            [1.0, 0.5],
            [1.0, 0.7, 0.5, 0.3],
            [1.0, 0.8, 0.7, 0.6, 0.0, 0.5, 0.0, 0.4],
            [1.0, 0.9, 0.8, 0.8, 0.0, 0.7, 0.0, 0.7, 0.0, 0.5, 0.0, 0.5, 0.0, 0.0, 0.0, 0.4],
        ],
    ),
    "vowel": (
        "a voice opening from oo through oh to ah and a bright ae",
        [
            [1.0, 0.35, 0.1, 0.05],
            [1.0, 0.7, 0.45, 0.2, 0.1, 0.05],
            [0.7, 0.9, 1.0, 0.8, 0.55, 0.35, 0.25, 0.2, 0.15, 0.1, 0.08, 0.06],
            [0.5, 0.6, 0.7, 0.5, 0.3, 0.2, 0.3, 0.5, 0.6, 0.45, 0.3, 0.2, 0.15, 0.1],
        ],
    ),
    "glass": (
        "hollow odd harmonics rising into a high glassy ring",
        [
            [1.0, 0.0, 0.3, 0.0, 0.2],
            [0.6, 0.0, 0.2, 0.0, 0.4, 0.0, 0.5, 0.0, 0.3],
            [0.4, 0.0, 0.1, 0.0, 0.2, 0.0, 0.3, 0.0, 0.5, 0.0, 0.6, 0.0, 0.4, 0.0, 0.2],
        ],
    ),
}


def table_frames(name: str) -> list[dict[str, list[float]]]:
    """The frames of a named table, as a wavetable block holds them."""
    found = NAMED_TABLES.get(name)
    if found is None:
        valid = ", ".join(repr(n) for n in NAMED_TABLES)
        raise invalid_spec(
            f"table: no table named {name!r}. Valid values: {valid}.",
            field="table",
            valid_values=list(NAMED_TABLES),
        )
    return [{"harmonics": list(frame)} for frame in found[1]]
