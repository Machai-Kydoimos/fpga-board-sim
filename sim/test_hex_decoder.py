"""Behavioral test for hdl/hex_decoder_7seg.vhd.

The design is combinational: a byte on the switches appears immediately on the
two right-hand digits in hex.  The test drives every one of the 256 byte values
and decodes the digits back, so it checks the whole font rather than a sample --
a decoder is exactly the kind of table where one wrong entry hides forever.
"""

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

# Active-high glyphs at the simulator's boundary, index = nibble value.
# Must match hdl/hex_decoder_7seg.vhd's `to_seg`.
_GLYPHS = (
    0x3F,  # 0
    0x06,  # 1
    0x5B,  # 2
    0x4F,  # 3
    0x66,  # 4
    0x6D,  # 5
    0x7D,  # 6
    0x07,  # 7
    0x7F,  # 8
    0x6F,  # 9
    0x77,  # A
    0x7C,  # b
    0x39,  # C
    0x5E,  # d
    0x79,  # E
    0x71,  # F
)
_GLYPH_TO_NIBBLE = {glyph: value for value, glyph in enumerate(_GLYPHS)}


def _digit(dut: Any, index: int) -> int:
    """Return the nibble displayed on digit *index*, decoded through the font."""
    raw = int(dut.seg.value)
    glyph = (raw >> (8 * index)) & 0xFF
    assert glyph in _GLYPH_TO_NIBBLE, f"digit {index} shows an unknown glyph {glyph:#04x}"
    return _GLYPH_TO_NIBBLE[glyph]


@cocotb.test()
async def test_every_byte_reads_back(dut):
    """All 256 switch values decode to the right two hex digits."""
    Clock(dut.clk, 10, unit="ns").start()
    dut.btn.value = 0
    await Timer(20, unit="ns")

    width = len(dut.sw.value)
    assert width >= 8, f"this test needs 8 switches at the boundary, got {width}"

    for value in range(256):
        dut.sw.value = value
        await Timer(20, unit="ns")
        low, high = _digit(dut, 0), _digit(dut, 1)
        shown = (high << 4) | low
        assert shown == value, f"sw={value:#04x} displayed {shown:#04x} (digits {high:x}{low:x})"

    print("PASS hex decoder: all 256 byte values render correctly")


@cocotb.test()
async def test_leds_mirror_the_switches(dut):
    """The LEDs show the same byte in binary, as far as they reach."""
    Clock(dut.clk, 10, unit="ns").start()
    dut.btn.value = 0
    await Timer(20, unit="ns")

    n_led = len(dut.led.value)
    for value in (0x00, 0x5A, 0xA5, 0xFF):
        dut.sw.value = value
        await Timer(20, unit="ns")
        expected = value & ((1 << min(n_led, 8)) - 1)
        actual = int(dut.led.value) & ((1 << min(n_led, 8)) - 1)
        assert actual == expected, f"sw={value:#04x}: led low bits {actual:#04x} != {expected:#04x}"

    print("PASS hex decoder: LEDs mirror the switch byte")
