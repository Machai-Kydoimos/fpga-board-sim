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

import copy
import re
from collections.abc import Callable, Sequence
from typing import Any, NamedTuple, TypeVar

_T = TypeVar("_T")

# Net-name suffix that flags an active-low bank even when the source carries no
# explicit polarity flag (e.g. litex ``led_n`` / ``rgb_led_n``).
_ACTIVE_LOW_SUFFIX = re.compile(r"_n$", re.IGNORECASE)

# Compass-point suffix letters (center/north/south/east/west). A directional
# button cluster like KCU116/ZCU216's ``user_btn_c/_n/_s/_w/_e`` names its
# North member ``_n`` -- a direction, not the active-low marker.
_COMPASS_SUFFIX = re.compile(r"^(.*)_([cnsew])$", re.IGNORECASE)


def _compass_norths(names: list[str]) -> set[str]:
    """Names whose trailing ``_n`` means North, not active-low.

    A name qualifies when >=2 distinct compass suffixes (``_c``/``_n``/``_s``/
    ``_e``/``_w``) hang off its shared prefix -- a lone ``user_btn_n`` with no
    compass siblings stays ambiguous and keeps the active-low reading.
    """
    by_prefix: dict[str, set[str]] = {}
    for name in names:
        m = _COMPASS_SUFFIX.match(name)
        if m:
            by_prefix.setdefault(m.group(1).lower(), set()).add(m.group(2).lower())
    return {
        name
        for name in names
        if name.lower().endswith("_n") and len(by_prefix.get(name[:-2].lower(), set())) >= 2
    }


def group_by_name(
    items: Sequence[_T], name: Callable[[_T], str], number: Callable[[_T], int]
) -> list[_T]:
    """Return *items* with each upstream name's resources together, in number order.

    Names keep the order upstream first declares them in.  This order is both what
    the board shows and the order of the boundary bits.  The native wrapper puts a
    bank's bit k on boundary bit k (``resize`` in ``wrapper.py``), so a bank that
    another name's resource splits drives the wrong LED.  Sorting by number alone
    did exactly that: the Tang Primer 20K dock's WS2812 landed between ``led`` 0
    and ``led`` 1, so a native design's ``led(1)`` lit the WS2812, each higher bit
    lit the LED one below its own, and LED 5 never lit.  Amaranth's Nexys 4 DDR
    lists switches 8 and 9 last, which put switch 10 on boundary bit 8 (U56
    Phase 2).
    """
    first: dict[str, int] = {}
    for item in items:
        first.setdefault(name(item), len(first))
    return sorted(items, key=lambda item: (first[name(item)], number(item)))


#: A sub-signal name that marks one LED among several (U56 Phase 5, D-3): a segment
#: letter of an alphanumeric display (the Versa's ``a``..``p`` and ``dp``) or a color
#: letter (the Alibaba XCKU3P's ``r``/``g``/``h``).  A clock, select, data or enable
#: line -- ``clk``, ``cs_n``, ``mosi``, ``dat``, ``en`` -- makes a bus, not LEDs.
_ONE_LED_SUBSIGNAL = re.compile(r"[a-z]|dp")


def multi_pin_shape(subsignals: Sequence[tuple[str, int]], direction: str) -> str:
    """Return how a resource of several pins becomes components (U56 Phase 5, D-3).

    ``subsignals`` lists each sub-signal's name and pin count, and is empty for plain
    ``Pins("a b c")``.  The answer is one of:

    * ``"rgb"`` -- sub-signals exactly ``r``, ``g`` and ``b``, one pin each: one RGB
      site, whatever the resource is called (the Efinix Ti60's ``user_led``);
    * ``"split"`` -- plain pins, or one-pin sub-signals named like segments or
      colors: one component per pin (Trenz ``gpio_leds``, the Versa's ``alnum_led``);
    * ``"unsupported"`` -- bidirectional pins, a sub-signal of several pins, or a bus
      (Siglent's ``cs_n``/``clk``/``mosi``/``oe``).  The resource stays one component,
      as before, and the sync's ledger says so: a bus or a multiplexed array is not
      a row of LEDs.
    """
    if direction == "io":
        return "unsupported"
    if not subsignals:
        return "split"
    if any(count != 1 for _, count in subsignals):
        return "unsupported"
    names = sorted(name.lower() for name, _ in subsignals)
    if names == ["b", "g", "r"]:
        return "rgb"
    if all(_ONE_LED_SUBSIGNAL.fullmatch(name) for name in names):
        return "split"
    return "unsupported"


class LedView(NamedTuple):
    """What :func:`plan_led_aliases` needs to know of one LED entry."""

    pins: tuple[str, ...]
    rgb: bool  # a 3-pin RGB site


def plan_led_aliases(
    leds: Sequence[LedView],
) -> tuple[dict[int, tuple[int, int | None]], list[int]]:
    """Find the LED entries that are other names for an LED (U56 Phase 6, D-1).

    Upstream lists some LEDs twice on purpose: Amaranth's iCEBreaker adds
    ``led_r``/``led_g`` as "semantic aliases" of ``led`` 0 and 1, and the
    OrangeCrab's ``user_led`` 0-2 are its ``rgb_led``'s r, g and b.  The evidence
    is upstream's own pin assignment: two entries on one pin are one LED.

    Returns ``{alias: (primary, channel)}`` and the entries that overlap in any
    other way.  A one-pin entry on an RGB site's pin is that site's channel
    (``channel`` 0-2 for r, g, b); one on an earlier one-pin entry's pin is that
    LED (``channel`` ``None``).  The first-declared entry stays the LED.  Nothing
    else merges -- two RGB sites sharing a pin, or a whole multi-pin resource
    sharing one -- and those come back as overlaps, kept separate.
    """
    rgb_pin: dict[str, tuple[int, int]] = {}
    overlaps: set[int] = set()
    for i, led in enumerate(leds):
        if not led.rgb:
            continue
        if any(pin in rgb_pin for pin in led.pins):
            overlaps.add(i)
            continue
        for c, pin in enumerate(led.pins):
            rgb_pin[pin] = (i, c)
    plan: dict[int, tuple[int, int | None]] = {}
    mono: dict[str, int] = {}
    for i, led in enumerate(leds):
        if led.rgb or len(led.pins) != 1:
            continue
        pin = led.pins[0]
        if pin in rgb_pin:
            plan[i] = rgb_pin[pin]
        elif pin in mono:
            plan[i] = (mono[pin], None)
        else:
            mono[pin] = i
    owners: dict[str, list[int]] = {}
    for i, led in enumerate(leds):
        for pin in led.pins:
            owners.setdefault(pin, []).append(i)
    for i, led in enumerate(leds):
        if led.rgb or len(led.pins) <= 1:
            continue
        if any(len(owners[pin]) > 1 for pin in led.pins):
            overlaps.add(i)
    return plan, sorted(overlaps)


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
    ``pins_per_bit`` -- physical pins backing this one bit.  >1 means a resource
        with no single declarable ``std_logic`` port (an RGB LED's r/g/b, an
        RGBW's r/g/b/w), so it is not emittable as a native port -- see
        :func:`build_bank`.
    ``split`` -- the bit came from splitting a multi-pin resource (U56 Phase 5,
        D-3).  A split group never becomes the primary bank: splitting the XTRX
        boards' 3-pin ``user_led2`` would otherwise replace the ``user_led`` bank
        a design is written to.  It is one of the ``led_banks`` instead (Phase 6).
    ``channel`` -- the boundary channel this bit reaches: an LED channel (mono LEDs
        first, then r, g, b per RGB site) or the switch's or button's place in the
        board's list (U56 Phase 6).  A bank whose bit k does not reach channel k
        carries a ``channels`` map; ``None`` means the parser does not say.
    """

    normalized: str
    raw: str
    bit: int
    inverted: bool
    pins_per_bit: int = 1
    split: bool = False
    channel: int | None = None


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
    ``names[]`` cluster.  The bank is marked active-low when every emitted name is
    active-low (an ``inverted`` flag on a backing bit, or a name ending in ``_n``
    that isn't a compass North -- see :func:`_compass_norths`); a bank whose names
    *disagree* on polarity is dropped, since the single ``active_low`` flag cannot
    represent it.  Returns ``None`` for an empty role so the caller can omit an
    absent bank (the U31 floor).

    A bit backed by >1 physical pin (``pins_per_bit`` > 1) is an RGB/RGBW LED with
    r/g/b(/w) subsignals -- there is no single declarable ``std_logic`` port for it,
    so advertising one would be fiction.  Such bits are dropped up front; a bank
    left empty (an RGB-only board with no plain LEDs) yields no convention, so the
    board simply isn't board-native-able -- truth over coverage.  Bits split from a
    multi-pin resource (``split``) are dropped too, so a split never moves a bank.
    """
    entries = [e for e in entries if e.pins_per_bit <= 1 and not e.split]
    if not entries:
        return None
    # (A) Prefer a plain-normalized bank, so `rgb_led` yields to `led` and a stray
    # named button yields to the main `button` bank.  Absent any plain bank (e.g.
    # Basys3's directional `button_c/u/l/r/d`), keep every entry as peers.
    plain = [e for e in entries if e.normalized in _PRIMARY_NETS]
    pool = plain or entries
    return _shape_bank(pool)


def _shape_bank(pool: list[RoleEntry]) -> dict[str, Any] | None:
    """Shape role entries into one bank by their raw names (step B of :func:`build_bank`)."""
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
        emitted_names = [raw]
        bank = {"name": raw, "width": width_of(raw)}
    else:
        # Several distinct single-bit ports: a scalar cluster (schema `names[]`).  Two
        # names on one LED are aliases (U56 Phase 6): the first keeps the cluster's
        # place and the other stays a bank of its own, so no design drives one LED
        # twice through a single bank.
        emitted_names = []
        seen: set[int] = set()
        for raw in sorted(raw_groups):
            channel = raw_groups[raw][0].channel
            if channel is not None and channel in seen:
                continue
            if channel is not None:
                seen.add(channel)
            emitted_names.append(raw)
        bank = {"names": emitted_names, "width": len(emitted_names)}

    # Per-name polarity: an explicit inverted flag on any backing bit, or an
    # ``_n`` suffix that is not the North member of a compass cluster.
    norths = _compass_norths(emitted_names)
    low = [
        any(e.inverted for e in raw_groups[name])
        or (name not in norths and bool(_ACTIVE_LOW_SUFFIX.search(name)))
        for name in emitted_names
    ]
    if all(low):
        bank["active_low"] = True
    elif any(low):
        # Mixed polarity (gmm7550: active-high ``led_green`` + active-low
        # ``led_red_n``): the bank's single ``active_low`` flag cannot tell the
        # truth for both names, so the bank is not advertised at all -- truth
        # over coverage, exactly like the multi-pin rule above.
        return None
    channels = _bank_channels(bank, raw_groups)
    if channels is not None:
        bank["channels"] = channels
    return bank


def _bank_channels(
    bank: dict[str, Any], raw_groups: dict[str, list[RoleEntry]]
) -> list[int | None] | None:
    """Return the bank's ``channels`` map, or ``None`` when bit k reaches channel k.

    Bit k of a vector is its entry numbered k (a bit with no entry reaches no
    resource: the ECP5 EVN numbers its DIP switches from 1); member k of a cluster
    is its k-th name.  A parser that gives no channels gets no map.
    """
    if "names" in bank:
        channels = [raw_groups[name][0].channel for name in bank["names"]]
    else:
        by_bit = {e.bit: e.channel for e in raw_groups[bank["name"]]}
        channels = [by_bit.get(k) for k in range(bank["width"])]
    if all(c is None for c in channels):
        return None
    if channels == list(range(len(channels))):
        return None
    return channels


def build_led_banks(
    entries: list[RoleEntry], primary: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Return every other LED bank a design may declare, one per upstream name (U56 Phase 6).

    D-1 accepts every upstream name as a native port: an alias of an LED, a group
    split from a multi-pin resource (D-3), another named group.  Each is one bank
    with its ``channels`` map, so a design may use any of them -- the matcher turns
    away two that reach one LED.  The primary bank's own vector is not repeated; a
    primary cluster's names are, so a design may use some of them.
    """
    usable = [e for e in entries if e.pins_per_bit <= 1 and e.channel is not None]
    by_raw: dict[str, list[RoleEntry]] = {}
    for entry in usable:
        by_raw.setdefault(entry.raw, []).append(entry)
    primary_vector = primary.get("name") if primary else None
    banks = []
    for raw, group in by_raw.items():
        if raw == primary_vector:
            continue
        bank = _shape_bank(group)
        if bank is None:
            continue
        if "channels" not in bank:
            bank["channels"] = list(range(bank["width"]))
        banks.append(bank)
    return banks


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
    led_banks = build_led_banks(leds, leds_bank)
    if not (clk_name and (leds_bank or led_banks)):
        return None
    block: dict[str, Any] = {"description": description, "clk": clk_name}
    if leds_bank:
        block["leds"] = leds_bank
    if led_banks:
        block["led_banks"] = led_banks
    block["naming"] = "framework-derived"
    switches_bank = build_bank(switches)
    if switches_bank:
        block["switches"] = switches_bank
    buttons_bank = build_bank(buttons)
    if buttons_bank:
        block["buttons"] = buttons_bank
    return {framework: block}


# Roles a framework block and a canonical block can both map for the same physical
# resources, and whose polarity therefore has a single physical truth.
_RECONCILED_ROLES = ("leds", "leds_green", "switches", "buttons")


def _bank_width(bank: dict[str, Any]) -> int | None:
    """Width a bank covers, whether shaped ``{name, width}`` or ``{names[, width]}``."""
    width = bank.get("width")
    if isinstance(width, int):
        return width
    names = bank.get("names")
    if isinstance(names, list):
        return len(names)
    return None


def _canonical_polarity(canonical: list[dict[str, Any]], role: str, width: int) -> bool | None:
    """Effective ``active_low`` of a canonical bank mapping *role* at *width*, else None."""
    for block in canonical:
        cbank = block.get(role)
        if isinstance(cbank, dict) and _bank_width(cbank) == width:
            return bool(cbank.get("active_low", False))
    return None


def reconcile_framework_polarity(port_conventions: dict[str, Any]) -> dict[str, Any]:
    """Return *port_conventions* with framework-derived banks' polarity corrected.

    Polarity is a physical fact.  A ``framework-derived`` block (U32) advertises
    the framework's port *names* but guesses polarity from the source's textual
    signals (a ``_n`` suffix, an amaranth ``PinsN``), which can disagree with a
    curated, cited canonical block describing the *same physical resource* on the
    same board.  When such a disagreement exists -- a canonical block (``naming``
    absent or ``"canonical"``) maps the same role at the same width -- the
    canonical value wins: the framework bank keeps its names but inherits the
    canonical bank's effective ``active_low`` (absent, for a curated block, is a
    deliberate active-high claim).  The join is on role + width only, so shape may
    differ (a canonical ``names[]`` of width 4 reconciles a framework vector of
    width 4).

    Pure -- returns a new dict, input untouched.  Idempotent and independent of
    convention order, so re-syncs converge whichever writer runs.
    """
    result = copy.deepcopy(port_conventions)
    canonical = [
        b
        for b in result.values()
        if isinstance(b, dict) and b.get("naming", "canonical") == "canonical"
    ]
    if not canonical:
        return result
    for block in result.values():
        if not isinstance(block, dict) or block.get("naming") != "framework-derived":
            continue
        for role in _RECONCILED_ROLES:
            fbank = block.get(role)
            if not isinstance(fbank, dict):
                continue
            fwidth = _bank_width(fbank)
            if fwidth is None:
                continue
            truth = _canonical_polarity(canonical, role, fwidth)
            if truth is None:
                continue  # no same-role, same-width canonical bank to defer to
            if truth:
                fbank["active_low"] = True
            else:
                fbank.pop("active_low", None)
    return result
