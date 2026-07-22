"""Regression suite for issue #309: the walker must stay visible past 16 LEDs.

The generated ``cpu_io``'s LED output is a 16-bit register pair ($E020/$E021)
zero-extended onto the board's ``led`` boundary, so LED positions 16+ are
physically unreachable.  The config register at $E004 therefore reports
``minimum(NUM_LEDS, 16)`` and the firmware bounces the walker within the range
it can actually light.  Pre-fix, a 27-channel board (DE2-115) read N=27 and the
one-hot walker went dark for 11 steps of every sweep.

Run against a walking-style system with NUM_LEDS wider than the LED register
(the driver uses 27, the DE2-115's channel count).  Timing follows
test_cpu_walking: one prescaler tick == one step at full switch speed (~41 us
at the wrapper's 40 ns period); sampling every 20 us outruns the step rate, so
every visited position is observed.
"""

from typing import Any

import cocotb
from cocotb.triggers import Timer

_STEP_NS = 41_000  # one prescaler tick == one step at full switch speed
_LED_REG_WIDTH = 16  # width of cpu_io's led_reg — the visible-position ceiling


def _leds(dut: Any) -> int:
    return int(dut.led.value)


@cocotb.test()
async def walker_stays_visible_and_bounces_within_register(dut):
    """On a >16-LED board the walker never goes dark and sweeps exactly LED0-15."""
    dut.sw.value = (1 << len(dut.sw.value)) - 1  # all switches on -> step every tick
    dut.btn.value = 0

    await Timer(5 * _STEP_NS, "ns")  # boot: firmware reads config, lights LED0

    # A full bounce cycle over 16 positions is 30 steps (~1.23 ms); 100 samples
    # at 20 us span ~1.6 cycles while sampling faster than the walker steps.
    positions: list[int] = []
    for _ in range(100):
        await Timer(20_000, "ns")
        led = _leds(dut)
        assert led != 0, (
            f"walker went dark (led = 0) after {positions}: "
            "config must report the reachable LED count, not the board count"
        )
        assert (led & (led - 1)) == 0, f"LED not one-hot: 0x{led:X}"
        positions.append(led.bit_length() - 1)

    assert max(positions) == _LED_REG_WIDTH - 1, (
        f"walker never reached LED{_LED_REG_WIDTH - 1}: positions {sorted(set(positions))}"
    )
    deltas = [b - a for a, b in zip(positions, positions[1:], strict=False) if b != a]
    assert any(d > 0 for d in deltas), f"LED never walked up: {positions}"
    assert any(d < 0 for d in deltas), f"LED never walked down (no bounce): {positions}"
