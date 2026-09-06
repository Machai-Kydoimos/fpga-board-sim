"""Tests for 7-segment display extraction in board_loader.

Hermetic inline-source tests run without the submodule.
Parametric real-board tests are skipped when the submodule is absent.
"""

import pytest
from amaranth_parser import load_board_from_source

from fpga_sim.board_loader import (
    BoardDef,
    SevenSegDef,
    discover_boards,
    get_default_boards_path,
)

# ── Inline source fixtures ─────────────────────────────────────────────────────

_INLINE_4SEG_INDEPENDENT = """
from amaranth.build import *
from amaranth.vendor import IntelPlatform
class FakeDe0Platform(IntelPlatform):
    resources = [
        *LEDResources(pins="A B C D"),
        Display7SegResource(0, a="P1", b="P2", c="P3", d="P4",
                            e="P5", f="P6", g="P7", dp="P8", invert=True),
        Display7SegResource(1, a="Q1", b="Q2", c="Q3", d="Q4",
                            e="Q5", f="Q6", g="Q7", dp="Q8", invert=True),
        Display7SegResource(2, a="R1", b="R2", c="R3", d="R4",
                            e="R5", f="R6", g="R7", dp="R8", invert=True),
        Display7SegResource(3, a="S1", b="S2", c="S3", d="S4",
                            e="S5", f="S6", g="S7", dp="S8", invert=True),
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
    assert ssd.select_inverted is True  # PinsN companion → active-low


def test_inline_no_dp_flag():
    boards = load_board_from_source(_INLINE_6SEG_NO_DP)
    ssd = boards[0].seven_seg
    assert ssd is not None
    assert ssd.has_dp is False


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


def test_summary_uses_middle_dot_separator():
    """Compact format uses ' · ' between parts, not ', '."""
    boards = load_board_from_source(_INLINE_NO_SEG)
    s = boards[0].summary
    assert " · " in s
    assert ", " not in s


def test_summary_uses_btn_and_sw_abbreviations():
    """Compact format abbreviates 'buttons'/'switches' to 'BTN'/'SW'."""
    boards = load_board_from_source(_INLINE_NO_SEG)
    s = boards[0].summary
    assert " BTN" in s
    assert " SW" in s
    assert "buttons" not in s
    assert "switches" not in s


def test_summary_full_format_with_7seg():
    """End-to-end check of the compact format with a 7-seg board."""
    boards = load_board_from_source(_INLINE_4SEG_INDEPENDENT)
    b = boards[0]
    assert b.seven_seg is not None
    expected = (
        f"{len(b.leds)} LEDs · {len(b.buttons)} BTN · "
        f"{len(b.switches)} SW · {b.seven_seg.num_digits}-digit 7-seg"
    )
    assert b.summary == expected


# ── Real-submodule parametric tests ───────────────────────────────────────────


@pytest.fixture(scope="module")
def all_boards():
    path = get_default_boards_path()
    if not path.is_dir():
        pytest.skip("amaranth-boards submodule not initialized")
    return discover_boards(path)


_EXPECTED_7SEG = {
    # Board name fragment (must match _prettify_class_name() output)
    # → (num_digits, has_dp, is_multiplexed)
    "DE0": (4, True, False),  # "DE0" board (not DE0 CV)
    "Nandland Go": (2, False, False),
    "DE0 CV": (6, False, False),  # prettified from DE0CVPlatform
    "DE1 So": (6, False, False),  # "DE1 So C" from DE1SoCPlatform
    "DE10": (6, True, False),  # "DE10 Lite"
    "Nexys4": (8, True, True),  # "Nexys4 DDR"
    "RZEasy": (4, True, True),  # "RZEasy FPGAA2-2"
    "Step MXO2": (2, True, True),  # multiplexed, 2 select pins (active-low)
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


# ── Pin data for the pin map (U53) ───────────────────────────────────────────

_BOARDS = discover_boards(get_default_boards_path())


def _board_named(name: str) -> BoardDef:
    match = [b for b in _BOARDS if b.name == name]
    assert len(match) == 1, f"{name}: {len(match)} matches"
    return match[0]


def test_clock_pins_survive_the_loader():
    """They used to be narrowed to bare Hz on the way in and lost."""
    board = _board_named("DE10-Standard")
    assert board.clock_defs[0].pin == "AF14"
    assert board.clock_defs[0].hz == 50_000_000
    assert board.clocks[0] == 50_000_000  # the Hz-only view its consumers use


def test_clock_pins_survive_a_round_trip():
    """to_dict() used to write floats back, erasing the pins it had dropped."""
    board = _board_named("Basys 3")
    again = BoardDef.from_json(board.to_json())
    assert again.clock_defs == board.clock_defs
    assert again.clock_defs[0].pin == "W5"


def test_a_directly_driven_display_has_one_pin_row_per_digit():
    seg = _board_named("DE10-Standard").seven_seg
    assert seg is not None and seg.has_pin_data and not seg.is_scan
    assert len(seg.segment_pins) == seg.num_digits == 6
    assert all(len(row) == 7 for row in seg.segment_pins)
    assert seg.segment_pins[0] == ("W17", "V18", "AG17", "AG16", "AH17", "AG18", "AH18")


def test_a_scanned_display_has_one_shared_row_and_an_enable_per_digit():
    """The enables are what say the single row is shared, not a one-digit board."""
    seg = _board_named("Basys 3").seven_seg
    assert seg is not None and seg.is_scan
    assert len(seg.segment_pins) == 1
    assert seg.segment_pins[0] == ("W7", "W6", "U8", "V8", "U5", "V5", "U7")
    assert seg.digit_enable_pins == ("U2", "U4", "V4", "W4")
    assert len(seg.digit_enable_pins) == seg.num_digits
    assert seg.dp_pins == ("V7",)


def test_the_de2_115_display_is_eight_directly_driven_digits():
    seg = _board_named("DE2-115").seven_seg
    assert seg is not None and seg.has_pin_data and not seg.is_scan
    assert len(seg.segment_pins) == seg.num_digits == 8
    assert all(len(row) == 7 for row in seg.segment_pins)
    assert seg.segment_pins[0] == ("G18", "F22", "E17", "L26", "L25", "J22", "H22")
    assert seg.segment_pins[7] == ("AD17", "AE17", "AG17", "AH17", "AF17", "AG18", "AA14")


def test_the_veek_mt2_is_a_de2_115_underneath():
    """Not a copy-paste: the VEEK-MT2 *is* a DE2-115 with a screen bolted on.

    Same EP4CE115, same Y2 clock, same user I/O pins -- which is why one cited
    source covers both, and why the two must not be allowed to drift apart.
    """
    de2, veek = _board_named("DE2-115"), _board_named("VEEK-MT2")
    assert de2.seven_seg is not None and veek.seven_seg is not None
    assert veek.seven_seg.segment_pins == de2.seven_seg.segment_pins
    assert veek.clock_defs[0].pin == de2.clock_defs[0].pin == "Y2"
    for role in ("leds", "switches", "buttons"):
        got = [c.pins for c in getattr(veek, role)]
        want = [c.pins for c in getattr(de2, role)]
        assert got == want, role


def test_pin_data_is_optional_and_absent_boards_still_load():
    without = [b for b in _BOARDS if b.seven_seg and not b.seven_seg.has_pin_data]
    assert without, "expected boards with a display but no pin data"
    assert all(b.seven_seg is not None and b.seven_seg.num_digits > 0 for b in without)


def test_boards_with_pin_data_are_internally_consistent():
    """Whatever the shape, the pin counts must match what the board claims."""
    for board in _BOARDS:
        seg = board.seven_seg
        if seg is None or not seg.has_pin_data:
            continue
        widths = {len(row) for row in seg.segment_pins}
        assert widths == {7} or widths == {8}, f"{board.name}: segment widths {widths}"
        if seg.is_scan:
            assert len(seg.segment_pins) == 1, board.name
            assert len(seg.digit_enable_pins) == seg.num_digits, board.name
        else:
            assert len(seg.segment_pins) == seg.num_digits, board.name


def test_malformed_pin_data_degrades_instead_of_raising():
    """Board JSON is external data; a bad pin list must not take the board out."""
    seg = SevenSegDef.from_dict(
        {
            "num_digits": 2,
            "has_dp": False,
            "is_multiplexed": False,
            "segment_pins": "not-a-list",
            "digit_enable_pins": {"nope": 1},
        }
    )
    assert seg.segment_pins == () and seg.digit_enable_pins == ()
    assert not seg.has_pin_data and seg.num_digits == 2
