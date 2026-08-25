"""Input edge queue for the headless child (roadmap U44, issue #353).

The host sends **full-state** input messages -- every switch and every button
as one pair of bitmasks -- which makes arbitrary simultaneous input expressible
on the wire.  What it does *not* survive is the child's drain loop.

``sim/sim_testbench.py`` drains every pending message and assigns
``dut.sw`` / ``dut.btn`` for each one with **no ``await`` between them**, so
cocotb collapses the whole batch to the last value written: the intermediate
states never exist as far as the simulator is concerned.  Usually harmless,
because one loop iteration is 16.667 ms of wall time at *every* speed setting
(the speed factor cancels in ``target_s = (sim_step_ns / 1e9) / speed``) and no
human generates two edges inside one frame.  But when the requested step hits
the cycle cap the loop is CPU-limited and a single iteration can take hundreds
of milliseconds -- exactly the embedded-core (``hdl/mx65_*.vhd``,
``hdl/t80_*.vhd``) and multi-digit scan designs.  Then a press in one frame and
its release two frames later land in the *same* drain, collapse to
``btn = 0``, and **the design never sees the press**: tap ``btn(0)`` to roll the
die in ``mx65_dice_7seg`` and sometimes nothing happens.

The fix cannot live on the host.  Holding a press an extra frame does nothing
when the drain window is 300 ms, and it would desynchronize the rendered board
from what the DUT sees -- the invariant ``sim/capture_frames.py`` and the demo
assets rely on.

So the child buffers what it drains and applies **at most one state per loop
iteration**, guaranteeing every distinct input value at least one ``await
Timer`` of exposure.  That turns the input stream from a *sampled level* into a
*sequence of edges*, which is what a button actually is.

Two bounds keep the queue honest:

* **Consecutive duplicates are dropped on push.**  The host sends full state,
  so a state equal to the one before it carries no edge and applying it would
  waste an iteration of the backlog.
* **The backlog is hard-capped**, discarding the *oldest* entries.  Without a
  cap, frantic tapping during a CPU-limited run would queue minutes of lag and
  the DUT would fall arbitrarily far behind what the board shows.  Past the cap
  the newest states are the ones worth keeping: staying near reality beats
  replaying ancient edges.

This module is pygame-free and cocotb-free -- the same rule
:mod:`fpga_sim.sim_duty` follows -- so it is unit-testable with no simulator
installed at all.
"""

from __future__ import annotations

from collections import deque
from typing import NamedTuple

#: Maximum states held for later application.  Sized in *edges*, against the
#: worst case that matters: a CPU-limited run applying one per iteration at a
#: few hundred ms each.  16 absorbs roughly a second of frantic tapping (~8
#: presses/s = 16 edges/s); much beyond that the lag it would introduce is a
#: worse artifact than the dropped edges, since the board on screen is the
#: user's ground truth and the DUT trailing it by many seconds reads as broken.
DEFAULT_MAX_PENDING: int = 16


class InputState(NamedTuple):
    """One full-state input snapshot from the host.

    *sw* and *btn* are the switch / button bitmasks; *seq* is the host's
    monotonic input counter, echoed back in every ``state`` message so the host
    (and the tests) can assert which edge the child has actually applied.
    """

    sw: int
    btn: int
    seq: int


class InputQueue:
    """Bounded queue that releases at most one input state per simulation step.

    Push everything drained in one iteration; pop **once** per iteration and
    apply what comes back.  A backlog therefore drains one edge per
    ``await Timer``, which is precisely the exposure a press needs to be seen.
    """

    def __init__(self, max_pending: int = DEFAULT_MAX_PENDING) -> None:
        """Hold at most *max_pending* states before discarding the oldest."""
        self._max_pending = max(1, max_pending)
        self._pending: deque[InputState] = deque()
        #: Last state known to the queue, applied or merely queued -- the
        #: reference the duplicate check compares against.
        self._latest: tuple[int, int] | None = None
        self._applied_seq: int = 0
        self._dropped: int = 0

    def __len__(self) -> int:
        """Return how many states are still waiting to be applied."""
        return len(self._pending)

    @property
    def applied_seq(self) -> int:
        """Highest host ``seq`` whose state the DUT is known to be showing.

        Advanced by :meth:`pop`, and also by a duplicate push arriving while
        the queue is empty: that state is already applied, so acknowledging it
        immediately is truthful rather than optimistic.
        """
        return self._applied_seq

    @property
    def dropped(self) -> int:
        """How many states the backlog cap has discarded this run."""
        return self._dropped

    def push(self, sw: int, btn: int, seq: int) -> None:
        """Queue one full-state message, deduplicating and capping the backlog."""
        state = (sw, btn)
        if state == self._latest:
            # No edge.  Carry the newer seq anyway so the acknowledgement keeps
            # up: either fold it into the queued twin, or -- with nothing
            # queued -- settle it now, since the DUT already shows this state.
            if self._pending:
                tail = self._pending[-1]
                self._pending[-1] = InputState(tail.sw, tail.btn, seq)
            else:
                self._applied_seq = max(self._applied_seq, seq)
            return

        self._pending.append(InputState(sw, btn, seq))
        self._latest = state
        while len(self._pending) > self._max_pending:
            self._pending.popleft()
            self._dropped += 1

    def pop(self) -> InputState | None:
        """Return the next state to apply, or None when nothing is pending."""
        if not self._pending:
            return None
        state = self._pending.popleft()
        self._applied_seq = state.seq
        return state
