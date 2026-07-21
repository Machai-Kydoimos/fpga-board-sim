"""Shared LED color helpers for the sync pipeline (U36).

Two source-agnostic tiers assign the optional ``component.color`` on a board's
LEDs (see ``boards/schema/board.schema.json``); an LED left unset by both keeps
``""`` and the renderer falls back to the theme default.

1. **Name heuristic** (:func:`color_from_name`).  The amaranth, litex, and
   digilent parsers call it when building an LED, so a resource whose name
   encodes a color (``led_r`` -> red, ``led_g`` -> green, ``led_b`` -> blue,
   ``led_o`` -> orange, ``led_g_n`` -> green) carries that color into the JSON.
   Only *self-evident, name-encoded* colors are assigned; a plain ``led`` bank
   that merely happens to be red on the silkscreen is left unset here.

2. **Cited registry** (:func:`load_color_registry` / :func:`apply_registry_colors`).
   A plain ``led`` bank whose physical color is documented but not in its name
   is colored from ``docs/led_color_sources/*.toml`` -- one cited entry per
   board bank.  Applied at sync time (in ``sync_common.write_outputs`` and the
   standalone ``scripts/sync_led_colors.py``), and stamped at **higher
   precedence** than the name heuristic: a cited datum outranks an inferred one.

The name heuristic is kept deliberately conservative: single-letter tokens are
honored only for the four colors that actually occur in upstream board files
(``r``/``g``/``b``/``o``); every other color must be spelled out, so an odd
one-letter suffix is never mistaken for a color.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

# Name token -> canonical color.  Single letters r/g/b/o are evidence-backed
# (Black Ice ``led_o``, iCEBreaker ``led_r``/``led_g``, litex ``led_g_n`` ...);
# the spelled-out forms cover the rest of the schema enum for future sources.
_COLOR_TOKENS: dict[str, str] = {
    "r": "red",
    "red": "red",
    "g": "green",
    "green": "green",
    "b": "blue",
    "blue": "blue",
    "o": "orange",
    "orange": "orange",
    "yellow": "yellow",
    "amber": "amber",
    "white": "white",
}

# Tokens that must never be read as a color: the active-low marker ``_n``
# (litex ``led_g_n``) and structural words that surround the color token.
_IGNORE_TOKENS: frozenset[str] = frozenset({"n", "led", "leds", "user", "usr", "rgb"})


def color_from_name(name: str) -> str:
    """Return the LED color implied by a resource name, or ``""`` if none.

    Splits ``name`` on ``_`` and returns the first token that names a color.
    Structural tokens and the active-low marker ``_n`` are skipped, so
    ``led_g_n`` -> ``"green"`` while ``led_n`` -> ``""`` (an active-low LED of
    unknown color) and a bare ``led`` -> ``""``.
    """
    for token in name.lower().split("_"):
        if not token or token in _IGNORE_TOKENS:
            continue
        color = _COLOR_TOKENS.get(token)
        if color:
            return color
    return ""


# ═══════════════════════════════════════════════════════════════════════
#  Cited color registry (docs/led_color_sources/*.toml)
# ═══════════════════════════════════════════════════════════════════════

_REGISTRY_DIR = Path(__file__).resolve().parent.parent / "docs" / "led_color_sources"

# Named colors accepted by boards/schema/board.schema.json (component.color),
# plus the "#RRGGBB" hex form.  Kept in sync with the schema enum.
_SCHEMA_NAMED_COLORS: frozenset[str] = frozenset(
    {"red", "green", "blue", "yellow", "orange", "amber", "white"}
)
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _is_schema_color(color: str) -> bool:
    """Return whether ``color`` is a schema-valid component color (named/``#RRGGBB``)."""
    return color in _SCHEMA_NAMED_COLORS or bool(_HEX_COLOR_RE.match(color))


@dataclass(frozen=True)
class ColorBank:
    """One cited LED-bank color.

    Assigns ``color`` to every ``leds[]`` entry whose ``name`` equals ``match``,
    backed by the quote in ``source``.
    """

    match: str
    color: str
    source: str


def load_color_registry(registry_dir: Path | None = None) -> dict[str, list[ColorBank]]:
    """Load ``docs/led_color_sources/*.toml`` into ``{board_file: [ColorBank]}``.

    ``board_file`` is a board JSON path relative to ``boards/`` (e.g.
    ``"amaranth-boards/de0_cv.json"``), taken from each row's ``files``.  Every
    ``[[board.bank]]`` must carry a non-empty ``match``, a schema-valid
    ``color``, and a non-empty ``source`` -- the verify-or-omit rule is enforced
    here, so a malformed or uncited entry fails the sync loudly rather than
    stamping a bogus color.  Raises ``ValueError`` naming the offending row.
    """
    if registry_dir is None:
        registry_dir = _REGISTRY_DIR
    out: dict[str, list[ColorBank]] = {}
    for path in sorted(registry_dir.glob("*.toml")):
        with path.open("rb") as f:
            data = tomllib.load(f)
        for board in data.get("board", []):
            label = board.get("name", "<unnamed>")
            files = board.get("files") or []
            if not files:
                raise ValueError(f"{path.name}: board {label!r} has no `files`")
            parsed: list[ColorBank] = []
            for b in board.get("bank") or []:
                match = b.get("match", "")
                color = b.get("color", "")
                source = b.get("source", "")
                if not match:
                    raise ValueError(f"{path.name}: board {label!r} has a bank with no `match`")
                if not _is_schema_color(color):
                    raise ValueError(
                        f"{path.name}: board {label!r} bank {match!r} has invalid color {color!r}"
                    )
                if not source.strip():
                    raise ValueError(
                        f"{path.name}: board {label!r} bank {match!r} has no `source` citation"
                    )
                parsed.append(ColorBank(match=match, color=color, source=source))
            if not parsed:
                raise ValueError(f"{path.name}: board {label!r} has no `[[board.bank]]` entries")
            for file in files:
                out.setdefault(file, []).extend(parsed)
    return out


def apply_registry_colors(
    board: dict[str, Any], board_file: str, registry: dict[str, list[ColorBank]]
) -> bool:
    """Stamp ``leds[].color`` on a parsed board dict from the registry.

    Colors every LED whose ``name`` matches a registry bank for ``board_file``,
    overriding any name-heuristic color already present (cited > inferred).
    Returns ``True`` iff a color actually changed.
    """
    colors = {bank.match: bank.color for bank in registry.get(board_file, [])}
    if not colors:
        return False
    changed = False
    for led in board.get("leds", []):
        color = colors.get(led.get("name"))
        if color is not None and led.get("color", "") != color:
            led["color"] = color
            changed = True
    return changed


def colorize_content(content: str, board_file: str, registry: dict[str, list[ColorBank]]) -> str:
    """Apply registry colors to a *canonical* board-JSON string.

    Re-serializes (``json.dumps(indent=2)`` -- the layout the sync scripts emit)
    only when a color actually changes; otherwise the exact input string is
    returned, so a re-sync's ``git diff`` stays silent on boards this registry
    does not touch.  Used by ``sync_common.write_outputs``.
    """
    if board_file not in registry:
        return content
    board = json.loads(content)
    if not apply_registry_colors(board, board_file, registry):
        return content
    return json.dumps(board, indent=2) + "\n"
