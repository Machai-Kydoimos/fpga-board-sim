"""Tests for FPGABoard._handle_events keyboard shortcuts.

Currently covers the R key (reset switches off, release held buttons).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fpga_sim.board_loader import BoardDef, ComponentInfo

if TYPE_CHECKING:
    from types import ModuleType

    from pygame.event import Event

    from fpga_sim.ui import FPGABoard


def _sample_board() -> BoardDef:
    return BoardDef(
        name="Test Board",
        class_name="TestBoard",
        vendor="TestVendor",
        device="TestDevice",
        package="QFP100",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(3)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(4)],
    )


def _make_board(headless_pygame: ModuleType) -> FPGABoard:
    from fpga_sim.ui import FPGABoard

    headless_pygame.display.set_mode((1024, 700))
    return FPGABoard(board_def=_sample_board(), width=1024, height=700)


def _r_keydown(pygame: ModuleType) -> Event:
    ev: Event = pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_r, "mod": 0})
    return ev


# ── R key: switch reset ──────────────────────────────────────────────────────


def test_r_resets_all_switches_off(headless_pygame):
    """All toggled switches must flip off after pressing R."""
    board = _make_board(headless_pygame)
    board.switches[0].state = True
    board.switches[2].state = True
    board._handle_events([_r_keydown(headless_pygame)])
    assert all(not sw.state for sw in board.switches)


def test_r_fires_callback_for_toggled_switches_only(headless_pygame):
    """Switches already off must not fire callbacks; toggled switches must."""
    board = _make_board(headless_pygame)
    board.switches[0].state = True
    board.switches[2].state = True

    fired: list[tuple[int, bool]] = []
    for sw in board.switches:
        sw.callback = lambda idx, state, _info, fired=fired: fired.append((idx, state))

    board._handle_events([_r_keydown(headless_pygame)])
    assert sorted(fired) == [(0, False), (2, False)]


# ── R key: button release ────────────────────────────────────────────────────


def test_r_releases_held_buttons(headless_pygame):
    """All held buttons must flip to released after pressing R."""
    board = _make_board(headless_pygame)
    board.buttons[1].pressed = True
    board.buttons[2].pressed = True
    board._handle_events([_r_keydown(headless_pygame)])
    assert all(not btn.pressed for btn in board.buttons)


def test_r_fires_callback_for_held_buttons_only(headless_pygame):
    """Buttons already released must not fire callbacks; held buttons must."""
    board = _make_board(headless_pygame)
    board.buttons[1].pressed = True

    fired: list[tuple[int, bool]] = []
    for btn in board.buttons:
        btn.callback = lambda idx, state, _info, fired=fired: fired.append((idx, state))

    board._handle_events([_r_keydown(headless_pygame)])
    assert fired == [(1, False)]


# ── R key: combined + idempotence ────────────────────────────────────────────


def test_r_with_no_active_inputs_is_a_noop(headless_pygame):
    """Pressing R when nothing is toggled must fire no callbacks and change nothing."""
    board = _make_board(headless_pygame)

    fired: list[tuple[int, bool]] = []
    for sw in board.switches:
        sw.callback = lambda idx, state, _info, fired=fired: fired.append((idx, state))
    for btn in board.buttons:
        btn.callback = lambda idx, state, _info, fired=fired: fired.append((idx, state))

    board._handle_events([_r_keydown(headless_pygame)])
    assert fired == []
    assert all(not sw.state for sw in board.switches)
    assert all(not btn.pressed for btn in board.buttons)


def test_r_resets_switches_and_buttons_together(headless_pygame):
    """Switches and buttons must both reset in a single R press."""
    board = _make_board(headless_pygame)
    board.switches[0].state = True
    board.switches[3].state = True
    board.buttons[0].pressed = True

    board._handle_events([_r_keydown(headless_pygame)])
    assert all(not sw.state for sw in board.switches)
    assert all(not btn.pressed for btn in board.buttons)


# ── Help overlay triggers (F1 / ? / the (?) button) ──────────────────────────


def _keydown(pygame: ModuleType, key: int, unicode: str = "") -> Event:
    ev: Event = pygame.event.Event(pygame.KEYDOWN, {"key": key, "mod": 0, "unicode": unicode})
    return ev


def test_f1_requests_help(headless_pygame):
    board = _make_board(headless_pygame)
    board._handle_events([_keydown(headless_pygame, headless_pygame.K_F1)])
    assert board._help_requested is True


def test_question_mark_requests_help(headless_pygame):
    board = _make_board(headless_pygame)
    board._handle_events([_keydown(headless_pygame, headless_pygame.K_SLASH, "?")])
    assert board._help_requested is True


def test_r_key_without_unicode_does_not_crash(headless_pygame):
    """A sparse synthetic event (no .unicode) must not raise in the F1/? guard."""
    board = _make_board(headless_pygame)
    board.switches[0].state = True
    board._handle_events([_r_keydown(headless_pygame)])  # event has no 'unicode'
    assert board._help_requested is False
    assert all(not sw.state for sw in board.switches)


def test_help_button_click_requests_help(headless_pygame):
    board = _make_board(headless_pygame)
    board._draw()  # populates self._help_btn_rect
    assert board._help_btn_rect is not None
    click = headless_pygame.event.Event(
        headless_pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": board._help_btn_rect.center}
    )
    board._handle_events([click])
    assert board._help_requested is True


# ── Resize reconciliation after the help overlay closes ──────────────────────


def test_help_sync_reflows_to_resized_surface(headless_pygame):
    """A resize during help must reflow the board layout once help closes."""
    board = _make_board(headless_pygame)
    before = board.leds[0].rect.copy()
    board.screen = headless_pygame.Surface((1500, 1000))  # auto-resized display
    board._sync_to_surface()
    assert (board.width, board.height) == (1500, 1000)  # _height_offset is 0 here
    assert board.leds[0].rect != before  # layout reflowed to the new size


def test_help_sync_without_resize_is_stable(headless_pygame):
    board = _make_board(headless_pygame)
    before = board.leds[0].rect.copy()
    board._sync_to_surface()  # surface unchanged (1024x700)
    assert (board.width, board.height) == (1024, 700)
    assert board.leds[0].rect == before


# ── run() result mapping (D6a ScreenResult enum) ─────────────────────────────


def test_result_maps_exit_flags_to_screenresult(headless_pygame):
    """_result() must map the loop-exit flags to the right ScreenResult, with
    simulate > load_vhdl > back > quit precedence (mirrors the run() if-ladder)."""
    from fpga_sim.ui import ScreenResult

    board = _make_board(headless_pygame)
    assert board._result() is ScreenResult.QUIT  # no action flag set → window closed
    board._go_back = True
    assert board._result() is ScreenResult.BACK
    board._load_vhdl = True  # load_vhdl outranks go_back
    assert board._result() is ScreenResult.LOAD_VHDL
    board._simulate = True  # simulate outranks everything
    assert board._result() is ScreenResult.SIMULATE
