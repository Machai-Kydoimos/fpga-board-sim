"""When the board looks frozen (U48): the judgment and the arithmetic.

A design whose visible rate comes from the top bits of a clock divider is
correct, runs, and shows nothing.  These tests are mostly about the two ways
that observation can be got wrong: blaming the student when the *simulator*
stopped, and losing the timer because they touched a switch.
"""

import pytest

from fpga_sim.stall import (
    DEFAULT_THRESHOLD_S,
    StallFacts,
    StallWatch,
    stall_heading,
    stall_message,
)

_T = DEFAULT_THRESHOLD_S


def _quiet(watch, *, frames=3, start=0.0, step=_T, sim_ns=1_000_000, sig="same"):
    """Hold one signature across *frames* samples, advancing sim time each one."""
    out = False
    for i in range(frames):
        out = watch.sample(sig, sim_ns * (i + 1), start + step * i)
    return out


# ── Detection ────────────────────────────────────────────────────────────────


def test_a_changing_board_never_fires():
    w = StallWatch()
    for i in range(20):
        assert not w.sample(f"frame{i}", 1_000_000 * (i + 1), i * 2.0)


def test_quiet_outputs_with_time_advancing_fire():
    w = StallWatch()
    assert not w.sample("same", 1_000_000, 0.0)
    assert not w.sample("same", 2_000_000, _T - 0.1)
    assert w.sample("same", 3_000_000, _T + 0.1)


def test_a_stopped_simulator_is_never_blamed_on_the_design():
    """The clause that separates "your design is slow" from "we stopped"."""
    w = StallWatch()
    assert not w.sample("same", 5_000_000, 0.0)
    for t in (_T + 1, _T + 10, _T + 60):
        assert not w.sample("same", 5_000_000, t), "sim time never advanced"


def test_a_paused_run_is_not_a_symptom():
    w = StallWatch()
    w.sample("same", 1_000_000, 0.0)
    assert not w.sample("same", 1_000_000, _T + 5, paused=True)
    # and un-pausing starts the clock again rather than firing instantly
    assert not w.sample("same", 2_000_000, _T + 6)


def test_a_switch_flip_must_not_reset_the_timer():
    """It cannot, because the signature it is fed carries outputs only.

    The guard for that is in `output_signature`; here we pin the consequence:
    identical output signatures keep counting no matter what else moved.
    """
    w = StallWatch()
    w.sample(("leds", 0), 1_000_000, 0.0)
    assert w.sample(("leds", 0), 9_000_000, _T + 0.1)


def test_one_step_does_not_take_the_offer_away():
    """The step is evidence *for* the slow-divider reading, not against it.

    A design that toggles an LED once every thirty seconds is exactly the case
    this exists for, and hiding the offer the instant that is confirmed -- then
    bringing it back ten seconds later, forever -- would be both wrong and a
    flicker.
    """
    w = StallWatch()
    w.sample("a", 1_000_000, 0.0)
    assert w.sample("a", 2_000_000, _T + 1)
    assert w.sample("b", 3_000_000, _T + 2), "one step must not withdraw it"
    assert w.sample("b", 4_000_000, _T + 3)


def test_a_board_that_really_is_running_loses_the_offer_and_keeps_it_lost():
    w = StallWatch()
    w.sample("a", 1_000_000, 0.0)
    assert w.sample("a", 2_000_000, _T + 1)
    # ...and now it animates continuously
    for i in range(60):
        showing = w.sample(f"f{i}", 3_000_000 + i * 100_000, _T + 2 + i)
    assert not showing
    assert not w.sample("done", 90_000_000, _T + 200)


def test_the_quiet_timer_still_restarts_on_a_step():
    """Lingering is only about what is *shown*; the measurement window resets."""
    w = StallWatch()
    w.sample("a", 1_000_000, 0.0)
    w.sample("a", 2_000_000, _T + 1)
    w.sample("b", 3_000_000, _T + 2)
    facts = w.facts(3_500_000, _T + 3, 50e6, 50e6)
    assert facts.quiet_s == pytest.approx(1.0), "measured from the step, not before it"


# ── A design that is merely waiting for input ────────────────────────────────
#
# The false positive this module was shipped with.  A design that lights an LED
# while a button is held is *correct* to show nothing when nobody is pressing
# anything -- and on the wire that is indistinguishable from a stalled divider:
# static inputs, static outputs, simulated time advancing.  The trigger cannot
# separate them, so the message must carry both readings.


def test_an_idle_input_follower_still_trips_the_watch():
    """It has to: there is no observation that separates it from a slow divider."""
    w = StallWatch()
    leds_all_off = ((0,) * 10, ())
    nobody_touching = (("off",) * 10, ())
    w.sample(leds_all_off, 1_000_000, 0.0, inputs=nobody_touching)
    assert w.sample(leds_all_off, 9_000_000, _T + 1, inputs=nobody_touching)


def test_untouched_controls_are_remembered():
    w = StallWatch()
    quiet = ((0,) * 10, ())
    w.sample(quiet, 1_000_000, 0.0, inputs=("a",))
    w.sample(quiet, 2_000_000, 1.0, inputs=("a",))
    assert not w.inputs_used


def test_a_touched_control_is_remembered_even_after_it_is_put_back():
    w = StallWatch()
    quiet = ((0,) * 10, ())
    w.sample(quiet, 1_000_000, 0.0, inputs=("a",))
    w.sample(quiet, 2_000_000, 1.0, inputs=("b",))
    w.sample(quiet, 3_000_000, 2.0, inputs=("a",))
    assert w.inputs_used, "flipping a switch back is still having used the board"


def test_using_a_control_does_not_reset_the_quiet_timer():
    """The original rule survives: poking the board must not silence the advice."""
    w = StallWatch()
    quiet = ((0,) * 10, ())
    w.sample(quiet, 1_000_000, 0.0, inputs=("a",))
    assert w.sample(quiet, 9_000_000, _T + 1, inputs=("b",))


def test_an_untouched_board_is_told_to_try_a_switch_first(facts):
    """The fix for the false positive: the likelier reading leads."""
    head = stall_heading(waiting_for_input=True)
    lines = stall_message(facts, divider_bits=24, waiting_for_input=True)
    assert head == "Nothing has changed on the board"
    assert "may just be slow" not in head
    assert "no switch or button has been touched" in lines[0]
    assert "try one" in lines[1]
    # ...and the divider arithmetic is still there, as the alternative
    assert any("16.8 M cycles per step" in line for line in lines)
    assert any("If instead it counts" in line for line in lines)


def test_a_board_that_has_been_used_gets_the_direct_claim(facts):
    head = stall_heading(waiting_for_input=False)
    lines = stall_message(facts, divider_bits=24, waiting_for_input=False)
    assert head == "This design may just be slow, not broken"
    assert "switch or button" not in " ".join(lines)
    assert "wall-clock" in lines[0]


# ── The arithmetic ───────────────────────────────────────────────────────────


@pytest.fixture
def facts():
    # 10 s of wall clock bought 38 ms of a 50 MHz board = 1.9 M cycles,
    # so this machine managed 190 k simulated cycles per wall second.
    return StallFacts(quiet_s=10.0, sim_ns=38_000_000, sim_clock_hz=50e6, board_hz=50e6)


# ── Every number describes THIS window, on THIS machine ──────────────────────


def test_cycles_are_counted_at_the_clock_actually_being_simulated():
    """The user can move the clock preset, and the arithmetic has to follow.

    Counting at the board's nominal frequency instead overstated the headline
    number by the whole ratio -- 50x for anyone who had dropped a 50 MHz board
    to 1 MHz to watch something happen.
    """
    slowed = StallFacts(quiet_s=10.0, sim_ns=10_000_000, sim_clock_hz=1e6, board_hz=50e6)
    assert slowed.cycles == pytest.approx(10_000)
    text = " ".join(stall_message(slowed, divider_bits=24))
    assert "10 k clock cycles" in text
    assert "1 MHz you selected" in text
    assert "the board's" not in text.split("cycles")[1].split(".")[0]


def test_the_real_board_comparison_still_uses_the_real_board():
    """Slowing the *simulation* does not slow the silicon it is compared against."""
    slowed = StallFacts(quiet_s=10.0, sim_ns=10_000_000, sim_clock_hz=1e6, board_hz=50e6)
    assert slowed.seconds_on_board(2**24) == pytest.approx(2**24 / 50e6)
    assert "336 ms on the real board" in " ".join(stall_message(slowed, divider_bits=24))


def test_the_rate_is_this_window_not_a_running_average(facts):
    """Derived from the window so it cannot inherit throughput from before it.

    The stats panel's reading is an exponential moving average -- right for a
    live readout, wrong here, because the interesting question is what the
    machine managed *while the board was quiet*.
    """
    assert facts.effective_hz == pytest.approx(facts.cycles / facts.quiet_s)
    assert facts.effective_hz == pytest.approx(190_000)


def test_a_clock_change_restarts_the_window():
    """A window spanning two clock rates would report cycles nobody ran."""
    w = StallWatch()
    quiet = ((0,) * 4, ())
    w.sample(quiet, 1_000_000, 0.0, clock_hz=50e6)
    assert w.sample(quiet, 9_000_000, _T + 1, clock_hz=50e6)
    # The student drops the preset: the *measurement* starts again from here.
    # The offer itself lingers, as it does after any change -- what must not
    # happen is a window that mixes two clock rates.
    w.sample(quiet, 10_000_000, _T + 2, clock_hz=1e6)
    assert w.facts(11_000_000, _T + 3, 1e6, 50e6).quiet_s == pytest.approx(1.0)
    assert w.sample(quiet, 20_000_000, _T * 2 + 4, clock_hz=1e6)


def test_the_cycle_count_is_derived_not_assumed(facts):
    assert facts.cycles == pytest.approx(1_900_000)


def test_it_reports_both_clocks(facts):
    """D-15: every number is labeled simulated or wall-clock."""
    text = " ".join(stall_message(facts, divider_bits=24))
    assert "wall-clock" in text
    assert "1.9 M clock cycles" in text
    assert "38 ms" in text
    assert "50 MHz" in text


def test_a_known_divider_turns_the_complaint_into_a_number(facts):
    text = " ".join(stall_message(facts, divider_bits=24))
    assert "16.8 M cycles per step" in text
    assert "88 s here" in text  # 2**24 / 190_000
    assert "336 ms on the real board" in text  # 2**24 / 50e6


def test_without_a_divider_it_explains_rather_than_guesses(facts):
    text = " ".join(stall_message(facts))
    assert "may simply be counting" in text
    assert "cycles per step" not in text


def test_a_faster_machine_gets_a_smaller_number():
    """Nothing here is a constant; NVC on the same design says something else."""
    slow = StallFacts(quiet_s=10.0, sim_ns=38_000_000, sim_clock_hz=50e6, board_hz=50e6)
    fast = StallFacts(quiet_s=10.0, sim_ns=300_000_000, sim_clock_hz=50e6, board_hz=50e6)
    assert slow.seconds_here(2**24) > fast.seconds_here(2**24)
    assert "11 s here" in " ".join(stall_message(fast, divider_bits=24))


def test_a_dead_measurement_does_not_divide_by_zero():
    dead = StallFacts(quiet_s=10.0, sim_ns=0, sim_clock_hz=50e6, board_hz=50e6)
    assert dead.seconds_here(2**24) == float("inf")
    assert "forever" in " ".join(stall_message(dead, divider_bits=24))
