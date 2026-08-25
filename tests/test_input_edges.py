"""End-to-end proof that fast input edges reach the design (U44 phase 2, issue #353).

``tests/test_sim_input.py`` covers :class:`~fpga_sim.sim_input.InputQueue`'s
contract as pure logic.  What it cannot cover is the **wiring**: that the child
actually queues what it drains and applies one state per loop iteration rather
than assigning them all back to back.  That only shows up against a real
simulator, so these tests run a real headless child over a real ``sim_link``.

The fixture is ``sim/input_probe.vhd``, which counts *rising edges* on
``btn(0)`` into ``led`` and never clears.  A latching probe is essential: a
design that merely mirrors ``btn`` cannot distinguish a swallowed press from a
press that never happened, since both end with the LED off.

The regime under test is the one the bug lives in -- a burst of input messages
arriving inside a single drain window.  Sending them back to back guarantees
that, whatever the child's iteration timing: several messages are in the pipe
before the next drain, so the pre-fix code would collapse them to the last value
and the intervening presses would never exist.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from fpga_sim.sim_link import drain, send

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef
    from fpga_sim.sim_bridge import SimChild

PROJECT = Path(__file__).resolve().parent.parent
INPUT_PROBE = PROJECT / "sim" / "input_probe.vhd"

#: Taps sent in one burst.  Enough that a collapse is unmistakable, few enough
#: to stay inside InputQueue's backlog cap (16 states = 8 taps), so a failure
#: means edges were lost rather than deliberately dropped by the cap.
_TAPS = 8


def _probe_board() -> BoardDef:
    """A board with enough LEDs to hold the edge count (Arty A7-35: 4 mono)."""
    from fpga_sim.board_loader import discover_boards, get_default_boards_path

    boards = discover_boards(get_default_boards_path())
    board = next((b for b in boards if "ArtyA7_35Platform" in (b.class_name, b.name)), None)
    assert board is not None, "Arty A7-35 board not found"
    return board


def _wait_connected(child: SimChild, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.link.wait_connected(0.1):
            return
    raise AssertionError("the simulation child never connected")


def _wait_for_state(child: SimChild, timeout: float = 30.0) -> dict[str, Any]:
    """Block until the child reports its first state (it is running by then)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for kind, payload in drain(child.link.conn):
            if kind == "state":
                return payload
        time.sleep(0.01)
    raise AssertionError("the simulation child never sent a state message")


def _await_led(child: SimChild, want: int, timeout: float) -> tuple[int, int]:
    """Poll state until ``led`` reaches *want*; return the best (led, seq) seen."""
    best_led, best_seq = 0, 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for kind, payload in drain(child.link.conn):
            if kind != "state":
                continue
            led = int(payload.get("led", 0) or 0)
            best_led = max(best_led, led)
            best_seq = max(best_seq, int(payload.get("input_seq", 0) or 0))
            if best_led >= want:
                return best_led, best_seq
        time.sleep(0.01)
    return best_led, best_seq


def _run_edge_burst(simulator: str) -> None:
    """Send *_TAPS* press/release pairs in one burst; every press must be counted."""
    from fpga_sim.controller import build_generics
    from fpga_sim.sim_bridge import finish_waveform, start_simulation

    board = _probe_board()
    child = start_simulation(
        board.to_json(),
        INPUT_PROBE,
        "input_probe",
        build_generics(board),
        simulator=cast(Any, simulator),
        board_def=board,
        speed_factor=0.1,
    )
    try:
        _wait_connected(child)
        _wait_for_state(child)  # the loop is turning before any input is sent

        # The burst: 2 * _TAPS full-state messages with nothing between them, so
        # they reach the child together and are drained in one batch.
        seq = 0
        for _ in range(_TAPS):
            for btn in (1, 0):
                seq += 1
                send(child.link.conn, "input", {"sw": 0, "btn": btn, "seq": seq})

        led, applied_seq = _await_led(child, want=_TAPS, timeout=60.0)
        assert led == _TAPS, (
            f"design saw {led} of {_TAPS} presses -- edges were swallowed in the drain "
            f"(#353); last acknowledged input_seq={applied_seq}"
        )
        # Every message must also be acknowledged, so the host can tell that the
        # child is caught up rather than still working through a backlog.
        assert applied_seq == 2 * _TAPS
    finally:
        child.stop()
        finish_waveform(child)


@pytest.mark.slow
def test_burst_of_taps_all_reach_the_design_ghdl(ghdl):
    _run_edge_burst("ghdl")


@pytest.mark.slow
def test_burst_of_taps_all_reach_the_design_nvc(nvc):
    _run_edge_burst("nvc")
