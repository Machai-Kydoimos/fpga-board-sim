"""When the board looks frozen: deciding that, and saying it with numbers (U48).

A design whose visible rate comes from the top bits of a clock divider is
correct, runs, and shows nothing.  ``CNTR_LEN = 24`` at 50 MHz steps about three
times a second on the bench; here it steps about once every ninety seconds, and
on screen that is indistinguishable from a design that does not work.  A student
alone at 11 pm cannot tell those apart, and the tool has never helped.

This module is the judgment and the arithmetic.  It holds no pygame: what it
gets is *what the board is showing*, *how much simulated time has passed*, and
*how fast this machine is actually going*; what it returns is whether to speak
and what to say.

Three rules it is built around.

**Detection is a runtime observation, never a static lint.**  Nothing here reads
the design.  Whether a divider is too wide depends on the machine it is running
on, which is exactly why a message about it has to be measured rather than
predicted.

**"Nothing changed" is not enough -- simulated time must be advancing too.**
Otherwise a hung or crashed child raises a banner blaming the student's divider,
which is worse than silence.  The two clauses separate "your design is slow" from
"our simulator stopped", and they must not be collapsed.

**Only outputs count.**  Flipping a switch changes the board's picture without
telling us anything about the design, so the signature this watches is LEDs and
segments alone.  A student wiggling switches to see whether anything is alive
must not reset the timer that would have told them.

**And the fourth, learned the hard way: the trigger cannot tell a slow divider
from an idle input-follower.**  A design that lights an LED while a button is
held is *correct* to show nothing when nobody is pressing anything -- and on the
wire that is identical to a stalled divider: static inputs, static outputs,
simulated time advancing.  There is no observation that separates them, and the
first version of this module asserted "your design may just be slow" to a
student whose combinational lab was working perfectly.  So the advisory reports
what it can actually see and offers *both* explanations, leading with the one
the evidence favors: if the controls have never been touched this run, "try a
switch" comes first, because a design waiting for input is the likelier reading
of a board nobody has touched.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Wall seconds of unchanging output before the advisory appears.  Long enough
#: that a slow-but-working design is not accused, short enough to arrive while
#: the user is still wondering rather than after they have given up.
DEFAULT_THRESHOLD_S = 10.0


@dataclass(frozen=True)
class StallFacts:
    """What was measured while the advisory's window was open.

    Four inputs, and only two of them are measurements -- the rest of the
    arithmetic is derived here so that no caller can supply a number from
    somewhere else and have it read as though it came from this window.

    The two clocks are deliberately separate.  ``sim_clock_hz`` is what is
    *actually being simulated*, which the user can change at run time from the
    panel; ``board_hz`` is what the silicon would run at.  Using the board's
    figure for both was worth a **50x** error in the headline cycle count for
    anyone who had touched the clock preset.
    """

    quiet_s: float  # wall seconds since any LED or digit last changed
    sim_ns: int  # simulated nanoseconds elapsed in that window
    sim_clock_hz: float  # the clock actually being simulated, right now
    board_hz: float  # what the real board's clock would be

    @property
    def cycles(self) -> float:
        """Clock cycles simulated during the quiet window."""
        return self.sim_ns * 1e-9 * self.sim_clock_hz

    @property
    def effective_hz(self) -> float:
        """Simulated cycles per wall second, over this window and nothing else.

        Derived rather than taken from the stats panel, whose reading is an
        exponential moving average: that is the right number for a live readout
        and the wrong one here, because it carries throughput from *before* the
        board went quiet.  Cycles-in-the-window over seconds-in-the-window is
        the rate this machine actually just demonstrated.
        """
        return self.cycles / self.quiet_s if self.quiet_s > 0 else 0.0

    def seconds_here(self, cycles: float) -> float:
        """Wall seconds this machine needs to simulate *cycles* clocks."""
        return cycles / self.effective_hz if self.effective_hz > 0 else float("inf")

    def seconds_on_board(self, cycles: float) -> float:
        """Wall seconds the real board needs for *cycles* clocks."""
        return cycles / self.board_hz if self.board_hz > 0 else float("inf")


class StallWatch:
    """Track whether the board's outputs have gone quiet while the sim runs.

    Feed it :meth:`sample` once per frame.  What it reports is only ever that
    the board *has* gone quiet -- what to do about that is the caller's, and in
    this application the answer is to offer help rather than to interrupt:
    the detection is not confident enough to be worth a banner (see the module
    docstring), so it earns an indicator the user may click.
    """

    def __init__(self, *, threshold_s: float = DEFAULT_THRESHOLD_S) -> None:
        """Start watching, with *threshold_s* of quiet before the advisory fires."""
        self.threshold_s = threshold_s
        self._signature: object = None
        self._quiet_since: float | None = None
        self._sim_ns_at_quiet: int = 0
        self.fired = False
        #: Set once any switch or button has moved since the run began, and never
        #: cleared.  It does not gate the advisory -- it chooses which
        #: explanation leads, because "nobody has touched anything" makes an
        #: input-driven design the likelier reading of a still board.
        self.inputs_used = False
        self._first_inputs: object = None
        self._clock_hz: float | None = None

    def reset(self) -> None:
        """Forget the current quiet spell (the outputs moved, or the run did)."""
        self._quiet_since = None
        self.fired = False

    def sample(
        self,
        signature: object,
        sim_ns: int,
        now: float,
        *,
        paused: bool = False,
        inputs: object = None,
        clock_hz: float | None = None,
    ) -> bool:
        """Record one frame; return whether the advisory should be showing.

        *signature* must cover **outputs only** -- see the module docstring.
        *sim_ns* is the child's running total of simulated nanoseconds, which is
        how "the simulator is still working" is told from "the simulator
        stopped".

        *inputs* is the switch/button state.  It is **recorded, never acted on**:
        it does not reset the quiet timer (a student poking at the board must not
        silence the thing that was about to explain it) and it does not suppress
        the advisory.  All it does is set :attr:`inputs_used`, which decides
        which explanation the message leads with.
        """
        if clock_hz is not None and clock_hz != self._clock_hz:
            # The virtual clock is the basis of every figure in the message, so
            # a window that straddles a change to it would report cycles that
            # were never run at one rate.  Start again instead.
            restart = self._clock_hz is not None
            self._clock_hz = clock_hz
            if restart:
                self._quiet_since = now
                self._sim_ns_at_quiet = sim_ns
                self.fired = False
                return False
        if self._first_inputs is None:
            self._first_inputs = inputs
        elif inputs != self._first_inputs:
            self.inputs_used = True
        if signature != self._signature:
            self._signature = signature
            self._quiet_since = now
            self._sim_ns_at_quiet = sim_ns
            self.fired = False
            return False
        if paused:
            # A paused run advances no simulated time, so the "still working"
            # clause could never be satisfied -- but say it explicitly rather
            # than relying on that, because a pause is not a symptom.
            self._quiet_since = now
            self._sim_ns_at_quiet = sim_ns
            self.fired = False
            return False
        if self._quiet_since is None:
            self._quiet_since = now
            self._sim_ns_at_quiet = sim_ns
            return False
        if now - self._quiet_since < self.threshold_s:
            return False
        if sim_ns <= self._sim_ns_at_quiet:
            return False  # nothing is advancing: this is a stopped sim, not a slow design
        self.fired = True
        return True

    def facts(self, sim_ns: int, now: float, sim_clock_hz: float, board_hz: float) -> StallFacts:
        """Snapshot the numbers behind the current spell, for the message.

        Both figures are differences taken across *this* window -- the wall
        clock since the outputs last moved, and the simulated time the child
        reported over the same span -- so the arithmetic downstream describes
        this machine, this backend and these ten seconds, and nothing else.
        """
        quiet = now - self._quiet_since if self._quiet_since is not None else 0.0
        return StallFacts(
            quiet_s=quiet,
            sim_ns=max(0, sim_ns - self._sim_ns_at_quiet),
            sim_clock_hz=sim_clock_hz,
            board_hz=board_hz,
        )


def _duration(seconds: float) -> str:
    """Render a wall-clock duration the way a person would say it."""
    if seconds == float("inf"):
        return "forever"
    if seconds < 1:
        return f"{seconds * 1000:.0f} ms"
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def _count(n: float) -> str:
    for limit, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= limit:
            return f"{n / limit:.3g} {suffix}"
    return f"{n:.0f}"


def _sim_time(ns: float) -> str:
    if ns < 1e3:
        return f"{ns:.0f} ns"
    if ns < 1e6:
        return f"{ns / 1e3:.3g} us"
    if ns < 1e9:
        return f"{ns / 1e6:.3g} ms"
    return f"{ns / 1e9:.3g} s"


def stall_heading(*, waiting_for_input: bool) -> str:
    """Build the advisory's title, which is a claim and so must match the evidence."""
    if waiting_for_input:
        return "Nothing has changed on the board"
    return "This design may just be slow, not broken"


def _divider_clause(facts: StallFacts, divider_bits: int) -> str:
    step = float(2**divider_bits)
    return (
        f"A {divider_bits}-bit divider means {_count(step)} cycles per step:"
        f" about {_duration(facts.seconds_here(step))} here,"
        f" {_duration(facts.seconds_on_board(step))} on the real board."
    )


def stall_message(
    facts: StallFacts,
    divider_bits: int | None = None,
    *,
    waiting_for_input: bool = False,
) -> list[str]:
    """Build the advisory, in the student's terms and in measured numbers (D-15).

    Every figure comes from the live run: what the machine actually managed in
    the window that just went quiet.  Nothing here is a constant, because a
    number that is wrong about *their* machine teaches them to ignore the box.

    *divider_bits*, when the design declares a plausible divider generic, turns
    the general complaint into the specific one -- how long one step of *this*
    design takes here, and how long it takes on the board.

    *waiting_for_input* says the board has controls and nobody has touched one
    since the run began.  That does not mean the design is fine -- it means the
    likeliest reading of a still board is that it is waiting, so the suggestion
    to try a switch leads and the divider arithmetic follows it as the
    alternative.  Getting this order wrong is how the advisory told a student
    their working combinational lab might be broken.
    """
    # Name the clock the cycles were actually counted at.  When the user has
    # moved the preset off the board's own frequency, saying "the board's
    # 50 MHz" would be describing a run that did not happen.
    slowed = facts.board_hz > 0 and abs(facts.sim_clock_hz - facts.board_hz) > 1.0
    at_clock = (
        f"the {facts.sim_clock_hz / 1e6:.3g} MHz you selected"
        if slowed
        else f"the board's {facts.sim_clock_hz / 1e6:.3g} MHz"
    )
    counted = (
        f"this machine simulated {_count(facts.cycles)} clock cycles"
        f" = {_sim_time(facts.sim_ns)} of {at_clock}"
    )
    if waiting_for_input:
        lines = [
            f"No LED or digit has changed in {_duration(facts.quiet_s)},"
            " and no switch or button has been touched.",
            "If your design follows the switches or buttons, try one:"
            " a design that is waiting for input is right to show nothing.",
        ]
    else:
        lines = [
            f"No LED or digit has changed in {_duration(facts.quiet_s)} of wall-clock time.",
        ]
    if waiting_for_input:
        tail = f"If instead it counts, it may just be slow here: in that time {counted}."
    else:
        tail = f"In that time {counted}."
    lines.append(tail)
    if divider_bits is not None and divider_bits > 0:
        lines.append(_divider_clause(facts, divider_bits))
        lines.append("Lower it for the simulator and your file keeps its hardware value.")
    else:
        lines.append(
            "If your design divides the clock, it may simply be counting."
            " The simulator runs far slower than the board, so a divider sized"
            " for hardware can take minutes to show one step."
        )
    return lines


#: Generic names that plausibly size a clock divider.  Matching by *name* is a
#: heuristic and is treated as one: it only ever changes the wording of an
#: advisory, never a decision, so a false positive costs a sentence and a false
#: negative costs the general phrasing instead of the specific one.
_DIVIDER_HINTS = (
    "cntr_len",
    "counter_bits",
    "count_len",
    "divider_bits",
    "div_bits",
    "prescaler_bits",
)


def divider_bits(vhdl_text: str, toplevel: str) -> int | None:
    """Guess the design's clock-divider width from its generics, or ``None``.

    Reads only what the design already declares; nothing is inferred from the
    architecture, because a wrong *number* in the advisory is worse than no
    number.  When several candidates exist the widest wins -- that is the one
    setting the slowest visible rate, which is the one being complained about.
    """
    from fpga_sim.generics import Kind, design_generics  # noqa: PLC0415 - avoid a cycle

    widths: list[int] = []
    for g in design_generics(vhdl_text, toplevel):
        if g.kind != Kind.INTEGER or g.name not in _DIVIDER_HINTS:
            continue
        try:
            widths.append(int(g.default_text.replace("_", "")))
        except ValueError:
            continue
    plausible = [w for w in widths if 1 <= w <= 64]
    return max(plausible) if plausible else None
