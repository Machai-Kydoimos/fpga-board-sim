"""Sequencing test for hdl/running_light.vhd.

One LED is lit and it walks.  Both halves of that need checking over time: a
still can show one lit LED while the design is stuck, and a design that lights
two at once or jumps two positions looks fine in any frame where it happens to
be at rest.
"""

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge


def _position(dut: Any) -> int:
    """Index of the single lit LED; asserts that exactly one is lit."""
    bits = int(dut.led.value)
    assert bits != 0, "no LED is lit"
    assert bits & (bits - 1) == 0, f"more than one LED is lit: {bits:#0b}"
    return bits.bit_length() - 1


async def _next_move(dut: Any, was: int, limit: int = 40_000) -> int:
    for _ in range(limit):
        await RisingEdge(dut.clk)
        now = _position(dut)
        if now != was:
            return now
    raise AssertionError(f"the lit LED never left position {was}")


@cocotb.test()
async def test_exactly_one_led_walks_one_step_at_a_time(dut):
    """The lit position advances by one each step and wraps at the end."""
    Clock(dut.clk, 10, unit="ns").start()
    dut.sw.value = 0
    dut.btn.value = 0
    for _ in range(5):
        await RisingEdge(dut.clk)

    width = len(dut.led.value)
    position = _position(dut)
    seen = [position]
    for _ in range(width + 2):  # far enough to cross the wrap at least once
        position = await _next_move(dut, position)
        expected = (seen[-1] + 1) % width
        assert position == expected, f"went from {seen[-1]} to {position}, expected {expected}"
        seen.append(position)

    assert 0 in seen and width - 1 in seen, f"never reached both ends: {seen}"
    print(f"PASS running light: walked {' '.join(str(p) for p in seen)}")
