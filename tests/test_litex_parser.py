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


def test_no_simulatable_resources_skipped():
    assert parse_litex_board(_NO_RESOURCES, "bare.py") == []


def test_broken_source_returns_empty():
    assert parse_litex_board("class Broken(: pass", "broken.py") == []
