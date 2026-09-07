"""When the board looks frozen (U48): the judgment and the arithmetic.

A design whose visible rate comes from the top bits of a clock divider is
correct, runs, and shows nothing.  These tests are mostly about the ways that
observation can be got wrong: blaming the student when the *simulator* stopped,
losing the timer because they touched a switch, accusing a design that is
merely waiting for a button, and counting wall time nobody was watching.

Everything here drives the watch the way the run loop does -- **one sample per
frame** -- because that is the only shape in which its answers mean anything:
it counts time it observed, and a test that jumped ten seconds in one call
would be handing it an interruption, not a wait.
"""

from typing import Any

import pytest

from fpga_sim.stall import (
    DEFAULT_THRESHOLD_S,
    MAX_OBSERVED_GAP_S,
    Divider,
    StallFacts,
    StallWatch,
    find_divider,
    stall_heading,
    stall_message,
    suggested_bits,
)

_T = DEFAULT_THRESHOLD_S
_FRAME = 0.05  # 20 fps, comfortably inside MAX_OBSERVED_GAP_S


class Loop:
    """A run loop: wall clock and simulated time advancing together."""

    def __init__(self, watch: StallWatch, *, sim_per_frame: int = 200_000) -> None:
        self.w = watch
        self.t = 0.0
        self.sim = 0
        self.sim_per_frame = sim_per_frame
        self.showing = False

    def run(
        self,
        seconds: float,
        *,
        sig: object = "still",
        frozen: bool = False,
        **kw: Any,
    ) -> bool:
        """Advance *seconds* of wall clock, one frame at a time."""
        for _ in range(max(1, round(seconds / _FRAME))):
            self.t += _FRAME
            if not frozen:
                self.sim += self.sim_per_frame
            self.showing = self.w.sample(sig, self.sim, self.t, **kw)
        return self.showing

    def blocked(self, seconds: float) -> None:
        """Wall time in which the loop did not run at all (a modal, a drag)."""
        self.t += seconds


# ── Detection ────────────────────────────────────────────────────────────────


def test_a_changing_board_never_fires():
    loop = Loop(StallWatch())
    for i in range(40):
        assert not loop.run(0.5, sig=f"frame{i}")


def test_quiet_outputs_with_time_advancing_fire():
    loop = Loop(StallWatch())
    assert not loop.run(_T - 1)
    assert loop.run(2)


def test_a_stopped_simulator_is_never_blamed_on_the_design():
    """The clause that separates "your design is slow" from "we stopped"."""
    loop = Loop(StallWatch())
    assert not loop.run(_T * 6, frozen=True)


def test_a_switch_flip_must_not_reset_the_timer():
    """The guard is `output_signature`; this pins the consequence."""
    loop = Loop(StallWatch())
    assert loop.run(_T + 1, sig=("leds", 0))


def test_one_step_does_not_take_the_offer_away():
    """The step is evidence *for* the slow-divider reading, not against it.

    A design that toggles an LED once every thirty seconds is exactly the case
    this exists for; hiding the offer at the instant that is confirmed, then
    restoring it ten seconds later, forever, would be both wrong and a flicker.
    """
    loop = Loop(StallWatch())
    assert loop.run(_T + 1)
    assert loop.run(1, sig="stepped"), "one step must not withdraw it"
    assert loop.run(3, sig="stepped")


def test_a_board_that_really_is_running_loses_the_offer_and_keeps_it_lost():
    loop = Loop(StallWatch())
    assert loop.run(_T + 1)
    for i in range(400):  # changing every frame, for 20 s
        loop.t += _FRAME
        loop.sim += loop.sim_per_frame
        showing = loop.w.sample(f"f{i}", loop.sim, loop.t)
    assert not showing
    assert not loop.run(5, sig="finally-still")


# ── Time the loop never watched ──────────────────────────────────────────────


def test_a_blocking_modal_is_not_evidence_that_the_board_is_stalled():
    """Reading the F1 help for thirty seconds used to raise the offer on close."""
    loop = Loop(StallWatch())
    loop.run(2)
    loop.blocked(30.0)
    assert not loop.run(0.2), "the help modal's wall time is not the board's silence"


def test_a_long_gap_contributes_a_bounded_amount_not_all_of_it():
    loop = Loop(StallWatch())
    loop.run(1)
    loop.blocked(300.0)
    assert not loop.run(_T - 2 - MAX_OBSERVED_GAP_S)
    assert loop.run(2), "...but real frames still accumulate normally"


def test_a_clock_that_goes_backwards_observes_nothing():
    w = StallWatch()
    w.sample("still", 1_000_000, 100.0)
    assert not w.sample("still", 2_000_000, 40.0)


# ── Pause ────────────────────────────────────────────────────────────────────


def test_a_paused_run_is_not_a_symptom():
    """Wall-clock time spent paused is not evidence of anything."""
    loop = Loop(StallWatch())
    assert not loop.run(_T * 12, paused=True, frozen=True)


def test_pausing_does_not_take_an_offer_away():
    """Pausing to read the thing carefully is the obvious move; do not punish it."""
    loop = Loop(StallWatch())
    assert loop.run(_T + 1)
    assert loop.run(_T * 8, paused=True, frozen=True), "the offer must survive a pause"


def test_a_pause_freezes_the_quiet_clock_without_losing_it():
    """Neither accrue time while paused nor throw away the time already earned."""
    loop = Loop(StallWatch())
    loop.run(_T - 2)
    earned = loop.w.facts(loop.sim, loop.t, 50e6, 50e6).quiet_s
    assert earned == pytest.approx(_T - 2, abs=0.2)

    loop.run(100, paused=True, frozen=True)
    assert loop.w.facts(loop.sim, loop.t, 50e6, 50e6).quiet_s == pytest.approx(earned), "frozen"

    assert loop.run(2.5), "the time already earned still counts"


def test_a_pause_adds_no_simulated_time_to_the_window():
    """ "Paused" does not stop simulated time -- the child steps 1 ns instead.

    So a long pause quietly adds milliseconds of simulated time to a window
    that gained no wall time at all, and every figure derived from the pair
    comes out overstated.  Measured before the fix: a 60 s pause added 3.6 ms
    to a 31.8 ms window, an 11% overstatement of the rate.
    """
    loop = Loop(StallWatch())
    loop.run(8)
    before = loop.w.facts(loop.sim, loop.t, 50e6, 50e6)

    # paused, but the child keeps creeping forward at 1 ns a step
    loop.sim_per_frame = 3_000
    loop.run(60, paused=True)
    after = loop.w.facts(loop.sim, loop.t, 50e6, 50e6)

    assert after.sim_ns == before.sim_ns
    assert after.effective_hz == pytest.approx(before.effective_hz)


# ── The basis every figure rests on ──────────────────────────────────────────


def test_changing_the_clock_restarts_the_measurement_but_keeps_the_offer():
    loop = Loop(StallWatch())
    assert loop.run(_T + 1, clock_hz=50e6)
    assert loop.run(1, clock_hz=1e6), "the board is no less still than it was"
    assert loop.w.facts(loop.sim, loop.t, 1e6, 50e6).quiet_s == pytest.approx(1.0, abs=0.2)


def test_changing_the_speed_restarts_the_measurement_too():
    """Otherwise the "here" figure blends two throughputs and describes neither."""
    loop = Loop(StallWatch())
    assert loop.run(_T + 1, speed_factor=1.0)
    loop.run(1, speed_factor=4.0)
    assert loop.w.facts(loop.sim, loop.t, 50e6, 50e6).quiet_s == pytest.approx(1.0, abs=0.2)


# ── Which explanation leads ──────────────────────────────────────────────────


def test_an_idle_input_follower_still_trips_the_watch():
    """It has to: there is no observation that separates it from a slow divider."""
    loop = Loop(StallWatch())
    assert loop.run(_T + 1, inputs=("nobody", "touching"))


def test_untouched_controls_are_remembered():
    loop = Loop(StallWatch())
    loop.run(2, inputs=("a",))
    assert not loop.w.inputs_used


def test_a_touched_control_is_remembered_even_after_it_is_put_back():
    loop = Loop(StallWatch())
    loop.run(1, inputs=("a",))
    loop.run(1, inputs=("b",))
    loop.run(1, inputs=("a",))
    assert loop.w.inputs_used, "flipping a switch back is still having used the board"


def test_using_a_control_does_not_reset_the_quiet_timer():
    loop = Loop(StallWatch())
    loop.run(_T - 1, inputs=("a",))
    assert loop.run(2, inputs=("b",))


def test_an_untouched_board_is_told_to_try_a_switch_first(facts):
    """The fix for the false positive: the likelier reading leads."""
    head = stall_heading(waiting_for_input=True)
    lines = stall_message(facts, divider=Divider("cntr_len", 24), waiting_for_input=True)
    assert head == "Nothing has changed on the board"
    assert "may just be slow" not in head
    assert "no switch or button has been touched" in lines[0]
    assert "try one" in lines[1]
    assert any("16.8 M cycles per step" in line for line in lines)
    assert any("If instead it counts" in line for line in lines)


def test_a_board_that_has_been_used_gets_the_direct_claim(facts):
    head = stall_heading(waiting_for_input=False)
    lines = stall_message(facts, None, waiting_for_input=False)
    assert head == "This design may just be slow, not broken"
    assert "switch or button" not in " ".join(lines)
    assert "wall-clock" in lines[0]


# ── The arithmetic ───────────────────────────────────────────────────────────


@pytest.fixture
def facts():
    # 10 s of wall clock bought 38 ms of a 50 MHz board = 1.9 M cycles,
    # so this machine managed 190 k simulated cycles per wall second.
    return StallFacts(quiet_s=10.0, sim_ns=38_000_000, sim_clock_hz=50e6, board_hz=50e6)


def test_cycles_are_counted_at_the_clock_actually_being_simulated():
    """The user can move the clock preset, and the arithmetic has to follow.

    Counting at the board's nominal frequency instead overstated the headline
    number by the whole ratio -- 50x for anyone who had dropped a 50 MHz board
    to 1 MHz to watch something happen.
    """
    slowed = StallFacts(quiet_s=10.0, sim_ns=10_000_000, sim_clock_hz=1e6, board_hz=50e6)
    assert slowed.cycles == pytest.approx(10_000)
    text = " ".join(stall_message(slowed, divider=Divider("cntr_len", 24)))
    assert "10 k clock cycles" in text
    assert "1 MHz you selected" in text


def test_the_real_board_comparison_still_uses_the_real_board():
    """Slowing the *simulation* does not slow the silicon it is compared against."""
    slowed = StallFacts(quiet_s=10.0, sim_ns=10_000_000, sim_clock_hz=1e6, board_hz=50e6)
    assert slowed.seconds_on_board(2**24) == pytest.approx(2**24 / 50e6)
    assert "336 ms on the real board" in " ".join(
        stall_message(slowed, divider=Divider("cntr_len", 24))
    )


def test_the_rate_is_this_window_not_a_running_average(facts):
    """Derived from the window so it cannot inherit throughput from before it."""
    assert facts.effective_hz == pytest.approx(facts.cycles / facts.quiet_s)
    assert facts.effective_hz == pytest.approx(190_000)


def test_the_cycle_count_is_derived_not_assumed(facts):
    assert facts.cycles == pytest.approx(1_900_000)


def test_it_reports_both_clocks(facts):
    """D-15: every number is labeled simulated or wall-clock."""
    text = " ".join(stall_message(facts, divider=Divider("cntr_len", 24)))
    assert "wall-clock" in text
    assert "1.9 M clock cycles" in text
    assert "38 ms" in text
    assert "50 MHz" in text


def test_a_known_divider_turns_the_complaint_into_a_number(facts):
    text = " ".join(stall_message(facts, divider=Divider("cntr_len", 24)))
    assert "16.8 M cycles per step" in text
    assert "88 s here" in text  # 2**24 / 190_000
    assert "336 ms on the real board" in text


def test_without_a_divider_it_explains_rather_than_guesses(facts):
    text = " ".join(stall_message(facts))
    assert "may simply be counting" in text
    assert "cycles per step" not in text


# ── The advice has to be something a student can act on ──────────────────────


def test_it_prints_the_command_to_type(facts):
    """ "Lower it for the simulator" is a diagnosis, not an instruction."""
    lines = stall_message(facts, Divider("cntr_len", 24))
    text = " ".join(lines)
    assert "[Generics…] on the preview" in text
    assert "--generic CNTR_LEN=" in text
    assert "Your file is not touched" in text
    assert "CNTR_LEN stays 24 for the real board" in text


def test_the_suggested_width_is_computed_from_the_measured_rate():
    """A constant would suit the author's machine and nobody else's."""
    divider = Divider("cntr_len", 24)
    slow = StallFacts(quiet_s=10.0, sim_ns=1_000_000, sim_clock_hz=50e6, board_hz=50e6)
    here = StallFacts(quiet_s=10.0, sim_ns=16_300_000, sim_clock_hz=50e6, board_hz=50e6)
    fast = StallFacts(quiet_s=10.0, sim_ns=163_000_000, sim_clock_hz=50e6, board_hz=50e6)

    widths = []
    for f in (slow, here, fast):
        w = suggested_bits(f, divider)
        assert w is not None
        assert f.seconds_here(float(2**w)) < 1.0, "every suggestion is watchable"
        widths.append(w)
    assert widths == sorted(widths), "a faster machine can afford a wider divider"


def test_a_divider_that_is_already_quick_is_left_alone():
    """Suggesting a smaller number would send somebody chasing the wrong thing."""
    facts = StallFacts(quiet_s=10.0, sim_ns=16_300_000, sim_clock_hz=50e6, board_hz=50e6)
    assert suggested_bits(facts, Divider("cntr_len", 4)) is None
    text = " ".join(stall_message(facts, Divider("cntr_len", 4)))
    assert "already small" in text
    assert "--generic" not in text


def test_without_a_divider_it_says_how_to_make_one(facts):
    """The design hard-codes its width, so the fix is to expose it."""
    text = " ".join(stall_message(facts))
    assert "Put the divider's width in a generic" in text
    assert "[Generics…] on the preview" in text


def test_the_divider_generic_is_found_by_name_with_its_name_kept():
    src = (
        "entity r is generic (CNTR_LEN : positive := 22;"
        " COUNTER_BITS : positive := 24); port (clk : in bit); end entity;"
    )
    found = find_divider(src, "r")
    assert found is not None
    assert (found.name, found.bits) == ("counter_bits", 24), "the widest wins"
    assert find_divider("entity t is port (c : in bit); end entity;", "t") is None


def test_a_faster_machine_gets_a_smaller_number():
    """Nothing here is a constant; NVC on the same design says something else."""
    slow = StallFacts(quiet_s=10.0, sim_ns=38_000_000, sim_clock_hz=50e6, board_hz=50e6)
    fast = StallFacts(quiet_s=10.0, sim_ns=300_000_000, sim_clock_hz=50e6, board_hz=50e6)
    assert slow.seconds_here(2**24) > fast.seconds_here(2**24)
    assert "11 s here" in " ".join(stall_message(fast, divider=Divider("cntr_len", 24)))


def test_a_dead_measurement_does_not_divide_by_zero():
    dead = StallFacts(quiet_s=10.0, sim_ns=0, sim_clock_hz=50e6, board_hz=50e6)
    assert dead.seconds_here(2**24) == float("inf")
    assert "forever" in " ".join(stall_message(dead, divider=Divider("cntr_len", 24)))
