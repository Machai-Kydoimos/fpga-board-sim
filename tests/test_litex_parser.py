"""Tests for the litex-boards parser (scripts/litex_parser.py).

Hermetic: exercises parse_litex_board() with inline platform-file source, no network.
"""

from litex_parser import parse_litex_board

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
