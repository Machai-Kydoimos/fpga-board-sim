"""Headless cocotb tests for rgb_rainbow (U37) - per-channel duty behavior.

Runs against the generated ``sim_wrapper`` (TOPLEVEL=sim_wrapper), like the
duty suite: GHDL-mcode applies ``-r``-time generic overrides to the toplevel's
ports but not to generic-dependent *generate* structure, so a bare
``-r rgb_rainbow -gNUM_RGB_LEDS=...`` run leaves every ``led`` driver
unelaborated (all-U outputs). Instantiating the design through the wrapper -
the product path - elaborates the generics ordinarily on every backend.

Elaborated with NUM_LEDS=7, NUM_RGB_LEDS=2, NUM_SWITCHES=10, COUNTER_BITS=10,
CLK_HALF_NS_INIT=5 (10 ns clock): MONO=1, so led(0) is the switch mirror and
bits 1..6 are site0/site1's (r, g, b) channels. COUNTER_BITS=10 makes every
rate fast: the hue rotation is 2^14 clocks, the cube's red axis sweeps in
2^12, and one PWM period is 256 clocks.

The wrapper free-runs its own clock, so tests pace themselves with Timer
awaits; sampling once per 10 ns clock period over whole PWM periods makes the
sample count the duty byte (the PWM compare is synchronous to the counter).
"""

import cocotb
from cocotb.triggers import Timer

MONO = 1  # led(0) mirrors sw(0); channels sit above it
N_CHANNELS = 6  # 2 sites x (r, g, b)
CLK_NS = 10
PWM_PERIODS = 10  # measurement window: 10 x 256 clocks


async def _settle(dut, sw_value):
    """Apply switches, then let a few clocks pass so the mode takes effect."""
    dut.sw.value = sw_value
    dut.btn.value = 0
    await Timer(3 * CLK_NS, unit="ns")


async def _measure(dut):
    """Per-channel duty over a whole number of PWM periods, by sampling."""
    counts = [0] * N_CHANNELS
    total = 256 * PWM_PERIODS
    for _ in range(total):
        await Timer(CLK_NS, unit="ns")
        led = int(dut.led.value)
        for ch in range(N_CHANNELS):
            counts[ch] += (led >> (MONO + ch)) & 1
    return [c / total for c in counts]


@cocotb.test()
async def mono_led_mirrors_its_switch(dut):
    """led(0) follows sw(0) combinationally, whatever the RGB mode."""
    await _settle(dut, 0b0000000001)  # sw(0)=1, mode 00
    assert int(dut.led.value) & 1 == 1
    await _settle(dut, 0b0000000000)
    assert int(dut.led.value) & 1 == 0


@cocotb.test()
async def white_breathe_drives_all_channels_equally(dut):
    """Mode 11: r = g = b on every site, every single sample."""
    await _settle(dut, 0b11)
    for _ in range(512):
        await Timer(CLK_NS, unit="ns")
        led = int(dut.led.value) >> MONO
        for site in (0, 3):
            r, g, b = (led >> site) & 1, (led >> (site + 1)) & 1, (led >> (site + 2)) & 1
            assert r == g == b, f"white mix broken: r={r} g={g} b={b}"


@cocotb.test()
async def static_hue_zero_is_red_dominant(dut):
    """Mode 01 with hue switches 0: r duty ~254/256, g and b ~1/3 of that."""
    await _settle(dut, 0b01)  # mode 01, sw(9:2) = 0 -> hue 0
    duty = await _measure(dut)
    for site in (0, 3):
        r, g, b = duty[site], duty[site + 1], duty[site + 2]
        assert r > 0.9, f"site {site}: red should saturate at hue 0, got {r:.3f}"
        assert 0.2 < g < 0.5 and 0.2 < b < 0.5, f"site {site}: g={g:.3f} b={b:.3f}"
        assert r > 2 * g and r > 2 * b


@cocotb.test()
async def rotate_mode_sites_are_phase_opposed(dut):
    """Mode 00, two sites: their duties sum to ~1 per channel at every hue.

    Site1's phase offset is 180 degrees and tri(x) + tri(x+128) = 254, so
    the invariant holds even while the hue keeps rotating mid-window.
    """
    await _settle(dut, 0b00)
    duty = await _measure(dut)
    for ch in range(3):
        pair = duty[ch] + duty[3 + ch]
        assert 0.9 < pair < 1.05, f"channel {ch}: opposed duties sum to {pair:.3f}"


@cocotb.test()
async def cube_scan_red_axis_is_the_fast_one(dut):
    """Mode 10: red is the fast cube axis; blue is nearly frozen.

    The red window sweeps its full byte within the measurement window (duty
    ~0.5 averaged), while blue barely moves from wherever the counter sits.
    """
    await _settle(dut, 0b10)
    # Two consecutive windows: red's average stays ~0.5 (full sweeps), blue's
    # value is nearly identical window-to-window (slow axis).
    first = await _measure(dut)
    second = await _measure(dut)
    for site in (0, 3):
        assert 0.3 < first[site] < 0.7, f"red axis not sweeping: {first[site]:.3f}"
        drift = abs(second[site + 2] - first[site + 2])
        assert drift < 0.1, f"blue axis moved too fast: {drift:.3f}"


@cocotb.test()
async def button_forces_full_white(dut):
    """Any held button snaps every channel to (near) full duty."""
    await _settle(dut, 0b00)
    dut.btn.value = 0b01
    await Timer(3 * CLK_NS, unit="ns")
    duty = await _measure(dut)
    dut.btn.value = 0
    for ch in range(N_CHANNELS):
        assert duty[ch] > 0.99, f"channel {ch} not forced full: {duty[ch]:.3f}"
