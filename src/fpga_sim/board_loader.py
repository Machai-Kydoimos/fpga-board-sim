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

    @property
    def display_name(self) -> str:
        """Short label for the UI, e.g. 'LED0', 'BTN2', 'UP0', 'RGB1'."""
        prefixes = {"led": "LED", "button": "BTN", "switch": "SW"}
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
    source: str = ""

    @property
    def summary(self) -> str:
        """One-line summary of resource counts for display in the UI."""
        parts = [
            f"{len(self.leds)} LEDs",
            f"{len(self.buttons)} BTN",
            f"{len(self.switches)} SW",
        ]
        if self.seven_seg:
            parts.append(f"{self.seven_seg.num_digits}-digit 7-seg")
        return " · ".join(parts)

    def to_json(self) -> str:
        """Serialize to JSON for passing to the cocotb subprocess."""

        def _comp(c: ComponentInfo) -> dict[str, object]:
            return {
                "name": c.name,
                "number": c.number,
                "pins": c.pins,
                "direction": c.direction,
                "inverted": c.inverted,
                "connector": list(c.connector) if c.connector else None,
                "attrs": c.attrs,
            }

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
