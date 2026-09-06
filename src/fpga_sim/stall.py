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
"""

from __future__ import annotations

from dataclasses import dataclass

#: Wall seconds of unchanging output before the advisory appears.  Long enough
#: that a slow-but-working design is not accused, short enough to arrive while
#: the user is still wondering rather than after they have given up.
DEFAULT_THRESHOLD_S = 10.0


@dataclass(frozen=True)
class StallFacts:
    """What was measured when the advisory fired. Every number, no constants."""

    quiet_s: float  # wall seconds since any LED or digit last changed
    sim_ns: int  # simulated nanoseconds elapsed in that window
    board_hz: float  # the board's own clock
    effective_hz: float  # simulated cycles per wall second, measured here

    @property
    def cycles(self) -> float:
        """Board clock cycles simulated during the quiet window."""
        return self.sim_ns * 1e-9 * self.board_hz

    def seconds_here(self, cycles: float) -> float:
        """Wall seconds this machine needs to simulate *cycles* clocks."""
        return cycles / self.effective_hz if self.effective_hz > 0 else float("inf")

    def seconds_on_board(self, cycles: float) -> float:
        """Wall seconds the real board needs for *cycles* clocks."""
        return cycles / self.board_hz if self.board_hz > 0 else float("inf")


class StallWatch:
    """Track whether the board's outputs have gone quiet while the sim runs.

    Feed it :meth:`sample` once per frame.  It is deliberately edge-triggered:
    :attr:`fired` goes true once per quiet spell, so the caller shows one banner
    rather than one per frame, and a dismissal lasts until something actually
    changes.
    """

    def __init__(self, *, threshold_s: float = DEFAULT_THRESHOLD_S) -> None:
        """Start watching, with *threshold_s* of quiet before the advisory fires."""
        self.threshold_s = threshold_s
        self._signature: object = None
        self._quiet_since: float | None = None
        self._sim_ns_at_quiet: int = 0
        self._dismissed = False
        self.fired = False

    def reset(self) -> None:
        """Forget the current quiet spell (the outputs moved, or the run did)."""
        self._quiet_since = None
        self._dismissed = False
        self.fired = False

    def dismiss(self) -> None:
        """Stop showing this spell's advisory; a real change re-arms it."""
        self._dismissed = True
        self.fired = False

    def sample(
        self,
        signature: object,
        sim_ns: int,
        now: float,
        *,
        paused: bool = False,
    ) -> bool:
        """Record one frame; return whether the advisory should be showing.

        *signature* must cover **outputs only** -- see the module docstring.
        *sim_ns* is the child's running total of simulated nanoseconds, which is
        how "the simulator is still working" is told from "the simulator
        stopped".
        """
        if signature != self._signature:
            self._signature = signature
            self._quiet_since = now
            self._sim_ns_at_quiet = sim_ns
            self._dismissed = False
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
        self.fired = not self._dismissed
        return self.fired

    def facts(self, sim_ns: int, now: float, board_hz: float, effective_hz: float) -> StallFacts:
        """Snapshot the numbers behind the current spell, for the message."""
        quiet = now - self._quiet_since if self._quiet_since is not None else 0.0
        return StallFacts(
            quiet_s=quiet,
            sim_ns=max(0, sim_ns - self._sim_ns_at_quiet),
            board_hz=board_hz,
            effective_hz=effective_hz,
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


def stall_message(facts: StallFacts, divider_bits: int | None = None) -> list[str]:
    """Build the advisory, in the student's terms and in measured numbers (D-15).

    Every figure comes from the live run: what the machine actually managed in
    the window that just went quiet.  Nothing here is a constant, because a
    number that is wrong about *their* machine teaches them to ignore the box.

    *divider_bits*, when the design declares a plausible divider generic, turns
    the general complaint into the specific one -- how long one step of *this*
    design takes here, and how long it takes on the board.
    """
    lines = [
        f"No LED or digit has changed in {_duration(facts.quiet_s)} of wall-clock time.",
        f"In that time this machine simulated {_count(facts.cycles)} clock cycles"
        f" = {_sim_time(facts.sim_ns)} of the board's"
        f" {facts.board_hz / 1e6:.3g} MHz.",
    ]
    if divider_bits is not None and divider_bits > 0:
        step = float(2**divider_bits)
        lines.append(
            f"A {divider_bits}-bit divider means {_count(step)} cycles per step:"
            f" about {_duration(facts.seconds_here(step))} here,"
            f" {_duration(facts.seconds_on_board(step))} on the real board."
        )
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
