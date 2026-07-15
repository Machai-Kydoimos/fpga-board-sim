"""Dialect-agnostic classification of a parsed port table into a convention dict.

Produces a ``port_convention``-shaped dict (``clk``/``leds``/``leds_green``/
``switches``/``buttons``/``seven_seg``) from a :class:`PortTable`. ``leds_green``
(a Terasic-style *secondary* LED bank, e.g. DE2-115's ``LEDG`` alongside its red
``LEDR``) is matched on the more specific ``ledg`` substring so it can never win
the primary ``leds`` slot by count. A board whose *only* LED bank is green
(e.g. DE0's lone ``LEDG``) has no separate primary, so that bank becomes ``leds``
and ``leds_green`` is absent.

This module knows nothing about QSF/XDC/UCF/etc. syntax — it only looks at
already-extracted ``(port, pin)`` pairs and reasons about *names*. That is a
deliberate split from the per-dialect ``parse()`` functions: the same
name-shape rules apply to a board regardless of which constraint format its
source happens to use.

**Why ``active_low`` is almost always absent from the output:** none of the
eight constraint dialects state signal polarity as syntax — ``PACKAGE_PIN``/
``LOC``/``SITE``/``IO_LOC`` bind a name to a physical pin, full stop. Polarity
is normally answered by a schematic or manual, which is exactly why the U21
arc plan puts it in the (hand-maintained, cited) generator overlay rather than
asking the parser to guess it. The one exception handled here is a genuine
*textual* convention some sources do use: a trailing ``_N``/``_n`` on the port
name itself (e.g. ICEBreaker's ``BTN_N``, ``LEDR_N``) — that is derived
because it is literally spelled out in the name, not inferred from outside
knowledge.

**Distinct scalar ports vs. a shared vector:** a bracket-indexed group
(``led[0..7]``) or a single scalar (``btn``) becomes ``{"name":
..., "width": ...}``. Boards whose LEDs/switches/buttons are named as
distinct un-bracketed scalars sharing a common prefix (Nandland Go's
``o_LED_1``..``o_LED_4``, Pipistrello's ``LED1``..``LED5``) instead become
``{"names": [...], "width": ...}`` — real port names, not a fabricated
vector port nothing declares. (This mirrors ``seven_seg``'s ``names`` list,
added in A0 for the same per-digit / per-segment-scalar reason;
``port_mapping`` gained the same field later for exactly this case.) Two
*unrelated* scalar names with no shared prefix at all (GateMate's
``FPGA_LED``/``JTAG_LED``) still yield nothing — there is no single
convention to name there, invented or otherwise.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from port_convention_parsers.types import PortTable

_RE_BRACKET_INDEX = re.compile(r"^(.*?)[\[(<](\d+)[\])>]$")
_RE_BARE_DIGIT = re.compile(r"^(.*?)(\d+)$")
_RE_ACTIVE_LOW_SUFFIX = re.compile(r"_[nN]$")

# "led" only counts as a user LED at a token boundary: at the start, or after a
# `_` / `-` / digit -- so `led0` and `m2led` (litefury/nitefury's M.2 status LED)
# both count, while a *letter* before "led" does not, keeping `oled*` (OLED
# display buses) and `segled` out of the primary LED bank. A bare-substring test
# wrongly swept those in and inflated the bank; this mirrors the same fix already
# in scripts/{litex,amaranth}_parser.py's `_LED_TOKEN` (U33 Wave 4).
_LED_INTEREST = re.compile(r"(?:^|[_\-0-9])led", re.IGNORECASE)
_LEDS_GREEN_INTEREST = re.compile(r"(?:^|[_\-0-9])ledg", re.IGNORECASE)
_SWITCH_INTEREST = re.compile(r"switch", re.IGNORECASE)
_BUTTON_INTEREST = re.compile(r"button|btn", re.IGNORECASE)
_CLOCK_INTEREST = re.compile(r"clk|clock", re.IGNORECASE)
_SEG_INTEREST = re.compile(r"seg|hex", re.IGNORECASE)

# Digilent's compass-direction button names: a shared prefix plus exactly one
# of C(enter)/U(p)/D(own)/L(eft)/R(ight), nothing else after it.
_RE_DIRECTION_BUTTON = re.compile(r"^(.+?)([CUDLRcudlr])$")

# Two-level 7-seg shapes: a digit index folded into the prefix, then a
# bracketed per-digit index (Terasic-style HEX0[3]) or a bracket-free
# per-digit-per-segment-letter suffix (Nandland-style o_Segment1_A).
_RE_DIGIT_THEN_BRACKET = re.compile(r"^(.*?[A-Za-z_])(\d+)\[(\d+)\]$")
_RE_DIGIT_THEN_LETTER = re.compile(r"^(.+?)(\d+)_?([A-Ga-g])$")

# Older-Terasic split per-digit 7-seg: a 7-bit segment vector `<prefix><n>_D[k]`
# plus a separate decimal-point scalar `<prefix><n>_DP` (e.g. DE0's HEX0_D[6:0]
# + HEX0_DP). The `_D` sits between the digit and the bracket, so these never
# match `_RE_DIGIT_THEN_BRACKET`.
_RE_DIGIT_D_SEGMENT = re.compile(r"^(.*?)(\d+)_[Dd]\[(\d+)\]$")
_RE_DIGIT_DP = re.compile(r"^(.*?)(\d+)_[Dd][Pp]$")


def _strip_index(name: str) -> str:
    """Return `name` with a trailing bracketed or bare-digit index removed."""
    m = _RE_BRACKET_INDEX.match(name) or _RE_BARE_DIGIT.match(name)
    return m.group(1) if m else name


def _exact_base(name: str, token: str) -> bool:
    """Return whether `name`'s base (after stripping a trailing index) is exactly `token`."""
    return _strip_index(name).lower() == token.lower()


def _is_leds_green(name: str) -> bool:
    return bool(_LEDS_GREEN_INTEREST.search(name))


def _is_led(name: str) -> bool:
    # Excludes leds_green matches outright (rather than relying on the
    # primary group always being larger) so a green LED bank can never win
    # the primary "leds" slot regardless of relative counts.
    return bool(_LED_INTEREST.search(name)) and not _is_leds_green(name)


def _is_switch(name: str) -> bool:
    return bool(_SWITCH_INTEREST.search(name)) or _exact_base(name, "sw")


def _is_button(name: str) -> bool:
    return bool(_BUTTON_INTEREST.search(name)) or _exact_base(name, "key")


def _is_clock(name: str) -> bool:
    return bool(_CLOCK_INTEREST.search(name))


def _is_seg(name: str) -> bool:
    return bool(_SEG_INTEREST.search(name))


def _is_digit_enable(name: str) -> bool:
    return _exact_base(name, "an") or _exact_base(name, "enable")


def _maybe_set_active_low(result: dict[str, Any], name: str) -> None:
    if _RE_ACTIVE_LOW_SUFFIX.search(name):
        result["active_low"] = True


def _vector_or_scalar(names: list[str]) -> dict[str, Any] | None:
    """Populate a ``port_mapping``-shaped dict from `names`.

    Three shapes, in priority order: a bracket-indexed vector (``name[idx]``,
    width = max index + 1); a single scalar (width 1); or -- since the
    schema's ``port_mapping`` gained a ``names`` list, symmetric with
    ``seg_port_mapping``'s -- more than one *bare-digit* (non-bracketed)
    scalar sharing a common prefix (Nandland Go's ``o_LED_1``..``o_LED_4``),
    listed by name rather than fabricating a vector port nothing declares.
    Returns ``None`` only when `names` is empty or shares no such structure.
    """
    if not names:
        return None

    bracket_groups: dict[str, list[int]] = {}
    bare_groups: dict[str, list[tuple[int, str]]] = {}
    for name in names:
        bracket_m = _RE_BRACKET_INDEX.match(name)
        if bracket_m:
            bracket_groups.setdefault(bracket_m.group(1), []).append(int(bracket_m.group(2)))
            continue
        bare_m = _RE_BARE_DIGIT.match(name)
        if bare_m:
            bare_groups.setdefault(bare_m.group(1), []).append((int(bare_m.group(2)), name))

    if bracket_groups:
        base, indices = max(bracket_groups.items(), key=lambda kv: len(kv[1]))
        result: dict[str, Any] = {"name": base, "width": max(indices) + 1}
        _maybe_set_active_low(result, base)
        return result

    if len(names) == 1:
        result = {"name": names[0], "width": 1}
        _maybe_set_active_low(result, names[0])
        return result

    if bare_groups:
        prefix, members = max(bare_groups.items(), key=lambda kv: len(kv[1]))
        if len(members) > 1:
            ordered = [name for _, name in sorted(members)]
            result = {"names": ordered, "width": len(ordered)}
            _maybe_set_active_low(result, prefix)
            return result

    return None


def _named_direction_group(names: list[str]) -> dict[str, Any] | None:
    """Digilent's ``btnC``/``btnU``/``btnD``/``btnL``/``btnR`` named-button convention."""
    if len(names) < 2:
        return None
    bases = set()
    for name in names:
        m = _RE_DIRECTION_BUTTON.match(name)
        if not m:
            return None
        bases.add(m.group(1))
    if len(bases) != 1:
        return None
    (base,) = bases
    return {"name": base, "width": len(names)}


def _matching_ports(table: PortTable, predicate: Callable[[str], bool]) -> list[str]:
    """Distinct port names (first-seen order) whose port matches `predicate`.

    Deduplicated so a constraint file that states the same port twice (a
    stray copy-paste repeat, or a second line adding an attribute to a port
    already bound to a pin) can't inflate a count-based classification, e.g.
    ``_named_direction_group``'s ``len(names)`` or the largest-group pick in
    ``_vector_or_scalar``.
    """
    seen: dict[str, None] = {}
    for entry in table.pins:
        if predicate(entry.port):
            seen.setdefault(entry.port, None)
    return list(seen)


def _classify_clock(table: PortTable) -> str | None:
    if table.clocks:
        return table.clocks[0].port
    for entry in table.pins:
        if _is_clock(entry.port):
            return entry.port
    return None


def _classify_individual_seven_seg(seg_names: list[str]) -> dict[str, Any] | None:
    """Per-digit ports, e.g. Terasic ``HEX0[0..6]``..``HEX5[0..6]``."""
    per_prefix: dict[str, dict[int, list[int]]] = {}
    for name in seg_names:
        m = _RE_DIGIT_THEN_BRACKET.match(name)
        if not m:
            return None
        prefix, digit, seg_idx = m.group(1), int(m.group(2)), int(m.group(3))
        per_prefix.setdefault(prefix, {}).setdefault(digit, []).append(seg_idx)
    if len(per_prefix) != 1:
        return None
    ((prefix, per_digit),) = per_prefix.items()
    widths = {len(idxs) for idxs in per_digit.values()}
    if len(widths) != 1:
        return None
    names = [f"{prefix}{d}" for d in sorted(per_digit)]
    return {"style": "individual", "names": names, "width_per_digit": widths.pop()}


def _classify_split_dp_seven_seg(seg_names: list[str]) -> dict[str, Any] | None:
    """Split per-digit style: a `<prefix><n>_D[k]` segment vector + separate `_DP` scalar.

    Older Terasic boards (e.g. DE0) drive each digit's 7 segments through a
    vector port `HEX0_D[6:0]` and its decimal point through a companion scalar
    `HEX0_DP`. Reported as ``individual`` over the segment-vector ports (which is
    what the sim drives); the `_DP` scalars are recognized so they don't derail
    classification, but stay out of the block -- the sim's 8th (dp) bit is simply
    unused for this style, matching how the bare-`HEXn` boards ship 7-bit here.
    """
    segments: dict[str, dict[int, list[int]]] = {}  # prefix -> digit -> [segment index]
    bases: dict[tuple[str, int], str] = {}  # (prefix, digit) -> the actual port name
    for name in seg_names:
        seg_m = _RE_DIGIT_D_SEGMENT.match(name)
        if seg_m:
            prefix, digit = seg_m.group(1), int(seg_m.group(2))
            segments.setdefault(prefix, {}).setdefault(digit, []).append(int(seg_m.group(3)))
            bases[(prefix, digit)] = _strip_index(name)
            continue
        if _RE_DIGIT_DP.match(name):
            continue  # companion decimal-point scalar
        return None  # a seg name fitting neither shape -> not this style
    if len(segments) != 1:
        return None
    ((prefix, per_digit),) = segments.items()
    widths = {len(idxs) for idxs in per_digit.values()}
    if len(widths) != 1:
        return None
    names = [bases[(prefix, d)] for d in sorted(per_digit)]
    return {"style": "individual", "names": names, "width_per_digit": widths.pop()}


def _classify_per_segment_scalars(seg_names: list[str]) -> dict[str, Any] | None:
    """Per-digit-per-segment scalars, e.g. Nandland Go's ``o_Segment1_A..G``."""
    prefixes: set[str] = set()
    per_digit: dict[int, list[str]] = {}
    order: dict[str, tuple[int, str]] = {}
    for name in seg_names:
        m = _RE_DIGIT_THEN_LETTER.match(name)
        if not m:
            return None
        prefix, digit, letter = m.group(1), int(m.group(2)), m.group(3).upper()
        prefixes.add(prefix)
        per_digit.setdefault(digit, []).append(name)
        order[name] = (digit, letter)
    if len(prefixes) != 1:
        return None
    widths = {len(members) for members in per_digit.values()}
    if len(widths) != 1:
        return None
    names_sorted = sorted(seg_names, key=lambda n: order[n])
    return {"style": "per_segment_scalars", "names": names_sorted, "width_per_digit": widths.pop()}


def _classify_seven_seg(table: PortTable) -> dict[str, Any] | None:
    seg_names = _matching_ports(table, _is_seg)
    if not seg_names:
        return None

    individual = _classify_individual_seven_seg(seg_names)
    if individual:
        return individual

    split_dp = _classify_split_dp_seven_seg(seg_names)
    if split_dp:
        return split_dp

    scalars = _classify_per_segment_scalars(seg_names)
    if scalars:
        return scalars

    vector = _vector_or_scalar(seg_names)
    if not vector:
        return None
    result: dict[str, Any] = {
        "style": "packed_vector",
        "name": vector["name"],
        "width_per_digit": vector["width"],
    }

    enable_names = _matching_ports(table, _is_digit_enable)
    enable = _vector_or_scalar(enable_names)
    if enable:
        result["style"] = "scan"
        result["digit_enable"] = enable
    return result


def classify(table: PortTable) -> dict[str, Any]:
    """Bucket a parsed constraint file's ports into a ``port_convention``-shaped dict.

    Only keys the table has enough evidence for are present; a board with no
    recognizable LEDs, say, simply has no ``"leds"`` key. Callers (the A3
    generator) are expected to attach ``description``/``source``/``naming``
    themselves, since those require board-level context this function does
    not have.
    """
    result: dict[str, Any] = {}

    clk = _classify_clock(table)
    if clk:
        result["clk"] = clk

    led_names = _matching_ports(table, _is_led)
    green_names = _matching_ports(table, _is_leds_green)
    if not led_names and green_names:
        # A board whose only LED bank is green (e.g. DE0's LEDG) -- the green
        # bank IS the primary `leds`. `leds_green` is only for a *secondary*
        # green bank alongside a primary (red) one (e.g. DE2-115's LEDR + LEDG).
        led_names, green_names = green_names, []

    leds = _vector_or_scalar(led_names)
    if leds:
        result["leds"] = leds

    leds_green = _vector_or_scalar(green_names)
    if leds_green:
        result["leds_green"] = leds_green

    switches = _vector_or_scalar(_matching_ports(table, _is_switch))
    if switches:
        result["switches"] = switches

    button_names = _matching_ports(table, _is_button)
    buttons = _vector_or_scalar(button_names) or _named_direction_group(button_names)
    if buttons:
        result["buttons"] = buttons

    seven_seg = _classify_seven_seg(table)
    if seven_seg:
        result["seven_seg"] = seven_seg

    return result
