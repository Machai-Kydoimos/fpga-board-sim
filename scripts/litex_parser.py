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

from framework_conventions import (
    LedView,
    RoleEntry,
    build_convention,
    group_by_name,
    multi_pin_shape,
    plan_led_aliases,
)
from led_metadata import color_from_name
from sync_common import ParseOutcome, ProducedBoard, normalize_error
from sync_identity import VERSION_PARAMS
from upstream_reader import InterpretedFunction, ModuleStub, UpstreamValue, read_module

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
        self.constraints = self.ios  # upstream's attribute name, which extension code reads


class _Misc:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass


class _Extension:
    """Mock of LiteX's ``litex.build.extension.Extension`` (U56 Phase 4).

    Hardware plugged on a host's connectors ("slots"): a Pmod, a dock, a daughterboard.
    It mirrors upstream (``litex/build/extension.py`` at ``57dc334``): slots bind to host
    connectors positionally or by name, and ``get_io`` is ``define_io`` with every
    ``"slot:pin"`` remapped to ``"connector:pin"``, plus the number offset, renames and
    misc constraints.  The subclasses are upstream's ``litex_boards.extensions``, read by
    the reader, so their ``define_io`` is interpreted, never executed.  Upstream raises
    on a bad binding; so does this, and the reader reports it as the file's error.
    """

    slots: dict[str, object] = {"default": None}
    connector_type: object = None

    def __init__(
        self,
        *args: object,
        number: int | None = None,
        name: object = None,
        iostandard: object = None,
        misc: object = None,
        **bindings: object,
    ) -> None:
        slots = list(self.slots)
        if len(args) > len(slots):
            raise ValueError("too many connectors for the extension's slots")
        self.bindings = dict(self.slots)
        for slot, conn in zip(slots, args, strict=False):
            self.bindings[slot] = conn
        for slot, conn in bindings.items():
            if slot not in self.slots:
                raise ValueError(f"unknown slot {slot!r}")
            self.bindings[slot] = conn
        for slot, conn in self.bindings.items():
            if conn is None:
                raise ValueError(f"no connector bound to slot {slot!r}")
        self.number = number
        self.name = name
        self.misc = [] if misc is None else list(misc) if isinstance(misc, list | tuple) else [misc]
        self._iostandard = _IOStandard(iostandard) if isinstance(iostandard, str) else iostandard

    def iostandard(self, platform: object) -> list[object]:
        if self._iostandard is not None:
            return [self._iostandard]
        return _io_attr(platform, "iostandard_3v3")

    # Upstream's are staticmethods; classmethods behave the same for a caller and are
    # bound to our own class, which is what lets the reader call them.
    @classmethod
    def pullup(cls, platform: object) -> list[object]:
        return _io_attr(platform, "pullup")

    @classmethod
    def slew_fast(cls, platform: object) -> list[object]:
        return _io_attr(platform, "slew_fast")

    def define_io(self, platform: object) -> list[object]:
        return []

    def define_connectors(self, platform: object) -> list[object]:
        return []

    def get_io(self, platform: object) -> list[tuple[object, ...]]:
        resources = self.define_io(platform)
        if not isinstance(resources, list | tuple):
            return []
        names = self._get_names(resources)
        io: list[tuple[object, ...]] = []
        for resource in resources:
            if not isinstance(resource, tuple) or len(resource) < 2:
                continue
            name, number, *elements = resource
            if self.number is not None and isinstance(number, int):
                number += self.number
            remapped = [self._remap_constraint(e) for e in elements]
            io.append((names.get(name, name), number, *remapped, *self.misc))
        return io

    def get_connectors(self, platform: object) -> list[object]:
        return []  # connectors carry no LED, switch or button

    def _get_names(self, resources: list[object] | tuple[object, ...]) -> dict[object, object]:
        if self.name is None:
            return {}
        if isinstance(self.name, dict):
            return dict(self.name)
        found = sorted({r[0] for r in resources if isinstance(r, tuple) and r})
        if len(found) != 1:
            raise ValueError("a string name needs a single resource name; use a dict")
        return {found[0]: self.name}

    def _remap_identifier(self, identifier: object) -> object:
        if not isinstance(identifier, str) or ":" not in identifier:
            return identifier
        conn, pin = identifier.split(":", 1)
        if conn in self.bindings:
            return f"{self.bindings[conn]}:{pin}"
        return identifier

    def _remap_constraint(self, constraint: object) -> object:
        if isinstance(constraint, _Pins):
            return _Pins(" ".join(str(self._remap_identifier(i)) for i in constraint.identifiers))
        if isinstance(constraint, _Subsignal):
            return _Subsignal(constraint.name, *[self._remap_constraint(c) for c in constraint.ios])
        return constraint


class _IOExtension(_Extension):
    """Mock of LiteX's ``IOExtension``: an extension built from static I/O lists."""

    def __init__(
        self,
        *args: object,
        io: object = (),
        connectors: object = (),
        slots: dict[str, object] | None = None,
        **kwargs: UpstreamValue,
    ) -> None:
        if slots is not None:
            self.slots = slots
        self._io = list(io) if isinstance(io, list | tuple) else []
        self._connectors = list(connectors) if isinstance(connectors, list | tuple) else []
        _Extension.__init__(self, *args, **kwargs)

    def define_io(self, platform: object) -> list[object]:
        return self._io

    def define_connectors(self, platform: object) -> list[object]:
        return self._connectors


def _io_attr(platform: object, name: str) -> list[object]:
    """``platform.get_io_attr(name)`` as a list: vendor IO attributes carry no I/O for us."""
    get = getattr(platform, "get_io_attr", None)
    attr = get(name) if callable(get) else None
    return list(attr) if isinstance(attr, list | tuple) else []


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


def _fresh_namespace(
    source: str,
    stand_ins: Mapping[str, object],
    modules: Mapping[str, str] | None = None,
    reading: frozenset[str] = frozenset(),
) -> dict[str, object]:
    ns = _make_litex_namespace()
    _bind_imports(source, ns, modules, reading)
    ns.update({k: v for k, v in stand_ins.items() if k not in ns})
    return ns


def _blank_import_lines(source: str) -> str:
    """Return *source* with each import line blanked, so line numbers still match."""
    return "\n".join(
        "" if line.strip().startswith(("import ", "from ")) else line for line in source.split("\n")
    )


def _read_module(
    name: str, modules: Mapping[str, str], reading: frozenset[str]
) -> dict[str, object] | None:
    """Read upstream module *name* from the archive, never executing it (U56 Phase 4).

    For ``litex_boards.extensions.*`` and its helpers: an extension class must be a real
    interpreted class for ``add_extension`` to get its I/O, where a stand-in has none.
    The module is read like a board file -- its own imports bound the same way, so the
    read is recursive -- and freshly for each board file, so one board's reading never
    leaks into another's.  ``None`` for a module already being read (an import cycle):
    its names stay stand-ins.  A module that cannot be read fails the board file that
    imports it, as a failing import would upstream.
    """
    if name in reading:
        return None
    source = modules[name]
    allow = _unmocked_star_import(source)
    stand_ins: dict[str, object] = {}
    for _attempt in range(32):
        ns = _fresh_namespace(source, stand_ins, modules, reading | {name})
        try:
            return read_module(_blank_import_lines(source), name.replace(".", "/") + ".py", ns)
        except Exception as exc:
            missing = _star_name(exc, allow, stand_ins)
            if missing is None:
                raise
            stand_ins[missing] = _stub_class(missing)
    raise RuntimeError(f"{name}: too many star-imported names")


def _star_name(exc: BaseException, allow: bool, stand_ins: Mapping[str, object]) -> str | None:
    """Return the missing name to stand in for, when *exc* is a star-imported name."""
    name = getattr(exc, "name", None)
    if isinstance(exc, NameError) and allow and isinstance(name, str) and name not in stand_ins:
        return name
    return None


def _bind_imports(
    source: str,
    ns: dict[str, object],
    modules: Mapping[str, str] | None = None,
    reading: frozenset[str] = frozenset(),
) -> None:
    """Bind every name the file imports and the mocks do not provide (U56 §4.4).

    Import lines are blanked before the file is read; this walks the original file's
    syntax tree -- module level and inside functions -- so each imported name still
    means something: a name from an upstream module in *modules*, read by
    :func:`_read_module`; a vetted module function; or a stand-in.  ``from x import *``
    is what the mocks cover.  A name imported nowhere stays undefined, a genuine gap.
    """
    known = modules or {}
    read: dict[str, dict[str, object] | None] = {}
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
            module = node.module or ""
            safe = _SAFE_MODULES.get(module)
            if module in known and module not in read:
                read[module] = _read_module(module, known, reading)
            upstream = read.get(module)
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                if bound in ns:
                    continue
                if upstream is not None and alias.name in upstream:
                    ns[bound] = upstream[alias.name]
                elif safe is not None and alias.name in safe:
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

        def add_extension(self, io: object, *args: object, **kwargs: object) -> None:
            # LiteX's add_extension(io) extends the platform's I/O just as
            # add_resources does; it used to be a no-op here, which dropped every
            # LED, switch and button a dock or a board variant adds (U56 Phase 2,
            # defect 1).  Like LiteX's, it asks an extension *object* (upstream's
            # litex_boards.extensions, at heads) for get_io(platform), its I/O with
            # slot pins remapped onto the host's connectors -- interpreted, never
            # executed.
            get_io = getattr(io, "get_io", None)
            if not isinstance(io, (list, tuple)) and callable(get_io):
                io = get_io(self)
            if isinstance(io, (list, tuple)):
                self._captured_io.extend(io)

        def request(self, *args: object, **kwargs: object) -> None:
            pass

        @classmethod
        def get_io_attr(cls, name: str) -> list[object]:
            # Upstream returns a vendor's IOStandard/pull-up/slew constraints; none of
            # them carries I/O, so an extension's resources get none (U56 Phase 4).
            # A classmethod, as upstream's is: shims call it on the platform class.
            return []

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
        # litex.build.extension (U56 Phase 4): upstream's extension classes derive from these.
        "Extension": _Extension,
        "IOExtension": _IOExtension,
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
    # A DIP switch is a switch, though LiteX names it `user_dip_btn` (U56 D-2, Phase 5):
    # upstream's own name says "dip", and Amaranth declares the same Versa parts as
    # switches.  Tested before "btn", which the name also contains.
    if "dip" in n:
        return "switch"
    if n in ("user_btn", "key", "usr_btn", "button_1") or "btn" in n:
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


#: Multiplexed resources whose shape and name do not say so; upstream's own words do
#: (U56 Phase 5, D-3).  Each stays one component, as before, and the ledger lists it.
_MULTIPLEXED: dict[tuple[str, str, int], str] = {
    # Upstream's comment: "Cathodes via FET".  `led` 0, "Anodes", splits into 11 LEDs,
    # as the Amaranth twin (supercon19badge) declares them.
    ("hackaday_hadbadge.py", "led", 1): "the cathodes of an LED matrix",
    # The target drives it with one constant, 0b010 ("Blue"): the color of all seven
    # user LEDs, which the Amaranth twin declares together as `rgb_leds_muxed`.
    ("gsd_butterstick.py", "user_led_color", 0): "the color lines of the seven user LEDs",
}


def _resource_components(
    filename: str, res_name: str, res_num: int, ios: tuple[Any, ...], kind: str
) -> tuple[list[dict[str, Any]], str]:
    """Turn one resource into its components; say why when its shape is unsupported.

    A resource of one pin is one component, as always.  One of several pins follows
    :func:`framework_conventions.multi_pin_shape` (U56 Phase 5, D-3): one RGB site, in
    r, g, b order; one component per pin, marked ``_split`` and numbered later by
    :func:`_number_split_groups`; or, for a bus or a multiplexed array, one component
    as before, with a note for the ledger.
    """
    comp = _parse_io_as_component(res_name, res_num, ios, kind)
    if len(comp["pins"]) <= 1:
        return [comp], ""
    subsignals = [item for item in ios if isinstance(item, _Subsignal)]
    sub_pins = {
        sub.name: [n for p in sub.ios if isinstance(p, _Pins) for n in p.names]
        for sub in subsignals
    }
    known = _MULTIPLEXED.get((filename, res_name, res_num))
    shape = (
        "unsupported"
        if known
        else multi_pin_shape([(n, len(p)) for n, p in sub_pins.items()], comp["direction"])
    )
    if shape == "unsupported":
        why = known or (
            f"sub-signals {', '.join(sub_pins)}"
            if all(len(p) == 1 for p in sub_pins.values())
            else "a sub-signal of several pins"
        )
        return [comp], f"unsupported_shape: {res_name} {res_num} ({why})"
    if shape == "rgb":
        pins = {name.lower(): p[0] for name, p in sub_pins.items()}
        comp["name"] = "rgb_led"
        comp["pins"] = [pins["r"], pins["g"], pins["b"]]
        comp.pop("color", None)
        return [comp], ""
    parts = []
    for k, pin in enumerate(comp["pins"]):
        part = dict(comp, pins=[pin], attrs=dict(comp["attrs"]), _split=True, _order=(res_num, k))
        if comp["connector"] is not None:
            part["connector"] = list(comp["connector"])
        parts.append(part)
    return parts, ""


def _number_split_groups(components: list[dict[str, Any]]) -> None:
    """Renumber a split resource's components after the labels already in use (D-3).

    Upstream numbers the resource, not its pins, so these numbers are ours.  They
    run in upstream's order, after the highest number another port name shows under
    the same label: the XTRX's `user_led2` pins become LED1-LED3 after `user_led`'s
    LED0, instead of three more LED0-LED2.  A port name with a split numbers its
    other resources in the same run (the Hadbadge's cathodes become LED11).
    """
    split = [c["raw_name"] for c in components if c.get("_split")]
    names = list(dict.fromkeys(split))
    if not names:
        return
    last: dict[str, int] = {}
    for comp in components:
        if comp["raw_name"] not in names:
            last[comp["name"]] = max(last.get(comp["name"], -1), int(comp["number"]))
    for raw in names:
        group = [c for c in components if c["raw_name"] == raw]
        group.sort(key=lambda c: c.get("_order", (int(c["number"]), 0)))
        for comp in group:
            number = last.get(comp["name"], -1) + 1
            comp["number"] = number
            last[comp["name"]] = number


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
            split=bool(comp.get("_split")),  # never the primary bank (D-3)
            channel=comp.get("_channel"),  # the boundary channel it reaches (Phase 6)
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


def _upstream_order(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group components by their LiteX port name, in number order (U56 Phase 2).

    Keyed on ``raw_name`` (``user_led``), not the display name (``led``): two port
    names can share a display name, as the OCP TAP Timecard's ``user_led`` and
    ``led`` do.
    """
    return group_by_name(components, lambda c: str(c["raw_name"]), lambda c: int(c["number"]))


def _is_rgb_site(led: dict[str, Any]) -> bool:
    """Whether *led* is a 3-pin RGB site (``BoardDef.is_rgb``'s rule)."""
    return led.get("name") == "rgb_led" and len(led.get("pins", [])) == 3


def _merge_led_aliases(
    leds: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Fold the LED entries upstream lists under another name into one LED (D-1).

    Upstream's own pin assignment decides (:func:`framework_conventions.plan_led_aliases`):
    the OrangeCrab's ``user_led`` 0-2 are its ``rgb_led``'s r, g and b, so the board
    draws one RGB LED, not three LEDs beside it.  The first-declared entry stays the
    LED and lists the others in ``aliases``; a name that carries a color colors it.
    Returns the LEDs, the folded entries (each still a native port, so the
    convention builder sees it, with ``_target`` and ``_offset`` saying where it
    lands) and an ``alias_overlap`` note for any other kind of shared pin.
    """
    plan, overlaps = plan_led_aliases(
        [LedView(tuple(led["pins"]), _is_rgb_site(led)) for led in leds]
    )
    for i in sorted(plan):
        target, offset = plan[i]
        alias, primary = leds[i], leds[target]
        record: dict[str, Any] = {"name": alias["raw_name"], "number": alias["number"]}
        if offset is not None:
            record["channel"] = "rgb"[offset]
        primary.setdefault("aliases", []).append(record)
        color = color_from_name(alias["raw_name"]) or alias.get("color", "")
        if offset is None and color and "color" not in primary:
            primary["color"] = color
        alias["_target"], alias["_offset"] = primary, offset
    notes = [
        f"alias_overlap: {leds[i]['raw_name']} {leds[i]['number']} (shares a pin, not as a name)"
        for i in overlaps
    ]
    merged = [led for i, led in enumerate(leds) if i not in plan]
    return merged, [leds[i] for i in sorted(plan)], notes


def _number_channels(
    leds: list[dict[str, Any]],
    aliases: list[dict[str, Any]],
    buttons: list[dict[str, Any]],
    switches: list[dict[str, Any]],
) -> None:
    """Record the boundary channel each component and alias reaches (U56 Phase 6).

    The board's own layout (``BoardDef.led_channels``): mono LEDs in order, then
    r, g, b per RGB site.  An alias reaches its LED's channel, or its site's.
    Switches and buttons reach their place in the board's list.
    """
    mono = [led for led in leds if not _is_rgb_site(led)]
    for k, led in enumerate(mono):
        led["_channel"] = k
    for j, led in enumerate(led for led in leds if _is_rgb_site(led)):
        led["_channel"] = len(mono) + 3 * j
    for alias in aliases:
        alias["_channel"] = alias["_target"]["_channel"] + (alias["_offset"] or 0)
    for group in (buttons, switches):
        for k, comp in enumerate(group):
            comp["_channel"] = k


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


def _effective_version(version: Mapping[str, Any], instance: object) -> dict[str, Any]:
    """Return each version parameter as the constructor resolved it (plan §4.1, U56 Phase 4).

    A constructor may settle a parameter before it uses it: at LiteX head the Colorlight
    i5 takes ``revision=None`` and stores ``self.revision = "7.0"``, its first supported
    revision.  The signature's ``None`` would make the default construction a new
    identity -- a second file, identical to ``colorlight_i5.json`` -- each time upstream
    moved a default into the body.  So a plain value the constructor left on the
    instance under the parameter's own name wins.  Anything else leaves the signature
    default, or the value passed, standing: the Arty Z7 keeps a dict in ``self.board``.
    """
    stored = vars(instance)
    return {
        key: stored[key] if isinstance(stored.get(key), str | int | float) else value
        for key, value in version.items()
    }


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
    source: str,
    filename: str,
    args: Mapping[str, Any] | None = None,
    modules: Mapping[str, str] | None = None,
) -> ParseOutcome:
    """Read one platform file, without executing it, into a :class:`ParseOutcome`.

    The board carries its identity (U56 plan §4.1): the platform class and the effective
    values of the constructor's version parameters.  ``args`` builds a recorded
    non-default identity, ``Platform(**args)``, instead of the default construction; a
    constructor that fails then is an ``error``, never the module-level fallback, so the
    sync can report that version as no longer defined.  ``modules`` maps dotted names to
    the upstream modules a board file may import and the reader reads rather than stubs
    (``litex_boards.extensions.*``, U56 Phase 4).
    """
    cleaned = _blank_import_lines(source)

    allow = _unmocked_star_import(source)
    stand_ins: dict[str, object] = {}
    for _attempt in range(32):
        try:
            return _read_once(source, cleaned, filename, args, allow, stand_ins, modules)
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
    modules: Mapping[str, str] | None = None,
) -> ParseOutcome:
    """Read the file and build its board once, with the given stand-ins bound."""
    try:
        ns = _fresh_namespace(source, stand_ins, modules)  # may read upstream modules
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
    version = _effective_version(version, instance)
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

    notes: list[str] = []  # unsupported multi-pin shapes, for the ledger (D-3)
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
        if kind in ("led", "button", "switch"):
            comps, note = _resource_components(filename, res_name, res_num, ios, kind)
            {"led": leds, "button": buttons, "switch": switches}[kind].extend(comps)
            if note:
                notes.append(note)
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

    for group in (leds, buttons, switches):
        _number_split_groups(group)
    leds = _mono_then_rgb(_upstream_order(leds))
    buttons = _upstream_order(buttons)
    switches = _upstream_order(switches)
    leds, aliases, overlaps = _merge_led_aliases(leds)
    notes.extend(overlaps)
    _number_channels(leds, aliases, buttons, switches)
    port_conventions = _build_litex_convention(clocks, leds + aliases, buttons, switches)
    # `raw_name`, `_split`, `_order` and `_channel` exist only to build the convention
    # and the order above; keep them out of the persisted component JSON.
    for comp in (*leds, *buttons, *switches):
        for key in ("raw_name", "_split", "_order", "_channel"):
            comp.pop(key, None)

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
        "leds": leds,
        "buttons": buttons,
        "switches": switches,
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
    return ParseOutcome(boards=[produced], warnings=notes)
