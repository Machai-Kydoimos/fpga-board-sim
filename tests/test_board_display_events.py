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


# ── [SIM:…] simulator toggle (U35) ───────────────────────────────────────────


def test_sim_toggle_cycles_installed_sims(headless_pygame):
    """Clicking [SIM:…] advances board.sim through the installed list and wraps."""
    from fpga_sim.sim_bridge import SimulatorInfo
    from fpga_sim.ui import FPGABoard

    ghdl = SimulatorInfo("ghdl", "/u/ghdl", "mcode", "GHDL", "g")
    nvc = SimulatorInfo("nvc", "/u/nvc", "nvc", "NVC", "n")
    headless_pygame.display.set_mode((1024, 700))
    board = FPGABoard(
        board_def=_sample_board(), width=1024, height=700, sim=ghdl, available_sims=[ghdl, nvc]
    )

    def _click_toggle() -> None:
        board._draw(flip=False)  # lays out the (right-anchored, label-sized) toggle rect
        assert board._sim_toggle_rect is not None
        ev = headless_pygame.event.Event(
            headless_pygame.MOUSEBUTTONDOWN,
            {"button": 1, "pos": board._sim_toggle_rect.center},
        )
        board._handle_events([ev])

    assert board.sim is ghdl
    _click_toggle()
    assert board.sim is nvc  # advanced to the next installed sim
    _click_toggle()
    assert board.sim is ghdl  # wraps around


def test_sim_toggle_absent_when_single_sim(headless_pygame):
    """One installed simulator → the toggle is drawn but disabled (no cycle)."""
    from fpga_sim.sim_bridge import SimulatorInfo
    from fpga_sim.ui import FPGABoard

    only = SimulatorInfo("ghdl", "/u/ghdl", "mcode", "GHDL", "g")
    headless_pygame.display.set_mode((1024, 700))
    board = FPGABoard(
        board_def=_sample_board(), width=1024, height=700, sim=only, available_sims=[only]
    )
    board._draw(flip=False)
    assert board._sim_toggle_rect is not None
    ev = headless_pygame.event.Event(
        headless_pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": board._sim_toggle_rect.center}
    )
    board._handle_events([ev])
    assert board.sim is only  # a single-entry list does not cycle


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


# ── Settings (gear) button — U5 ───────────────────────────────────────────────


def test_settings_button_click_requests_settings(headless_pygame):
    board = _make_board(headless_pygame)
    board._draw()  # populates self._settings_btn_rect
    assert board._settings_btn_rect is not None
    click = headless_pygame.event.Event(
        headless_pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": board._settings_btn_rect.center}
    )
    board._handle_events([click])
    assert board._settings_requested is True
    assert board._help_requested is False  # the neighboring (?) must not fire


def test_settings_button_sits_left_of_help(headless_pygame):
    board = _make_board(headless_pygame)
    board._draw()
    assert board._settings_btn_rect is not None and board._help_btn_rect is not None
    assert board._settings_btn_rect.right < board._help_btn_rect.left
    assert board._settings_btn_rect.top == board._help_btn_rect.top


def test_settings_button_absent_without_footer(headless_pygame):
    """The sim subprocess (show_footer=False) draws no gear — nothing to click."""
    board = _make_board(headless_pygame)
    board._show_footer = False
    board._draw()
    assert board._settings_btn_rect is None


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


# ── Hold sources: mouse identity, transient release, reset (U44) ─────────────


def _mousedown(pygame: ModuleType, pos: tuple[int, int], button: int = 1) -> Event:
    ev: Event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": button})
    return ev


def _mouseup(pygame: ModuleType, pos: tuple[int, int], button: int = 1) -> Event:
    ev: Event = pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": pos, "button": button})
    return ev


def test_mouse_up_releases_only_the_pressed_button(headless_pygame):
    """A mouse release must not disturb a button held by another source."""
    board = _make_board(headless_pygame)
    board._draw()  # lay out the widget rects
    board.buttons[0].hold("key:30")

    board._handle_events([_mousedown(headless_pygame, board.buttons[1].rect.center)])
    assert board.buttons[1].pressed is True

    board._handle_events([_mouseup(headless_pygame, board.buttons[1].rect.center)])
    assert board.buttons[1].pressed is False
    assert board.buttons[0].pressed is True  # the key hold is untouched


def test_two_buttons_release_in_reverse_order(headless_pygame):
    """Independent hold sets release independently, whatever the order."""
    board = _make_board(headless_pygame)
    board.buttons[0].hold("key:30")
    board.buttons[1].hold("key:31")

    board.buttons[1].handle_release("key:31")
    assert (board.buttons[0].pressed, board.buttons[1].pressed) == (True, False)
    board.buttons[0].handle_release("key:30")
    assert (board.buttons[0].pressed, board.buttons[1].pressed) == (False, False)


def test_drag_off_then_release_releases_the_pressed_button(headless_pygame):
    """Press BTN0, drag onto BTN1, release: BTN0 goes up, BTN1 never went down.

    The hold is keyed by the widget the press landed on, not by where the
    cursor happens to be at release — the standard UI convention, and what
    real hardware does.
    """
    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, board.buttons[0].rect.center)])
    board._handle_events([_mouseup(headless_pygame, board.buttons[1].rect.center)])
    assert board.buttons[0].pressed is False
    assert board.buttons[1].pressed is False


def test_mouse_up_off_every_widget_still_releases_the_hold(headless_pygame):
    """Releasing over empty board area must not strand the pressed button."""
    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, board.buttons[0].rect.center)])
    assert board.buttons[0].pressed is True
    board._handle_events([_mouseup(headless_pygame, (0, 0))])
    assert board.buttons[0].pressed is False


def test_mouse_hold_survives_a_resize(headless_pygame):
    """Holds are keyed by widget index, so a mid-gesture relayout keeps them."""
    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, board.buttons[0].rect.center)])
    board._resize(1400, 900)
    assert board.buttons[0].pressed is True

    board._handle_events([_mouseup(headless_pygame, board.buttons[0].rect.center)])
    assert board.buttons[0].pressed is False


def test_release_transient_holds_keeps_latches(headless_pygame):
    """Focus loss / a modal drops live holds only; latched buttons stay down."""
    from fpga_sim.ui.components import Button

    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, board.buttons[0].rect.center)])
    board.buttons[1].hold(Button.LATCH_SOURCE)
    board.buttons[2].hold("key:32")

    board.release_transient_holds()
    assert [b.pressed for b in board.buttons] == [False, True, False]
    assert board._mouse_holds == {}


def test_r_clears_latches_with_one_callback_each(headless_pygame):
    """R is the documented escape hatch, so it must clear latches too."""
    from fpga_sim.ui.components import Button

    board = _make_board(headless_pygame)
    board.buttons[0].hold(Button.LATCH_SOURCE)
    board.buttons[0].hold("key:30")
    board.buttons[1].hold(Button.LATCH_SOURCE)

    fired: list[tuple[int, bool]] = []
    for btn in board.buttons:
        btn.callback = lambda idx, state, _info, fired=fired: fired.append((idx, state))

    board._handle_events([_r_keydown(headless_pygame)])
    assert all(not btn.pressed for btn in board.buttons)
    assert fired == [(0, False), (1, False)]


def test_chrome_click_does_not_drop_later_events_in_the_batch(headless_pygame):
    """A chrome hit must consume only its own event, not the rest of the frame.

    Pre-U44 the chrome handlers ``return``ed out of the whole event loop, so
    every later event in the same batch — including a MOUSEBUTTONUP that ends
    a hold — was silently discarded.
    """
    board = _make_board(headless_pygame)
    board._draw()  # populates the footer chrome rects
    assert board._help_btn_rect is not None

    board._handle_events(
        [
            _mousedown(headless_pygame, board._help_btn_rect.center),
            _mousedown(headless_pygame, board.buttons[0].rect.center),
        ]
    )
    assert board._help_requested is True
    assert board.buttons[0].pressed is True  # the second event was still handled


# ── Right-click latching (U44 phase 3) ───────────────────────────────────────


def test_right_click_latches_and_unlatches(headless_pygame):
    board = _make_board(headless_pygame)
    board._draw()
    pos = board.buttons[1].rect.center

    board._handle_events([_mousedown(headless_pygame, pos, button=3)])
    assert board.buttons[1].latched is True
    assert board.buttons[1].pressed is True

    board._handle_events([_mousedown(headless_pygame, pos, button=3)])
    assert board.buttons[1].latched is False
    assert board.buttons[1].pressed is False


def test_left_mouse_up_does_not_clear_a_latch(headless_pygame):
    """The pre-U44 mouse-up released everything; a latch must survive it."""
    board = _make_board(headless_pygame)
    board._draw()
    pos = board.buttons[0].rect.center

    board._handle_events([_mousedown(headless_pygame, pos)])  # left hold
    board._handle_events([_mousedown(headless_pygame, pos, button=3)])  # + latch
    board._handle_events([_mouseup(headless_pygame, pos)])  # left release

    assert board.buttons[0].pressed is True
    assert board.buttons[0].latched is True


def test_right_click_off_every_button_is_a_noop(headless_pygame):
    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, (0, 0), button=3)])
    assert all(not b.latched for b in board.buttons)


def test_right_click_latches_only_the_button_under_the_cursor(headless_pygame):
    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, board.buttons[2].rect.center, button=3)])
    assert [b.latched for b in board.buttons] == [False, False, True]


def test_latch_survives_release_transient_holds(headless_pygame):
    """Focus loss / a modal must not silently drop a deliberate latch."""
    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, board.buttons[0].rect.center, button=3)])
    board.release_transient_holds()
    assert board.buttons[0].latched is True
    assert board.buttons[0].pressed is True


def test_latch_enters_the_visual_signature(headless_pygame):
    """Mouse-hold → latch → mouse-up leaves `pressed` True the whole way.

    Without the latch in the fingerprint the U23 redraw-skip would keep the
    held style on screen over a latched button indefinitely.
    """
    board = _make_board(headless_pygame)
    board._draw()
    pos = board.buttons[0].rect.center

    board._handle_events([_mousedown(headless_pygame, pos)])
    held = board.visual_signature()
    board._handle_events([_mousedown(headless_pygame, pos, button=3)])
    latched = board.visual_signature()

    assert board.buttons[0].pressed is True  # unchanged across the transition
    assert latched != held


def test_r_clears_a_latch_taken_by_right_click(headless_pygame):
    board = _make_board(headless_pygame)
    board._draw()
    board._handle_events([_mousedown(headless_pygame, board.buttons[1].rect.center, button=3)])
    board._handle_events([_r_keydown(headless_pygame)])
    assert board.buttons[1].latched is False
    assert board.buttons[1].pressed is False
