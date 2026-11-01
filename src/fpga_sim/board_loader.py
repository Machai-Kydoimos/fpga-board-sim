"""Board Loader – load board JSON definitions into :class:`BoardDef` objects.

This is the runtime board path: :func:`discover_boards` reads the JSON board
definitions under ``boards/`` (one subdirectory per source) into
:class:`BoardDef` objects, with no amaranth dependency.

The complementary *offline* path — turning upstream amaranth-style board ``.py``
files into ``BoardDef`` objects by reading them against a mock namespace, never
executing them — lives in ``scripts/amaranth_parser.py`` and is used only by the
``sync_*`` regenerators.
That parser imports the data classes defined here; this module never imports the
parser, so the runtime loader and the offline tooling evolve independently.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fpga_sim.paths import BOARDS_DIR

_FALLBACK_CLOCK_HZ: float = 12e6  # most common across 80 surveyed boards

#: The first sentence of an orphaned board's note, by why upstream dropped it (U56 §4.8).
_ORPHAN_LEADS: dict[str, str] = {
    "file_removed": "No longer in {source}{noticed}.",
    "no_longer_defined": "{source} no longer defines this version{noticed}.",
    "no_simulatable_io": "{source} lists no LED, switch or button for this board{noticed}.",
}


# ═══════════════════════════════════════════════════════════════════════
#  Display-name overrides (U49)
# ═══════════════════════════════════════════════════════════════════════

#: Corrected display names, keyed by ``class_name``.
#:
#: The two sync parsers derive a board's display name from its upstream class
#: or file name (``scripts/amaranth_parser._prettify_class_name``,
#: ``scripts/litex_parser._prettify_filename``).  Since U56 Phase 1b (P35) they
#: no longer mangle part numbers or leave dangling hyphens -- ``ULX3S_45F_`` reads
#: "ULX3S-45F", ``DE1SoC`` "DE1 SoC" -- so this table holds only what no rule can
#: derive: a vendor's hyphen ("DE1-SoC", "DE0-CV"), a space before a part
#: ("Logicbone 85F"), a brand's own styling ("OrangeCrab R0.2 25F", "iCEstick").
#: ``tests/test_board_display_names.py`` fails on an entry the parsers now emit
#: on their own, so the table shrinks whenever they improve.
#:
#: Every entry is grounded in data already in the tree rather than in what a
#: board "should" be called: the ``source.upstream_file`` recorded in each board
#: JSON, and the ``class_name``, are both un-mangled.  Where those two disagree
#: with a vendor's marketing styling, this table follows them and undoes the
#: mangling only -- it is a repair, not a rebrand.
#:
#: ``find_board`` compares names with separators and case stripped, so renaming
#: here cannot break a ``--board`` argument, a saved session (which stores
#: ``class_name``), or a documented example.
_DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    # ── Mangled by the case/digit split (F7) ──────────────────────────────
    "DE1SoCPlatform": "DE1-SoC",  # de1_soc.py
    "Logicbone85FPlatform": "Logicbone 85F",  # logicbone.py; 85F is the ECP5 part
    "OrangeCrabR0_2_25FPlatform": "OrangeCrab R0.2 25F",  # orangecrab_r0_2.py
    "OrangeCrabR0_2_85FPlatform": "OrangeCrab R0.2 85F",  # orangecrab_r0_2.py
    "SitlinvAE115fbPlatform": "Sitlinv AE115fb",  # sitlinv_a_e115fb.py
    "IceVWirelessPlatform": "ICE-V Wireless",  # ice_v_wireless.py; its header: "ICE-V wireless"
    "RFSoC4x2Platform": "RFSoC 4x2",  # rfsoc4x2.py; AMD and Real Digital: "RFSoC 4x2"
    # ── A space where the vendor uses a hyphen ────────────────────────────
    # Not caught by the guard below -- "DE0 CV" breaks no mechanical rule --
    # but wrong all the same, and these are the boards this project's own
    # course fleet is built on, so they are the ones a student will scan for.
    "DE0CVPlatform": "DE0-CV",  # de0_cv.py
    "DE0NanoPlatform": "DE0-Nano",  # de0nano.py
    "DE10LitePlatform": "DE10-Lite",  # de10_lite.py
    "DE10NanoPlatform": "DE10-Nano",  # de10_nano.py
    "TangNano9kPlatform": "Tang Nano 9K",  # tang_nano_9k.py
    "ICEStickPlatform": "iCEstick",  # icestick.py; Lattice styles the i lowercase
}


# ═══════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════


def _pin_list(raw: object) -> tuple[str, ...]:
    """Coerce a JSON pin array to a tuple of strings; anything else to empty.

    Board JSON is external data, and a malformed pin list should cost the pin
    map its ability to target that board -- not raise on the way in and take the
    board out of the picker entirely.
    """
    if not isinstance(raw, list):
        return ()
    return tuple(str(pin) for pin in raw)


def _pin_rows(raw: object) -> tuple[tuple[str, ...], ...]:
    """Coerce a JSON array-of-pin-arrays, dropping any row that is not a list."""
    if not isinstance(raw, list):
        return ()
    return tuple(_pin_list(row) for row in raw if isinstance(row, list))


@dataclass
class SevenSegDef:
    """7-segment display capability extracted from a board definition.

    The three ``*_pins`` lists are optional and exist for the pin map (U53),
    which binds a design's ports to board resources **by pin**.  Every other
    consumer works from the counts and polarity above them, so a board without
    pin data behaves exactly as it always has -- it simply cannot be targeted
    through a constraint file.

    ``segment_pins`` is one inner list per digit on a directly-driven display
    (Terasic's ``HEX0``..``HEX5``), and exactly **one** inner list on a scanned
    display, whose segment lines are shared and selected by
    ``digit_enable_pins``.  The presence of ``digit_enable_pins`` is what
    distinguishes the two, so a scanned board is never mistaken for a one-digit
    one.
    """

    num_digits: int
    has_dp: bool
    is_multiplexed: bool
    inverted: bool  # board hardware active-low (metadata; VHDL is active-high)
    select_inverted: bool  # mux select lines active-low (v2 use)
    #: Segment pins in a..g order; per digit, or one shared list when scanned.
    segment_pins: tuple[tuple[str, ...], ...] = ()
    #: Decimal-point pins: one per digit, or a single shared pin when scanned.
    dp_pins: tuple[str, ...] = ()
    #: Digit-select pins, digit 0 first.  Non-empty only on a scanned display.
    digit_enable_pins: tuple[str, ...] = ()

    @property
    def is_scan(self) -> bool:
        """Whether the segment lines are shared and selected per digit."""
        return bool(self.digit_enable_pins)

    @property
    def has_pin_data(self) -> bool:
        """Whether this display can be targeted through a constraint file."""
        return bool(self.segment_pins)

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict for inclusion in BoardDef JSON."""
        d: dict[str, object] = {
            "num_digits": self.num_digits,
            "has_dp": self.has_dp,
            "is_multiplexed": self.is_multiplexed,
            "inverted": self.inverted,
            "select_inverted": self.select_inverted,
        }
        # Omitted rather than written empty, so a board with no pin data keeps
        # the JSON it had and the drift check stays quiet.
        if self.segment_pins:
            d["segment_pins"] = [list(row) for row in self.segment_pins]
        if self.dp_pins:
            d["dp_pins"] = list(self.dp_pins)
        if self.digit_enable_pins:
            d["digit_enable_pins"] = list(self.digit_enable_pins)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "SevenSegDef":
        """Deserialize from a dict produced by to_dict()."""
        return cls(
            num_digits=int(d["num_digits"]),  # type: ignore[call-overload]  # strict: required field
            has_dp=bool(d["has_dp"]),  # strict: required field
            is_multiplexed=bool(d["is_multiplexed"]),  # strict: required field
            inverted=bool(d.get("inverted", False)),
            select_inverted=bool(d.get("select_inverted", False)),
            segment_pins=_pin_rows(d.get("segment_pins")),
            dp_pins=_pin_list(d.get("dp_pins")),
            digit_enable_pins=_pin_list(d.get("digit_enable_pins")),
        )


@dataclass(frozen=True)
class ClockDef:
    """One clock source, with the pin it arrives on when the board data says.

    ``BoardDef.clocks`` has always been a list of plain Hz values, which is what
    its two consumers want (the stats panel's clock presets and the board-image
    renderer's caption).  The board JSON, though, carries richer objects --
    ``{"name": "clk50", "hz": 50e6, "pin": "AF14", "is_default": true}`` -- for
    196 of the 274 boards, and the loader used to narrow them to floats on the
    way in and write floats back out, so **the pin was discarded at load and
    would have been erased by any round-trip**.

    The pin is what a project's constraint file binds a design's clock port to,
    so the pin map (U53) cannot work without it.
    """

    hz: float
    name: str = ""
    pin: str = ""
    is_default: bool = False

    def to_dict(self) -> dict[str, object]:
        """Serialize back to the board JSON's clock-object shape, pin included."""
        d: dict[str, object] = {"hz": self.hz}
        if self.name:
            d["name"] = self.name
        if self.pin:
            d["pin"] = self.pin
        if self.is_default:
            d["is_default"] = True
        return d

    @classmethod
    def from_raw(cls, raw: object) -> "ClockDef":
        """Build from either JSON shape: a bare Hz number or a clock object."""
        if isinstance(raw, dict):
            return cls(
                hz=float(raw.get("hz", 0.0)),
                name=str(raw.get("name", "")),
                pin=str(raw.get("pin", "")),
                is_default=bool(raw.get("is_default", False)),
            )
        return cls(hz=float(raw))  # type: ignore[arg-type]


@dataclass
class ComponentInfo:
    """Describes a single LED, button, or switch extracted from a board."""

    kind: str  # "led", "button", or "switch"
    name: str  # amaranth resource name, e.g. "led", "button_up", "rgb_led"
    number: int  # resource index
    pins: list[str] = field(default_factory=list)
    direction: str = ""
    inverted: bool = False
    connector: tuple[str, int] | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    color: str = ""  # LED color when known ("red" / "#ff0000"); "" => theme fallback (U36)

    @property
    def is_rgb(self) -> bool:
        """True for a 3-pin ``rgb_led`` (one boundary bit per r/g/b channel, U37).

        The pin-count gate is load-bearing, not defensive: a 1-pin ``rgb_led``
        is a serial addressable LED (WS2812-style, e.g. colorlight_i9plus) and
        a 4-pin one is RGBW (modretro_chromatic) -- neither is three PWM
        channels, so both stay ordinary mono boundary bits.
        """
        return self.name == "rgb_led" and len(self.pins) == 3

    @property
    def display_name(self) -> str:
        """Short label for the UI, e.g. 'LED0', 'BTN2', 'UP0', 'RGB1'."""
        prefixes = {"led": "LED", "button": "BTN", "switch": "SW"}
        if self.name == "rgb_led":
            # "RGB_LED0" crowds the puck row; the bank label already says RGB,
            # so the item label stays compact (U37).
            return f"RGB{self.number}"
        if self.name == self.kind:
            return f"{prefixes.get(self.kind, self.kind.upper())}{self.number}"
        suffix = self.name
        if suffix.startswith(self.kind):
            suffix = suffix[len(self.kind) :]
        suffix = suffix.lstrip("_")
        if not suffix:
            return f"{prefixes.get(self.kind, self.kind.upper())}{self.number}"
        return f"{suffix.upper()}{self.number}"

    @property
    def connector_str(self) -> str:
        """Human-readable pin/connector/attrs summary for callback printing."""
        parts = []
        if self.pins:
            lbl = "Pins" if len(self.pins) > 1 else "Pin"
            parts.append(f"{lbl}: {', '.join(self.pins)}")
        if self.connector:
            parts.append(f"Conn: {self.connector[0]}[{self.connector[1]}]")
        for k, v in self.attrs.items():
            parts.append(f"{k}={v}")
        return " | ".join(parts) if parts else "no pin info"


@dataclass
class BoardDef:
    """Parsed board definition with UI-relevant resources."""

    name: str
    class_name: str
    vendor: str = ""
    device: str = ""
    package: str = ""
    clocks: list[float] = field(default_factory=list)  # Hz, e.g. [25e6, 100e6]
    #: The same clocks with their names and pins kept (U53).  ``clocks`` above
    #: stays the Hz-only view its consumers want; this is the one the pin map
    #: reads.  Empty for a board whose JSON lists bare numbers.
    clock_defs: list[ClockDef] = field(default_factory=list)
    default_clock_hz: float = _FALLBACK_CLOCK_HZ  # Hz; drives cocotb Clock()
    #: ``True`` when upstream states no frequency, so ``default_clock_hz`` is the
    #: sync's fallback rather than upstream data (U56 D-6); the chip says "assumed".
    default_clock_assumed: bool = False
    leds: list[ComponentInfo] = field(default_factory=list)
    buttons: list[ComponentInfo] = field(default_factory=list)
    switches: list[ComponentInfo] = field(default_factory=list)
    seven_seg: "SevenSegDef | None" = None
    port_conventions: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    #: The board file's name without ``.json`` (``nexys_4_ddr``).  Set by discovery,
    #: like ``source``, and like it never serialized: the pair is the one spelling
    #: that names exactly one board (:attr:`qualified_name`).
    file_stem: str = ""
    #: ``"orphaned"`` when upstream no longer defines this board (U56 plan §4.3): the
    #: file is kept, frozen at its last good sync, so designs written for it still
    #: run.  Empty for a board upstream still defines.  Read from the board file's
    #: ``source`` block, like the three fields below.
    upstream_status: str = ""
    #: The upstream commit of the sync that found the board orphaned.
    orphaned_at_commit: str = ""
    #: The UTC date (``YYYY-MM-DD``) of that sync, which the preview shows.
    orphaned_at_date: str = ""
    #: ``file_removed`` / ``no_longer_defined`` / ``no_simulatable_io``.
    orphaned_reason: str = ""
    #: ``<source>/<file>.json`` of the board that replaces an orphan.  The sync names
    #: one only when its FPGA, clocks and I/O are identical to the orphan's.  It is a
    #: hint, never an automatic migration.
    successor: str = ""

    @property
    def qualified_name(self) -> str:
        """``<source>/<file stem>``, e.g. ``digilent-xdc/nexys_4_ddr``; empty if unknown.

        A display name or class name can be shared across sources -- Amaranth and
        Digilent both ship a Nexys 4 DDR, with the same class name -- but a file
        path cannot, so this is the ``--board`` spelling that is never ambiguous.
        """
        if not (self.source and self.file_stem):
            return ""
        return f"{self.source}/{self.file_stem}"

    @property
    def summary(self) -> str:
        """One-line summary of resource counts for display in the UI."""
        parts = [
            self.led_summary(),
            f"{len(self.buttons)} BTN",
            f"{len(self.switches)} SW",
        ]
        if self.seven_seg:
            parts.append(f"{self.seven_seg.num_digits}-digit 7-seg")
        return " · ".join(parts)

    @property
    def led_banks(self) -> list[tuple[str, list[ComponentInfo]]]:
        """LEDs grouped into consecutive same-name runs (a view over ``leds``).

        E.g. DE2-115's 18 ``led`` + 9 ``led_g`` ->
        ``[("led", [...18]), ("led_g", [...9])]``.  ``leds`` stays the single
        source of truth; banks are derived for per-bank labels and color
        clustering in the renderer (U36).  Interleaved names yield one bank per
        run, mirroring physical order.
        """
        banks: list[tuple[str, list[ComponentInfo]]] = []
        for c in self.leds:
            if banks and banks[-1][0] == c.name:
                banks[-1][1].append(c)
            else:
                banks.append((c.name, [c]))
        return banks

    @property
    def led_channels(self) -> list[tuple[ComponentInfo, str]]:
        """Boundary ``led`` bit k -> (component, channel) (U37).

        Mono LEDs first (JSON order), then ``("r", "g", "b")`` per RGB LED
        (JSON order) -- this IS the layout convention the VHDL contract
        documents: ``MONO = NUM_LEDS - 3*NUM_RGB_LEDS``, and
        ``led(MONO + 3*i + 0/1/2)`` drives site i's red/green/blue. Display
        order stays physical (``leds`` as-is); only the boundary mapping is
        normalized mono-first, so no JSON reordering is ever needed.
        """
        mono = [c for c in self.leds if not c.is_rgb]
        rgb = [c for c in self.leds if c.is_rgb]
        return [(c, "mono") for c in mono] + [(c, ch) for c in rgb for ch in ("r", "g", "b")]

    @property
    def num_led_channels(self) -> int:
        """Width of the boundary ``led`` vector: mono LEDs + 3 per RGB LED.

        This is what ``NUM_LEDS`` must be set to -- ``len(leds)`` counts
        *components* (an RGB LED is one component but three channels).
        """
        return len(self.leds) + 2 * self.num_rgb_leds

    @property
    def num_rgb_leds(self) -> int:
        """Number of 3-channel RGB LED sites (what ``NUM_RGB_LEDS`` is set to)."""
        return sum(1 for c in self.leds if c.is_rgb)

    @property
    def led_channel_targets(self) -> list[int]:
        """Component index (into ``leds``) driven by each boundary channel.

        Aligned with :attr:`led_channels` (mono first, then 3 per RGB site);
        an RGB component's index appears three times. The renderer folds
        channel-indexed state onto per-component widgets with this.
        """
        mono = [i for i, c in enumerate(self.leds) if not c.is_rgb]
        rgb = [i for i, c in enumerate(self.leds) if c.is_rgb]
        return mono + [i for i in rgb for _ in range(3)]

    def led_summary(self) -> str:
        """LED portion of :attr:`summary`, broken out by bank (U36).

        Two mono banks read as ``18+9 LEDs``; RGB banks are counted separately,
        ``4 LEDs + 4 RGB``. A single mono bank stays ``N LEDs`` as before.
        """
        mono = [len(comps) for name, comps in self.led_banks if "rgb" not in name]
        rgb = sum(len(comps) for name, comps in self.led_banks if "rgb" in name)
        segs = []
        if mono:
            # Break out two banks (the common two-color-row case, e.g. 18+9);
            # collapse more than two to a single total to stay readable.
            mono_str = "+".join(str(m) for m in mono) if len(mono) <= 2 else str(sum(mono))
            segs.append(f"{mono_str} LEDs")
        if rgb:
            segs.append(f"{rgb} RGB")
        return " + ".join(segs) if segs else "0 LEDs"

    def _primary_convention(self) -> dict[str, Any] | None:
        """Return the canonical port_convention block to read bank labels from.

        Framework-derived blocks are skipped: their generic ``led`` / ``user_led``
        names are no better than the friendly default label, so only a
        vendor-canonical block (or ``None``) supplies names like ``LEDR`` (U36).
        """
        canonical = [
            v
            for v in self.port_conventions.values()
            if isinstance(v, dict) and v.get("naming") != "framework-derived"
        ]
        return canonical[0] if canonical else None

    def led_bank_label(self, bank_name: str) -> str:
        """Human label for an LED bank (U36).

        A canonical convention port name (``LEDR`` / ``LEDG``) when the board
        declares one, else a friendly default: a plain ``led`` bank -> ``LEDs``,
        an ``rgb_led`` bank -> ``RGB``, otherwise the uppercased resource name.
        """
        if "rgb" in bank_name:
            return "RGB"
        conv = self._primary_convention()
        if conv is not None:
            if bank_name == "led":
                leds = conv.get("leds")
                if isinstance(leds, dict) and leds.get("name"):
                    return str(leds["name"])
            elif bank_name in ("led_g", "led_green", "ledg"):
                green = conv.get("leds_green")
                if isinstance(green, dict) and green.get("name"):
                    return str(green["name"])
        return "LEDs" if bank_name == "led" else bank_name.upper()

    def to_json(self) -> str:
        """Serialize to JSON for passing to the cocotb subprocess."""

        def _comp(c: ComponentInfo) -> dict[str, object]:
            d: dict[str, object] = {
                "name": c.name,
                "number": c.number,
                "pins": c.pins,
                "direction": c.direction,
                "inverted": c.inverted,
                "connector": list(c.connector) if c.connector else None,
                "attrs": c.attrs,
            }
            if c.color:  # emit only when set -- keep JSON diffs minimal (U36)
                d["color"] = c.color
            return d

        return json.dumps(
            {
                "name": self.name,
                "class_name": self.class_name,
                "vendor": self.vendor,
                "device": self.device,
                "package": self.package,
                # The rich form when we have it: a round-trip used to downgrade
                # a board's clock objects to bare Hz and drop the pins.
                "clocks": (
                    [c.to_dict() for c in self.clock_defs] if self.clock_defs else self.clocks
                ),
                "default_clock_hz": self.default_clock_hz,
                # Emitted only when set, like an LED's color: every other board
                # serializes exactly as before (U56 D-6).
                **({"default_clock_assumed": True} if self.default_clock_assumed else {}),
                "leds": [_comp(c) for c in self.leds],
                "buttons": [_comp(c) for c in self.buttons],
                "switches": [_comp(c) for c in self.switches],
                "seven_seg": self.seven_seg.to_dict() if self.seven_seg else None,
                # Board-native VHDL port conventions (U21). Carried verbatim as
                # the schema-shaped dict; consumed launcher-side (contract
                # matcher + native wrapper), so it rides to the subprocess
                # harmlessly and needs no typed round-trip here.
                "port_conventions": self.port_conventions,
                # Only an orphaned board carries a source block, so every other
                # board's serialization stays exactly as it was (U56 §4.3).
                **({"source": self._orphan_source()} if self.upstream_status else {}),
            }
        )

    def orphan_note(self) -> str:
        """Return what to tell someone about an orphaned board, else ``""`` (U56 §4.8).

        :meth:`orphan_parts` as text: the lead, then one line per row, with the labels
        padded so the two file names line up in a terminal.  ``--board`` prints it.
        """
        lead, rows = self.orphan_parts()
        if not lead:
            return ""
        width = max(len(label) for label, _ in rows) if rows else 0
        return "\n".join([lead, *(f"{label:<{width}} {value}" for label, value in rows)])

    def orphan_parts(self) -> tuple[str, list[tuple[str, str]]]:
        """Return an orphan's note as a lead and label/value rows, else ``("", [])``.

        The lead says why upstream dropped the board, when the sync noticed, and that
        a design still runs on this saved copy.  When the sync noticed, not since when:
        a sync reads one upstream snapshot, so it cannot know the commit that dropped
        the board.  (The Efinix renames it found at Phase 4 were upstream's of July,
        noticed in November.)  With a successor, two rows follow, this
        board's file and then the successor's, so a reader can compare the names.
        Both use the ``<source>/<file>`` spelling that ``--board`` takes, the one name
        that picks exactly one board (display names repeat across sources).  The sync
        names a successor only when its FPGA, clocks and I/O are identical (§4.3),
        and the row says so.
        """
        if self.upstream_status != "orphaned":
            return "", []
        date, commit = self.orphaned_at_date, self.orphaned_at_commit[:7]
        when = ", at ".join(part for part in (date, commit) if part)
        noticed = f" (noticed {'at ' if commit and not date else ''}{when})" if when else ""
        why = _ORPHAN_LEADS.get(self.orphaned_reason, "{source} no longer defines it{noticed}.")
        lead = (
            why.format(source=self.source or "Upstream", noticed=noticed)
            + " Your design still runs on this saved copy; it will not receive upstream fixes."
        )
        if not self.successor:
            return lead, []
        return lead, [
            ("This board:", self.qualified_name or self.name),
            ("Successor:", f"{self.successor.removesuffix('.json')} (same FPGA, clocks and I/O)"),
        ]

    def _orphan_source(self) -> dict[str, str]:
        """Return the orphan fields of the board file's ``source`` block, for ``to_json``."""
        fields = {
            "upstream_status": self.upstream_status,
            "orphaned_at_commit": self.orphaned_at_commit,
            "orphaned_at_date": self.orphaned_at_date,
            "orphaned_reason": self.orphaned_reason,
            "successor": self.successor,
        }
        return {k: v for k, v in fields.items() if v}

    @classmethod
    def from_json(cls, raw: str) -> "BoardDef":
        """Deserialize from JSON produced by to_json()."""
        data = json.loads(raw)

        def _make(items: list[dict[str, Any]], kind: str) -> list[ComponentInfo]:
            return [
                ComponentInfo(
                    kind=kind,
                    name=c["name"],
                    number=c["number"],
                    pins=c.get("pins", []),
                    direction=c.get("direction", ""),
                    inverted=c.get("inverted", False),
                    connector=tuple(c["connector"]) if c.get("connector") else None,
                    attrs=c.get("attrs", {}),
                    color=c.get("color", ""),
                )
                for c in items
            ]

        clock_defs = [ClockDef.from_raw(c) for c in data.get("clocks", [])]
        raw_clocks = [c.hz for c in clock_defs]

        raw_7seg = data.get("seven_seg")
        class_name = data["class_name"]
        source = data.get("source")
        if not isinstance(source, dict):
            source = {}
        return cls(
            # U49: repair the sync parsers' name heuristic at load time, so the
            # correction reaches every consumer -- selector, session log, and
            # the copy serialized to the headless child -- from one place.
            name=_DISPLAY_NAME_OVERRIDES.get(class_name, data["name"]),
            class_name=class_name,
            vendor=data.get("vendor", ""),
            device=data.get("device", ""),
            package=data.get("package", ""),
            clocks=raw_clocks,
            clock_defs=clock_defs,
            default_clock_hz=data.get("default_clock_hz", _FALLBACK_CLOCK_HZ),
            default_clock_assumed=data.get("default_clock_assumed") is True,
            leds=_make(data.get("leds", []), "led"),
            buttons=_make(data.get("buttons", []), "button"),
            switches=_make(data.get("switches", []), "switch"),
            seven_seg=SevenSegDef.from_dict(raw_7seg) if raw_7seg else None,
            # `or {}` also covers an explicit ``"port_conventions": null``, not
            # just an absent key -- a board without conventions gets an empty mapping.
            port_conventions=data.get("port_conventions") or {},
            upstream_status=str(source.get("upstream_status", "")),
            orphaned_at_commit=str(source.get("orphaned_at_commit", "")),
            orphaned_at_date=str(source.get("orphaned_at_date", "")),
            orphaned_reason=str(source.get("orphaned_reason", "")),
            successor=str(source.get("successor", "")),
        )


# ═══════════════════════════════════════════════════════════════════════
#  Discovery
# ═══════════════════════════════════════════════════════════════════════


def _discover_boards_json(boards_dir: Path) -> list[BoardDef]:
    """Read JSON board files from all source subdirectories.

    Every subdirectory under boards_dir (except 'schema') is a source.
    All boards from all sources are returned -- no deduplication.
    """
    all_boards: list[BoardDef] = []
    for source_dir in sorted(boards_dir.iterdir()):
        if not source_dir.is_dir() or source_dir.name == "schema":
            continue
        source_name = source_dir.name
        for json_file in sorted(source_dir.glob("*.json")):
            if json_file.name.startswith("_"):
                continue
            try:
                board = BoardDef.from_json(json_file.read_text(encoding="utf-8"))
                board.source = source_name
                board.file_stem = json_file.stem
                all_boards.append(board)
            except Exception:
                continue
    return all_boards


def discover_boards(boards_dir: str | Path) -> list[BoardDef]:
    """Scan a directory for JSON board definitions and return all BoardDefs.

    Each subdirectory under ``boards_dir`` (except ``schema``) is a source; every
    ``*.json`` board file it contains is loaded.  Returns an empty list if the
    directory does not exist or has no source subdirectories.
    """
    boards_dir = Path(boards_dir)
    if not boards_dir.is_dir():
        return []
    return _discover_boards_json(boards_dir)


def get_default_boards_path() -> Path:
    """Path to the ``boards/`` directory containing JSON board definitions."""
    return BOARDS_DIR


def _board_key(text: str) -> str:
    """Lowercase alphanumerics only: the spelling-insensitive form of a board name."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


def match_boards(boards: list[BoardDef], wanted: str) -> list[BoardDef]:
    """Every board a ``--board`` argument names, in load order; the first is the answer.

    Three spellings are accepted, because all three are visible to the user:

    * the **display name** the selector shows ("DE10-Standard") and the **class
      name** the session file and the docs use ("DE10StandardPlatform"), matched
      case-insensitively and ignoring the separators the two disagree about, so
      ``de10-standard``, ``DE10 Standard`` and ``DE10StandardPlatform`` find the
      same board -- a student typing a name from the screen should not have to
      guess its punctuation.  The ``Platform`` suffix is optional.
    * the board's **file**, ``<source>/<file stem>`` (``digilent-xdc/nexys_4_ddr``;
      ``.json`` and a leading ``boards/`` are optional, case is not significant).

    Names are not unique: sources ship the same board under the same name --
    Amaranth's and Digilent's Nexys 4 DDR even share a class name -- and a name
    says nothing about its source, so a name can return several boards.  Load
    order (source folders sorted, then files) decides which comes first, which
    keeps the answer every earlier release gave.  A file names exactly one board,
    which is what it is for: without it, a board whose name another source also
    uses could not be reached from the command line at all.
    """
    text = wanted.strip()
    if "/" in text or "\\" in text:
        parts = [p for p in text.replace("\\", "/").split("/") if p]
        if len(parts) >= 2:
            source = parts[-2].lower()
            stem = parts[-1].lower().removesuffix(".json")
            hits = [b for b in boards if b.source.lower() == source and b.file_stem.lower() == stem]
            if hits:
                return hits
        # No such file: fall through, so a name that contains a slash still matches.
    target = _board_key(text)
    if not target:
        return []
    hits = [b for b in boards if target in (_board_key(b.class_name), _board_key(b.name))]
    if hits:
        return hits
    # The class names all end in "Platform", so let the suffix be optional rather
    # than making it a thing to remember.
    suffixed = _board_key(text + "Platform")
    return [b for b in boards if _board_key(b.class_name) == suffixed]


def find_board(boards: list[BoardDef], wanted: str) -> BoardDef | None:
    """Resolve a ``--board`` argument to one board: the first of :func:`match_boards`.

    Returns ``None`` when nothing matches; the caller decides whether that is
    fatal (the benchmark) or a warning (the launcher, which falls back to the
    selector).  A caller that talks to the user should also print
    :func:`ambiguity_note`, so a name that matched several boards says so.
    """
    hits = match_boards(boards, wanted)
    return hits[0] if hits else None


def ambiguity_note(wanted: str, hits: list[BoardDef]) -> str | None:
    """Return the line to print when ``--board`` named several boards, else ``None``.

    The first board is opened, as before; the note names it and the others by
    their files, the spelling that picks one -- a screenshot or smoke test of the
    other source's board otherwise looks exactly like a test of the one meant.
    """
    if len(hits) < 2:
        return None
    others = ", ".join(b.qualified_name or b.class_name for b in hits[1:])
    first = hits[0].qualified_name or hits[0].class_name
    return (
        f"--board {wanted!r} matches {len(hits)} boards; opening {first}. "
        f"To open another, name its file: {others}"
    )
