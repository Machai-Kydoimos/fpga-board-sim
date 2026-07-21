"""Shared LED-name -> color heuristic for the sync parsers (U36).

Source-agnostic: the amaranth, litex, and digilent parsers all call
:func:`color_from_name` when building an LED component, so a resource whose
name encodes a color (``led_r`` -> red, ``led_g`` -> green, ``led_b`` -> blue,
``led_o`` -> orange, ``led_g_n`` -> green) carries that color into the
generated board JSON.

Only *self-evident, name-encoded* colors are assigned here.  A plain ``led``
bank that merely happens to be red on the silkscreen is left unset by this
heuristic and populated from the cited color registry instead (U36 PR-2),
which the loader treats as higher precedence.  An unrecognized name yields
``""`` (unknown -> the renderer falls back to the theme default).

Kept deliberately conservative: single-letter tokens are honored only for the
four colors that actually occur in upstream board files (``r``/``g``/``b``/
``o``); every other color must be spelled out, so an odd one-letter suffix is
never mistaken for a color.  The result is always one of the schema's named
colors (see ``boards/schema/board.schema.json`` ``component.color``).
"""

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
