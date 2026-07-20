"""Headless cocotb tests for the U9 duty engine (sim/duty/*.vhd.frag).

Runs against a **Full-mode** ``sim_wrapper`` wrapped around ``duty_probe.vhd``,
whose channels have exactly-known duty cycles, and asserts the measured values
against that ground truth through the same math the headless child uses
(``fpga_sim.sim_duty.DutyTracker``).  Driven by ``tests/test_duty.py`` under
both GHDL and NVC.

Elaborated with NUM_LEDS=8, NUM_SWITCHES=4, CLK_HALF_NS_INIT=5, so the clock
period is 10 ns and duty_probe's channels are:

    led(0) '0'                     led(3) 50% @ 1000 ns (non-power-of-two)
    led(1) '1'                     led(4) = sw(0)  (combinational)
    led(2) 25% @ 2560 ns, sw(1)-gated              led(5..7) '0'

The tests share one simulation, so they run in declaration order and simulated
time carries over; the >2.147 s overflow probe is deliberately last.
"""

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time

from fpga_sim.sim_duty import DutyTracker

NUM_LEDS = 8

#: VHDL INTEGER is 32-bit: a naive ``now / 1 ns`` dies past this many ns.
_INTEGER_MAX_NS = 2**31 - 1


def _snapshot(dut, tracker):
    """Fold one instant's led/accumulator reads into *tracker* and return the duties.

    All three reads happen with no ``await`` between them, so the levels and the
    accumulators describe the same instant -- the coherence the in-progress-
    interval term depends on.  Returns ``None`` when no simulated time has
    passed since the previous snapshot (i.e. when priming).
    """
    return tracker.update(
        int(dut.led_acc.value),
        int(dut.led_tch.value),
        int(dut.led.value),
        round(get_sim_time("ns")),
    )


async def _measure(dut, window_ns):
    """Duty of every channel over the next *window_ns* nanoseconds."""
    tracker = DutyTracker(NUM_LEDS)
    _snapshot(dut, tracker)  # prime: anchors the window at "now"
    await Timer(window_ns, unit="ns")
    duties = _snapshot(dut, tracker)
    assert duties is not None, "window advanced no simulated time"
    return duties


@cocotb.test()
async def test_accumulators_readable_at_t0(dut):
    """Before anything runs, both accumulators read as clean zeros, not 'U'.

    The wrapper initializes the ports (``:= (others => '0')``) precisely so the
    child's very first read cannot land on a metavalue: one 'U' bit anywhere in
    the vector would poison ``int()`` for every channel at once.
    """
    assert int(dut.led_acc.value) == 0, "led_acc not zero-initialized"
    assert int(dut.led_tch.value) == 0, "led_tch not zero-initialized"
    print("PASS metavalue-clean at t=0")


@cocotb.test()
async def test_static_duties(dut):
    """Each channel's measured duty matches its known ground truth."""
    dut.sw.value = 0b11  # sw(0) -> led(4) on, sw(1) -> led(2) PWM enabled
    dut.btn.value = 0
    await Timer(1000, unit="ns")  # settle inputs, leave t=0 behind

    # 256 us = 100 periods of the 25% channel, 256 of the 50% channel, so a
    # partial period at either end can move the result by at most ~0.25%.
    duties = await _measure(dut, 256_000)

    assert duties[0] == 0.0, f"stuck-OFF channel measured {duties[0]}"
    assert duties[1] == 1.0, f"stuck-ON channel measured {duties[1]}"
    assert abs(duties[2] - 0.25) < 0.01, f"25% channel measured {duties[2]}"
    assert abs(duties[3] - 0.50) < 0.01, f"50% channel measured {duties[3]}"
    assert duties[4] == 1.0, f"sw-driven channel measured {duties[4]}"
    assert all(d == 0.0 for d in duties[5:]), f"spare channels measured {duties[5:]}"
    print(f"PASS static duties: {[round(d, 4) for d in duties]}")


@cocotb.test()
async def test_mid_run_gate_flip(dut):
    """Duty tracks a channel that changes level partway through the run.

    Covers the two cases a naive integrator gets wrong: a channel that is *on*
    at the snapshot instant (its in-progress interval has not been folded into
    the accumulator yet) and one whose last change predates the window.
    """
    dut.sw.value = 0b00
    await Timer(1000, unit="ns")
    off = await _measure(dut, 100_000)
    assert off[4] == 0.0, f"gated-off channel measured {off[4]}"
    assert off[2] == 0.0, f"gated-off PWM channel measured {off[2]}"

    dut.sw.value = 0b01  # led(4) high for the whole of the next window
    await Timer(1000, unit="ns")
    on = await _measure(dut, 100_000)
    assert on[4] == 1.0, f"gated-on channel measured {on[4]}"

    # Flip halfway through a window: half on, half off.
    tracker = DutyTracker(NUM_LEDS)
    _snapshot(dut, tracker)
    await Timer(50_000, unit="ns")
    dut.sw.value = 0b00
    await Timer(50_000, unit="ns")
    half = _snapshot(dut, tracker)
    assert abs(half[4] - 0.5) < 0.001, f"half-window flip measured {half[4]}"
    print(f"PASS gate flip: off={off[4]} on={on[4]} half={round(half[4], 4)}")


@cocotb.test()
async def test_long_gap_no_integer_overflow(dut):
    """Time math stays exact past 2.147 s, where a plain ``now / 1 ns`` overflows.

    Slowing the wrapper's clock to a 0.1 s half-period lets the run reach 2.4 s
    of simulated time in a handful of events, then a fresh transition stamps
    ``led_tch`` on the far side of the 32-bit INTEGER boundary.  A broken
    decomposition either kills the simulation outright or writes a wrapped
    timestamp, which the duty assertion below would catch.
    """
    dut.sw.value = 0b00
    dut.clk_half_ns.value = 100_000_000  # 0.1 s half-period: skip time cheaply
    await Timer(2_400_000_000, unit="ns")

    now_ns = round(get_sim_time("ns"))
    assert now_ns > _INTEGER_MAX_NS, f"gap did not clear the INTEGER boundary: {now_ns}"

    dut.sw.value = 0b01  # led(4) rises here, well past 2**31 ns
    await Timer(1000, unit="ns")

    tch4 = (int(dut.led_tch.value) >> (48 * 4)) & ((1 << 48) - 1)
    assert tch4 > _INTEGER_MAX_NS, f"led_tch(4) did not record the late change: {tch4}"
    assert abs(tch4 - now_ns) < 1000, f"led_tch(4)={tch4} is not the flip time {now_ns}"

    duties = await _measure(dut, 1_000_000)
    assert duties[4] == 1.0, f"channel measured {duties[4]} after the long gap"
    assert duties[1] == 1.0, f"stuck-ON channel measured {duties[1]} after the long gap"
    print(f"PASS long gap: now={now_ns} ns, led_tch(4)={tch4} ns")
