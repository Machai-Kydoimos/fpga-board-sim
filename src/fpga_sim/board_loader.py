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

_FALLBACK_CLOCK_HZ: float = 12e6  # most common across 80 surveyed boards


# ═══════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class SevenSegDef:
    """7-segment display capability extracted from a board definition."""

    num_digits: int
    has_dp: bool
    is_multiplexed: bool
    inverted: bool  # board hardware active-low (metadata; VHDL is active-high)
    select_inverted: bool  # mux select lines active-low (v2 use)

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict for inclusion in BoardDef JSON."""
        return {
            "num_digits": self.num_digits,
            "has_dp": self.has_dp,
            "is_multiplexed": self.is_multiplexed,
            "inverted": self.inverted,
            "select_inverted": self.select_inverted,
        }

    @classmethod
    def from_dict(cls, d: dict[str, object]) -> "SevenSegDef":
        """Deserialize from a dict produced by to_dict()."""
        return cls(
            num_digits=int(d["num_digits"]),  # type: ignore[call-overload]  # strict: required field
            has_dp=bool(d["has_dp"]),  # strict: required field
            is_multiplexed=bool(d["is_multiplexed"]),  # strict: required field
            inverted=bool(d.get("inverted", False)),
            select_inverted=bool(d.get("select_inverted", False)),
        )


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
                "clocks": self.clocks,
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

        raw_clocks = data.get("clocks", [])
        if raw_clocks and isinstance(raw_clocks[0], dict):
            raw_clocks = [c["hz"] for c in raw_clocks]

        raw_7seg = data.get("seven_seg")
        return cls(
            name=data["name"],
            class_name=data["class_name"],
            vendor=data.get("vendor", ""),
            device=data.get("device", ""),
            package=data.get("package", ""),
            clocks=raw_clocks,
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
    return Path(__file__).parent.parent.parent / "boards"
