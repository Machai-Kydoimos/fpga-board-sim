"""Headless cocotb check for the U56 Phase 6 LED-alias designs.

Runs against the native ``sim_wrapper`` around a ``tests/fixtures/led_aliases``
design (driven by ``tests/test_led_alias_designs.py`` under GHDL and NVC): the
design drives an LED through one of its upstream aliases, and the wrapper's
channel map must land it on the boundary channel of that LED.
"""

import os

import cocotb
from cocotb.triggers import Timer


@cocotb.test()
async def the_alias_lights_its_leds_boundary_channel(dut):
    """Check the boundary ``led`` reads the pattern the design drove, MSB first."""
    await Timer(200, unit="ns")
    want = os.environ["ALIAS_EXPECT_LED"]
    got = str(dut.led.value)
    assert got == want, f"boundary led = {got}, expected {want}"
