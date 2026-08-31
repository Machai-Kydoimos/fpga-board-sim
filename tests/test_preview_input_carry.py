"""Tests for carrying preview switch/latch state into the run (U45).

The preview screen and the simulation build **separate** ``FPGABoard`` objects,
and the controller rebuilds the preview's on every entry, so switches and
latches used to be discarded at each screen boundary.  Three layers here: the
``BoardInputs`` snapshot/restore pair on the board, the ``SimulationScreen``
seam that applies one at construction, and the controller flow that carries it
preview -> run -> preview and drops it when the board changes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from fpga_sim.board_loader import BoardDef, ComponentInfo
from fpga_sim.ui import BoardInputs, FPGABoard
from fpga_sim.ui.components import Button

if TYPE_CHECKING:
    from types import ModuleType


@pytest.fixture(autouse=True)
def _isolate_session(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect session writes away from ~/.fpga_simulator for every test."""
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr("fpga_sim.sim_session_log._SESSION_DIR", tmp_path / "sessions")


def _board_def() -> BoardDef:
    return BoardDef(
        name="Test Board",
        class_name="TestBoard",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(3)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(4)],
    )


def _board(pygame: ModuleType) -> FPGABoard:
    return FPGABoard(board_def=_board_def(), screen=pygame.display.set_mode((1024, 700)))


# ── Snapshot / restore on the board ───────────────────────────────────────────


def test_snapshot_records_switches_and_latches(headless_pygame: ModuleType) -> None:
    board = _board(headless_pygame)
    board.switches[1].state = True
    board.switches[3].state = True
    board.buttons[2].toggle_latch()

    snap = board.input_snapshot()
    assert snap.switches == (False, True, False, True)
    assert snap.latched == frozenset({2})


def test_snapshot_omits_live_mouse_and_key_holds(headless_pygame: ModuleType) -> None:
    """A hold belongs to a gesture that is over; only the latch is carried."""
    board = _board(headless_pygame)
    board.buttons[0].hold("mouse:1")
    board.buttons[1].hold("key:s30")
    board.buttons[1].toggle_latch()

    assert board.input_snapshot().latched == frozenset({1})


def test_restore_puts_the_state_back(headless_pygame: ModuleType) -> None:
    board = _board(headless_pygame)
    assert board.restore_inputs(BoardInputs(switches=(True, False, True, False), latched={1}))
    assert [sw.state for sw in board.switches] == [True, False, True, False]
    assert board.buttons[1].latched
    assert board.buttons[1].pressed
    assert not board.buttons[0].latched


def test_restore_is_silent(headless_pygame: ModuleType) -> None:
    """No widget callbacks: the caller ships the whole state in one message."""
    board = _board(headless_pygame)
    fired: list[tuple[str, int]] = []
    board.set_switch_callback(lambda i, s, info: fired.append(("sw", i)))
    board.set_button_callback(lambda i, p, info: fired.append(("btn", i)))

    board.restore_inputs(BoardInputs(switches=(True, True, True, True), latched={0, 1, 2}))
    assert fired == []


def test_restore_round_trips(headless_pygame: ModuleType) -> None:
    a, b = _board(headless_pygame), _board(headless_pygame)
    a.switches[0].state = True
    a.buttons[1].toggle_latch()
    b.restore_inputs(a.input_snapshot())
    assert b.input_snapshot() == a.input_snapshot()


def test_restore_clears_what_the_snapshot_does_not_hold(headless_pygame: ModuleType) -> None:
    """Restoring is an assignment, not a merge — a released latch stays released."""
    board = _board(headless_pygame)
    board.switches[0].state = True
    board.buttons[0].toggle_latch()

    board.restore_inputs(BoardInputs(switches=(False, False, False, False)))
    assert not any(sw.state for sw in board.switches)
    assert not board.buttons[0].latched
    assert not board.buttons[0].pressed


def test_restore_leaves_live_holds_alone(headless_pygame: ModuleType) -> None:
    """set_latched touches only the latch source, never a hold the user is making."""
    board = _board(headless_pygame)
    board.buttons[0].hold("mouse:1")
    board.restore_inputs(BoardInputs(latched=frozenset()))
    assert board.buttons[0].pressed
    assert board.buttons[0].holds == frozenset({"mouse:1"})


def test_restore_tolerates_a_mismatched_width(headless_pygame: ModuleType) -> None:
    """A wrong-sized snapshot truncates rather than raising in the launcher."""
    board = _board(headless_pygame)  # 4 switches, 3 buttons
    board.restore_inputs(BoardInputs(switches=(True,) * 9, latched={0, 7}))
    assert [sw.state for sw in board.switches] == [True] * 4
    assert board.buttons[0].latched


def test_empty_inputs_are_falsey(headless_pygame: ModuleType) -> None:
    """An all-off board carries nothing, so callers can skip the work."""
    assert not BoardInputs()
    assert not BoardInputs(switches=(False, False))
    assert BoardInputs(switches=(False, True))
    assert BoardInputs(latched={0})
    assert not _board(headless_pygame).input_snapshot()


def test_set_latched_is_silent_and_idempotent(headless_pygame: ModuleType) -> None:
    btn = Button(0)
    fired: list[bool] = []
    btn.callback = lambda i, p, info: fired.append(p)

    btn.set_latched(True)
    btn.set_latched(True)
    assert btn.latched and btn.pressed and fired == []
    btn.set_latched(False)
    btn.set_latched(False)
    assert not btn.latched and not btn.pressed and fired == []


# ── The SimulationScreen seam ─────────────────────────────────────────────────


def test_run_starts_with_the_carried_state(headless_pygame: ModuleType, fake_child: Any) -> None:
    from tests.test_simulation_screen import _make_screen

    child, _client = fake_child
    screen = _make_screen(
        headless_pygame,
        child,
        initial_inputs=BoardInputs(switches=(False, True, False, True), latched={1}),
    )
    assert [sw.state for sw in screen.board.switches] == [False, True, False, True]
    assert screen.board.buttons[1].latched


def test_carried_state_reaches_the_child_before_the_first_step(
    headless_pygame: ModuleType, fake_child: Any
) -> None:
    """The dirty flag survives the disconnected frames, so nothing is lost."""
    from fpga_sim.sim_link import drain
    from tests.test_simulation_screen import _collect, _make_screen

    child, client = fake_child
    screen = _make_screen(
        headless_pygame,
        child,
        initial_inputs=BoardInputs(switches=(True, False, True, False), latched={2}),
    )
    # Nothing can be in flight here: _flush_input returns before sending.
    screen._flush_input()  # still disconnected: held back, flag kept
    assert drain(client) == []

    screen._connected = True
    screen._flush_input()
    # _collect, not a bare drain: the loopback send is asynchronous, so on a
    # slower host the write has not landed by the time drain() looks. This
    # failed on macOS/py3.10 in CI while passing everywhere else.
    msgs = _collect(client, 1)
    assert len(msgs) == 1
    kind, payload = msgs[0]
    assert kind == "input"
    assert payload["sw"] == 0b0101
    assert payload["btn"] == 0b100


def test_no_carried_state_sends_nothing(headless_pygame: ModuleType, fake_child: Any) -> None:
    """An all-off carry must not manufacture an input message the user never made."""
    from tests.test_simulation_screen import _collect, _make_screen

    child, client = fake_child
    screen = _make_screen(headless_pygame, child, initial_inputs=BoardInputs())
    screen._connected = True
    screen._flush_input()
    # Asserting an absence, so allow time for a send to arrive before concluding
    # none was made -- a bare drain() would pass with one still in flight.
    assert _collect(client, 1, timeout=0.3) == []


# ── The controller flow ───────────────────────────────────────────────────────


def test_preview_restores_then_recaptures(headless_pygame: ModuleType, monkeypatch: Any) -> None:
    """Re-entering the preview shows what the user left, not a reset board."""
    from fpga_sim.ui import ScreenResult
    from tests.test_controller import _board as _ctrl_board
    from tests.test_controller import _install_preview, _make_controller

    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_ctrl_board())
    left_holding = BoardInputs(switches=(True, False), latched={1})

    fake = _install_preview(monkeypatch, ScreenResult.QUIT)
    fake.final_inputs = left_holding
    ctrl._run_preview()
    assert ctrl.state.inputs == left_holding  # captured on the way out

    fake.final_inputs = None
    ctrl._run_preview()
    assert fake.restored[-1] == left_holding  # and restored on the way back in


def test_choosing_another_board_drops_the_carry(headless_pygame: ModuleType) -> None:
    """Indices mean nothing across boards, so a new board starts from its defaults."""
    from tests.test_controller import _board as _ctrl_board

    ctrl = _make_ctrl(headless_pygame)
    ctrl.on_board_selected(_ctrl_board())
    ctrl.state.inputs = BoardInputs(switches=(True, True), latched={0})

    ctrl.on_board_selected(BoardDef("Other", "OtherPlatform", source="custom"))
    assert ctrl.state.inputs == BoardInputs()


def test_reselecting_the_same_board_keeps_the_carry(headless_pygame: ModuleType) -> None:
    """Only a *different* board resets it — re-picking the current one must not."""
    from tests.test_controller import _board as _ctrl_board

    ctrl = _make_ctrl(headless_pygame)
    ctrl.on_board_selected(_ctrl_board())
    carried = BoardInputs(switches=(True,), latched={0})
    ctrl.state.inputs = carried

    ctrl.on_board_selected(_ctrl_board())
    assert ctrl.state.inputs == carried


def test_simulate_passes_the_carry_in_and_takes_it_back(
    headless_pygame: ModuleType, monkeypatch: Any, tmp_path: Any
) -> None:
    from fpga_sim.ui import SimExit
    from tests.test_controller import _attached_harness, _FakeSimScreen

    ctrl, _starts, _finishes = _attached_harness(
        headless_pygame, monkeypatch, tmp_path, sim_exits=[SimExit.STOPPED]
    )
    ctrl.state.inputs = BoardInputs(switches=(True, False), latched={0})
    ended_with = BoardInputs(switches=(False, True), latched={1})
    _FakeSimScreen.final_inputs = [ended_with]

    ctrl.on_simulate()
    assert _FakeSimScreen.instances[0]["initial_inputs"] == BoardInputs(
        switches=(True, False), latched={0}
    )
    assert ctrl.state.inputs == ended_with  # the run's own edits survive [Stop]


def _make_ctrl(pygame: ModuleType) -> Any:
    from tests.test_controller import _make_controller

    return _make_controller(pygame)
