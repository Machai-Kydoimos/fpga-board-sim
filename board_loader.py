"""Board Loader – discovers and parses amaranth-boards definitions.

Uses lightweight mock classes to evaluate board files without
requiring the full amaranth toolchain.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════
#  Mock amaranth.build classes (just enough to exec board files)
# ═══════════════════════════════════════════════════════════════════════

class _Attrs(dict):
    def __init__(self, **kwargs: str) -> None:
        super().__init__(**kwargs)


class _Pins:
    def __init__(
        self,
        names: str | list[str],
        *,
        dir: str = "io",
        invert: bool = False,
        conn: str | None = None,
        assert_width: int | None = None,
    ) -> None:
        self.names = names.split() if isinstance(names, str) else list(names)
        self.dir = dir
        self.invert = invert
        self.conn = conn


class _PinsN(_Pins):
    def __init__(self, names: str | list[str], **kwargs: object) -> None:
        kwargs["invert"] = True
        super().__init__(names, **kwargs)  # type: ignore[arg-type]


class _DiffPairs:
    def __init__(
        self,
        p: str | list[str],
        n: str | list[str],
        *,
        dir: str = "io",
        invert: bool = False,
        conn: str | None = None,
        assert_width: int | None = None,
    ) -> None:
        self.p = p.split() if isinstance(p, str) else list(p)
        self.n = n.split() if isinstance(n, str) else list(n)
        self.dir = dir


class _Clock:
    def __init__(self, freq: float) -> None:
        self.freq = freq


class _Subsignal:
    def __init__(self, name: str, *ios: object, **kwargs: object) -> None:
        self.name = name
        self.ios = [io for io in ios if io is not None]


class _Connector:
    def __init__(
        self,
        name: str,
        number: int,
        pins: str | dict = "",
        **kwargs: object,
    ) -> None:
        self.name = name
        self.number = number
        if isinstance(pins, str):
            self.mapping = {}
            for i, p in enumerate(pins.split()):
                if p != "-":
                    self.mapping[str(i)] = p
        elif isinstance(pins, dict):
            self.mapping = {str(k): v for k, v in pins.items()}
        else:
            self.mapping = {}


class _Resource:
    def __init__(self, name: str, number: int, *ios: object) -> None:
        self.name = name
        self.number = number
        self.ios = []
        self.attrs = _Attrs()
        for io in ios:
            if isinstance(io, _Attrs):
                self.attrs = io
            elif io is not None:
                self.ios.append(io)

    @classmethod
    def family(
        cls,
        *args: object,
        default_name: str,
        ios: list,
        name_suffix: str = "",
    ) -> "_Resource":
        """Construct a _Resource from positional (number,) or (name, number) args."""
        # args is (number,) or (name, number) – mirrors the real amaranth API
        if len(args) >= 2 and isinstance(args[0], str):
            name, number = args[0], args[1]
        elif len(args) >= 1:
            name, number = default_name, args[0]
        else:
            name, number = default_name, 0
        if name_suffix:
            name = f"{name}_{name_suffix}"
        return cls(name, number, *ios)  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════
#  Resource helper functions (mirrors amaranth_boards/resources/)
# ═══════════════════════════════════════════════════════════════════════

def _split_resources(
    *args: object,
    pins: str | list | dict,
    invert: bool = False,
    conn: str | None = None,
    attrs: "_Attrs | None" = None,
    default_name: str,
    dir: str,
) -> list[_Resource]:
    if isinstance(pins, str):
        pins = pins.split()
    if isinstance(pins, list):
        pins = dict(enumerate(pins))
    resources = []
    for number, pin in pins.items():
        ios: list[_Pins | _Attrs] = [_Pins(pin, dir=dir, invert=invert, conn=conn)]
        if attrs is not None:
            ios.append(attrs)
        resources.append(
            _Resource.family(*args, number, default_name=default_name, ios=ios))
    return resources


def _led_resources(*args: object, **kwargs: object) -> list[_Resource]:
    return _split_resources(*args, **kwargs, default_name="led", dir="o")  # type: ignore[arg-type]


def _rgb_led_resource(
    *args: object,
    r: str,
    g: str,
    b: str,
    invert: bool = False,
    conn: str | None = None,
    attrs: "_Attrs | None" = None,
) -> _Resource:
    ios: list[_Subsignal | _Attrs] = [
        _Subsignal("r", _Pins(r, dir="o", invert=invert, conn=conn, assert_width=1)),
        _Subsignal("g", _Pins(g, dir="o", invert=invert, conn=conn, assert_width=1)),
        _Subsignal("b", _Pins(b, dir="o", invert=invert, conn=conn, assert_width=1)),
    ]
    if attrs is not None:
        ios.append(attrs)
    return _Resource.family(*args, default_name="rgb_led", ios=ios)


def _button_resources(*args: object, **kwargs: object) -> list[_Resource]:
    return _split_resources(*args, **kwargs, default_name="button", dir="i")  # type: ignore[arg-type]


def _switch_resources(*args: object, **kwargs: object) -> list[_Resource]:
    return _split_resources(*args, **kwargs, default_name="switch", dir="i")  # type: ignore[arg-type]


def _stub_single(*args: object, **kwargs: object) -> _Resource:
    """Stub for single-resource helpers we don't simulate."""
    return _Resource("_stub", 0)


def _stub_multi(*args: object, **kwargs: object) -> list[_Resource]:
    """Stub for multi-resource helpers we don't simulate."""
    return [_Resource("_stub", 0)]


# ═══════════════════════════════════════════════════════════════════════
#  Exec namespace
# ═══════════════════════════════════════════════════════════════════════

_PLATFORM_VENDORS: dict[str, str] = {
    "XilinxPlatform":           "Xilinx",
    "Xilinx7SeriesPlatform":    "Xilinx",
    "XilinxUltraScalePlatform": "Xilinx",
    "IntelPlatform":            "Intel",
    "LatticeICE40Platform":     "Lattice",
    "LatticeECP5Platform":      "Lattice",
    "LatticeMachXO2Platform":   "Lattice",
    "LatticeMachXO3LPlatform":  "Lattice",
    "QuicklogicPlatform":       "QuickLogic",
    "GowinPlatform":            "Gowin",
}


def _make_namespace() -> dict[str, object]:
    ns: dict[str, object] = {
        # Core build DSL
        "Resource":     _Resource,
        "Subsignal":    _Subsignal,
        "Pins":         _Pins,
        "PinsN":        _PinsN,
        "DiffPairs":    _DiffPairs,
        "Attrs":        _Attrs,
        "Clock":        _Clock,
        "Connector":    _Connector,
        # User resources (the ones we actually parse)
        "LEDResources":     _led_resources,
        "RGBLEDResource":   _rgb_led_resource,
        "ButtonResources":  _button_resources,
        "SwitchResources":  _switch_resources,
        # Display stubs
        "Display7SegResource": _stub_single,
        "VGAResource":         _stub_single,
        # Interface stubs
        "UARTResource":      _stub_single,
        "IrDAResource":      _stub_single,
        "SPIResource":       _stub_single,
        "I2CResource":       _stub_single,
        "DirectUSBResource": _stub_single,
        "ULPIResource":      _stub_single,
        "PS2Resource":       _stub_single,
        # Memory stubs
        "SPIFlashResources":  _stub_multi,
        "SDCardResources":    _stub_multi,
        "SRAMResource":       _stub_single,
        "SDRAMResource":      _stub_single,
        "NORFlashResources":  _stub_multi,
        "DDR3Resource":       _stub_single,
        # Stdlib modules used by board files
        "os":         __import__("os"),
        "subprocess": __import__("subprocess"),
        "unittest":   __import__("unittest"),
        # Prevent __main__ guard from running
        "__name__":     "_board_loader_exec",
        "__builtins__": __builtins__,
    }
    for name, vendor in _PLATFORM_VENDORS.items():
        ns[name] = type(name, (), {
            "resources": [], "connectors": [], "_vendor": vendor,
        })
    return ns


# ═══════════════════════════════════════════════════════════════════════
#  Clock extraction
# ═══════════════════════════════════════════════════════════════════════

def _extract_clocks(resources: list) -> list[float]:
    """Return sorted unique clock frequencies (Hz) from the resource list."""
    seen: set[float] = set()
    for res in resources:
        for io in res.ios:
            if isinstance(io, _Clock):
                seen.add(io.freq)
    return sorted(seen)


_FALLBACK_CLOCK_HZ: float = 12e6  # most common across 80 surveyed boards


def _find_default_clock_hz(resources: list, default_clk: str | None) -> float:
    """Return Hz for the named default_clk resource, or _FALLBACK_CLOCK_HZ."""
    if default_clk:
        for res in resources:
            if res.name == default_clk:
                for io in res.ios:
                    if isinstance(io, _Clock):
                        return float(io.freq)
    return _FALLBACK_CLOCK_HZ


# ═══════════════════════════════════════════════════════════════════════
#  Data classes
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ComponentInfo:
    """Describes a single LED, button, or switch extracted from a board."""

    kind: str           # "led", "button", or "switch"
    name: str           # amaranth resource name, e.g. "led", "button_up", "rgb_led"
    number: int         # resource index
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
            suffix = suffix[len(self.kind):]
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
    clocks: list = field(default_factory=list)   # Hz, e.g. [25e6, 100e6]
    default_clock_hz: float = _FALLBACK_CLOCK_HZ  # Hz; drives cocotb Clock()
    leds: list = field(default_factory=list)
    buttons: list = field(default_factory=list)
    switches: list = field(default_factory=list)

    @property
    def summary(self) -> str:
        """One-line summary of resource counts for display in the UI."""
        return (f"{len(self.leds)} LEDs, "
                f"{len(self.buttons)} buttons, "
                f"{len(self.switches)} switches")

    def to_json(self) -> str:
        """Serialize to JSON for passing to the cocotb subprocess."""
        def _comp(c: ComponentInfo) -> dict[str, object]:
            return {
                "name": c.name, "number": c.number,
                "pins": c.pins, "direction": c.direction,
                "inverted": c.inverted,
                "connector": list(c.connector) if c.connector else None,
                "attrs": c.attrs,
            }
        return json.dumps({
            "name": self.name, "class_name": self.class_name,
            "vendor": self.vendor, "device": self.device,
            "package": self.package, "clocks": self.clocks,
            "default_clock_hz": self.default_clock_hz,
            "leds":    [_comp(c) for c in self.leds],
            "buttons": [_comp(c) for c in self.buttons],
            "switches": [_comp(c) for c in self.switches],
        })

    @classmethod
    def from_json(cls, raw: str) -> "BoardDef":
        """Deserialize from JSON produced by to_json()."""
        data = json.loads(raw)

        def _make(items: list, kind: str) -> list[ComponentInfo]:
            return [ComponentInfo(
                kind=kind,
                name=c["name"], number=c["number"],
                pins=c.get("pins", []), direction=c.get("direction", ""),
                inverted=c.get("inverted", False),
                connector=tuple(c["connector"]) if c.get("connector") else None,
                attrs=c.get("attrs", {}),
            ) for c in items]

        return cls(
            name=data["name"], class_name=data["class_name"],
            vendor=data.get("vendor", ""), device=data.get("device", ""),
            package=data.get("package", ""), clocks=data.get("clocks", []),
            default_clock_hz=data.get("default_clock_hz", _FALLBACK_CLOCK_HZ),
            leds=_make(data.get("leds", []), "led"),
            buttons=_make(data.get("buttons", []), "button"),
            switches=_make(data.get("switches", []), "switch"),
        )


# ═══════════════════════════════════════════════════════════════════════
#  Extraction helpers
# ═══════════════════════════════════════════════════════════════════════

def _extract_pins(
    resource: _Resource,
) -> tuple[list[str], str, bool, str | None]:
    pins, direction, inverted, connector = [], "", False, None
    for io in resource.ios:
        if isinstance(io, _Pins):
            pins.extend(io.names)
            direction = io.dir
            inverted = io.invert
            connector = io.conn
        elif isinstance(io, _Subsignal):
            for sub in io.ios:
                if isinstance(sub, _Pins):
                    pins.extend(sub.names)
                    if not direction:
                        direction = sub.dir
                    inverted = inverted or sub.invert
                    if sub.conn:
                        connector = sub.conn
    return pins, direction, inverted, connector


def _classify(resource: _Resource) -> str | None:
    """Return 'led', 'button', 'switch', or None."""
    n = resource.name.lower()
    if n == "_stub":
        return None
    if "led" in n:
        return "led"
    if "button" in n or n.startswith("btn"):
        return "button"
    if "switch" in n or n.startswith("sw"):
        return "switch"
    return None


def _to_component(resource: _Resource, kind: str) -> ComponentInfo:
    pins, direction, inverted, connector = _extract_pins(resource)
    return ComponentInfo(
        kind=kind,
        name=resource.name,
        number=resource.number,
        pins=pins,
        direction=direction,
        inverted=inverted,
        connector=connector,  # type: ignore[arg-type]
        attrs=dict(resource.attrs),
    )


def _prettify_class_name(name: str) -> str:
    """Convert 'ArtyA7_35Platform' → 'Arty A7-35'."""
    name = re.sub(r"Platform$", "", name)
    name = name.lstrip("_")
    # Insert space between camelCase boundaries
    name = re.sub(r"([a-z\d])([A-Z])", r"\1 \2", name)
    name = name.replace("_", "-")
    return name


# ═══════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════

def load_board_from_source(source: str, filename: str = "<string>") -> list[BoardDef]:
    """Parse a single board file's source and return a list of BoardDefs."""
    # Strip import statements – we inject everything via namespace
    lines = source.split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if s.startswith(("import ", "from ")):
            cleaned.append("")
        else:
            cleaned.append(line)

    ns = _make_namespace()
    try:
        exec(compile("\n".join(cleaned), filename, "exec"), ns)
    except Exception:
        return []

    all_names: list | None = ns.get("__all__")  # type: ignore[assignment]

    boards = []
    for obj_name, obj in list(ns.items()):
        if not isinstance(obj, type):
            continue
        if obj_name.startswith("_"):
            continue
        if "Test" in obj_name and "Platform" not in obj_name:
            continue
        if all_names and obj_name not in all_names:
            continue

        resources = getattr(obj, "resources", None)
        if not isinstance(resources, list) or not resources:
            continue

        leds, buttons, switches = [], [], []
        for res in resources:
            if not isinstance(res, _Resource):
                continue
            kind = _classify(res)
            if kind == "led":
                leds.append(_to_component(res, "led"))
            elif kind == "button":
                buttons.append(_to_component(res, "button"))
            elif kind == "switch":
                switches.append(_to_component(res, "switch"))

        if not (leds or buttons or switches):
            continue

        vendor = next(
            (getattr(base, "_vendor", "") for base in obj.__mro__
             if getattr(base, "_vendor", "")),
            ""
        )
        default_clk = getattr(obj, "default_clk", None)
        boards.append(BoardDef(
            name=_prettify_class_name(obj_name),
            class_name=obj_name,
            vendor=vendor,
            device=getattr(obj, "device", ""),
            package=getattr(obj, "package", ""),
            clocks=_extract_clocks(resources),
            default_clock_hz=_find_default_clock_hz(resources, default_clk),
            leds=leds,
            buttons=buttons,
            switches=switches,
        ))

    return boards


def discover_boards(boards_dir: str | Path) -> list[BoardDef]:
    """Scan a directory of board .py files and return all BoardDefs."""
    boards_dir = Path(boards_dir)
    if not boards_dir.is_dir():
        return []
    all_boards = []
    for py_file in sorted(boards_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
            all_boards.extend(load_board_from_source(source, str(py_file)))
        except Exception:
            continue
    return all_boards


def get_default_boards_path() -> Path:
    """Path to amaranth_boards/ inside the git submodule."""
    return Path(__file__).parent / "amaranth-boards" / "amaranth_boards"
