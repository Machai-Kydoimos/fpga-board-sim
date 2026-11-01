"""Tests for the litex-boards parser (scripts/litex_parser.py).

Hermetic: exercises parse_litex_board() with inline platform-file source, no network.
"""

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


class BuildsItsIO:
    def define_io(self, platform):
        return [("user_btn", n, Pins(f"B{n}")) for n in range(2)]


class HoldsItsIO:
    io = [("user_sw", 0, Pins("C1"))]


class Platform(Xilinx7SeriesPlatform):
    default_clk_name = "clk100"
    default_clk_period = 1e9 / 100e6

    def __init__(self):
        Xilinx7SeriesPlatform.__init__(self, "xc7a35t", _io)
        self.add_extension(BuildsItsIO())
        self.add_extension(HoldsItsIO())
"""


def test_add_extension_reads_an_extension_object_without_executing_it():
    """A dock builds its I/O in ``define_io(platform)`` -- interpreted -- or holds ``.io``."""
    b = parse_litex_board(_EXTENSION_OBJECTS, "objects.py")[0]
    assert len(b["buttons"]) == 2
    assert len(b["switches"]) == 1


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
