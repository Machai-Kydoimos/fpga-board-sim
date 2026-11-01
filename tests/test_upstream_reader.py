"""The parse-only reader of upstream board files (U56 Phase 0, plan decision D-7).

Two halves. The reader must *evaluate* what board files actually write -- or the sync
loses boards -- with Python's own semantics, or the boards change. And it must *refuse*
everything else, uncatchably, without running it: the planted files at the end try to
read the environment, run a command or reach a real module, and each must leave its
marker file uncreated.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import amaranth_parser  # noqa: E402
import litex_parser  # noqa: E402
import upstream_reader  # noqa: E402
from upstream_reader import ModuleStub, UnsupportedConstructError, read_module  # noqa: E402


class _Base:
    """A stand-in for a parser's mock platform base."""

    def __init__(self, device="", io=None, **kwargs):
        self.device = device
        self.captured = list(io or [])

    def add(self, item):
        self.captured.append(item)


def _ns(**extra):
    ns = {"Base": _Base, "__name__": "_reader_test"}
    ns.update(extra)
    return ns


def _read(source, **extra):
    return read_module(source, "test.py", _ns(**extra))


# ── what board files write: evaluated, with Python's semantics ─────────────────


def test_literals_operators_and_comprehensions():
    ns = _read(
        "pins = 'A1 B2 C3'.split()\n"
        "leds = [(f'led{i}', p) for i, p in enumerate(pins) if p != 'B2']\n"
        "width = len(pins) * 2 + 1\n"
        "clock = 1e9 / 100e6\n"
        "lut = {name: n for n, name in enumerate(['a', 'b'])}\n"
        "both = [*pins, 'D4']\n"
    )
    assert ns["leds"] == [("led0", "A1"), ("led2", "C3")]
    assert ns["width"] == 7
    assert ns["clock"] == 10.0
    assert ns["lut"] == {"a": 0, "b": 1}
    assert ns["both"] == ["A1", "B2", "C3", "D4"]


def test_augmented_assignment_mutates_the_list_in_place():
    # `_io_v2 = _io; _io_v2 += [...]` changes `_io` too in Python -- and must here.
    ns = _read("_io = [1]\n_io_v2 = _io\n_io_v2 += [2]\n")
    assert ns["_io"] == [1, 2]
    assert ns["_io"] is ns["_io_v2"]


def test_definitions_land_in_the_namespace_in_file_order():
    ns = _read("b = 1\nclass P(Base):\n    pass\na = 2\n")
    assert list(ns)[-3:] == ["b", "P", "a"]


def test_main_guard_stays_dormant():
    ns = _read("ran = False\nif __name__ == '__main__':\n    ran = True\n")
    assert ns["ran"] is False


def test_a_class_is_a_real_class_with_an_interpreted_constructor():
    ns = _read(
        "class Platform(Base):\n"
        "    default_clk_name = 'clk100'\n"
        "    def __init__(self, revision=2, toolchain='vivado'):\n"
        "        Base.__init__(self, 'xc7a35t', ['io'], toolchain=toolchain)\n"
        "        self.revision = revision\n"
        "        self.add(self.extra())\n"
        "    def extra(self):\n"
        "        return 'ext'\n"
    )
    assert isinstance(ns["Platform"], type) and issubclass(ns["Platform"], _Base)
    cls: Any = ns["Platform"]  # its attributes come from the interpreted class body
    assert cls.default_clk_name == "clk100"
    instance = cls()  # native call: type.__call__ runs the interpreted __init__
    assert (instance.device, instance.revision, instance.captured) == ("xc7a35t", 2, ["io", "ext"])


def test_super_and_in_file_inheritance():
    ns = _read(
        "class A(Base):\n"
        "    resources = ['led']\n"
        "    def __init__(self):\n"
        "        super().__init__('dev-a')\n"
        "class B(A):\n"
        "    resources = A.resources + ['button']\n"
        "    def __init__(self):\n"
        "        super().__init__()\n"
        "        self.device += '-b'\n"
    )
    b = ns["B"]()
    assert b.device == "dev-a-b"
    assert ns["B"].resources == ["led", "button"]
    assert ns["B"].__mro__[1] is ns["A"]


def test_class_body_names_are_invisible_to_its_comprehensions_as_in_python():
    # Only the outermost iterable sees the class body; the element does not.
    ns = _read("class P(Base):\n    n = 3\n    xs = [i for i in range(n)]\n")
    assert ns["P"].xs == [0, 1, 2]
    with pytest.raises(NameError):
        _read("class P(Base):\n    n = 3\n    xs = [n for i in range(2)]\n")


def test_closures_bind_late():
    ns = _read("fs = [lambda: i for i in range(3)]\nvals = [f() for f in fs]\n")
    assert ns["vals"] == [2, 2, 2]


def test_keyword_only_none_default_and_missing_argument():
    ns = _read("def f(*, conn=None, dir='io'):\n    return (conn, dir)\nr = f()\n")
    assert ns["r"] == (None, "io")
    with pytest.raises(TypeError):
        _read("def f(*, conn):\n    return conn\nr = f()\n")


def test_upstream_try_except_catches_ordinary_errors():
    ns = _read("try:\n    x = undefined_name\nexcept NameError:\n    x = 'fallback'\n")
    assert ns["x"] == "fallback"


def test_property_and_staticmethod_decorators():
    ns = _read(
        "class P(Base):\n"
        "    @property\n"
        "    def part(self):\n"
        "        return 'GW1N'\n"
        "    @staticmethod\n"
        "    def pins():\n"
        "        return ['A1']\n"
    )
    assert ns["P"]().part == "GW1N"
    assert ns["P"].pins() == ["A1"]


def test_a_module_stub_offers_only_its_members():
    stub = ModuleStub("unittest", TestCase=type("TestCase", (), {}))
    ns = _read("class TestCase(unittest.TestCase):\n    pass\n", unittest=stub)
    assert isinstance(ns["TestCase"], type)
    with pytest.raises(AttributeError):
        _read("x = unittest.mock\n", unittest=stub)


# ── refusals: reported, never run, never catchable ─────────────────────────────


@pytest.mark.parametrize(
    "source",
    [
        "x = ().__class__.__base__.__subclasses__()",  # the classic escape
        "x = Base.__dict__",
        "x = Base.mro()",
        "x = getattr(Base, '__dict__')",  # getattr applies the same rules as a written name
        "x = getattr((), '__class__')",
        "x = '{0.__class__}'.format(Base)",  # str.format reads attributes without a call
        "x = '{0[0]}'.format(['a'])",
        "x = 1; import os",  # an import the parsers' line blanking cannot see
        "class P(Base, metaclass=type):\n    pass",
        "def f():\n    yield 1\nx = f()",
        "with open('x') as f:\n    pass",
        "global x",
    ],
)
def test_refused_constructs(source):
    with pytest.raises(UnsupportedConstructError):
        _read(source)


@pytest.mark.parametrize(
    "source",
    [
        "x = open('/etc/hostname')",
        "x = __import__('os')",
        "x = type('X', (), {})",
        "x = eval('1')",
        "x = exec('y = 1')",
        "x = globals()",
    ],
)
def test_dangerous_builtins_are_simply_not_there(source):
    with pytest.raises(NameError):
        _read(source)


def test_a_refusal_cannot_be_caught_by_upstream_code():
    with pytest.raises(UnsupportedConstructError):
        _read("try:\n    x = ().__class__\nexcept Exception:\n    x = 'swallowed'\n")


def test_a_real_module_handed_over_by_mistake_is_still_untouchable():
    # Even if a parser put a real module in the namespace, the reader would not use it.
    import os

    with pytest.raises(UnsupportedConstructError):
        _read("x = os.environ", os=os)
    with pytest.raises(UnsupportedConstructError):
        _read("x = os.getcwd()", os=os)


def test_step_budget(monkeypatch):
    monkeypatch.setattr(upstream_reader, "MAX_STEPS", 10_000)
    with pytest.raises(UnsupportedConstructError, match="step budget"):
        _read("while True:\n    pass\n")


@pytest.mark.parametrize(
    "source", ["x = 'a' * 10_000_000", "x = range(10**9)", "x = 10 ** 10 ** 6", "x = 1 << 10**7"]
)
def test_size_budget(source):
    with pytest.raises(UnsupportedConstructError):
        _read(source)


# ── planted upstream files, through the real parsers ──────────────────────────


def _amaranth_board(extra_module="", extra_class=""):
    return (
        "import os\n"
        "import subprocess\n"
        "from amaranth.build import *\n"
        f"{extra_module}\n"
        "class EvilPlatform(LatticeICE40Platform):\n"
        "    device = 'iCE40UP5K'\n"
        "    default_clk = 'clk12'\n"
        "    resources = [\n"
        "        Resource('clk12', 0, Pins('35', dir='i'), Clock(12e6)),\n"
        "        *LEDResources(pins='39 40', invert=True),\n"
        "    ]\n"
        f"{extra_class}\n"
        "    def toolchain_program(self, products, name):\n"
        "        subprocess.check_call([os.environ.get('ICEPROG', 'iceprog'), name])\n"
    )


def test_an_ordinary_board_still_reads():
    boards = amaranth_parser.load_board_from_source(_amaranth_board(), "evil.py")
    assert [b.class_name for b in boards] == ["EvilPlatform"]
    assert len(boards[0].leds) == 2


@pytest.mark.parametrize(
    ("where", "payload"),
    [
        ("module", "subprocess.run(['touch', MARKER])"),
        ("module", "os.system('touch ' + MARKER)"),
        ("module", "open(MARKER, 'w').write('x')"),
        ("module", "[c for c in ().__class__.__base__.__subclasses__()]"),
        ("class", "    leaked = os.environ.get('GITHUB_TOKEN')"),
        ("class", "    _ = __import__('os').system('touch ' + MARKER)"),
    ],
)
def test_planted_amaranth_payloads_never_run(tmp_path, capsys, where, payload):
    marker = tmp_path / "ran"
    line = payload.replace("MARKER", repr(str(marker)))
    if where == "module":
        source = _amaranth_board(extra_module=line)
    else:
        source = _amaranth_board(extra_class=line)
    assert amaranth_parser.load_board_from_source(source, "evil.py") == []
    assert not marker.exists()
    assert "skipped evil.py" in capsys.readouterr().err  # loud, never silent


def test_planted_litex_constructor_payload_never_runs(tmp_path, capsys):
    marker = tmp_path / "ran"
    source = (
        "import os\n"
        "from litex.build.generic_platform import *\n"
        "from litex.build.xilinx import Xilinx7SeriesPlatform\n"
        "_io = [\n"
        "    ('clk100', 0, Pins('E3'), IOStandard('LVCMOS33')),\n"
        "    ('user_led', 0, Pins('H5'), IOStandard('LVCMOS33')),\n"
        "]\n"
        "class Platform(Xilinx7SeriesPlatform):\n"
        "    default_clk_name = 'clk100'\n"
        "    default_clk_period = 1e9/100e6\n"
        "    def __init__(self, toolchain='vivado'):\n"
        "        Xilinx7SeriesPlatform.__init__(self, 'xc7a35t', _io, toolchain=toolchain)\n"
        f"        os.system('touch ' + {str(marker)!r})\n"
    )
    outcome = litex_parser.read_litex_file(source, "evil_board.py")
    assert not marker.exists()
    # The file imports `os`, so `os` is an inert stand-in: `os.system(...)` does nothing at
    # all, and the board's own resources still read.
    assert outcome.outcome == "boards" and len(outcome.boards[0].board["leds"]) == 1
