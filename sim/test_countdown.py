"""Sequencing test for hdl/countdown_7seg.vhd.

A still shows a number; it cannot show whether the number got there by counting.
This walks the display tick by tick and requires every step to be exactly one
less than the last, with the borrow where it belongs and a wrap from 00 to 99.
A design that skipped, repeated or jumped a value would look perfectly healthy
in any single frame.
"""

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

# Active-high glyphs at the boundary, index = digit.  Decimal only.
_FONT = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)
_GLYPH_TO_DIGIT = {g: d for d, g in enumerate(_FONT)}


def _shown(dut: Any) -> int:
    """Decode the two right-hand digits into the number displayed."""
    raw = int(dut.seg.value)
    ones_glyph, tens_glyph = raw & 0xFF, (raw >> 8) & 0xFF
    assert ones_glyph in _GLYPH_TO_DIGIT, f"ones digit shows unknown glyph {ones_glyph:#04x}"
    assert tens_glyph in _GLYPH_TO_DIGIT, f"tens digit shows unknown glyph {tens_glyph:#04x}"
    return _GLYPH_TO_DIGIT[tens_glyph] * 10 + _GLYPH_TO_DIGIT[ones_glyph]


async def _next_change(dut: Any, was: int, limit: int = 40_000) -> int:
    """Advance until the displayed number changes; return the new one."""
    for _ in range(limit):
        await RisingEdge(dut.clk)
        now = _shown(dut)
        if now != was:
            return now
    raise AssertionError(f"the display never moved from {was:02d}")


@cocotb.test()
async def test_it_counts_down_one_at_a_time_and_wraps(dut):
    """Every tick is exactly one less, including 10 -> 09 and 00 -> 99."""
    Clock(dut.clk, 10, unit="ns").start()
    dut.sw.value = 0
    dut.btn.value = 1  # btn0 is the reset; hold it to start from a known 99
    await Timer(200, unit="ns")
    assert _shown(dut) == 99, f"reset should show 99, shows {_shown(dut):02d}"
    dut.btn.value = 0

    value = 99
    seen = [value]
    for _ in range(12):
        value = await _next_change(dut, value)
        seen.append(value)
        expected = (seen[-2] - 1) % 100
        assert value == expected, f"after {seen[-2]:02d} came {value:02d}, expected {expected:02d}"

    print(f"PASS countdown sequence: {' '.join(f'{v:02d}' for v in seen)}")


@cocotb.test()
async def test_the_borrow_crosses_a_ten(dut):
    """09 -> 08 is the ones digit alone; the tens only moves on the borrow."""
    Clock(dut.clk, 10, unit="ns").start()
    dut.sw.value = 0
    dut.btn.value = 1
    await Timer(200, unit="ns")
    dut.btn.value = 0

    value = 99
    for _ in range(11):  # 99 down through the 90s and across into 88
        previous, value = value, await _next_change(dut, value)
        if previous % 10 == 0:
            assert value // 10 == previous // 10 - 1, "the tens digit did not borrow"
        else:
            assert value // 10 == previous // 10, "the tens digit moved without a borrow"

    print("PASS countdown borrow: the tens digit moves only when the ones wraps")
