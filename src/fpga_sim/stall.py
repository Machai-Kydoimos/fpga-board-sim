"""When the board looks frozen: deciding that, and saying it with numbers (U48).

A design whose visible rate comes from the top bits of a clock divider is
correct, runs, and shows nothing.  ``CNTR_LEN = 24`` at 50 MHz steps about three
times a second on the bench; here it steps once every forty-five seconds to three
minutes depending on the backend, and on screen that is indistinguishable from a
design that does not work.  A student
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

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

#: Wall seconds of unchanging output before the advisory appears.  Long enough
#: that a slow-but-working design is not accused, short enough to arrive while
#: the user is still wondering rather than after they have given up.
DEFAULT_THRESHOLD_S = 10.0

#: How long the offer stays up after the board starts moving again, as a
#: multiple of the threshold.  It exists because **one step is evidence for the
#: slow-divider reading, not against it**: a design that toggles an LED once
#: every thirty seconds is precisely the case this feature is for, and hiding
#: the offer at the instant that is confirmed -- then bringing it back ten
#: seconds later, over and over -- is both wrong and a flicker.  Greater than 1
#: so that a design which goes quiet again never leaves a gap; small enough
#: that a design which is genuinely animating loses the offer and keeps it lost.
_LINGER_FACTOR = 1.5

#: The most any single gap between samples may contribute.  A frame is about
#: 16 ms, so this passes ordinary frames untouched while a thirty-second help
#: modal contributes one second instead of thirty.
#:
#: Clamped rather than discarded, deliberately.  Throwing the whole gap away
#: would be tidier against modals and would silently switch the feature *off*
#: on a machine slow enough that every frame exceeds the cap -- which is
#: precisely the machine whose user most needs to be told the board is not
#: broken.  Clamping degrades in both directions instead: interruptions leak a
#: bounded, negligible amount, and a slow machine keeps working.
MAX_OBSERVED_GAP_S = 1.0


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
    this application the answer is to offer help rather than to interrupt: the
    detection is not confident enough to be worth a banner (see the module
    docstring), so it earns an indicator the user may click.

    **It counts observed time, not elapsed time.**  Every clock here accumulates
    the gap between consecutive samples, and only when that gap is small enough
    to have been a frame.  Anything longer is wall time during which the loop
    was not running at all -- the F1 help modal, an error dialog, a window drag,
    an alt-tab freeze, somebody's debugger -- and that is not evidence about the
    board.  Reading the help for thirty seconds used to make the offer appear
    the instant the dialog closed, which is exactly the kind of surprise a tool
    like this cannot afford; taking the gap out at the source fixes it for every
    such interruption at once, including the ones not written yet.
    """

    def __init__(self, *, threshold_s: float = DEFAULT_THRESHOLD_S) -> None:
        """Start watching, with *threshold_s* of quiet before the advisory fires."""
        self.threshold_s = threshold_s
        self.linger_s = threshold_s * _LINGER_FACTOR
        self._signature: object = None
        self._quiet_elapsed: float | None = None  # observed seconds of stillness
        self._linger_elapsed: float | None = None  # observed seconds since it fired
        self._sim_elapsed: int = 0  # simulated ns accrued over those seconds
        self._last_now: float | None = None
        self._last_sim_ns: int | None = None
        self.fired = False
        #: Set once any switch or button has moved since the run began, and never
        #: cleared.  It does not gate the advisory -- it chooses which
        #: explanation leads, because "nobody has touched anything" makes an
        #: input-driven design the likelier reading of a still board.
        self.inputs_used = False
        self._first_inputs: object = None
        self._basis: tuple[float, float] | None = None

    def reset(self) -> None:
        """Forget the current quiet spell (the outputs moved, or the run did)."""
        self._quiet_elapsed = None
        self._linger_elapsed = None
        self._sim_elapsed = 0
        self._last_now = None
        self._last_sim_ns = None
        self.fired = False

    def _observed(self, now: float, *, paused: bool) -> float:
        """Wall seconds since the previous sample that this watch may count."""
        previous, self._last_now = self._last_now, now
        if previous is None or paused:
            return 0.0
        delta = now - previous
        if delta <= 0.0:  # a clock that went backwards observes nothing
            return 0.0
        return min(delta, MAX_OBSERVED_GAP_S)

    def _restart_window(self) -> None:
        """Begin measuring again from here, without touching what is on offer."""
        self._quiet_elapsed = 0.0
        self._sim_elapsed = 0
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
        speed_factor: float | None = None,
    ) -> bool:
        """Record one frame; return whether the offer should be showing.

        *signature* must cover **outputs only** -- see the module docstring.
        *sim_ns* is the child's running total of simulated nanoseconds, which is
        how "the simulator is still working" is told from "the simulator
        stopped".

        *paused* contributes no observed time, so a pause neither starts a quiet
        spell nor ends one, and the waiting already done is kept rather than
        thrown away.

        *inputs* is the switch/button state.  It is **recorded, never acted on**:
        it does not reset the quiet timer (a student poking at the board must not
        silence the thing that was about to explain it) and it does not suppress
        the offer.  All it does is set :attr:`inputs_used`, which decides which
        explanation the message leads with.

        *clock_hz* and *speed_factor* are the basis every figure in the message
        rests on.  Changing either restarts the measurement -- a window that
        straddled a change would report a rate nobody ever ran at -- but does
        **not** withdraw an offer already made, because the board is no less
        still than it was a moment ago.
        """
        observed = self._observed(now, paused=paused)
        # Simulated time is accumulated over the same frames as the wall clock,
        # and only those.  A "paused" run does not actually stop simulated time
        # -- the child shrinks its step to 1 ns rather than halting -- so a long
        # pause quietly adds milliseconds of simulated time to a window that
        # gained no wall time at all, and every figure derived from the pair
        # comes out overstated.  Counting both on the same frames keeps the
        # ratio honest by construction.
        previous_sim, self._last_sim_ns = self._last_sim_ns, sim_ns
        sim_delta = 0 if previous_sim is None or observed <= 0.0 else max(0, sim_ns - previous_sim)
        if self._linger_elapsed is not None:
            self._linger_elapsed += observed

        if self._first_inputs is None:
            self._first_inputs = inputs
        elif inputs != self._first_inputs:
            self.inputs_used = True

        basis = (clock_hz or 0.0, speed_factor or 0.0)
        if self._basis is not None and basis != self._basis:
            self._basis = basis
            self._restart_window()
            return self._lingering()
        self._basis = basis

        if signature != self._signature:
            self._signature = signature
            self._restart_window()
            return self._lingering()
        if self._quiet_elapsed is None:
            self._restart_window()
            return self._lingering()

        self._quiet_elapsed += observed
        self._sim_elapsed += sim_delta
        if self._quiet_elapsed < self.threshold_s:
            return self._lingering()
        if self._sim_elapsed <= 0:
            # Nothing is advancing: a stopped sim, not a slow design.  Do not
            # linger over it either -- that is a different problem, and this
            # offer would be answering the wrong question.
            self._linger_elapsed = None
            self.fired = False
            return False
        self.fired = True
        self._linger_elapsed = 0.0
        return True

    def _lingering(self) -> bool:
        """Report whether a recent quiet spell still justifies showing the offer."""
        return self._linger_elapsed is not None and self._linger_elapsed < self.linger_s

    def facts(self, sim_ns: int, now: float, sim_clock_hz: float, board_hz: float) -> StallFacts:
        """Snapshot the numbers behind the current spell, for the message.

        Both figures are differences taken across *this* window -- the observed
        wall time since the outputs last moved, and the simulated time the child
        reported over the same span -- so the arithmetic downstream describes
        this machine, this backend and these ten seconds, and nothing else.
        """
        return StallFacts(
            quiet_s=self._quiet_elapsed or 0.0,
            sim_ns=self._sim_elapsed,
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


def _divider_clause(facts: StallFacts, divider: Divider) -> str:
    """State the width the run is using, and say so when it is not the file's.

    Quoting a number the student cannot see in their editor is how an advisory
    loses their trust, so when the two differ the message names both and says
    which is which -- "running at 17, your file says 24" -- rather than picking
    one and hoping.
    """
    step = float(2**divider.bits)
    name = divider.name.upper()
    if divider.overridden:
        why = (
            "you set that here"
            if divider.source == "user"
            else "the simulator lowers it so a design blinks visibly here"
        )
        head = (
            f"{name} is running at {divider.bits}, not the {divider.file_bits} in your file"
            f" ({why}) — that is {_count(step)} cycles per step:"
        )
    else:
        head = f"Your {name} = {divider.bits} means {_count(step)} cycles per step:"
    return (
        f"{head}"
        f" about {_duration(facts.seconds_here(step))} here,"
        f" {_duration(facts.seconds_on_board(step))} on the real board."
    )


def _fix_clauses(facts: StallFacts, divider: Divider) -> list[str]:
    """Say what to type.  "Lower it" is not an instruction somebody can follow.

    The suggested width is computed from the rate just measured rather than
    picked, so it is a number that will actually work on *this* machine; and the
    flag is spelled out in full, because a student who is already unsure whether
    their design works should not also have to guess at a command line.
    """
    smaller = suggested_bits(facts, divider)
    if smaller is None:
        return [
            f"Nothing to lower automatically -- {divider.name.upper()} is already small."
            " If the board is still, the cause is elsewhere."
        ]
    step = float(2**smaller)
    return [
        f"To watch it here, set {divider.name.upper()} to about {smaller}:",
        "    [Stop], then [Generics…] on the preview"
        f"  —  or relaunch with  --generic {divider.name.upper()}={smaller}",
        f"That steps about every {_duration(facts.seconds_here(step))} instead."
        f" Your file is not touched: {divider.name.upper()} stays {divider.file_bits}"
        " for the real board.",
    ]


#: The backends this simulator can run, slowest first, keyed on
#: :attr:`~fpga_sim.sim_discovery.SimulatorInfo.backend`.  The *order* is what
#: matters here and it is stable across machines; the ratios behind it live in
#: ``docs/install.md`` ("Choosing a simulator") and are deliberately **not**
#: repeated in the message -- see :func:`faster_backend`.
_BACKEND_SPEED_ORDER: tuple[str, ...] = ("mcode", "llvm-jit", "llvm", "nvc")


def faster_backend(current: str, available: Iterable[str]) -> str | None:
    """Name the fastest installed backend faster than *current*, or ``None``.

    Order only, never a predicted ratio.  ``docs/install.md`` puts NVC at
    ~3.5-6x mcode and GHDL-LLVM at ~2.3-4.3x, and a range that wide is a range
    because the answer depends on the design and the machine -- so quoting a
    figure here would be the one thing this module refuses to do everywhere
    else, which is to tell somebody a number about their computer that was not
    measured on it.  The *ordering* is safe: it does not vary.

    Unknown backend names sort as unknown and are ignored rather than guessed
    at, so a code generator added later cannot silently be called slower.
    """
    try:
        here = _BACKEND_SPEED_ORDER.index(current)
    except ValueError:
        return None
    faster = [b for b in available if b in _BACKEND_SPEED_ORDER[here + 1 :]]
    return max(faster, key=_BACKEND_SPEED_ORDER.index) if faster else None


def _backend_clause(current: str, faster: str) -> str:
    """Point at the *existing* control rather than offering a second one.

    The simulator is chosen in exactly one place -- the preview's ``SIM:``
    toggle -- and it stays that way.  An in-run [Switch to NVC] button was
    considered and dropped: it would have been a second selection point whose
    meaning differed from the first, because switching engines mid-run restarts
    simulated time rather than continuing it.  A student who has been waiting
    three minutes would have lost the three minutes to a button that read like
    "go faster".  Saying "[Stop], then the toggle" keeps one control and is
    honest that a re-run is a re-run.
    """
    label = _BACKEND_LABELS.get(faster, faster)
    return (
        f"{label} is also installed here and is usually faster than"
        f" {_BACKEND_LABELS.get(current, current)}:"
        f" [Stop], then the SIM: toggle on the preview re-runs this design on it."
    )


#: Display names matching the preview toggle's own labels, so the message names
#: the thing the user will actually see on the button.
_BACKEND_LABELS: dict[str, str] = {
    "mcode": "GHDL",
    "llvm": "GHDL-LLVM",
    "llvm-jit": "GHDL-JIT",
    "nvc": "NVC",
}


def stall_message(
    facts: StallFacts,
    divider: Divider | None = None,
    *,
    waiting_for_input: bool = False,
    backend: str = "",
    available_backends: Iterable[str] = (),
) -> list[str]:
    """Build the advisory, in the student's terms and in measured numbers (D-15).

    Every figure comes from the live run: what the machine actually managed in
    the window that just went quiet.  Nothing here is a constant, because a
    number that is wrong about *their* machine teaches them to ignore the box.

    *divider*, when the design declares a plausible divider generic, turns the
    general complaint into the specific one -- how long one step of *this*
    design takes here, how long it takes on the board, and **the command to
    type** to see it move.  Naming the generic is what makes the advice
    actionable: "lower your divider" is a diagnosis, not an instruction.

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
    if divider is not None:
        lines.append(_divider_clause(facts, divider))
        lines.extend(_fix_clauses(facts, divider))
    else:
        lines.append(
            "If your design divides the clock, it may simply be counting."
            " The simulator runs far slower than the board, so a divider sized"
            " for hardware can take minutes to show one step."
        )
        lines.append(
            "Put the divider's width in a generic -- say"
            " `CNTR_LEN : positive := 24` -- and [Generics…] on the preview can"
            " lower it for the simulator without changing what your board uses."
        )
    # Last, and only when it is actionable: the other thing that makes a step
    # arrive sooner is a faster engine, and a student may already have one
    # installed without knowing the toggle changes anything.
    quicker = faster_backend(backend, available_backends) if backend else None
    if quicker is not None:
        lines.append(_backend_clause(backend, quicker))
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


@dataclass(frozen=True)
class Divider:
    """A generic that plausibly sizes the design's clock divider.

    Two widths, because the run and the file disagree more often than not.
    Every figure in the advisory is about the run that is happening, so
    :attr:`bits` is what the design is *actually* elaborated with; but the
    sentence promising the file is untouched has to quote the file, or it
    contradicts the editor the student is looking at.
    """

    name: str  # as declared, lowercased
    bits: int  # the width the run is actually using
    #: The file's own default, when the run is not using it -- the simulator
    #: floors COUNTER_BITS, and the user may have set anything through
    #: [Generics…] or --generic.  ``None`` means the two agree.
    declared: int | None = None
    #: Who moved it: ``"user"`` (they set it themselves) or ``"simulator"`` (the
    #: contract floor).  Worth distinguishing, because the two need opposite
    #: sentences: one person is being reminded of their own choice, the other is
    #: learning the tool did something to their design without saying so.
    source: str = ""

    @property
    def file_bits(self) -> int:
        """What the design file says, whatever the run was given."""
        return self.bits if self.declared is None else self.declared

    @property
    def overridden(self) -> bool:
        """Whether the run is using something other than the file's value."""
        return self.declared is not None and self.declared != self.bits


def find_divider(
    vhdl_text: str,
    toplevel: str,
    contract: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> Divider | None:
    """Find the design's clock-divider generic, or ``None``.

    Reads only what the design already declares; nothing is inferred from the
    architecture, because a wrong *number* in the advisory is worse than no
    number.  When several candidates exist the widest wins -- that is the one
    setting the slowest visible rate, which is the one being complained about.

    The **name** matters as much as the width: without it the advice can only
    say "lower your divider", which is not something a student can act on.  With
    it the message can print the flag they should actually type.

    *contract* is the wrapper's own generic map and *overrides* is whatever the
    user set through [Generics…] or ``--generic``; the user wins, then the
    contract, then the file.  They are kept apart rather than merged so the
    message can name **who** moved the value, which needs opposite sentences:
    somebody being reminded of their own choice, or somebody learning the tool
    changed their design without telling them.
    **Reading the file alone is not enough and was a defect.**
    The simulator floors ``COUNTER_BITS`` well below the 24 a design declares
    (17, or 20 on NVC), so a file saying 24 was described as stepping every
    16.8 M cycles when the run was doing 131 k -- wrong by 128x.  Worse, a
    student who took this advisory's own advice and lowered the generic in the
    dialog came back to it still quoting the old number and recommending the
    change they had just made.  Lookup is case-insensitive because the
    override map is keyed lowercase and the wrapper's is upper.
    """
    from fpga_sim.generics import Kind, design_generics  # noqa: PLC0415 - avoid a cycle

    by_user = {k.lower(): v for k, v in (overrides or {}).items()}
    by_tool = {k.lower(): v for k, v in (contract or {}).items()}
    found: list[Divider] = []
    for g in design_generics(vhdl_text, toplevel):
        if g.kind != Kind.INTEGER or g.name not in _DIVIDER_HINTS:
            continue
        try:
            declared = int(g.default_text.replace("_", ""))
        except ValueError:
            continue
        running, source = declared, ""
        for candidate, who in ((by_user.get(g.name), "user"), (by_tool.get(g.name), "simulator")):
            if candidate is None:
                continue
            try:
                running, source = int(str(candidate).replace("_", "")), who
            except ValueError:
                # A value we cannot read is not a reason to report a number we
                # know is wrong; fall back and say nothing clever.
                running, source = declared, ""
            break
        if 1 <= running <= 64 and 1 <= declared <= 64:
            found.append(
                Divider(
                    g.name,
                    running,
                    declared if declared != running else None,
                    source if declared != running else "",
                )
            )
    # Widest *as running*: that is the one setting the rate being complained
    # about, which is the whole reason a width is picked at all.
    return max(found, key=lambda d: d.bits) if found else None


#: How long a step should take here for the design to look alive.  Used to size
#: the width the advice suggests, from the rate just measured -- so the number
#: offered is one that will actually work on *this* machine rather than a
#: constant that happens to suit the author's.
_TARGET_STEP_S = 0.5


def suggested_bits(facts: StallFacts, divider: Divider) -> int | None:
    """Pick the widest divider whose step this machine can still show promptly."""
    if facts.effective_hz <= 0:
        return None
    if facts.seconds_here(float(2**divider.bits)) <= _TARGET_STEP_S:
        # Already quick enough here, so there is nothing to lower -- and
        # suggesting a smaller number anyway would send somebody chasing the
        # wrong thing when the real cause is elsewhere.
        return None
    width = int(math.floor(math.log2(max(1.0, _TARGET_STEP_S * facts.effective_hz))))
    width = max(1, min(width, divider.bits - 1))
    return width
