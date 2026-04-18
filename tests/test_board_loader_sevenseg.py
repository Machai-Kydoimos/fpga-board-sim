"""Tests for 7-segment display extraction in board_loader.

Hermetic inline-source tests run without the submodule.
Parametric real-board tests are skipped when the submodule is absent.
"""

import pytest

from fpga_sim.board_loader import (
    discover_boards,
    get_default_boards_path,
    load_board_from_source,
)

# ── Inline source fixtures ─────────────────────────────────────────────────────

_INLINE_4SEG_INDEPENDENT = """
from amaranth.build import *
from amaranth.vendor import IntelPlatform
class FakeDe0Platform(IntelPlatform):
    resources = [
        *LEDResources(pins="A B C D"),
        Display7SegResource(0, a="P1",b="P2",c="P3",d="P4",e="P5",f="P6",g="P7",dp="P8",invert=True),
        Display7SegResource(1, a="Q1",b="Q2",c="Q3",d="Q4",e="Q5",f="Q6",g="Q7",dp="Q8",invert=True),
        Display7SegResource(2, a="R1",b="R2",c="R3",d="R4",e="R5",f="R6",g="R7",dp="R8",invert=True),
        Display7SegResource(3, a="S1",b="S2",c="S3",d="S4",e="S5",f="S6",g="S7",dp="S8",invert=True),
    ]
"""

_INLINE_8SEG_MULTIPLEXED = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
class FakeNexys4Platform(XilinxPlatform):
    resources = [
        *LEDResources(pins="A B C D E F G H"),
        Display7SegResource(0, a="SA",b="SB",c="SC",d="SD",e="SE",f="SF",g="SG",dp="SP"),
        Resource("display_7seg_an", 0, PinsN("AN0 AN1 AN2 AN3 AN4 AN5 AN6 AN7", dir="o")),
    ]
"""

_INLINE_6SEG_NO_DP = """
from amaranth.build import *
from amaranth.vendor import IntelPlatform
class FakeDeCvPlatform(IntelPlatform):
    resources = [
        *LEDResources(pins="A B"),
        Display7SegResource(0, a="P1",b="P2",c="P3",d="P4",e="P5",f="P6",g="P7",invert=True),
        Display7SegResource(1, a="Q1",b="Q2",c="Q3",d="Q4",e="Q5",f="Q6",g="Q7",invert=True),
        Display7SegResource(2, a="R1",b="R2",c="R3",d="R4",e="R5",f="R6",g="R7",invert=True),
        Display7SegResource(3, a="S1",b="S2",c="S3",d="S4",e="S5",f="S6",g="S7",invert=True),
        Display7SegResource(4, a="T1",b="T2",c="T3",d="T4",e="T5",f="T6",g="T7",invert=True),
        Display7SegResource(5, a="U1",b="U2",c="U3",d="U4",e="U5",f="U6",g="U7",invert=True),
    ]
"""

_INLINE_NO_SEG = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
class FakeArtyPlatform(XilinxPlatform):
    resources = [*LEDResources(pins="A B C D")]
"""

_INLINE_4SEG_CTRL = """
from amaranth.build import *
from amaranth.vendor import LatticeICE40Platform
class FakeMercuryPlatform(LatticeICE40Platform):
    resources = [
        *LEDResources(pins="A B"),
        Display7SegResource(0, a="SA",b="SB",c="SC",d="SD",e="SE",f="SF",g="SG",dp="SP"),
        Resource("display_7seg_ctrl", 0, Pins("C0 C1 C2 C3", dir="o")),
    ]
"""

# ── Hermetic tests (no submodule required) ─────────────────────────────────────


def test_inline_4seg_independent():
    boards = load_board_from_source(_INLINE_4SEG_INDEPENDENT)
    ssd = boards[0].seven_seg
    assert ssd is not None
    assert ssd.num_digits == 4
    assert ssd.is_multiplexed is False
    assert ssd.has_dp is True
    assert ssd.inverted is True


def test_inline_8seg_multiplexed():
    boards = load_board_from_source(_INLINE_8SEG_MULTIPLEXED)
    ssd = boards[0].seven_seg
    assert ssd is not None
    assert ssd.num_digits == 8
    assert ssd.is_multiplexed is True
    assert ssd.select_inverted is True   # PinsN companion → active-low


def test_inline_no_dp_flag():
    boards = load_board_from_source(_INLINE_6SEG_NO_DP)
    assert boards[0].seven_seg.has_dp is False


def test_inline_no_sevenseg():
    boards = load_board_from_source(_INLINE_NO_SEG)
    assert boards[0].seven_seg is None


def test_inline_ctrl_companion_active_high():
    boards = load_board_from_source(_INLINE_4SEG_CTRL)
    ssd = boards[0].seven_seg
    assert ssd is not None
    assert ssd.num_digits == 4
    assert ssd.is_multiplexed is True
    assert ssd.select_inverted is False  # Pins (not PinsN) → active-high


def test_summary_includes_7seg():
    boards = load_board_from_source(_INLINE_4SEG_INDEPENDENT)
    assert "7-seg" in boards[0].summary


def test_summary_without_7seg():
    boards = load_board_from_source(_INLINE_NO_SEG)
    assert "7-seg" not in boards[0].summary


# ── Real-submodule parametric tests ───────────────────────────────────────────


@pytest.fixture(scope="module")
def all_boards():
    path = get_default_boards_path()
    if not path.is_dir():
        pytest.skip("amaranth-boards submodule not initialised")
    return discover_boards(path)


_EXPECTED_7SEG = {
    # Board name fragment (must match _prettify_class_name() output)
    # → (num_digits, has_dp, is_multiplexed)
    "DE0":          (4, True,  False),   # "DE0" board (not DE0 CV)
    "Nandland Go":  (2, False, False),
    "DE0 CV":       (6, False, False),   # prettified from DE0CVPlatform
    "DE1 So":       (6, False, False),   # "DE1 So C" from DE1SoCPlatform
    "DE10":         (6, True,  False),   # "DE10 Lite"
    "Nexys4":       (8, True,  True),    # "Nexys4 DDR"
    "RZEasy":       (4, True,  True),    # "RZEasy FPGAA2-2"
    "Step MXO2":    (2, True,  True),    # multiplexed, 2 select pins (active-low)
    # Mercury: 7-seg is in baseboard_no_sram (not in resources), so not detected
}


@pytest.mark.parametrize("name_frag,expected", _EXPECTED_7SEG.items())
def test_real_board_sevenseg(all_boards, name_frag, expected):
    matches = [b for b in all_boards if name_frag.lower() in b.name.lower()]
    if not matches:
        pytest.skip(f"{name_frag} not in submodule")
    ssd = matches[0].seven_seg
    assert ssd is not None, f"{name_frag}: expected SevenSegDef, got None"
    num_digits, has_dp, is_mux = expected
    assert ssd.num_digits == num_digits
    assert ssd.has_dp == has_dp
    assert ssd.is_multiplexed == is_mux


def test_arty_has_no_sevenseg(all_boards):
    arty = next((b for b in all_boards if "Arty A7-35" in b.name), None)
    if arty is None:
        pytest.skip("Arty not in submodule")
    assert arty.seven_seg is None
