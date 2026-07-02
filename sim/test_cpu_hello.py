"""Behavioral test for the embedded-core "hello" design -- the newcomer on-ramp.

The firmware (firmware/mx65_hello_7seg.s) is the smallest program that proves
the IO path: light LED0, show "0" on digit 0, then hold forever. Unlike the
walking-counter suite this design is deliberately static, so the one check
below confirms the one-time write landed and nothing ever changes afterward.
"""

import cocotb
from cocotb.triggers import Timer

_SETTLE_NS = 50_000  # generous margin over the ~20-instruction reset sequence
_HOLD_NS = 20_000


def _leds(dut):
    return int(dut.led.value)


def _segs(dut):
    """Return the per-digit segment bytes, digit 0 (units) first."""
    raw = int(dut.seg.value)
    return [(raw >> (8 * i)) & 0xFF for i in range(len(dut.seg.value) // 8)]


@cocotb.test()
async def hello_lights_led0_and_holds_forever(dut):
    """After reset settles: LED0 lit, digit 0 = glyph '0', rest blank -- and static."""
    await Timer(_SETTLE_NS, "ns")
    assert _leds(dut) == 0x01, f"led = 0x{_leds(dut):X}, expected 0x01 (LED0 only)"
    segs = _segs(dut)
    assert segs[0] == 0x3F, f"digit 0 = 0x{segs[0]:02X}, expected 0x3F (glyph '0')"
    assert all(b == 0x00 for b in segs[1:]), f"other digits not blank: {segs}"

    await Timer(_HOLD_NS, "ns")
    assert _leds(dut) == 0x01, f"led changed: 0x01 -> 0x{_leds(dut):X}"
    assert _segs(dut) == segs, f"segments changed: {segs} -> {_segs(dut)}"
