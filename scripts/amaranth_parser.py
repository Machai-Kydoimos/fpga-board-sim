"""Amaranth board-file parser — turn amaranth-style ``.py`` board files into BoardDefs.

Upstream amaranth-boards files are written against the amaranth build DSL
(``Resource``, ``Pins``, ``Connector``, platform base classes, …).  This module
reads them *without* importing amaranth and without executing them (U56 decision
D-7): :func:`load_board_from_source` blanks their imports and hands the source to
:func:`upstream_reader.read_module`, which parses it and interprets it against the
namespace from :func:`_make_namespace`, where every DSL name resolves to a
lightweight mock (or inert stub) defined here.  The mocks capture just enough to
extract LED / button / switch / 7-seg resources; everything else is stubbed.

This is offline tooling used only by ``scripts/sync_amaranth_boards.py`` and the
parser test suite.  It depends one-way on the :mod:`fpga_sim.board_loader` data
classes (``BoardDef`` / ``ComponentInfo`` / ``SevenSegDef``) and the shared
``_FALLBACK_CLOCK_HZ`` constant — the runtime loader never imports this module, so
the two can evolve independently.
"""

import ast
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from framework_conventions import RoleEntry, build_convention, group_by_name
from led_metadata import color_from_name
from sync_common import ParseOutcome, ProducedBoard, normalize_error
from upstream_reader import ModuleStub, read_module

from fpga_sim.board_loader import (
    _FALLBACK_CLOCK_HZ,
    BoardDef,
    ComponentInfo,
    SevenSegDef,
)

# ═══════════════════════════════════════════════════════════════════════
#  Mock amaranth.build classes (just enough to read board files)
# ═══════════════════════════════════════════════════════════════════════


class _Attrs(dict[str, str]):
    """Mock of amaranth ``Attrs`` — pin attributes (e.g. ``IOStandard``), kept on the resource."""

    def __init__(self, **kwargs: str) -> None:
        super().__init__(**kwargs)


class _Pins:
    """Mock of amaranth ``Pins`` — a whitespace- or list-specified set of pin names."""

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
    """Mock of amaranth ``PinsN`` — like :class:`_Pins` but active-low (``invert=True``)."""

    def __init__(self, names: str | list[str], **kwargs: object) -> None:
        kwargs["invert"] = True
        super().__init__(names, **kwargs)  # type: ignore[arg-type]


class _DiffPairs:
    """Mock of amaranth ``DiffPairs`` — a differential pin pair (p and n)."""

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
    """Mock of amaranth ``Clock`` — a clock-frequency annotation."""

    def __init__(self, freq: float) -> None:
        self.freq = freq


class _Subsignal:
    """Mock of amaranth ``Subsignal`` — a named sub-signal grouping one or more pin sets."""

    def __init__(self, name: str, *ios: object, **kwargs: object) -> None:
        self.name = name
        self.ios = [io for io in ios if io is not None]


class _Connector:
    """Mock of amaranth ``Connector`` — an expansion header's pin-number → pin-name map."""

    def __init__(
        self,
        name: str,
        number: int,
        pins: str | dict[str, str] = "",
        **kwargs: object,
    ) -> None:
        self.name = name
        self.number = number
        self.mapping: dict[str, str]
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
    """Mock of amaranth ``Resource`` — a named board resource with its I/O list and attrs."""

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
        ios: Sequence[object],
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
    pins: str | list[str] | dict[int, str],
    invert: bool = False,
    conn: str | None = None,
    attrs: "_Attrs | None" = None,
    default_name: str,
    dir: str,
) -> list[_Resource]:
    """Expand a pins spec into one :class:`_Resource` per pin (mirrors amaranth's helper)."""
    if isinstance(pins, str):
        pins = pins.split()
    if isinstance(pins, list):
        pins = dict(enumerate(pins))
    resources = []
    for number, pin in pins.items():
        ios: list[_Pins | _Attrs] = [_Pins(pin, dir=dir, invert=invert, conn=conn)]
        if attrs is not None:
            ios.append(attrs)
        resources.append(_Resource.family(*args, number, default_name=default_name, ios=ios))
    return resources


def _led_resources(*args: object, **kwargs: object) -> list[_Resource]:
    """Mock of amaranth ``LEDResources`` — one output resource named ``led`` per pin."""
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
    """Mock of amaranth ``RGBLEDResource`` — a single ``rgb_led`` with r/g/b sub-signals."""
    ios: list[_Subsignal | _Attrs] = [
        _Subsignal("r", _Pins(r, dir="o", invert=invert, conn=conn, assert_width=1)),
        _Subsignal("g", _Pins(g, dir="o", invert=invert, conn=conn, assert_width=1)),
        _Subsignal("b", _Pins(b, dir="o", invert=invert, conn=conn, assert_width=1)),
    ]
    if attrs is not None:
        ios.append(attrs)
    return _Resource.family(*args, default_name="rgb_led", ios=ios)


def _button_resources(*args: object, **kwargs: object) -> list[_Resource]:
    """Mock of amaranth ``ButtonResources`` — one input resource named ``button`` per pin."""
    return _split_resources(*args, **kwargs, default_name="button", dir="i")  # type: ignore[arg-type]


def _switch_resources(*args: object, **kwargs: object) -> list[_Resource]:
    """Mock of amaranth ``SwitchResources`` — one input resource named ``switch`` per pin."""
    return _split_resources(*args, **kwargs, default_name="switch", dir="i")  # type: ignore[arg-type]


def _stub_single(*args: object, **kwargs: object) -> _Resource:
    """Stub for single-resource helpers we don't simulate."""
    return _Resource("_stub", 0)


def _stub_multi(*args: object, **kwargs: object) -> list[_Resource]:
    """Stub for multi-resource helpers we don't simulate."""
    return [_Resource("_stub", 0)]


def _display7seg_resource(
    *args: object,
    a: str,
    b: str,
    c: str,
    d: str,
    e: str,
    f: str,
    g: str,
    dp: str | None = None,
    invert: bool = False,
    conn: str | None = None,
    attrs: "_Attrs | None" = None,
) -> "_Resource":
    """Mock for Display7SegResource — preserves polarity and DP metadata."""
    subsigs: list[_Subsignal | _Attrs] = [
        _Subsignal("a", _Pins(a, dir="o")),
        _Subsignal("b", _Pins(b, dir="o")),
        _Subsignal("c", _Pins(c, dir="o")),
        _Subsignal("d", _Pins(d, dir="o")),
        _Subsignal("e", _Pins(e, dir="o")),
        _Subsignal("f", _Pins(f, dir="o")),
        _Subsignal("g", _Pins(g, dir="o")),
    ]
    if dp is not None:
        subsigs.append(_Subsignal("dp", _Pins(dp, dir="o")))
    if attrs is not None:
        subsigs.append(attrs)
    # args is (number,) or (name, number) — mirrors the real amaranth API
    if len(args) >= 2 and isinstance(args[0], str):
        number = int(args[1])  # type: ignore[call-overload]
    elif args:
        number = int(args[0])  # type: ignore[call-overload]
    else:
        number = 0
    r = _Resource("display_7seg", number, *subsigs)
    r._seg_invert = invert  # type: ignore[attr-defined]
    r._seg_has_dp = dp is not None  # type: ignore[attr-defined]
    return r


# ═══════════════════════════════════════════════════════════════════════
#  Reader namespace
# ═══════════════════════════════════════════════════════════════════════

_PLATFORM_VENDORS: dict[str, str] = {
    "XilinxPlatform": "Xilinx",
    "Xilinx7SeriesPlatform": "Xilinx",
    "XilinxUltraScalePlatform": "Xilinx",
    "IntelPlatform": "Intel",
    "LatticeICE40Platform": "Lattice",
    "LatticeECP5Platform": "Lattice",
    "LatticeMachXO2Platform": "Lattice",
    "LatticeMachXO3LPlatform": "Lattice",
    "QuicklogicPlatform": "QuickLogic",
    "GowinPlatform": "Gowin",
}


def _make_namespace() -> dict[str, object]:
    """Build the namespace an upstream board ``.py`` file is read against.

    Maps every amaranth build-DSL name a board file might reference to a mock or
    stub in this module: the core DSL (``Resource``, ``Pins``, …), the resource
    helpers we actually parse (LEDs / buttons / switches / 7-seg), inert stubs for
    interfaces and memories we don't simulate, a ``unittest`` stub whose only
    member is the ``TestCase`` base seven board files subclass, and a dynamically
    generated platform base class per vendor.  ``__name__`` is set to a sentinel
    so any ``if __name__ == "__main__"`` guard in the board file stays dormant.
    No real module or builtin is in here: the reader supplies its own allowlist.
    """
    ns: dict[str, object] = {
        # Core build DSL
        "Resource": _Resource,
        "Subsignal": _Subsignal,
        "Pins": _Pins,
        "PinsN": _PinsN,
        "DiffPairs": _DiffPairs,
        "DiffPairsN": _DiffPairs,  # the Supercon badge (U56 defect 8)
        "Attrs": _Attrs,
        "Clock": _Clock,
        "Connector": _Connector,
        # User resources (the ones we actually parse)
        "LEDResources": _led_resources,
        "RGBLEDResource": _rgb_led_resource,
        "ButtonResources": _button_resources,
        "SwitchResources": _switch_resources,
        # Display resources
        # ULX3S display is behind an I2C GPIO expander (not direct FPGA pins) so
        # Display7SegResource was correctly omitted for that board by amaranth-boards.
        "Display7SegResource": _display7seg_resource,
        "VGAResource": _stub_single,
        # Interface stubs
        "UARTResource": _stub_single,
        "IrDAResource": _stub_single,
        "SPIResource": _stub_single,
        "I2CResource": _stub_single,
        "DirectUSBResource": _stub_single,
        "ULPIResource": _stub_single,
        "PS2Resource": _stub_single,
        # Memory stubs
        "SPIFlashResources": _stub_multi,
        "SDCardResources": _stub_multi,
        "SRAMResource": _stub_single,
        "SDRAMResource": _stub_single,
        "NORFlashResources": _stub_multi,
        "DDR3Resource": _stub_single,
        "DDR4Resource": _stub_single,  # RFSoC 4x2 (U56 defect 8)
        # Seven board files define `class TestCase(unittest.TestCase)`; the class is
        # skipped below, so its base only has to exist.  `os` and `subprocess` appear
        # only inside programmer methods the reader never runs.
        "unittest": ModuleStub("unittest", TestCase=type("TestCase", (), {})),
        # Prevent __main__ guard from running
        "__name__": "_board_loader_exec",
    }
    for name, vendor in _PLATFORM_VENDORS.items():
        ns[name] = type(
            name,
            (),
            {
                "resources": [],
                "connectors": [],
                "_vendor": vendor,
            },
        )
    return ns


# ═══════════════════════════════════════════════════════════════════════
#  Clock extraction
# ═══════════════════════════════════════════════════════════════════════


def _extract_clocks(resources: list[_Resource]) -> list[float]:
    """Return sorted unique clock frequencies (Hz) from the resource list."""
    seen: set[float] = set()
    for res in resources:
        for io in res.ios:
            if isinstance(io, _Clock):
                seen.add(io.freq)
    return sorted(seen)


#: Amaranth's ``default_clk_constraint`` for each on-chip oscillator a ``default_clk`` can
#: name instead of a ``Clock`` resource (``amaranth/vendor/_lattice.py``,
#: ``_siliconblue.py``, ``_altera.py``, ``_quicklogic.py``, ``_gowin.py``), reading the
#: parameters the board class itself sets (U56 defect 22).  Hz.
_OSCILLATOR_HZ: dict[str, Callable[[Any], float]] = {
    "OSCG": lambda cls: 310e6 / cls.oscg_div,  # ECP5
    "OSCH": lambda cls: cls.osch_frequency * 1e6,  # MachXO2/3L
    "OSCA": lambda cls: 450e6 / cls.osca_div,  # Nexus
    "SB_HFOSC": lambda cls: 48e6 / 2**cls.hfosc_div,  # iCE40
    "SB_LFOSC": lambda cls: 10e3,
    "cyclonev_oscillator": lambda cls: 100e6,
    "sys_clk0": lambda cls: cls.osc_freq / cls.osc_div,  # EOS S3
    "OSC": lambda cls: cls.osc_frequency,  # Gowin, in Hz
}


def _find_default_clock_hz(
    resources: list[_Resource], default_clk: str | None, cls: type | None = None
) -> float | None:
    """Return the default clock in Hz: its ``Clock`` resource, else its on-chip oscillator.

    ``None`` when upstream states no frequency -- a ``default_clk`` that names
    neither, or an oscillator whose parameters the class does not set.  The board
    then runs at ``_FALLBACK_CLOCK_HZ``, marked as assumed (U56 D-6).
    """
    if default_clk:
        for res in resources:
            if res.name == default_clk:
                for io in res.ios:
                    if isinstance(io, _Clock):
                        return float(io.freq)
        rule = _OSCILLATOR_HZ.get(default_clk)
        if rule is not None and cls is not None:
            try:
                return float(rule(cls))
            except (AttributeError, TypeError, ValueError, ZeroDivisionError):
                pass
    return None


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


# "led" only counts as a user LED at a token boundary: start, or after `_`/`-`/a
# digit -- so `m2led` (the M.2 status LED on litefury/nitefury) and `led0` both
# count, while a *letter* before "led" (`oled*` OLED buses) does not.  A bare
# substring test wrongly classified `oled*` as LEDs and inflated the LED bank
# (U33 Wave 4).  amaranth 7-seg uses `display_7seg` names (handled above), so
# there is no `segled_*` case here.
_LED_TOKEN = re.compile(r"(?:^|[_\-0-9])led")


def _classify(resource: _Resource) -> str | None:
    """Return 'led', 'button', 'switch', or None."""
    n = resource.name.lower()
    if n == "_stub" or n.startswith("display_7seg"):
        return None
    if _LED_TOKEN.search(n):
        return "led"
    if "button" in n or n.startswith("btn"):
        return "button"
    # "sw"/"switch" as a whole word: `swd` (QuickFeather's 2-pin debug port) is no switch
    # (U56 defect 9) -- the one name upstream writes that `startswith("sw")` misread.
    if re.search(r"(?:^|[_\-0-9])(?:sw|switch|switches)(?:$|[_\-0-9])", n):
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
        attrs={k: v for k, v in resource.attrs.items() if not callable(v)},
        color=color_from_name(resource.name) if kind == "led" else "",
    )


def _upstream_order(components: list[ComponentInfo]) -> list[ComponentInfo]:
    """Group components by resource name, in number order (U56 Phase 2).

    Declaration order alone put the Nexys 4 DDR's switches 8 and 9 after 15.
    """
    return group_by_name(components, lambda c: c.name, lambda c: c.number)


def _coalesce_rgb_trio(leds: list[ComponentInfo]) -> list[ComponentInfo]:
    """Fold a scalar ``led_r``/``led_g``/``led_b`` trio into one 3-pin ``rgb_led`` (U36).

    A few amaranth boards (UPduino v1, iCESugar, iCE40-UP5K-B-EVN) declare a
    single RGB LED as three separate single-pin ``led_r`` / ``led_g`` / ``led_b``
    resources rather than an ``RGBLEDResource``.  Downstream RGB handling (U37)
    keys on a 3-pin ``rgb_led``, so merge the trio into one component in place of
    its red channel (mono LEDs keep their spot ahead of it).

    Fires only when the *only* color-named LEDs are exactly one each of red,
    green, and blue, every one a single pin.  A fourth discrete color (Black
    Ice's ``led_o``) or a missing blue (iCEBreaker's red+green pair) leaves the
    bank untouched -- those are genuinely discrete single-color LEDs, colored
    individually by the name heuristic instead.
    """
    by_color: dict[str, list[ComponentInfo]] = {}
    for c in leds:
        col = color_from_name(c.name)
        if col:
            by_color.setdefault(col, []).append(c)
    if set(by_color) != {"red", "green", "blue"} or any(
        len(v) != 1 or len(v[0].pins) != 1 for v in by_color.values()
    ):
        return leds

    r, g, b = by_color["red"][0], by_color["green"][0], by_color["blue"][0]
    rgb = ComponentInfo(
        kind="led",
        name="rgb_led",
        number=0,
        pins=[r.pins[0], g.pins[0], b.pins[0]],
        direction="o",
        inverted=r.inverted,  # one physical LED: the trio shares polarity
        attrs=dict(r.attrs),
    )
    out: list[ComponentInfo] = []
    for c in leds:
        if c is r:
            out.append(rgb)
        elif c is g or c is b:
            continue
        else:
            out.append(c)
    return out


def _amaranth_role_entries(components: list[ComponentInfo]) -> list[RoleEntry]:
    """Adapt amaranth ``ComponentInfo`` to the shared ``RoleEntry`` shape.

    amaranth's resource names are already the framework's own port names (``led`` /
    ``button`` / ``switch`` / ``rgb_led``), so ``raw`` and ``normalized`` are the
    same here -- unlike litex, whose ``user_led`` normalizes to ``led``.  Polarity
    comes straight from ``inverted`` (an amaranth ``PinsN`` pin).
    """
    return [
        # An RGBLEDResource's r/g/b subsignals flatten to several pins on one bit;
        # that bit has no single declarable port, so build_bank drops it.
        RoleEntry(
            normalized=c.name,
            raw=c.name,
            bit=c.number,
            inverted=c.inverted,
            pins_per_bit=len(c.pins),
        )
        for c in components
    ]


def _build_amaranth_convention(
    default_clk: object,
    leds: list[ComponentInfo],
    buttons: list[ComponentInfo],
    switches: list[ComponentInfo],
) -> dict[str, object]:
    """Assemble a framework-derived ``port_conventions.amaranth`` block, or ``{}``.

    Advertises the amaranth board's own port names (its ``default_clk`` resource
    plus ``led`` / ``switch`` / ``button``), so a design hand-written to those
    names simulates unmodified.  The clk+LEDs floor and the raw-name / polarity
    rules live in :mod:`framework_conventions`, shared with the litex parser.
    """
    desc = "amaranth-boards platform port names (auto-derived from the board .py file)"
    return (
        build_convention(
            "amaranth",
            default_clk if isinstance(default_clk, str) else None,
            _amaranth_role_entries(leds),
            _amaranth_role_entries(switches),
            _amaranth_role_entries(buttons),
            description=desc,
        )
        or {}
    )


def _extract_sevenseg(resources: list[_Resource]) -> "SevenSegDef | None":
    """Return a SevenSegDef if any display_7seg resources are present, else None."""
    seg_resources = [r for r in resources if isinstance(r, _Resource) and r.name == "display_7seg"]
    if not seg_resources:
        return None

    # Any resource whose name starts with "display_7seg_" is the companion.
    # Prefix-based so future boards (e.g. "display_7seg_sel") are auto-detected.
    ctrl_resource = next(
        (r for r in resources if isinstance(r, _Resource) and r.name.startswith("display_7seg_")),
        None,
    )

    # Check inversion at both resource level (_seg_invert) and pin level (PinsN).
    res_level_inv = any(getattr(r, "_seg_invert", False) for r in seg_resources)
    _, _, pin_level_inv, _ = _extract_pins(seg_resources[0])
    inverted = res_level_inv or pin_level_inv

    has_dp = any(getattr(r, "_seg_has_dp", False) for r in seg_resources)

    if ctrl_resource is not None:
        ctrl_pins, _, ctrl_inv, _ = _extract_pins(ctrl_resource)
        return SevenSegDef(
            num_digits=max(1, len(ctrl_pins)),
            has_dp=has_dp,
            is_multiplexed=True,
            inverted=inverted,
            select_inverted=ctrl_inv,
        )
    return SevenSegDef(
        num_digits=len(seg_resources),
        has_dp=has_dp,
        is_multiplexed=False,
        inverted=inverted,
        select_inverted=False,
    )


def _prettify_class_name(name: str) -> str:
    """Convert 'ArtyA7_35Platform' → 'Arty A7-35' (P35, U56 Phase 1b).

    A capital after a lowercase letter starts a word (``ArtyA7`` → ``Arty A7``,
    ``MachXO2`` → ``Mach XO2``) unless it is a lone trailing capital (``SoC`` stays
    whole). A capital after a digit starts a word only when another letter follows
    (``Nexys4DDR`` → ``Nexys4 DDR``, ``DE10Lite`` → ``DE10 Lite``): a single trailing
    letter belongs to a part number (``AX7325B``, ``ULX3S``, ``07S``, ``5A75B``).
    Leading and trailing underscores are dropped, so no name ends in a hyphen
    (``ULX3S_12F_`` → ``ULX3S-12F``); the others become hyphens.  Vendor styling no
    rule can derive (``DE0-CV``, ``iCEstick``) stays in ``board_loader``'s overrides.
    """
    name = re.sub(r"Platform$", "", name).strip("_")
    name = re.sub(r"(?<=[a-z])(?=[A-Z])(?![A-Z](?:_|$))", " ", name)
    name = re.sub(r"(?<=\d)(?=[A-Z][A-Za-z])", " ", name)
    return name.replace("_", "-")


# ═══════════════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════════════


def load_board_from_source(
    source: str, filename: str = "<string>", siblings: Mapping[str, str] | None = None
) -> list[BoardDef]:
    """Read a single board file's source, without executing it, and return its BoardDefs."""
    try:
        boards, _ = _read_boards(source, filename, siblings)
    except Exception as exc:
        print(f"  skipped {filename}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []
    return boards


def read_amaranth_file(
    source: str, filename: str, siblings: Mapping[str, str] | None = None
) -> ParseOutcome:
    """Read one board file, without executing it, into a :class:`ParseOutcome`.

    Each board's identity (U56 plan §4.1) is its upstream class; Amaranth boards take no
    version arguments.  A file whose classes declare resources but none we simulate is
    ``no_simulatable_io``; one with no such class is ``not_a_board``.  ``siblings`` is the
    archive's other board files, for a class imported from one of them.
    """
    try:
        boards, had_resources = _read_boards(source, filename, siblings)
    except Exception as exc:
        # Recorded in the ledger by the sync; said aloud here for a direct caller.
        print(f"  skipped {filename}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return ParseOutcome(outcome="error", detail=normalize_error(exc))
    if not boards:
        detail = "no_simulatable_io" if had_resources else "not_a_board"
        return ParseOutcome(outcome="skipped", detail=detail)
    return ParseOutcome(
        boards=[
            ProducedBoard(
                board=json.loads(board.to_json()),
                upstream_file=filename,
                upstream_class=board.class_name,
            )
            for board in boards
        ]
    )


def _blank_imports(source: str) -> str:
    """Blank every import line: the namespace and :func:`_bind_siblings` stand in for them."""
    return "\n".join(
        "" if line.strip().startswith(("import ", "from ")) else line for line in source.split("\n")
    )


def _bind_siblings(
    source: str, ns: dict[str, object], siblings: Mapping[str, str], seen: frozenset[str]
) -> set[str]:
    """Bind the names this file imports from another board file in the archive (U56 §4.4).

    ``from .upduino_v1 import UpduinoV1Platform`` reads ``upduino_v1.py`` -- with the same
    reader, so it is never executed either -- and binds the class.  Cycle-guarded by
    *seen*.  Returns the names bound, which are never boards of *this* file.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        module = node.module or ""
        if node.level == 0 and not module.startswith("amaranth_boards."):
            continue
        sibling = f"{module.removeprefix('amaranth_boards.').split('.')[-1]}.py" if module else ""
        if sibling not in siblings or sibling in seen:
            continue
        sibling_ns = _make_namespace()
        _bind_siblings(siblings[sibling], sibling_ns, siblings, seen | {sibling})
        try:
            read_module(_blank_imports(siblings[sibling]), sibling, sibling_ns)
        except Exception:
            continue  # its own read reports it, as that file's ledger outcome
        for alias in node.names:
            wanted = (
                [k for k, v in sibling_ns.items() if isinstance(v, type) and not k.startswith("_")]
                if alias.name == "*"
                else [alias.name]
            )
            for key in wanted:
                name = key if alias.name == "*" else (alias.asname or key)
                if key in sibling_ns and name not in ns:
                    ns[name] = sibling_ns[key]
                    bound.add(name)
    return bound


def _read_boards(
    source: str, filename: str, siblings: Mapping[str, str] | None = None
) -> tuple[list[BoardDef], bool]:
    """Read *source*; return its boards and whether any class declared resources.

    Raises whatever the read raises (a ``SyntaxError``, the reader's
    ``UnsupportedConstructError``, a ``NameError`` for a name the mocks lack, ...).
    """
    ns = _make_namespace()
    imported = _bind_siblings(source, ns, siblings or {}, frozenset({filename}))
    read_module(_blank_imports(source), filename, ns)

    all_names: list[str] | None = ns.get("__all__")  # type: ignore[assignment]

    boards = []
    had_resources = False
    for obj_name, obj in list(ns.items()):
        if not isinstance(obj, type):
            continue
        if obj_name.startswith("_") or obj_name in imported:
            continue
        if "Test" in obj_name and "Platform" not in obj_name:
            continue
        if all_names and obj_name not in all_names:
            continue

        resources = getattr(obj, "resources", None)
        if not isinstance(resources, list) or not resources:
            continue
        had_resources = True

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

        leds = _upstream_order(_coalesce_rgb_trio(leds))
        buttons = _upstream_order(buttons)
        switches = _upstream_order(switches)
        seven_seg = _extract_sevenseg(resources)

        if not (leds or buttons or switches):
            continue

        vendor = next(
            (getattr(base, "_vendor", "") for base in obj.__mro__ if getattr(base, "_vendor", "")),
            "",
        )
        default_clk = getattr(obj, "default_clk", None)
        clock_hz = _find_default_clock_hz(resources, default_clk, obj)
        boards.append(
            BoardDef(
                name=_prettify_class_name(obj_name),
                class_name=obj_name,
                vendor=vendor,
                device=getattr(obj, "device", "") or getattr(obj, "part", ""),
                package=getattr(obj, "package", ""),
                clocks=_extract_clocks(resources),
                default_clock_hz=_FALLBACK_CLOCK_HZ if clock_hz is None else clock_hz,
                default_clock_assumed=clock_hz is None,
                leds=leds,
                buttons=buttons,
                switches=switches,
                seven_seg=seven_seg,
                port_conventions=_build_amaranth_convention(default_clk, leds, buttons, switches),
            )
        )

    return boards, had_resources
