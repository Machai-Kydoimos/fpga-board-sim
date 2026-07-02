"""Behavioral test for the hand-written interactive stopwatch design.

btn(0) starts/stops the count; btn(1) resets the digits to all-zero without
changing whether it is running. All switches are driven high for the fastest
count rate (see hdl/stopwatch_7seg.vhd's idx_proc).
"""

import cocotb
from cocotb.triggers import Timer

_TICK_NS = 164_000  # one time-base tick at COUNTER_BITS=17, all switches high (fastest rate)

# Decimal-to-7-seg glyphs for digits 0-9 (must match the design's SEG_LUT).
_BCD_GLYPHS = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F)
_GLYPH_TO_DIGIT = {glyph: digit for digit, glyph in enumerate(_BCD_GLYPHS)}


def _segs(dut):
    """Return the per-digit segment bytes, digit 0 (units) first."""
    raw = int(dut.seg.value)
    return [(raw >> (8 * i)) & 0xFF for i in range(len(dut.seg.value) // 8)]


def _number(dut):
    """Decode the displayed digits into a decimal value, or None if not all glyphs."""
    value = 0
    for i, glyph in enumerate(_segs(dut)):
        digit = _GLYPH_TO_DIGIT.get(glyph)
        if digit is None:
            return None
        value += digit * (10**i)
    return value


async def _press(dut, bit):
    """Pulse btn[bit] high for one tick then low, so the rising edge registers."""
    dut.btn.value = 1 << bit
    await Timer(_TICK_NS, "ns")
    dut.btn.value = 0
    await Timer(_TICK_NS, "ns")


@cocotb.test()
async def stopwatch_starts_stopped_then_runs_stops_and_resets(dut):
    """Cold: static at 0. btn(0): starts counting. btn(0) again: freezes. btn(1): resets."""
    dut.sw.value = (1 << len(dut.sw.value)) - 1  # all switches on -> fastest rate
    dut.btn.value = 0

    # Cold start: static at 0 until btn(0) is pressed.
    await Timer(3 * _TICK_NS, "ns")
    assert _number(dut) == 0, f"did not start at 0: {_segs(dut)}"
    await Timer(3 * _TICK_NS, "ns")
    assert _number(dut) == 0, f"advanced while stopped: {_segs(dut)}"

    # btn(0): start counting.
    await _press(dut, 0)
    await Timer(3 * _TICK_NS, "ns")
    running_value = _number(dut)
    assert running_value is not None and running_value > 0, f"did not advance: {_segs(dut)}"

    # btn(0) again: stop. Two samples apart must be equal (frozen).
    await _press(dut, 0)
    frozen_first = _number(dut)
    await Timer(3 * _TICK_NS, "ns")
    assert _number(dut) == frozen_first, (
        f"value changed while stopped: {frozen_first} -> {_number(dut)}"
    )

    # btn(1): reset digits to all-zero (running is already stopped here).
    await _press(dut, 1)
    assert _number(dut) == 0, f"did not reset to 0: {_segs(dut)}"
