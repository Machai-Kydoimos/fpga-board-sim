"""Board Loader – load board JSON definitions into :class:`BoardDef` objects.

This is the runtime board path: :func:`discover_boards` reads the JSON board
definitions under ``boards/`` (one subdirectory per source) into
:class:`BoardDef` objects, with no amaranth dependency.

The complementary *offline* path — turning upstream amaranth-style board ``.py``
files into ``BoardDef`` objects via a mock-exec namespace — lives in
``scripts/amaranth_parser.py`` and is used only by the ``sync_*`` regenerators.
That parser imports the data classes defined here; this module never imports the
parser, so the runtime loader and the offline tooling evolve independently.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fpga_sim.paths import BOARDS_DIR

_FALLBACK_CLOCK_HZ: float = 12e6  # most common across 80 surveyed boards


# ═══════════════════════════════════════════════════════════════════════
#  Display-name overrides (U49)
# ═══════════════════════════════════════════════════════════════════════

#: Corrected display names, keyed by ``class_name``.
#:
#: The two sync parsers derive a board's display name from its upstream class
#: name by splitting on case and digit boundaries
#: (``scripts/amaranth_parser._prettify_class_name``, and a second copy in
#: ``scripts/litex_parser``).  The heuristic is right for most of the fleet and
#: wrong for the names that matter here: it splits ``DE1SoC`` into "DE1 So C"
#: and turns ``ULX3S_45F_``'s trailing underscore into a dangling hyphen,
#: "ULX3 S-45 F-".
#:
#: **This table is the cheap half of the fix, on purpose.**  Correcting the
#: parsers would mean re-syncing every generated board, which the CI drift job
#: (``scripts/check_board_drift.py``) then has to agree with byte for byte --
#: real risk, three weeks before a semester, for a cosmetic defect.  Applied at
#: load time nothing regenerates and no board JSON changes, so there is nothing
#: for the drift job to disagree with.  The parser fix stays carded.
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
    "AX7325BPlatform": "AX7325B",  # alinx_ax7325b.py
    "Colorlight_5A75B_R70Platform": "Colorlight-5A75B-R70",  # colorlight_5a75b_r7_0.py
    "CoraZ7_07SPlatform": "Cora Z7-07S",  # class CoraZ7_07S; Digilent's variant suffix
    "DE1SoCPlatform": "DE1-SoC",  # de1_soc.py
    "Logicbone85FPlatform": "Logicbone 85F",  # logicbone.py; 85F is the ECP5 part
    "OrangeCrabR0_2_25FPlatform": "OrangeCrab R0.2 25F",  # orangecrab_r0_2.py
    "OrangeCrabR0_2_85FPlatform": "OrangeCrab R0.2 85F",  # orangecrab_r0_2.py
    "SitlinvAE115fbPlatform": "Sitlinv AE115fb",  # sitlinv_a_e115fb.py
    "TE0714_03_50_2IPlatform": "TE0714-03-50-2I",  # te0714_03_50_2I.py
    # ── Trailing underscore turned into a dangling separator ──────────────
    "CmodS7_Platform": "Cmod S7",  # cmod_s7.py
    "ULX3S_12F_Platform": "ULX3S-12F",  # ulx3s.py
    "ULX3S_25F_Platform": "ULX3S-25F",  # ulx3s.py
    "ULX3S_45F_Platform": "ULX3S-45F",  # ulx3s.py
    "ULX3S_85F_Platform": "ULX3S-85F",  # ulx3s.py
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
    leds: list[ComponentInfo] = field(default_factory=list)
    buttons: list[ComponentInfo] = field(default_factory=list)
    switches: list[ComponentInfo] = field(default_factory=list)
    seven_seg: "SevenSegDef | None" = None
    port_conventions: dict[str, Any] = field(default_factory=dict)
    source: str = ""

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
                "leds": [_comp(c) for c in self.leds],
                "buttons": [_comp(c) for c in self.buttons],
                "switches": [_comp(c) for c in self.switches],
                "seven_seg": self.seven_seg.to_dict() if self.seven_seg else None,
                # Board-native VHDL port conventions (U21). Carried verbatim as
                # the schema-shaped dict; consumed launcher-side (contract
                # matcher + native wrapper), so it rides to the subprocess
                # harmlessly and needs no typed round-trip here.
                "port_conventions": self.port_conventions,
            }
        )

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
            leds=_make(data.get("leds", []), "led"),
            buttons=_make(data.get("buttons", []), "button"),
            switches=_make(data.get("switches", []), "switch"),
            seven_seg=SevenSegDef.from_dict(raw_7seg) if raw_7seg else None,
            # `or {}` also covers an explicit ``"port_conventions": null``, not
            # just an absent key -- a board without conventions gets an empty mapping.
            port_conventions=data.get("port_conventions") or {},
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


def find_board(boards: list[BoardDef], wanted: str) -> BoardDef | None:
    """Resolve a ``--board`` argument against *boards* by class name or name.

    Both spellings are accepted because both are visible to the user: the
    selector shows ``name`` ("DE10-Standard") while the session file and every
    example in the docs use ``class_name`` ("DE10StandardPlatform").  The match
    is case-insensitive and ignores the separators the two spellings disagree
    about, so ``de10-standard``, ``DE10 Standard`` and ``DE10StandardPlatform``
    all find the same board -- a student typing a board name from the screen
    should not have to guess its punctuation.

    Returns ``None`` when nothing matches; the caller decides whether that is
    fatal (the benchmark) or a warning (the launcher, which falls back to the
    selector).
    """

    def key(text: str) -> str:
        return "".join(ch for ch in text.lower() if ch.isalnum())

    target = key(wanted)
    if not target:
        return None
    for board in boards:
        if key(board.class_name) == target or key(board.name) == target:
            return board
    # Second pass: the class names all end in "Platform", so let the suffix be
    # optional rather than making it a thing to remember.
    for board in boards:
        if key(board.class_name) == key(wanted + "Platform"):
            return board
    return None
