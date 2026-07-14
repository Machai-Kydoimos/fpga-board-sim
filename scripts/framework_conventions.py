"""Shared builder for framework-derived ``port_conventions`` (U32).

The litex and amaranth sync parsers each extract LED / switch / button / clock
resources, then hand them here to assemble a ``port_conventions.<framework>``
block in the board-JSON shape.  Kept source-agnostic -- callers adapt their own
component representation (litex dicts, amaranth ``ComponentInfo``) into the simple
``RoleEntry`` tuples below -- so the *rules* (primary-group selection, raw-name
emission, polarity, the clk+LEDs partial-interface floor) live in one place and
cannot drift between the two parsers.

A litex/amaranth board's ``_io`` / board file declares the framework's own port
names (litex ``user_led`` / ``user_sw`` / ``user_btn`` / ``clk100``; amaranth
``led`` / ``button`` / ``switch``).  A convention emitted here carries those *raw*
names, so a design hand-written to the framework's port names simulates unmodified
(U21 board-native mode).  Every block is stamped ``naming: "framework-derived"``,
which the matcher tries *after* canonical/hand-authored blocks -- so authoritative
vendor data added for a board later (its own sub-key, e.g. ``terasic``) stays
distinguishable and wins at match time.

Self-contained: no ``fpga_sim`` / network dependency, so the litex parser keeps its
"no ``fpga_sim`` import" property.
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple

# Net-name suffix that flags an active-low bank even when the source carries no
# explicit polarity flag (e.g. litex ``led_n`` / ``rgb_led_n``).
_ACTIVE_LOW_SUFFIX = re.compile(r"_n$", re.IGNORECASE)

# Normalized net-names that name a "primary" bank -- preferred over a decorated
# sibling such as ``rgb_led`` when choosing the group a convention advertises.
_PRIMARY_NETS = ("led", "switch", "button")


class RoleEntry(NamedTuple):
    """One extracted resource bit, normalized across frameworks.

    ``normalized`` -- simulator net-name, used only to *group / select* the bank
        (``led``, ``switch``, ``button``, ``rgb_led``, ...).
    ``raw`` -- the framework's actual port name, emitted into the convention
        (litex ``user_led``; amaranth ``led``).
    ``bit`` -- resource index (bit position within the bank).
    ``inverted`` -- the source encodes active-low for this bit (amaranth ``PinsN``).
    """

    normalized: str
    raw: str
    bit: int
    inverted: bool


def build_bank(entries: list[RoleEntry]) -> dict[str, Any] | None:
    """Collapse role entries into a port-mapping bank, or ``None`` for an empty role.

    Emits whichever shape the framework's ports actually take:

    * a shared **vector** ``{name, width}`` when the bank is one indexed port
      (litex ``user_led`` 0..3, ``user_btn`` 0..4);
    * a **scalar cluster** ``{names, width}`` when the bank is several distinct
      single-bit ports (Basys3's ``user_btnu`` / ``user_btnd`` / ``user_btnl`` /
      ``user_btnr`` / ``user_btnc``) -- the schema's ``names[]`` mapping.

    Two steps: (A) when a plain-normalized bank (``led`` / ``switch`` / ``button``)
    is present, decorated siblings such as ``rgb_led`` are dropped -- the card's
    "primary LED group (led over rgb_led)" rule; (B) the survivors are shaped by
    their *raw* framework names -- one raw name (or a dominant >=2-bit bus among
    stray scalars) becomes a vector, several single-bit raw names become a
    ``names[]`` cluster.  The bank is marked active-low when an emitted bit carries
    an ``inverted`` flag or an emitted raw name ends in ``_n``.  Returns ``None`` for
    an empty role so the caller can omit an absent bank (the U31 floor).
    """
    if not entries:
        return None
    # (A) Prefer a plain-normalized bank, so `rgb_led` yields to `led` and a stray
    # named button yields to the main `button` bank.  Absent any plain bank (e.g.
    # Basys3's directional `button_c/u/l/r/d`), keep every entry as peers.
    plain = [e for e in entries if e.normalized in _PRIMARY_NETS]
    pool = plain or entries

    # (B) Shape the survivors by their raw port names.
    raw_groups: dict[str, list[RoleEntry]] = {}
    for entry in pool:
        raw_groups.setdefault(entry.raw, []).append(entry)

    def width_of(raw: str) -> int:
        return max(e.bit for e in raw_groups[raw]) + 1

    indexed = [raw for raw in raw_groups if width_of(raw) >= 2]
    bank: dict[str, Any]
    if len(raw_groups) == 1 or indexed:
        # One port, or a real >=2-bit bus dominating a few stray scalars: a vector.
        raw = min(
            indexed or list(raw_groups),
            key=lambda r: (-width_of(r), len(r), r),
        )
        emitted = raw_groups[raw]
        emitted_names = [raw]
        bank = {"name": raw, "width": width_of(raw)}
    else:
        # Several distinct single-bit ports: a scalar cluster (schema `names[]`).
        emitted_names = sorted(raw_groups)
        emitted = pool
        bank = {"names": emitted_names, "width": len(emitted_names)}

    if any(e.inverted for e in emitted) or any(_ACTIVE_LOW_SUFFIX.search(n) for n in emitted_names):
        bank["active_low"] = True
    return bank


def build_convention(
    framework: str,
    clk_name: str | None,
    leds: list[RoleEntry],
    switches: list[RoleEntry],
    buttons: list[RoleEntry],
    *,
    description: str,
) -> dict[str, Any] | None:
    """Assemble ``{framework: {...}}``, or ``None`` if the clk+LEDs floor isn't met.

    Requires a clock and an LED bank (the U31 partial-interface minimum);
    switches/buttons are added only when the platform declares them.  Always
    stamps ``naming: "framework-derived"`` so an authoritative (canonical) block
    added for the board later stays distinguishable and wins at match time.
    """
    leds_bank = build_bank(leds)
    if not (clk_name and leds_bank):
        return None
    block: dict[str, Any] = {
        "description": description,
        "clk": clk_name,
        "leds": leds_bank,
        "naming": "framework-derived",
    }
    switches_bank = build_bank(switches)
    if switches_bank:
        block["switches"] = switches_bank
    buttons_bank = build_bank(buttons)
    if buttons_bank:
        block["buttons"] = buttons_bank
    return {framework: block}
