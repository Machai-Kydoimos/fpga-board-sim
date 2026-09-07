"""Behavioral test for hdl/gates_mux.vhd.

The design's header states a truth table, and this checks it exhaustively --
all four functions across all four input combinations, sixteen cases in total.
That matters more here than for a bigger design: `gates_mux.vhd` is the file a
beginner is pointed at first, and its whole value is that the table in the
comment can be trusted to describe the hardware.
"""

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

# sel -> the function of (a, b) the header promises.
_FUNCTIONS = {
    0b00: lambda a, b: a & b,
    0b01: lambda a, b: a | b,
    0b10: lambda a, b: a ^ b,
    0b11: lambda a, b: 1 - a,  # not a; b ignored
}


def _leds(dut: Any) -> int:
    return int(dut.led.value)


@cocotb.test()
async def test_the_truth_table_in_the_header_is_the_real_one(dut):
    """Every (sel, a, b) gives the documented result on led(0)."""
    Clock(dut.clk, 10, unit="ns").start()
    dut.btn.value = 0
    await Timer(20, unit="ns")

    for sel, expected in _FUNCTIONS.items():
        for a in (0, 1):
            for b in (0, 1):
                dut.sw.value = (sel << 2) | (b << 1) | a
                await Timer(20, unit="ns")
                got = _leds(dut) & 1
                want = expected(a, b)
                assert got == want, (
                    f"sel={sel:02b} a={a} b={b}: led(0)={got}, header promises {want}"
                )

    print("PASS gates_mux: all 16 cases match the documented truth table")


@cocotb.test()
async def test_the_inputs_are_echoed(dut):
    """led(1) and led(2) show a and b, so the switch positions are visible."""
    Clock(dut.clk, 10, unit="ns").start()
    dut.btn.value = 0
    await Timer(20, unit="ns")

    assert len(dut.led.value) >= 3, "this test needs three LEDs at the boundary"
    for a in (0, 1):
        for b in (0, 1):
            dut.sw.value = (b << 1) | a
            await Timer(20, unit="ns")
            leds = _leds(dut)
            assert (leds >> 1) & 1 == a, f"led(1) should echo a={a}"
            assert (leds >> 2) & 1 == b, f"led(2) should echo b={b}"

    print("PASS gates_mux: LEDs 1 and 2 echo the two data switches")
