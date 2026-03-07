"""Minimal smoke test for GHDL + cocotb VPI pipeline."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer


@cocotb.test()
async def smoke_test(dut):
    """Just start a clock, set inputs, read outputs."""
    cocotb.start_soon(Clock(dut.clk, 10, units="ns").start())

    dut.sw.value = 0
    dut.btn.value = 0

    # Run for a bit
    await Timer(100, units="ns")

    # Toggle a switch
    dut.sw.value = 0b0001
    await Timer(200, units="ns")

    led_val = int(dut.led.value)
    print(f"LED value after sw=0001: {led_val:#06b}")

    # All buttons
    dut.btn.value = 0b1111
    await Timer(100, units="ns")

    led_val = int(dut.led.value)
    print(f"LED value after btn=1111: {led_val:#06b}")
    print("SMOKE TEST PASSED")
