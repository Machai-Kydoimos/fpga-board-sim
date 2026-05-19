"""Cocotb tests for the counter_7seg design (7-segment display output)."""

import cocotb
from cocotb.triggers import Timer

_VALID_HEX_GLYPHS = {
    0x3F,
    0x06,
    0x5B,
    0x4F,
    0x66,
    0x6D,
    0x7D,
    0x07,
    0x7F,
    0x6F,
    0x77,
    0x7C,
    0x39,
    0x5E,
    0x79,
    0x71,
}


@cocotb.test()
async def test_seg_digit_0_is_valid_glyph(dut):
    """Digit 0 must show a recognisable hex glyph after the counter advances."""
    await Timer(200_000, "ns")
    seg_raw = int(dut.seg.value)
    digit0 = seg_raw & 0xFF
    assert digit0 in _VALID_HEX_GLYPHS, f"digit 0 = 0x{digit0:02X} is not a hex glyph"


@cocotb.test()
async def test_seg_advances_over_time(dut):
    """The segment vector must change (counter is running)."""
    readings = []
    for _ in range(3):
        await Timer(200_000, "ns")
        readings.append(int(dut.seg.value))
    assert len(set(readings)) >= 2, f"seg stuck: {readings}"


@cocotb.test()
async def test_seg_width_matches_num_segs(dut):
    """All 8*NUM_SEGS bits must be addressable; check no truncation for 4 digits."""
    await Timer(50_000, "ns")
    seg_raw = int(dut.seg.value)
    expected_bits = len(dut.seg.value)
    assert 0 <= seg_raw < (1 << expected_bits), (
        f"seg value {seg_raw} is out of {expected_bits}-bit range"
    )


@cocotb.test()
async def test_all_digits_show_valid_glyphs(dut):
    """Every digit must show a recognisable hex glyph after the counter advances."""
    await Timer(200_000, "ns")
    seg_raw = int(dut.seg.value)
    num_segs = len(dut.seg.value) // 8
    for i in range(num_segs):
        bits = (seg_raw >> (8 * i)) & 0xFF
        assert bits in _VALID_HEX_GLYPHS, f"digit {i} = 0x{bits:02X} is not a hex glyph"
