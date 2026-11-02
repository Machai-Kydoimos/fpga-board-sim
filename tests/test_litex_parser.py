"""Tests for the litex-boards parser (scripts/litex_parser.py).

Hermetic: exercises parse_litex_board() with inline platform-file source, no network.
"""

from pathlib import Path

from litex_parser import parse_litex_board, read_litex_file

_BASIC = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [
    ("clk100", 0, Pins("E3"), IOStandard("LVCMOS33")),
    ("user_led", 0, Pins("A1"), IOStandard("LVCMOS33")),
    ("user_led", 1, Pins("A2"), IOStandard("LVCMOS33")),
    ("user_btn", 0, Pins("B1"), IOStandard("LVCMOS33")),
    ("user_sw", 0, Pins("C1"), IOStandard("LVCMOS33")),
    ("user_sw", 1, Pins("C2"), IOStandard("LVCMOS33")),
]

class TestPlatform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9 / 100e6
    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
"""

_SEVEN_SEG = """
from litex.build.generic_platform import *
from litex.build.lattice import LatticeECP5Platform

_io = [
    ("clk25", 0, Pins("P1"), IOStandard("LVCMOS33")),
    ("user_led", 0, Pins("A1"), IOStandard("LVCMOS33")),
    ("seven_seg", 0, Pins("A B C D E F G DP"), IOStandard("LVCMOS33")),
    ("seven_seg_ctrl", 0, Pins("W X Y Z"), IOStandard("LVCMOS33")),
]

class SegPlatform(LatticeECP5Platform):
    default_clk_name = "clk25"
    default_clk_period = 1e9 / 25e6
    def __init__(self):
        LatticeECP5Platform.__init__(self, "LFE5U-25F", _io)
"""

_NO_RESOURCES = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [("clk100", 0, Pins("E3"), IOStandard("LVCMOS33"))]

class BarePlatform(Xilinx7SeriesPlatform):
    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
"""

# user_led + rgb_led (primary-group drop) and directional buttons (names[] cluster).
_RGB_AND_CLUSTER = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [
    ("clk100", 0, Pins("E3"), IOStandard("LVCMOS33")),
    ("user_led", 0, Pins("A1"), IOStandard("LVCMOS33")),
    ("user_led", 1, Pins("A2"), IOStandard("LVCMOS33")),
    ("rgb_led", 0, Subsignal("r", Pins("B1")), Subsignal("g", Pins("B2"))),
    ("user_btnu", 0, Pins("C1"), IOStandard("LVCMOS33")),
    ("user_btnd", 0, Pins("C2"), IOStandard("LVCMOS33")),
    ("user_btnc", 0, Pins("C3"), IOStandard("LVCMOS33")),
]

class RgbPlatform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9 / 100e6
    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
"""


# U56 Phase 2: a dock's `led` bank, declared out of number order and followed by a
# 1-pin WS2812 (the Tang Primer 20K), and DIP positions declared ahead of directional
# buttons (the VC707).  Sorting by number alone interleaved both.
_DOCK = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [
    ("clk27", 0, Pins("H11"), IOStandard("LVCMOS33")),
    ("led", 0, Pins("C13"), IOStandard("LVCMOS33")),
    ("led", 1, Pins("A13"), IOStandard("LVCMOS33")),
    ("led", 3, Pins("N14"), IOStandard("LVCMOS33")),
    ("led", 2, Pins("N16"), IOStandard("LVCMOS33")),
    ("rgb_led", 0, Pins("T9"), IOStandard("LVCMOS33")),
    ("user_dip_btn", 0, Pins("D1"), IOStandard("LVCMOS33")),
    ("user_dip_btn", 1, Pins("D2"), IOStandard("LVCMOS33")),
    ("user_btn_c", 0, Pins("E1"), IOStandard("LVCMOS33")),
    ("user_btn_n", 0, Pins("E2"), IOStandard("LVCMOS33")),
]

class DockPlatform(Xilinx7SeriesPlatform):
    default_clk_name = "clk27"
    default_clk_period = 1e9 / 27e6
    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
"""


# U33 Wave 4: `oled*` (OLED display buses) and `segled_*` (7-seg lines) merely
# *contain* "led" and must not be user LEDs; `m2led` (M.2 status LED -- a digit
# precedes "led") must stay one.
_OLED_M2LED = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [
    ("clk100", 0, Pins("E3"), IOStandard("LVCMOS33")),
    ("user_led", 0, Pins("A1"), IOStandard("LVCMOS33")),
    ("m2led", 0, Pins("M1"), IOStandard("LVCMOS33")),
    ("oled", 0, Pins("P1 P2 P3"), IOStandard("LVCMOS33")),
    ("oled_ctl", 0, Pins("N1 N2"), IOStandard("LVCMOS33")),
]

class OledPlatform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9 / 100e6
    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
"""

# U33 Wave 4: scalar `segled_*` 7-seg (older Digilent / Numato naming) -- `segled_an`
# digit-selects + `segled_ca`..`_cg`/`_dp` segment lines -- routed to a multiplexed
# seven_seg def, not leaked into the LED bank.
_SEGLED = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [
    ("clk100", 0, Pins("E3"), IOStandard("LVCMOS33")),
    ("user_led", 0, Pins("A1"), IOStandard("LVCMOS33")),
    ("user_led", 1, Pins("A2"), IOStandard("LVCMOS33")),
    ("segled_an", 0, Pins("N6"), IOStandard("LVCMOS33")),
    ("segled_an", 1, Pins("M6"), IOStandard("LVCMOS33")),
    ("segled_an", 2, Pins("M3"), IOStandard("LVCMOS33")),
    ("segled_an", 3, Pins("N5"), IOStandard("LVCMOS33")),
    ("segled_ca", 0, Pins("L3"), IOStandard("LVCMOS33")),
    ("segled_cb", 0, Pins("N1"), IOStandard("LVCMOS33")),
    ("segled_cc", 0, Pins("L5"), IOStandard("LVCMOS33")),
    ("segled_cd", 0, Pins("L4"), IOStandard("LVCMOS33")),
    ("segled_ce", 0, Pins("K3"), IOStandard("LVCMOS33")),
    ("segled_cf", 0, Pins("M2"), IOStandard("LVCMOS33")),
    ("segled_cg", 0, Pins("L6"), IOStandard("LVCMOS33")),
    ("segled_dp", 0, Pins("M4"), IOStandard("LVCMOS33")),
]

class SegledPlatform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9 / 100e6
    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
"""


def test_basic_counts_and_metadata():
    boards = parse_litex_board(_BASIC, "test_board.py")
    assert len(boards) == 1
    b = boards[0]
    assert b["name"] == "Test Board"  # prettified from filename
    assert b["class_name"] == "TestBoardPlatform"
    assert b["vendor"] == "Xilinx"
    assert b["device"] == "xc7a35t"
    assert len(b["leds"]) == 2
    assert len(b["buttons"]) == 1
    assert len(b["switches"]) == 2


def test_default_clock_hz_from_period():
    b = parse_litex_board(_BASIC, "test_board.py")[0]
    assert b["default_clock_hz"] == 100e6


def test_user_led_renamed_to_led():
    b = parse_litex_board(_BASIC, "test_board.py")[0]
    assert all(c["name"] == "led" for c in b["leds"])


def test_seven_seg_multiplexed():
    b = parse_litex_board(_SEVEN_SEG, "seg_board.py")[0]
    ss = b["seven_seg"]
    assert ss is not None
    assert ss["num_digits"] == 4  # from the 4 ctrl (digit-select) pins
    assert ss["is_multiplexed"] is True
    assert ss["has_dp"] is True  # 8 segment pins → includes DP


def test_oled_not_a_led_but_m2led_is():
    # U33 Wave 4: `oled`/`oled_ctl` dropped from the LED bank; `m2led` kept.
    b = parse_litex_board(_OLED_M2LED, "oled_board.py")[0]
    names = sorted(c["name"] for c in b["leds"])
    assert names == ["led", "m2led"]  # user_led -> led; oled/oled_ctl gone
    assert b["seven_seg"] is None


def test_segled_routed_to_seven_seg_not_leds():
    # U33 Wave 4: scalar segled_* becomes a multiplexed 7-seg, not phantom LEDs.
    b = parse_litex_board(_SEGLED, "segled_board.py")[0]
    assert len(b["leds"]) == 2  # only the two user_led; no segled_* leak
    ss = b["seven_seg"]
    assert ss is not None
    assert ss["num_digits"] == 4  # four segled_an digit-selects
    assert ss["has_dp"] is True  # segled_dp present
    assert ss["is_multiplexed"] is True
    assert ss["inverted"] is True and ss["select_inverted"] is True


def test_port_conventions_litex_uses_raw_names():
    # U32: the convention advertises the LiteX *raw* port names (user_led, not led).
    b = parse_litex_board(_BASIC, "test_board.py")[0]
    conv = b["port_conventions"]["litex"]
    assert conv["clk"] == "clk100"
    assert conv["leds"] == {"name": "user_led", "width": 2}
    assert conv["switches"] == {"name": "user_sw", "width": 2}
    assert conv["buttons"] == {"name": "user_btn", "width": 1}
    assert conv["naming"] == "framework-derived"


def test_port_conventions_primary_group_and_cluster():
    b = parse_litex_board(_RGB_AND_CLUSTER, "rgb_board.py")[0]
    conv = b["port_conventions"]["litex"]
    assert conv["leds"] == {"name": "user_led", "width": 2}  # rgb_led dropped
    assert conv["buttons"] == {  # distinct directional buttons -> names[] cluster
        "names": ["user_btnc", "user_btnd", "user_btnu"],
        "width": 3,
    }


def test_each_upstream_name_stays_together_in_number_order():
    # U56 Phase 2: the board shows a name's LEDs side by side, as the Dock has them.
    b = parse_litex_board(_DOCK, "dock_board.py")[0]
    assert [c["pins"] for c in b["leds"]] == [["C13"], ["A13"], ["N16"], ["N14"], ["T9"]]
    assert [c["pins"] for c in b["buttons"]] == [["D1"], ["D2"], ["E1"], ["E2"]]


def test_a_native_bank_is_the_first_bits_of_its_role():
    # The native wrapper puts a bank's bit k on boundary bit k, so the bank's own
    # resources must come first, in number order -- or `led(1)` lights the WS2812.
    b = parse_litex_board(_DOCK, "dock_board.py")[0]
    conv = b["port_conventions"]["litex"]
    assert conv["leds"] == {"name": "led", "width": 4}
    assert [c["pins"] for c in b["leds"][:4]] == [["C13"], ["A13"], ["N16"], ["N14"]]
    assert conv["buttons"] == {"name": "user_dip_btn", "width": 2}
    assert [c["pins"] for c in b["buttons"][:2]] == [["D1"], ["D2"]]


def test_no_simulatable_resources_skipped():
    assert parse_litex_board(_NO_RESOURCES, "bare.py") == []


def test_broken_source_returns_empty():
    assert parse_litex_board("class Broken(: pass", "broken.py") == []


_COLOR_LEDS = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [
    ("clk100", 0, Pins("E3"), IOStandard("LVCMOS33")),
    ("led_g_n", 0, Pins("A1"), IOStandard("LVCMOS33")),
    ("led_r_n", 0, Pins("A2"), IOStandard("LVCMOS33")),
    ("user_led", 0, Pins("A3"), IOStandard("LVCMOS33")),
]

class ColorPlatform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9 / 100e6
    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
"""


def test_led_name_color_heuristic():
    # U36: a color-suffixed LED name carries a color; the `_n` active-low marker is ignored.
    b = parse_litex_board(_COLOR_LEDS, "color.py")[0]
    by_name = {c["name"]: c for c in b["leds"]}
    assert by_name["led_g_n"]["color"] == "green"
    assert by_name["led_r_n"]["color"] == "red"
    assert "color" not in by_name["led"]  # user_led -> led, no name-derived color


# ── identity and outcomes (U56 plan §4.1–4.2) ──────────────────────────────────


_VERSIONED = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io_r1 = [("clk100", 0, Pins("E3")), ("user_led", 0, Pins("H5"))]
_io_r2 = [("clk100", 0, Pins("E3")), ("user_led", 0, Pins("H5")), ("user_led", 1, Pins("J5"))]

class Platform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9/100e6
    def __init__(self, revision=1, toolchain="vivado", speedgrade=-1):
        if revision not in (1, 2):
            raise ValueError("unknown revision")
        io = _io_r1 if revision == 1 else _io_r2
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", io, toolchain=toolchain)
"""


def test_the_board_records_its_class_and_version_defaults():
    outcome = read_litex_file(_VERSIONED, "versioned_board.py")
    assert outcome.outcome == "boards" and outcome.warnings == []
    (board,) = outcome.boards
    assert board.upstream_class == "Platform"
    # Only version-selecting parameters: toolchain and speedgrade are not identity.
    assert board.upstream_args == {"revision": 1}
    assert board.default is True
    assert len(board.board["leds"]) == 1


def test_a_recorded_identity_is_built_with_its_arguments():
    outcome = read_litex_file(_VERSIONED, "versioned_board.py", {"revision": 2})
    (board,) = outcome.boards
    assert board.upstream_args == {"revision": 2} and board.default is False
    assert len(board.board["leds"]) == 2


# LiteX head's Colorlight i5 (U56 Phase 4): the default is None, settled in the body.
_RESOLVED = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io_r1 = [("clk100", 0, Pins("E3")), ("user_led", 0, Pins("H5"))]
_io_r2 = [("clk100", 0, Pins("E3")), ("user_led", 0, Pins("H5")), ("user_led", 1, Pins("J5"))]

class Platform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9/100e6
    revisions = [1, 2]  # the first one is the default
    def __init__(self, revision=None, toolchain="vivado"):
        if revision is None:
            revision = self.revisions[0]
        self.revision = revision
        io = _io_r1 if revision == 1 else _io_r2
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", io, toolchain=toolchain)
"""


def test_a_default_the_constructor_settles_is_recorded_as_settled():
    # Recording the signature's None would make the default construction a new identity.
    (board,) = read_litex_file(_RESOLVED, "resolved_board.py").boards
    assert board.upstream_args == {"revision": 1} and board.default is True
    (explicit,) = read_litex_file(_RESOLVED, "resolved_board.py", {"revision": 1}).boards
    assert explicit.upstream_args == board.upstream_args


def test_a_stored_value_that_is_not_plain_leaves_the_default_standing():
    # The Arty Z7 keeps a dict in self.board: not a version, so the signature's value stands.
    source = _VERSIONED.replace(
        "        io = _io_r1", "        self.revision = {1: 'r1', 2: 'r2'}\n        io = _io_r1"
    )
    (board,) = read_litex_file(source, "dict_board.py").boards
    assert board.upstream_args == {"revision": 1}


def test_a_default_moved_into_the_body_keeps_the_board_s_file(tmp_path):
    """The whole write path: the new default pairs with the file the old default wrote."""
    from sync_identity import run_sync
    from sync_litex_boards import make_reader

    folder = tmp_path / "litex-boards"
    schema = Path(__file__).resolve().parents[1] / "boards" / "schema" / "board.schema.json"
    before = _RESOLVED.replace("revision=None,", "revision=1,")
    for source in (before, _RESOLVED):
        report = run_sync(
            origin="litex-boards",
            repo="litex-hub/litex-boards",
            files={"resolved_board.py": source},
            commit_sha="c0ffee",
            output_dir=folder,
            read=make_reader("c0ffee", timestamp="2026-11-01T00:00:00+00:00"),
            accept_list=[],
            schema_path=schema,
            color_registry={},
        )
    assert (report.new, report.orphans) == ([], [])
    assert sorted(p.name for p in folder.glob("*.json")) == [
        "_sync_metadata.json",
        "resolved_board.json",
    ]


def test_a_version_upstream_no_longer_accepts_is_an_error_not_a_fallback():
    outcome = read_litex_file(_VERSIONED, "versioned_board.py", {"revision": 3})
    assert (outcome.outcome, outcome.detail, outcome.boards) == ("error", "ValueError", [])


def test_a_constructor_that_fails_is_an_error_not_a_fallback():
    # Phase 1c removed the module-level fallback: a failing constructor reports itself.
    source = _VERSIONED.replace(
        '        if revision not in (1, 2):\n            raise ValueError("unknown revision")',
        '        raise ValueError("this constructor always fails")',
    )
    outcome = read_litex_file(source, "always_fails.py")
    assert (outcome.outcome, outcome.detail, outcome.boards) == ("error", "ValueError", [])


def test_the_permissive_platform_absorbs_toolchain_options_and_unknown_methods():
    source = _VERSIONED.replace(
        '        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", io, toolchain=toolchain)',
        '        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", io, toolchain=toolchain)\n'
        '        self.toolchain.bitstream_commands = ["set_property CFGBVS VCCO"]\n'
        '        self.toolchain.additional_commands += ["write_cfgmem"]\n'
        '        self.add_platform_command("set_property INTERNAL_VREF 0.675")\n'
        '        self.add_period_constraint(self.lookup_request("clk100"), 10.0)',
    )
    outcome = read_litex_file(source, "permissive.py")
    assert outcome.outcome == "boards" and outcome.boards[0].board["device"] == "xc7a35t"


def test_an_imported_helper_we_do_not_model_is_a_stand_in():
    source = _VERSIONED.replace(
        "_io_r1 =", "from litex_boards.extensions.pmod import PmodUSBUART\n\n_io_r1 ="
    ).replace(
        '        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", io, toolchain=toolchain)',
        '        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", io, toolchain=toolchain)\n'
        '        self.add_extension(PmodUSBUART("pmoda").get_io())',
    )
    outcome = read_litex_file(source, "with_pmod.py")
    assert outcome.outcome == "boards" and len(outcome.boards[0].board["leds"]) == 1


def test_a_name_from_an_unmocked_star_import_gets_a_stand_in_but_a_stray_name_does_not():
    star = "from migen import *\n" + _VERSIONED.replace(
        "        io = _io_r1 if revision == 1 else _io_r2",
        "        io = _io_r1 if revision == 1 else _io_r2\n        helper = Module()",
    )
    assert read_litex_file(star, "migen_user.py").outcome == "boards"
    stray = _VERSIONED.replace(
        "        io = _io_r1 if revision == 1 else _io_r2",
        "        io = _io_r1 if revision == 1 else _io_r2\n        helper = Module()",
    )
    assert read_litex_file(stray, "stray.py").detail == "NameError: Module"


def test_outcomes_say_why_a_file_has_no_board():
    assert read_litex_file("x = 1\n", "helpers.py").detail == "not_a_board"
    no_io = _VERSIONED.replace('("user_led", 0, Pins("H5"))', '("serial", 0, Pins("H5"))').replace(
        ', ("user_led", 1, Pins("J5"))', ""
    )
    assert read_litex_file(no_io, "no_io.py").detail == "no_simulatable_io"
    broken = read_litex_file("class Platform(Undefined):\n    pass\n", "broken.py")
    assert (broken.outcome, broken.detail) == ("error", "NameError: Undefined")


# ── Phase 1c: mocks that read what upstream writes (U56 defects 3–5) ───────────


def test_pins_takes_several_identifier_strings():
    import litex_parser

    pins = litex_parser._Pins("A1 B2", "C3", dir="o")
    assert pins.identifiers == ["A1", "B2", "C3"] and pins.names == pins.identifiers
    assert pins.dir == "o"


def test_the_vendor_table_uses_upstreams_spellings():
    import litex_parser

    vendors = litex_parser._PLATFORM_VENDORS
    assert vendors["LatticeiCE40Platform"] == "Lattice"
    assert "LatticeICE40Platform" not in vendors  # the old misspelling locked out iCE40
    for name in ("LatticePlatform", "MicrosemiPlatform", "AnlogicPlatform", "QuickLogicPlatform"):
        assert name in vendors


# ── Extensions and the constructor's clock (U56 Phase 2) ─────────────────────

_DOCKED = """
from litex.build.generic_platform import *
from litex.build.gowin.platform import GowinPlatform

_io = [
    ("clk27", 0, Pins("H11"), IOStandard("LVCMOS33")),
    ("user_led", 0, Pins("A1"), IOStandard("LVCMOS33")),
]

_dock_io = [
    ("user_led", 1, Pins("A2"), IOStandard("LVCMOS33")),
    ("user_btn", 0, Pins("B1"), IOStandard("LVCMOS33")),
]

_dock_lite_io = [("user_btn", 0, Pins("B1"), IOStandard("LVCMOS33"))]


class Platform(GowinPlatform):
    default_clk_name = "clk27"
    default_clk_period = 1e9 / 27e6

    def __init__(self, dock="standard"):
        GowinPlatform.__init__(self, "GW2A-LV18PG256C8/I7", _io)
        self.add_extension(_dock_io if dock == "standard" else _dock_lite_io)
"""


def test_add_extension_adds_the_io_it_is_given():
    """It used to be a no-op, which dropped every LED and button a dock adds."""
    b = parse_litex_board(_DOCKED, "docked.py")[0]
    assert len(b["leds"]) == 2
    assert len(b["buttons"]) == 1


_EXTENSION_OBJECTS = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [("clk100", 0, Pins("E3")), ("user_led", 0, Pins("A1"))]


class Dock:
    def get_io(self, platform):
        return [("user_btn", n, Pins(f"B{n}")) for n in range(2)]


class NotAnExtension:
    io = [("user_sw", 0, Pins("C1"))]


class Platform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9 / 100e6

    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
        self.add_extension(Dock())
        self.add_extension(NotAnExtension())
"""


def test_add_extension_asks_an_extension_object_for_its_io_as_litex_does():
    """``get_io(platform)``, interpreted; an object without one adds nothing (LiteX rejects it)."""
    b = parse_litex_board(_EXTENSION_OBJECTS, "objects.py")[0]
    assert len(b["buttons"]) == 2
    assert b["switches"] == []


_CLOCK_SET_BY_THE_CONSTRUCTOR = """
from litex.build.generic_platform import *
from litex.build.xilinx import Xilinx7SeriesPlatform

_io = [
    ("clk125", 0, Pins("U18")),
    ("clk122", 0, Pins("U19")),
    ("user_led", 0, Pins("F16")),
]


class Platform(Xilinx7SeriesPlatform):
    def __init__(self, board="redpitaya14"):
        Xilinx7SeriesPlatform.__init__(self, "xc7z010clg400-1", _io)
        if board == "redpitaya14":
            self.default_clk_name = "clk125"
            self.default_clk_freq = 125e6
        else:
            self.default_clk_name = "clk122"
            self.default_clk_freq = 122e6
        self.default_clk_period = 1e9 / self.default_clk_freq
"""


def test_the_default_clock_is_what_the_constructor_set():
    """Red Pitaya's shape: the board picks its clock in ``__init__``."""
    b = parse_litex_board(_CLOCK_SET_BY_THE_CONSTRUCTOR, "red_pitaya_like.py")[0]
    assert b["default_clock_hz"] == 125e6
    assert [c["name"] for c in b["clocks"] if c.get("is_default")] == ["clk125"]
    assert "default_clock_assumed" not in b


def test_a_class_level_frequency_the_constructor_turns_into_a_period():
    """Snickerdoodle's shape: ``default_clk_freq`` on the class, the period set in ``__init__``."""
    source = _BASIC.replace(
        "    default_clk_period = 1e9 / 100e6\n", "    default_clk_freq = 50e6\n"
    ).replace(
        '        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)',
        '        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)\n'
        "        self.default_clk_period = 1e9 / self.default_clk_freq",
    )
    assert parse_litex_board(source, "snickerdoodle_like.py")[0]["default_clock_hz"] == 50e6


def test_a_board_whose_upstream_states_no_frequency_says_its_clock_is_assumed():
    """12 MHz is our fallback, never upstream data (U56 D-6)."""
    source = _BASIC.replace("    default_clk_period = 1e9 / 100e6\n", "")
    b = parse_litex_board(source, "no_period.py")[0]
    assert b["default_clock_hz"] == 12e6
    assert b["default_clock_assumed"] is True
    assert "default_clock_assumed" not in parse_litex_board(_BASIC, "test_board.py")[0]


# ── Reading upstream's extension modules (U56 Phase 4) ───────────────────────

_SIPEED_LIKE = """
from litex.build.generic_platform import Pins, Subsignal
from litex.build.extension import Extension


class Dock(Extension):
    slots = {"card": "CARD1"}

    def define_io(self, platform):
        return [
            ("user_led", 0, Pins("card:44"), *self.iostandard(platform)),
            ("user_led", 1, Pins("card:46"), *self.pullup(platform)),
            ("user_btn", 0, Pins("card:15")),
        ]


class Pmod(Extension):
    slots = {"pmod": None}

    def define_io(self, platform):
        return [("user_sw", n, Pins(f"pmod:{n}")) for n in range(2)]
"""

_DOCKED_AT_HEAD = """
from litex.build.generic_platform import *
from litex.build.gowin.platform import GowinPlatform
from litex_boards.extensions.sipeed_like import Dock, Pmod

_io = [("clk27", 0, Pins("H11"))]


class Platform(GowinPlatform):
    default_clk_name = "clk27"
    default_clk_period = 1e9 / 27e6

    def __init__(self):
        GowinPlatform.__init__(self, "GW2A-LV18PG256C8/I7", _io)
        self.add_extension(Dock())
        self.add_extension(Pmod("pmodb", number=4))
"""

_MODULES = {"litex_boards.extensions.sipeed_like": _SIPEED_LIKE}


def _pins(board, kind):
    return [(c["number"], c["pins"]) for c in board[kind]]


def test_an_extension_module_is_read_and_its_slots_remapped():
    """The dock's ``card:N`` pins land on the host's ``CARD1:N``; the Pmod's numbers shift."""
    b = read_litex_file(_DOCKED_AT_HEAD, "docked.py", modules=_MODULES).boards[0].board
    assert _pins(b, "leds") == [(0, ["CARD1:44"]), (1, ["CARD1:46"])]
    assert _pins(b, "buttons") == [(0, ["CARD1:15"])]
    assert _pins(b, "switches") == [(4, ["pmodb:0"]), (5, ["pmodb:1"])]


def test_without_the_module_the_dock_is_a_stand_in_with_no_io():
    """What the bump would lose without reading extensions (Phase 1c stubbed them)."""
    outcome = read_litex_file(_DOCKED_AT_HEAD, "docked.py")
    assert outcome.outcome == "skipped" and outcome.detail == "no_simulatable_io"


def test_an_extension_rejects_a_bad_binding_as_upstream_does():
    unbound = _DOCKED_AT_HEAD.replace('Pmod("pmodb", number=4)', "Pmod()")
    outcome = read_litex_file(unbound, "unbound.py", modules=_MODULES)
    assert outcome.outcome == "error" and outcome.detail == "ValueError"


def test_an_extension_can_rename_its_resources():
    renamed = _DOCKED_AT_HEAD.replace(
        'Pmod("pmodb", number=4)', 'Pmod("pmodb", name={"user_sw": "user_btn"})'
    )
    b = read_litex_file(renamed, "renamed.py", modules=_MODULES).boards[0].board
    assert _pins(b, "buttons") == [(0, ["CARD1:15"]), (0, ["pmodb:0"]), (1, ["pmodb:1"])]


def test_modules_import_each_other_and_a_cycle_ends():
    """A module's own imports are read the same way; a cycle leaves stand-ins, never loops."""
    base = """
from litex.build.extension import Extension
from litex_boards.extensions.b import Unused


class Base(Extension):
    slots = {"j": "J2"}
"""
    child = """
from litex.build.generic_platform import Pins
from litex_boards.extensions.a import Base


class Unused(Base):
    pass


class Board(Base):
    def define_io(self, platform):
        return [("user_led", 0, Pins("j:1"))]
"""
    modules = {"litex_boards.extensions.a": base, "litex_boards.extensions.b": child}
    source = (
        _DOCKED_AT_HEAD.replace(
            "from litex_boards.extensions.sipeed_like import Dock, Pmod",
            "from litex_boards.extensions.b import Board",
        )
        .replace("self.add_extension(Dock())", "self.add_extension(Board())")
        .replace('        self.add_extension(Pmod("pmodb", number=4))\n', "")
    )
    b = read_litex_file(source, "chained.py", modules=modules).boards[0].board
    assert _pins(b, "leds") == [(0, ["J2:1"])]


def test_a_module_with_an_unmocked_star_import_gets_stand_ins():
    """qmtech's shape: ``from migen import *``, then ``Module`` at module level."""
    with_migen = "from migen import *\n" + _SIPEED_LIKE + "\nhelper = Module\n"
    modules = {"litex_boards.extensions.sipeed_like": with_migen}
    assert read_litex_file(_DOCKED_AT_HEAD, "docked.py", modules=modules).outcome == "boards"


def test_a_shim_calling_get_io_on_the_platform_class_works():
    """Upstream's deprecated helpers call ``Ext(...).get_io(PlatformClass)`` at module level."""
    shim = _DOCKED_AT_HEAD + '\n_compat = Pmod("pmoda").get_io(GowinPlatform)\n'
    assert read_litex_file(shim, "shim.py", modules=_MODULES).outcome == "boards"
