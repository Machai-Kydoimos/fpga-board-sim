"""Tests for the U44 child-side input queue (:mod:`fpga_sim.sim_input`, issue #353).

Pure host units against hand-worked sequences -- no simulator, no cocotb, no
pygame -- exactly as ``tests/test_duty.py``'s first layer exercises
:class:`~fpga_sim.sim_duty.DutyTracker`.  These cover the queue's contract; the
end-to-end proof that a press and its release arriving in the *same* drain still
reach a real design is a separate ``slow`` test against GHDL and NVC.
"""

from fpga_sim.sim_input import DEFAULT_MAX_PENDING, InputQueue, InputState


def _drain(q: InputQueue, steps: int) -> list[InputState]:
    """Pop once per simulated loop iteration, keeping only what was applied."""
    applied = []
    for _ in range(steps):
        state = q.pop()
        if state is not None:
            applied.append(state)
    return applied


# ── One state per iteration ──────────────────────────────────────────────────


def test_pop_returns_at_most_one_state_per_call():
    """Three states pushed in one drain must take three iterations to apply."""
    q = InputQueue()
    q.push(sw=0, btn=1, seq=1)
    q.push(sw=0, btn=0, seq=2)
    q.push(sw=0, btn=2, seq=3)
    assert len(q) == 3

    assert q.pop() == InputState(0, 1, 1)
    assert q.pop() == InputState(0, 0, 2)
    assert q.pop() == InputState(0, 2, 3)
    assert q.pop() is None


def test_empty_queue_pops_none():
    """An idle iteration must not fabricate an input to apply."""
    assert InputQueue().pop() is None


def test_press_and_release_in_one_drain_both_survive():
    """The #353 case: a tap arriving whole in one drain still yields two edges.

    Pre-U44 the child assigned ``dut.btn`` for each drained message with no
    ``await`` between them, so cocotb collapsed the pair to the release and the
    design never saw the press at all.
    """
    q = InputQueue()
    q.push(sw=0, btn=1, seq=1)  # press
    q.push(sw=0, btn=0, seq=2)  # release, same drain

    applied = _drain(q, steps=4)
    assert [s.btn for s in applied] == [1, 0]


def test_a_burst_of_taps_keeps_every_edge_in_order():
    """Four taps drained together must apply as eight ordered edges."""
    q = InputQueue()
    seq = 0
    for _ in range(4):
        for btn in (1, 0):
            seq += 1
            q.push(sw=0, btn=btn, seq=seq)

    applied = _drain(q, steps=12)
    assert [s.btn for s in applied] == [1, 0, 1, 0, 1, 0, 1, 0]
    assert [s.seq for s in applied] == list(range(1, 9))


# ── Consecutive duplicates collapse ──────────────────────────────────────────


def test_consecutive_duplicates_are_dropped():
    """The host sends full state, so an unchanged state carries no edge."""
    q = InputQueue()
    q.push(sw=3, btn=0, seq=1)
    q.push(sw=3, btn=0, seq=2)
    q.push(sw=3, btn=0, seq=3)
    assert len(q) == 1
    assert q.pop() == InputState(3, 0, 3)  # the newest seq, folded in
    assert q.pop() is None


def test_duplicate_after_apply_is_dropped_but_acknowledged():
    """A repeat of the state already applied must not cost an iteration."""
    q = InputQueue()
    q.push(sw=1, btn=0, seq=1)
    assert q.pop() == InputState(1, 0, 1)

    q.push(sw=1, btn=0, seq=2)
    assert len(q) == 0
    assert q.pop() is None
    assert q.applied_seq == 2  # truthful: the DUT already shows this state


def test_a_state_repeating_a_non_adjacent_one_is_kept():
    """Only *consecutive* duplicates collapse -- off/on/off is three edges."""
    q = InputQueue()
    q.push(sw=0, btn=0, seq=1)
    q.push(sw=0, btn=1, seq=2)
    q.push(sw=0, btn=0, seq=3)
    assert [s.btn for s in _drain(q, steps=4)] == [0, 1, 0]


def test_switch_and_button_are_compared_together():
    """A state differing only in sw is a real edge, not a button duplicate."""
    q = InputQueue()
    q.push(sw=0, btn=1, seq=1)
    q.push(sw=4, btn=1, seq=2)
    assert [(s.sw, s.btn) for s in _drain(q, steps=3)] == [(0, 1), (4, 1)]


# ── Acknowledgement (the seq echoed back in every state message) ─────────────


def test_applied_seq_starts_at_zero_and_only_advances_on_apply():
    """Queuing must not claim application; popping is what acknowledges."""
    q = InputQueue()
    assert q.applied_seq == 0

    q.push(sw=0, btn=1, seq=7)
    assert q.applied_seq == 0  # queued, not yet applied

    q.pop()
    assert q.applied_seq == 7


def test_applied_seq_tracks_the_backlog_one_step_at_a_time():
    """The ack must trail the backlog honestly rather than jumping to newest."""
    q = InputQueue()
    q.push(sw=0, btn=1, seq=1)
    q.push(sw=0, btn=0, seq=2)

    q.pop()
    assert q.applied_seq == 1
    q.pop()
    assert q.applied_seq == 2


# ── Backlog cap bounds the lag ───────────────────────────────────────────────


def test_backlog_cap_discards_the_oldest_entries():
    """Past the cap, staying near reality beats replaying ancient edges."""
    q = InputQueue(max_pending=4)
    for seq in range(1, 11):
        q.push(sw=seq, btn=0, seq=seq)

    assert len(q) == 4
    assert q.dropped == 6
    applied = _drain(q, steps=4)
    assert [s.seq for s in applied] == [7, 8, 9, 10]  # the newest survive


def test_backlog_cap_keeps_the_latest_state_reachable():
    """However deep the burst, the DUT must end on the user's current state."""
    q = InputQueue(max_pending=2)
    for seq in range(1, 21):
        q.push(sw=0, btn=seq % 2, seq=seq)

    applied = _drain(q, steps=20)
    assert applied[-1].seq == 20
    assert applied[-1].btn == 0  # 20 % 2


def test_default_cap_is_used_when_unspecified():
    """The shipped default bounds the queue without being passed explicitly."""
    q = InputQueue()
    for seq in range(1, DEFAULT_MAX_PENDING + 6):
        q.push(sw=seq, btn=0, seq=seq)
    assert len(q) == DEFAULT_MAX_PENDING
    assert q.dropped == 5


def test_cap_below_one_is_clamped():
    """A degenerate cap must still hold the newest state, not deadlock."""
    q = InputQueue(max_pending=0)
    q.push(sw=1, btn=0, seq=1)
    q.push(sw=2, btn=0, seq=2)
    assert len(q) == 1
    assert q.pop() == InputState(2, 0, 2)


def test_nothing_is_dropped_below_the_cap():
    """The cap is a safety valve, not a routine one."""
    q = InputQueue(max_pending=8)
    for seq in range(1, 9):
        q.push(sw=seq, btn=0, seq=seq)
    assert q.dropped == 0
    assert len(q) == 8
