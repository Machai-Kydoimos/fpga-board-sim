"""Parser for litex-boards platform files — read, never executed → board dicts.

Mocks the LiteX build-system classes, reads each board ``platform`` file against
that namespace with :func:`upstream_reader.read_module` -- which parses the file
and interprets it, never executing it (U56 decision D-7) -- and extracts LED /
button / switch / clock / 7-seg resources into plain board-definition dicts (the
JSON schema shape).  Self-contained: no ``fpga_sim`` dependency.  Used by
``scripts/sync_litex_boards.py`` and the parser test suite.
"""

import ast
import copy
import math
import re
import sys
from collections.abc import Iterator, Mapping
from typing import Any

from framework_conventions import RoleEntry, build_convention
from led_metadata import color_from_name
from sync_common import ParseOutcome, ProducedBoard, normalize_error
from sync_identity import VERSION_PARAMS
from upstream_reader import InterpretedFunction, ModuleStub, read_module

# ═══════════════════════════════════════════════════════════════════════
#  Mock LiteX build system classes
# ═══════════════════════════════════════════════════════════════════════


class _Pins:
    """Mock of LiteX ``Pins``: any number of whitespace-separated identifier strings.

    Upstream's signature is ``Pins(*identifiers)``; the old mock took one string and
    read a second as ``dir``, so ``Pins("A1", "B2")`` lost a pin and longer calls raised
    (U56 defect 3).
    """

    def __init__(
        self,
        *identifiers: object,
        dir: str = "io",
        conn: object = None,
        assert_width: int | None = None,
    ) -> None:
        self.identifiers = [
            name for item in identifiers if isinstance(item, str) for name in item.split()
        ]
        self.names = self.identifiers
        self.dir = dir
        self.conn = conn


class _IOStandard:
    def __init__(self, name: str = "") -> None:
        self.name = name


class _Subsignal:
    def __init__(self, name: str, *ios: object, **kwargs: object) -> None:
        self.name = name
        self.ios = list(ios)


class _Misc:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class _DiffPairs:
    def __init__(
        self,
        p: str = "",
        n: str = "",
        dir: str = "io",
        conn: object = None,
        assert_width: int | None = None,
    ) -> None:
        self.p = p.split() if isinstance(p, str) else list(p)
        self.n = n.split() if isinstance(n, str) else list(n)
        self.dir = dir


class _Connector:
    def __init__(
        self, name: str = "", number: int = 0, pins: str | dict[str, str] = "", **kwargs: object
    ) -> None:
        self.name = name
        self.number = number
        if isinstance(pins, str):
            self.mapping: dict[str, str] = {}
            for i, p in enumerate(pins.split()):
                if p != "-":
                    self.mapping[str(i)] = p
        elif isinstance(pins, dict):
            self.mapping = {str(k): str(v) for k, v in pins.items()}
        else:
            self.mapping = {}


class _Inverted:
    pass


class _Drive:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class _PlatformInfo:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class _StubMeta(type):
    """Metaclass of a stand-in class: any public class attribute is a stand-in too.

    So ``MachdyneML1.revisions`` reads.  Underscore names raise, so a stand-in never
    answers ``_vendor`` and is never taken for a platform class.
    """

    def __getattr__(cls, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)
        return _Stub()


class _Stub(metaclass=_StubMeta):
    """An inert stand-in for a name we do not model (U56 plan §4.4).

    Callable, any public attribute, indexable, ``+=``-able, and iterates as empty, so
    a file that touches an extension or helper we do not read still yields the
    resources it declares itself.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __call__(self, *args: object, **kwargs: object) -> "_Stub":
        return _Stub()

    def __getattr__(self, name: str) -> "_Stub":
        if name.startswith("_"):
            raise AttributeError(name)
        return _Stub()

    def __getitem__(self, key: object) -> "_Stub":
        return _Stub()

    def __setitem__(self, key: object, value: object) -> None:
        pass

    def __iadd__(self, other: object) -> "_Stub":
        return self

    def __iter__(self) -> Iterator[object]:
        return iter(())


def _stub_class(name: str) -> type:
    """Return a stand-in class named *name* (each imported name gets its own)."""
    return _StubMeta(name, (_Stub,), {})


#: Standard-library modules whose functions board code calls on data it then uses.
#: A stand-in would hand back the wrong data silently, so these are the real, pure
#: functions (U56 plan §4.4, Known growth: ``copy.deepcopy``).
_SAFE_MODULES: dict[str, dict[str, object]] = {
    "copy": {"copy": copy.copy, "deepcopy": copy.deepcopy},
    "math": {
        name: getattr(math, name)
        for name in ("ceil", "floor", "log2", "log10", "sqrt", "pi", "e", "gcd", "isclose")
    },
}


#: Modules whose star imports the mock namespace covers.
_MOCKED_STAR_MODULES = ("litex.build",)


def _unmocked_star_import(source: str) -> bool:
    """Return whether *source* star-imports a module the mocks do not cover (``migen``)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and any(alias.name == "*" for alias in node.names)
        and not (node.module or "").startswith(_MOCKED_STAR_MODULES)
        for node in ast.walk(tree)
    )


class _StarNameError(Exception):
    """A name the file uses after an unmocked ``from x import *``: retry with a stand-in."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def _fresh_namespace(source: str, stand_ins: Mapping[str, object]) -> dict[str, object]:
    ns = _make_litex_namespace()
    _bind_imports(source, ns)
    ns.update({k: v for k, v in stand_ins.items() if k not in ns})
    return ns


def _star_name(exc: BaseException, allow: bool, stand_ins: Mapping[str, object]) -> str | None:
    """Return the missing name to stand in for, when *exc* is a star-imported name."""
    name = getattr(exc, "name", None)
    if isinstance(exc, NameError) and allow and isinstance(name, str) and name not in stand_ins:
        return name
    return None


def _bind_imports(source: str, ns: dict[str, object]) -> None:
    """Bind every name the file imports and the mocks do not provide (U56 §4.4).

    Import lines are blanked before the file is read; this walks the original file's
    syntax tree -- module level and inside functions -- so each imported name still
    means something: a vetted module function, or a stand-in.  ``from x import *`` is
    what the mocks cover.  A name imported nowhere stays undefined, a genuine gap.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return  # the read reports it
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                bound = alias.asname or top
                if bound in ns:
                    continue
                safe = _SAFE_MODULES.get(alias.name if alias.asname else top)
                ns[bound] = ModuleStub(top, **safe) if safe is not None else _stub_class(bound)
        elif isinstance(node, ast.ImportFrom):
            safe = _SAFE_MODULES.get(node.module or "")
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                if bound in ns:
                    continue
                if safe is not None and alias.name in safe:
                    ns[bound] = safe[alias.name]
                else:
                    ns[bound] = _stub_class(bound)


# ═══════════════════════════════════════════════════════════════════════
#  Mock vendor platform base classes
# ═══════════════════════════════════════════════════════════════════════

_PLATFORM_VENDORS: dict[str, str] = {
    "GenericPlatform": "Unknown",
    "Xilinx7SeriesPlatform": "Xilinx",
    "XilinxUSPlatform": "Xilinx",
    "XilinxUSPPlatform": "Xilinx",
    "XilinxSpartan6Platform": "Xilinx",
    "XilinxPlatform": "Xilinx",
    "AlteraPlatform": "Intel",
    "IntelPlatform": "Intel",
    "LatticeECP5Platform": "Lattice",
    "LatticeiCE40Platform": "Lattice",  # upstream's spelling (U56 defect 4)
    "LatticePlatform": "Lattice",
    "MicrosemiPlatform": "Microsemi",
    "AnlogicPlatform": "Anlogic",
    "QuickLogicPlatform": "QuickLogic",
    "LatticeMachXO2Platform": "Lattice",
    "LatticeMachXO3Platform": "Lattice",
    "LatticeMachXO3LPlatform": "Lattice",
    "LatticeCrossLinkNXPlatform": "Lattice",
    "LatticeNexusPlatform": "Lattice",
    "LatticeCertusPro_NXPlatform": "Lattice",
    "GowinPlatform": "Gowin",
    "EfinixPlatform": "Efinix",
    "CologneChipPlatform": "CologneChip",
    "AnarchiPlatform": "Anarchi",
    "OsvvmPlatform": "OSVVM",
}


def _make_mock_platform(name: str, vendor: str) -> type:
    """Create a mock platform class for a given vendor."""

    class MockPlatform:
        _vendor = vendor
        #: Upstream sets toolchain options in constructors; a stand-in absorbs them.
        toolchain = _Stub()

        def __init__(
            self,
            device: object = "",
            io: object = None,
            connectors: object = None,
            **kwargs: object,
        ) -> None:
            self.device = str(device) if device else ""
            self._captured_io: list[tuple[Any, ...]] = (
                list(io) if isinstance(io, (list, tuple)) else []
            )

        def add_resources(self, resources: object) -> None:
            if isinstance(resources, list):
                self._captured_io.extend(resources)

        def add_connectors(self, connectors: object) -> None:
            pass

        def add_extension(self, extension: object, *args: object, **kwargs: object) -> None:
            # LiteX's add_extension(io) extends the platform's I/O just as
            # add_resources does; it used to be a no-op here, which dropped every
            # LED, switch and button a dock or a board variant adds (U56 Phase 2,
            # defect 1).  An extension *object* (litex_boards.extensions' docks and
            # Pmods, at upstream heads) builds its I/O in define_io(platform), or
            # holds it as .io -- both interpreted, never executed.
            io = extension
            if not isinstance(io, (list, tuple)):
                define_io = getattr(extension, "define_io", None)
                io = define_io(self) if callable(define_io) else getattr(extension, "io", None)
            if isinstance(io, (list, tuple)):
                self._captured_io.extend(io)

        def request(self, *args: object, **kwargs: object) -> None:
            pass

        def _noop(self, *args: object, **kwargs: object) -> None:
            return None

        def __getattr__(self, name: str) -> object:
            # Every other platform method (add_platform_command, add_period_constraint,
            # add_connector, lookup_request, ...) is a no-op: none declares I/O.
            if name.startswith("_"):
                raise AttributeError(name)
            return self._noop

    MockPlatform.__name__ = name
    MockPlatform.__qualname__ = name
    MockPlatform._vendor = vendor
    return MockPlatform


# ═══════════════════════════════════════════════════════════════════════
#  Reader namespace
# ═══════════════════════════════════════════════════════════════════════


def _make_litex_namespace() -> dict[str, object]:
    """Build the mock namespace litex board files are read against (no real modules)."""
    ns: dict[str, object] = {
        # generic_platform exports
        "Pins": _Pins,
        "IOStandard": _IOStandard,
        "Subsignal": _Subsignal,
        "Misc": _Misc,
        "DiffPairs": _DiffPairs,
        "Connector": _Connector,
        "Inverted": _Inverted,
        "Drive": _Drive,
        "PlatformInfo": _PlatformInfo,
        "AutoPins": _Pins,
        # Programmer stubs
        **{
            name: type(name, (), {"__init__": lambda self, *a, **kw: None})
            for name in (
                "OpenOCD",
                "USBBlaster",
                "VivadoProgrammer",
                "TinyFpgaBProgrammer",
                "IceStormProgrammer",
                "LatticeProgrammer",
                "EfinixProgrammer",
                "GowinProgrammer",
                "OpenFPGALoader",
                "DFUProg",
                "UJProg",
                "GenericProgrammer",
            )
        },
        # The stand-in base, so the reader trusts every stand-in instance (toolchain, ...).
        "_LitexStub": _Stub,
        # `os` and `subprocess` appear only inside methods the reader never runs.
        # Prevent __main__ guard from running
        "__name__": "_litex_board_loader_exec",
    }

    # Inject mock platform classes
    for name, vendor in _PLATFORM_VENDORS.items():
        ns[name] = _make_mock_platform(name, vendor)

    return ns


# ═══════════════════════════════════════════════════════════════════════
#  IO tuple parsing
# ═══════════════════════════════════════════════════════════════════════


# A resource is a user LED only when "led" appears at a token boundary: at the
# start, or after `_`/`-`/a digit (so `m2led` -- the M.2 status LED -- and `led0`
# both count).  A bare `"led" in name` substring test wrongly swept in `oled*`
# (OLED display buses) and `segled_*` (7-segment display lines) because those have
# a *letter* before "led"; that inflated the LED bank on several boards (U33 Wave 4).
_LED_TOKEN = re.compile(r"(?:^|[_\-0-9])led")


def _classify_resource(name: str) -> str | None:
    """Classify a LiteX resource name into a type."""
    n = name.lower()
    # 7-segment displays declared as scalar `segled_*` resources (older Digilent /
    # Numato naming): `segled_an` are the digit-select anodes, `segled_ca`..`_cg` /
    # `segled_dp` the shared segment lines.  Tested before the LED rule because
    # "segled" contains "led".
    if n.startswith("segled_an"):
        return "seven_seg_ctrl"
    if n.startswith("segled"):
        return "seven_seg"
    if n in ("user_led", "led") or (_LED_TOKEN.search(n) and "ctrl" not in n):
        return "led"
    if n in ("user_btn", "key", "usr_btn", "user_dip_btn", "button_1") or "btn" in n:
        return "button"
    # "switch" only as the leading word: `rf_switches` (the XTRX boards' RF-path switch
    # controls) is no user switch (U56 defect 21) -- the one name upstream writes that
    # the old `"switch" in n` test misread.
    if n in ("user_sw", "sw") or re.match(r"(user_|dip_)*switch", n) or "dip_sw" in n:
        return "switch"
    if n.startswith("clk") or n == "sys_clk" or n == "ext_clk":
        return "clock"
    if n == "seven_seg":
        return "seven_seg"
    if n.startswith("seven_seg_ctrl"):
        return "seven_seg_ctrl"
    return None


def _extract_io_pins(ios: tuple[Any, ...]) -> tuple[list[str], str, str, object]:
    """Extract pins, iostandard, direction, and connector from IO args.

    Returns (pin_names, iostandard, direction, connector).
    """
    pin_names: list[str] = []
    iostandard = ""
    direction = ""
    connector = None

    for item in ios:
        if isinstance(item, _Pins):
            pin_names.extend(item.names)
            if item.dir and item.dir != "io":
                direction = item.dir
            if item.conn:
                connector = item.conn
        elif isinstance(item, _IOStandard):
            iostandard = item.name
        elif isinstance(item, _Subsignal):
            for sub in item.ios:
                if isinstance(sub, _Pins):
                    pin_names.extend(sub.names)
                    if sub.dir and sub.dir != "io":
                        direction = sub.dir
                    if sub.conn:
                        connector = sub.conn
                elif isinstance(sub, _IOStandard):
                    iostandard = sub.name
        elif isinstance(item, _DiffPairs):
            pin_names.extend(item.p)
            if item.dir and item.dir != "io":
                direction = item.dir

    return pin_names, iostandard, direction, connector


def _parse_io_as_component(
    res_name: str, res_num: int, ios: tuple[Any, ...], kind: str
) -> dict[str, Any]:
    """Convert a single _io tuple into a component dict."""
    pin_names, iostandard, direction, connector = _extract_io_pins(ios)

    if not direction:
        direction = "o" if kind == "led" else "i"

    conn_val = None
    if isinstance(connector, tuple) and len(connector) == 2:
        conn_val = list(connector)

    name = res_name
    if kind == "led" and res_name.startswith("user_"):
        name = "led"
    elif kind == "led" and "rgb" in res_name.lower():
        name = "rgb_led"
    elif kind == "button":
        if res_name in ("user_btn", "usr_btn"):
            name = "button"
        elif res_name == "key":
            name = "button"
        elif res_name == "user_dip_btn":
            name = "button"
        elif res_name.startswith("user_btn"):
            suffix = res_name[len("user_btn") :]
            if suffix:
                name = f"button_{suffix}"
            else:
                name = "button"
        elif res_name.startswith("button"):
            name = res_name
        else:
            name = "button"
    elif kind == "switch":
        name = "switch"

    comp: dict[str, Any] = {
        "name": name,
        "raw_name": res_name,
        "number": res_num,
        "pins": pin_names,
        "direction": direction,
        "inverted": False,
        "connector": conn_val,
        "attrs": {"IOSTANDARD": iostandard} if iostandard else {},
    }
    color = color_from_name(name) if kind == "led" else ""
    if color:  # emit only when the name encodes a color (schema forbids "") (U36)
        comp["color"] = color
    return comp


def _parse_clock_info(res_name: str, ios: tuple[Any, ...]) -> dict[str, Any]:
    """Extract clock info from a clock resource tuple."""
    pin_names, _, _, _ = _extract_io_pins(ios)

    freq_hz: float | None = None
    m = re.search(r"(\d+)", res_name)
    if m:
        val = int(m.group(1))
        if val < 1000:
            freq_hz = val * 1e6
        else:
            freq_hz = float(val)

    return {
        "name": res_name,
        "pin": pin_names[0] if pin_names else "",
        "inferred_hz": freq_hz,
    }


def _build_seven_seg_def(
    seg_tuples: list[tuple[Any, ...]], ctrl_tuples: list[tuple[Any, ...]]
) -> dict[str, Any] | None:
    """Build a seven_seg definition from segment and control tuples."""
    if not seg_tuples:
        return None

    has_dp = False
    for seg in seg_tuples:
        seg_name = str(seg[0]).lower()
        pin_names, _, _, _ = _extract_io_pins(tuple(seg[2:]))
        # A single 8-pin bus (`seven_seg` a..g + dp) or a scalar `segled_dp` line
        # both signal the decimal point is present.
        if len(pin_names) == 8 or seg_name.endswith("dp"):
            has_dp = True
            break

    if ctrl_tuples:
        ctrl_pins: list[str] = []
        for _, _, *ios in ctrl_tuples:
            p, _, _, _ = _extract_io_pins(tuple(ios))
            ctrl_pins.extend(p)
        num_digits = max(len(ctrl_pins), 1)
        return {
            "num_digits": num_digits,
            "has_dp": has_dp,
            "is_multiplexed": True,
            "inverted": True,
            "select_inverted": True,
        }

    return {
        "num_digits": len(seg_tuples),
        "has_dp": has_dp,
        "is_multiplexed": False,
        "inverted": False,
        "select_inverted": False,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Framework-derived port conventions (U32)
# ═══════════════════════════════════════════════════════════════════════


def _litex_role_entries(components: list[dict[str, Any]]) -> list[RoleEntry]:
    """Adapt litex component dicts to the shared ``RoleEntry`` shape.

    ``name`` is the normalized net-name (``led`` / ``switch`` / ``button``) used
    to pick the primary group; ``raw_name`` is the litex port name (``user_led`` /
    ``user_sw`` / ``user_btn``) the convention actually advertises.  litex does not
    encode LED/switch polarity in the ``_io`` file, so ``inverted`` is always
    ``False`` here -- an ``_n`` name suffix is the only active-low signal.
    """
    return [
        RoleEntry(
            normalized=str(comp["name"]),
            raw=str(comp.get("raw_name", comp["name"])),
            bit=int(comp["number"]),
            inverted=bool(comp.get("inverted")),
            # An RGB LED's r/g/b subsignals flatten to several pins on one bit --
            # that bit has no single declarable port, so build_bank drops it.
            pins_per_bit=len(comp.get("pins") or []),
        )
        for comp in components
    ]


def _default_clock_name(clocks: list[dict[str, Any]]) -> str | None:
    """Return the platform's default clock net-name (``is_default`` wins, else first)."""
    for clk in clocks:
        if clk.get("is_default"):
            return str(clk["name"])
    return str(clocks[0]["name"]) if clocks else None


def _build_litex_convention(
    clocks: list[dict[str, Any]],
    leds: list[dict[str, Any]],
    buttons: list[dict[str, Any]],
    switches: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Assemble a framework-derived ``port_conventions.litex`` block, or ``None``.

    Advertises the LiteX platform's own port names (``clk100`` / ``user_led`` /
    ``user_sw`` / ``user_btn``), so a design hand-written to those names simulates
    unmodified.  The clk+LEDs floor and the raw-name / polarity rules live in
    :mod:`framework_conventions`, shared with the amaranth parser.
    """
    return build_convention(
        "litex",
        _default_clock_name(clocks),
        _litex_role_entries(leds),
        _litex_role_entries(switches),
        _litex_role_entries(buttons),
        description="LiteX platform port names (auto-derived from the litex-boards _io file)",
    )


# ═══════════════════════════════════════════════════════════════════════
#  Board name / class name derivation
# ═══════════════════════════════════════════════════════════════════════


def _prettify_filename(filename: str) -> str:
    """Convert 'digilent_arty.py' to 'Digilent Arty'.

    Each word's first letter is raised and the rest kept as upstream wrote it:
    ``str.capitalize`` lowered it, turning ``brisbaneSilicon`` into "Brisbanesilicon"
    and ``2I`` into "2i" (P35, U56 Phase 1b).  ``_make_class_name`` keeps the old
    spelling, because a board's ``class_name`` must never change.
    """
    name = filename.replace(".py", "")
    return " ".join(p[:1].upper() + p[1:] for p in name.split("_") if p)


def _make_class_name(filename: str) -> str:
    """Convert 'digilent_arty.py' to 'DigilentArtyPlatform'."""
    name = filename.replace(".py", "")
    parts = name.split("_")
    return "".join(p.capitalize() for p in parts) + "Platform"


# ═══════════════════════════════════════════════════════════════════════
#  Board file parsing
# ═══════════════════════════════════════════════════════════════════════


def _mono_then_rgb(leds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable-partition LEDs into mono, then 3-pin RGB sites (U56 defect 24).

    Sorting every LED by its upstream index interleaved ``user_led`` *n* with ``rgb_led``
    *n*.  This is the partition ``BoardDef.led_channels`` already applies to channels,
    so no ``led(i)`` moves; the order within each group is untouched (a reorder among
    the mono LEDs *would* move ``led(i)``).
    """

    def is_rgb(led: dict[str, Any]) -> bool:
        return led.get("name") == "rgb_led" and len(led.get("pins", [])) == 3

    return [c for c in leds if not is_rgb(c)] + [c for c in leds if is_rgb(c)]


def _version_args(platform_class: type) -> dict[str, Any]:
    """Return the defaults of the constructor's version parameters (plan §4.1)."""
    for klass in platform_class.__mro__:
        init = vars(klass).get("__init__")
        if isinstance(init, InterpretedFunction):
            defaults = init.parameter_defaults()
            return {key: defaults[key] for key in VERSION_PARAMS if key in defaults}
    return {}


def _platform_attr(instance: object, platform_class: type, name: str) -> object:
    """Return *name* as the constructor left it on *instance*, else the class's, else ``None``.

    Never ``getattr(instance, name)`` alone: the mock platform answers every public
    name it lacks with a no-op method, which would read as a clock name.
    """
    attrs = vars(instance)
    if name in attrs:
        return attrs[name]
    return getattr(platform_class, name, None)


def parse_litex_board(source: str, filename: str) -> list[dict[str, Any]]:
    """Read a litex-boards platform file, without executing it, and return board dicts."""
    return [produced.board for produced in read_litex_file(source, filename).boards]


def read_litex_file(
    source: str, filename: str, args: Mapping[str, Any] | None = None
) -> ParseOutcome:
    """Read one platform file, without executing it, into a :class:`ParseOutcome`.

    The board carries its identity (U56 plan §4.1): the platform class and the effective
    values of the constructor's version parameters.  ``args`` builds a recorded
    non-default identity, ``Platform(**args)``, instead of the default construction; a
    constructor that fails then is an ``error``, never the module-level fallback, so the
    sync can report that version as no longer defined.
    """
    lines = source.split("\n")
    cleaned = []
    for line in lines:
        s = line.strip()
        if s.startswith(("import ", "from ")):
            cleaned.append("")
        else:
            cleaned.append(line)

    allow = _unmocked_star_import(source)
    stand_ins: dict[str, object] = {}
    for _attempt in range(32):
        try:
            return _read_once(source, "\n".join(cleaned), filename, args, allow, stand_ins)
        except _StarNameError as missing:
            # A name from `from migen import *` is imported, just not one we mock: stand
            # in for it and read again (reading is cheap and runs nothing).
            stand_ins[missing.name] = _stub_class(missing.name)
    return ParseOutcome(outcome="error", detail="RuntimeError")


def _read_once(
    source: str,
    cleaned: str,
    filename: str,
    args: Mapping[str, Any] | None,
    allow: bool,
    stand_ins: Mapping[str, object],
) -> ParseOutcome:
    """Read the file and build its board once, with the given stand-ins bound."""
    ns = _fresh_namespace(source, stand_ins)
    try:
        read_module(cleaned, filename, ns)
    except Exception as exc:
        name = _star_name(exc, allow, stand_ins)
        if name is not None:
            raise _StarNameError(name) from exc
        # Recorded in the ledger by the sync; said aloud here for a direct caller.
        print(f"  skipped {filename}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return ParseOutcome(outcome="error", detail=normalize_error(exc))

    # Find the Platform class (skip injected mock base classes)
    platform_class = None
    for obj_name, obj in ns.items():
        if not isinstance(obj, type):
            continue
        if obj_name.startswith("_"):
            continue
        if obj_name in _PLATFORM_VENDORS:
            continue
        vendor = ""
        for base in getattr(obj, "__mro__", []):
            v = getattr(base, "_vendor", "")
            if v and v != "Unknown":
                vendor = v
                break
        if vendor:
            platform_class = obj
            break

    if platform_class is None:
        return ParseOutcome(outcome="skipped", detail="not_a_board")
    version = {**_version_args(platform_class), **(args or {})}

    # Instantiate: the constructor runs in the reader, against the permissive mock
    # platform, and hands the base class its device and I/O.  A constructor that still
    # fails is an `error` -- the module-level fallback that used to stand in, with no
    # device, is gone (U56 Phase 1c, defect 6).
    try:
        instance = platform_class(**(args or {}))
    except Exception as exc:
        name = _star_name(exc, allow, stand_ins)
        if name is not None:
            raise _StarNameError(name) from exc
        print(f"  {filename}: Platform() failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return ParseOutcome(outcome="error", detail=normalize_error(exc))
    device = getattr(instance, "device", "")
    # A constructor may set the default clock on the instance -- Red Pitaya picks
    # clk125 or clk122 by board, and the Snickerdoodle derives its period from a
    # class-level frequency -- so read what it left, then the class (U56 Phase 2,
    # defect 13).
    default_clk_name = _platform_attr(instance, platform_class, "default_clk_name")
    default_clk_period = _platform_attr(instance, platform_class, "default_clk_period")
    captured_io: list[tuple[Any, ...]] = list(getattr(instance, "_captured_io", []))
    if not captured_io:
        return ParseOutcome(outcome="skipped", detail="not_a_board")

    # Get vendor from class hierarchy
    vendor = ""
    for base in platform_class.__mro__:
        v = getattr(base, "_vendor", "")
        if v and v != "Unknown":
            vendor = v
            break

    # Parse all IO tuples
    leds: list[dict[str, Any]] = []
    buttons: list[dict[str, Any]] = []
    switches: list[dict[str, Any]] = []
    clock_infos: list[dict[str, Any]] = []
    seg_tuples: list[tuple[Any, ...]] = []
    seg_ctrl_tuples: list[tuple[Any, ...]] = []

    for io_tuple in captured_io:
        if not isinstance(io_tuple, tuple) or len(io_tuple) < 3:
            continue

        res_name = str(io_tuple[0])
        try:
            res_num = int(io_tuple[1])
        except (ValueError, TypeError):
            continue
        ios = io_tuple[2:]

        kind = _classify_resource(res_name)
        if kind == "led":
            leds.append(_parse_io_as_component(res_name, res_num, ios, "led"))
        elif kind == "button":
            buttons.append(_parse_io_as_component(res_name, res_num, ios, "button"))
        elif kind == "switch":
            switches.append(_parse_io_as_component(res_name, res_num, ios, "switch"))
        elif kind == "clock":
            clock_infos.append(_parse_clock_info(res_name, ios))
        elif kind == "seven_seg":
            seg_tuples.append(io_tuple)
        elif kind == "seven_seg_ctrl":
            seg_ctrl_tuples.append(io_tuple)

    if not (leds or buttons or switches):
        return ParseOutcome(outcome="skipped", detail="no_simulatable_io")

    # Calculate clock frequency
    default_clock_hz: float | None = None
    if isinstance(default_clk_period, (int, float)) and default_clk_period > 0:
        default_clock_hz = 1e9 / default_clk_period

    # Build clock list
    clocks: list[dict[str, Any]] = []
    for ci in clock_infos:
        hz = ci.get("inferred_hz")
        is_default = (ci["name"] == default_clk_name) if default_clk_name else False
        if is_default and default_clock_hz:
            hz = default_clock_hz
        if hz:
            entry: dict[str, Any] = {"name": ci["name"], "hz": hz, "pin": ci["pin"]}
            if is_default:
                entry["is_default"] = True
            clocks.append(entry)

    if not clocks and default_clock_hz and default_clk_name:
        clocks.append(
            {
                "name": default_clk_name,
                "hz": default_clock_hz,
                "pin": "",
                "is_default": True,
            }
        )

    # 7-segment
    seven_seg = _build_seven_seg_def(seg_tuples, seg_ctrl_tuples)

    board_name = _prettify_filename(filename)
    class_name = _make_class_name(filename)

    port_conventions = _build_litex_convention(clocks, leds, buttons, switches)
    # `raw_name` exists only to build the convention above; keep it out of the
    # persisted component JSON so the serialized led/btn/sw shape is unchanged.
    for comp in (*leds, *buttons, *switches):
        comp.pop("raw_name", None)

    board: dict[str, Any] = {
        "name": board_name,
        "class_name": class_name,
        "vendor": vendor,
        "device": device,
        "package": "",
        "clocks": clocks,
        "default_clock_hz": default_clock_hz or 12e6,
        # Upstream states no frequency: 12 MHz is our fallback, and says so (U56 D-6).
        **({} if default_clock_hz else {"default_clock_assumed": True}),
        "leds": _mono_then_rgb(sorted(leds, key=lambda c: c["number"])),
        "buttons": sorted(buttons, key=lambda c: c["number"]),
        "switches": sorted(switches, key=lambda c: c["number"]),
        "seven_seg": seven_seg,
    }
    if port_conventions:
        board["port_conventions"] = port_conventions
    produced = ProducedBoard(
        board=board,
        upstream_file=filename,
        upstream_class=platform_class.__name__,
        upstream_args=version,
        default=args is None,
    )
    return ParseOutcome(boards=[produced])
