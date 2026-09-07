"""Behavioral test for hdl/code_lock_fsm.vhd.

The lock opens on btn0, btn1, btn0 and on nothing else.  The tests below check
both halves of that claim, because an FSM that opens on the right sequence but
*also* on a wrong one is the failure a happy-path test cannot see.
"""

from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

_CLK_NS = 10


async def _press(dut: Any, index: int) -> None:
    """Press and release button *index*, held long enough to be sampled.

    The design detects the *edge*, so a press must go low again before the next
    one or the second press is never seen.
    """
    dut.btn.value = 1 << index
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.btn.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)


def _unlocked(dut: Any) -> bool:
    return bool(int(dut.led.value) & 1)


async def _relock(dut: Any) -> None:
    """Drive the relock input until the machine is back at LOCKED."""
    dut.btn.value = 1 << 2  # btn2 relocks, and is level-sensitive
    for _ in range(3):
        await RisingEdge(dut.clk)
    dut.btn.value = 0
    for _ in range(3):
        await RisingEdge(dut.clk)
    assert not _unlocked(dut), "relock did not take"


async def _start(dut: Any) -> None:
    """Start the clock and put the lock into a known state.

    All the tests in this module share one simulation, and the design has no
    power-on reset beyond its relock input -- which is realistic, and exactly
    why this matters: a test that ran earlier and left the lock *open* would
    make every later assertion here a statement about the wrong state.  So each
    test relocks first, and none of them depends on the order they run in.
    """
    Clock(dut.clk, _CLK_NS, unit="ns").start()
    dut.sw.value = 0
    dut.btn.value = 0
    await Timer(5 * _CLK_NS, unit="ns")

    await _relock(dut)


@cocotb.test()
async def test_the_right_sequence_opens_it(dut):
    """btn0, btn1, btn0 unlocks; it stays locked until the last press."""
    await _start(dut)
    assert not _unlocked(dut), "started unlocked"

    await _press(dut, 0)
    assert not _unlocked(dut), "opened after one press"
    await _press(dut, 1)
    assert not _unlocked(dut), "opened after two presses"
    await _press(dut, 0)
    assert _unlocked(dut), "did not open after the full sequence"

    print("PASS code lock: btn0, btn1, btn0 unlocks")


@cocotb.test()
async def test_a_wrong_press_starts_over(dut):
    """A wrong press resets progress, so the code cannot be stumbled into."""
    await _start(dut)

    # Two correct, then a wrong one, then the last correct press: had the wrong
    # press not reset progress, this would open the lock.
    await _press(dut, 0)
    await _press(dut, 1)
    await _press(dut, 1)  # wrong: expected btn0 here
    await _press(dut, 0)
    assert not _unlocked(dut), "a wrong press did not reset progress"

    # And the lock still works afterwards.  Relock first rather than pressing
    # on from wherever the machine ended up: the run above finishes in ONE_OK,
    # not LOCKED, so a "full sequence" from here would start one press in and
    # would be testing something other than what it claims.
    await _relock(dut)
    await _press(dut, 0)
    await _press(dut, 1)
    await _press(dut, 0)
    assert _unlocked(dut), "did not open after restarting the sequence"

    print("PASS code lock: a wrong press starts over")


@cocotb.test()
async def test_a_held_button_counts_once(dut):
    """Holding btn0 must not walk the machine through the whole code.

    This is the classic first-FSM bug: testing the level instead of the edge
    makes one press look like millions, and the lock springs open on its own.
    """
    await _start(dut)

    dut.btn.value = 1
    for _ in range(200):
        await RisingEdge(dut.clk)
    assert not _unlocked(dut), "holding one button opened the lock"

    print("PASS code lock: a held button is one press, not many")
