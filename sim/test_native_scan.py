"""Headless cocotb duty tests for the U22 native scan designs (Phase E).

Runs against a **Full-mode native** ``sim_wrapper`` wrapped around
``hdl/native/nexys4ddr_scan.vhd`` or ``hdl/native/basys3_scan.vhd`` (driven by
``tests/test_native_scan_design.py`` under GHDL and NVC).  The wrapper
demultiplexes the design's physical scan drive (shared segment lines + digit
enables, all active-low) onto the packed ``seg`` boundary combinationally and
unlatched, so the U9 duty accumulators integrate the *honest* scan physics:

* a lit segment of a scanned digit measures ~1/NUM_SEGS duty (its enable is
  active one slot in NUM_SEGS);
* an unlit segment measures ~0;
* the lamp test (btn(0), BTNC) enables every digit simultaneously -> ~100%.

Both designs show a hex counter whose displayed value taps counter bits 18+,
so within this suite's ~1 ms of simulated time every digit's glyph is the
static "0" (segments a..f lit, g dark) -- exact ground truth on every digit,
not just the top one.  The dp line marks digit 0 only.

The tests share one simulation and run in declaration order; the lamp test is
last so its all-on drive cannot leak into the scan-duty windows.  Digit count
is inferred from the boundary width (``len(dut.seg) / 8``), so the one module
serves both the 8-digit Nexys 4 DDR and the 4-digit Basys 3.
"""

import cocotb
from cocotb.triggers import Timer
from cocotb.utils import get_sim_time

from fpga_sim.sim_duty import DutyTracker

#: {dp,g,f,e,d,c,b,a} bit positions within a digit's boundary byte.
_SEG_A, _SEG_F, _SEG_G, _SEG_DP = 0, 5, 6, 7

#: Digit slot = 128 clocks at the 10 ns test period -> 1.28 us; the 256 us
#: windows below span 25 (Nexys) / 50 (Basys) whole scan sweeps, so start/end
#: slot truncation moves a duty by at most ~4% relative.
_WINDOW_NS = 256_000
_REL_TOL = 0.15
_OFF_TOL = 0.02


def _num_segs(dut):
    """Digit count, inferred from the packed boundary width (8 bits/digit)."""
    return len(dut.seg) // 8


def _snapshot(dut, tracker):
    """One coherent seg + accumulator read folded into *tracker* (no awaits)."""
    return tracker.update(
        int(dut.seg_acc.value),
        int(dut.seg_tch.value),
        int(dut.seg.value),
        round(get_sim_time("ns")),
    )


async def _measure_seg(dut, window_ns=_WINDOW_NS):
    """Duty of every seg channel over the next *window_ns* nanoseconds."""
    tracker = DutyTracker(8 * _num_segs(dut))
    _snapshot(dut, tracker)  # prime: anchors the window at "now"
    await Timer(window_ns, unit="ns")
    duties = _snapshot(dut, tracker)
    assert duties is not None, "window advanced no simulated time"
    return duties


@cocotb.test()
async def test_seg_accumulators_readable_at_t0(dut):
    """The seg accumulators start as clean zeros, not metavalues (U9 contract)."""
    assert int(dut.seg_acc.value) == 0, "seg_acc not zero-initialized"
    assert int(dut.seg_tch.value) == 0, "seg_tch not zero-initialized"
    print("PASS seg accumulators metavalue-clean at t=0")


@cocotb.test()
async def test_scan_digits_show_zero_at_scan_brightness(dut):
    """Every digit's "0" glyph measures at the honest 1/NUM_SEGS scan duty.

    The displayed value is 0 throughout this suite (content taps counter bits
    18+), so on every digit segments a..f are lit -- each active exactly one
    slot per sweep -- and g is dark.  This is the U22 done-when: correct
    digits via the physical scan interface, at physical scan brightness.
    """
    digits = _num_segs(dut)
    dut.sw.value = 0
    dut.btn.value = 0
    await Timer(10_000, unit="ns")  # settle inputs, leave t=0 behind

    duties = await _measure_seg(dut)
    slot = 1.0 / digits
    for d in range(digits):
        for k in range(_SEG_A, _SEG_F + 1):  # a..f: lit one slot per sweep
            got = duties[8 * d + k]
            assert abs(got - slot) <= slot * _REL_TOL, (
                f"digit {d} segment {k}: duty {got:.4f}, expected ~{slot:.4f}"
            )
        assert duties[8 * d + _SEG_G] <= _OFF_TOL, (
            f"digit {d} segment g should be dark, measured {duties[8 * d + _SEG_G]:.4f}"
        )
    print(f"PASS {digits} digits show '0' at ~{slot:.3f} scan duty")


@cocotb.test()
async def test_dp_marks_digit0_only(dut):
    """The shared dp line is driven only during digit 0's slot."""
    digits = _num_segs(dut)
    duties = await _measure_seg(dut)
    slot = 1.0 / digits
    got0 = duties[8 * 0 + _SEG_DP]
    assert abs(got0 - slot) <= slot * _REL_TOL, f"digit 0 dp: duty {got0:.4f}, expected ~{slot:.4f}"
    for d in range(1, digits):
        assert duties[8 * d + _SEG_DP] <= _OFF_TOL, (
            f"digit {d} dp should be dark, measured {duties[8 * d + _SEG_DP]:.4f}"
        )
    print("PASS dp gated to digit 0's slot")


@cocotb.test()
async def test_lamp_test_lights_everything(dut):
    """btn(0) (BTNC) enables all digits at once: every channel near 100%.

    Deliberately last: the all-on drive would otherwise contaminate the
    scan-duty windows above (the suite shares one simulation).
    """
    digits = _num_segs(dut)
    dut.btn.value = 1  # BTNC is the buttons bank's first scalar -> btn(0)
    await Timer(10_000, unit="ns")  # settle past the press

    duties = await _measure_seg(dut)
    for ch in range(8 * digits):
        assert duties[ch] >= 0.90, f"lamp test: channel {ch} at {duties[ch]:.4f}, expected ~1"
    print(f"PASS lamp test: all {8 * digits} channels lit")
