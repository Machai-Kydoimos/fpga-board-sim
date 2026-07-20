"""Duty-cycle math shared by the headless child and its tests (roadmap U9).

PWM is **measured, never inferred**.  Static analysis of the design cannot
work in principle -- the embedded-core designs compute their LED duty from
firmware bytes at run time, generics are overridden at launch, and any pattern
match is defeated by obfuscation -- so the generated ``sim_wrapper`` integrates
each LED/segment channel's on-time in VHDL (see ``sim/duty/*.vhd.frag``) and
this module turns two of those snapshots into an exact duty cycle.

The wrapper exports, per channel *i* of a monitored vector:

``<p>_acc(i)``
    total on-time, in ns, over ``[0, <p>_tch(i)]``
``<p>_tch(i)``
    the ns at which channel *i* last changed (0 if it never has)

The interval in progress past ``tch`` is deliberately *not* in ``acc`` -- the
VHDL folds it in only when it ends, which is what keeps the integrator free of
cross-channel state.  Adding it back here gives

    T_on(i, t) = acc(i) + (t - tch(i))   if the channel is currently on
                 acc(i)                  otherwise

which is *by construction* the exact on-time over ``[0, t]``.  Differencing two
snapshots therefore yields the exact on-time of the window between them, with
no correction term and no sampling artifact: a stuck-on channel reads 1.0 (it
never transitions, so ``acc`` stays 0 and the in-progress term carries it), a
stuck-off channel 0.0, and a channel that is mid-pulse at the snapshot instant
contributes exactly its partial tail.

This module is pygame-free and cocotb-free so the U34 headless child, the
cocotb duty tests and the host unit tests can all import it.
"""

from __future__ import annotations

#: Width of one channel's accumulator field in the packed wrapper ports.
#: 48 bits of nanoseconds is ~3.2 days of simulated time before wrap, and the
#: differencing below is wrap-proof anyway.
ACC_BITS: int = 48
_ACC_MASK: int = (1 << ACC_BITS) - 1


def unpack(packed: int, count: int) -> list[int]:
    """Split a packed ``48 * count``-bit accumulator vector into per-channel ints.

    Channel *i* occupies bits ``[48*i + 47 : 48*i]`` of the wrapper's
    ``std_logic_vector(48 * N - 1 downto 0)``, so the natural integer value of
    the whole vector shifts down cleanly.
    """
    return [(packed >> (ACC_BITS * i)) & _ACC_MASK for i in range(count)]


class DutyTracker:
    """Per-channel exact duty over the window between two wrapper snapshots.

    One instance per monitored vector (``led``, ``seg``).  Keeps the previous
    snapshot's ``T_on`` per channel and the sim time it was taken at, so
    :meth:`update` reports the duty of the window since then rather than since
    the start of the run.
    """

    def __init__(self, count: int) -> None:
        """Track *count* channels, seeded at sim time 0 with no on-time yet."""
        self.count = max(0, count)
        self._prev_ton: list[int] = [0] * self.count
        self._prev_ns: int = 0

    def update(
        self, packed_acc: int, packed_tch: int, levels: int, sim_ns: int
    ) -> list[float] | None:
        """Duty of every channel over ``(previous sim_ns, sim_ns]``.

        *packed_acc* / *packed_tch* are the wrapper's two accumulator vectors
        read as plain ints, *levels* the current value of the monitored vector
        (bit *i* = channel *i*'s present level), *sim_ns* the simulated time
        those three were read at.  All three must come from the same instant --
        the child reads them with no ``await`` in between -- or a channel's
        in-progress interval would be measured against the wrong clock.

        Returns ``None`` when no simulated time has passed since the last call
        (nothing new to average over: the caller should reuse its last values
        rather than render a spurious 0%).
        """
        window = sim_ns - self._prev_ns
        if window <= 0:
            return None

        duties: list[float] = []
        for i in range(self.count):
            ton = (packed_acc >> (ACC_BITS * i)) & _ACC_MASK
            if (levels >> i) & 1:
                # Currently on: add the interval that has not ended yet.
                ton += sim_ns - ((packed_tch >> (ACC_BITS * i)) & _ACC_MASK)
            # Wrap-proof: a window is many orders of magnitude below 2**48 ns.
            delta = (ton - self._prev_ton[i]) & _ACC_MASK
            self._prev_ton[i] = ton
            duties.append(min(1.0, max(0.0, delta / window)))

        self._prev_ns = sim_ns
        return duties
