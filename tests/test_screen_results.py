"""Tests for the D6a screen-transition enums (ScreenResult / DialogResult).

The FPGABoard.run() result mapping lives in test_board_display_events.py
(next to its board helper); here we cover the enum invariants and the
ErrorDialog producer (click / keyboard / quit → DialogResult).
"""

from fpga_sim.ui import DialogResult, ScreenResult

# ── Enum invariants ──────────────────────────────────────────────────────────


def test_screenresult_has_four_distinct_members():
    members = {
        ScreenResult.BACK,
        ScreenResult.LOAD_VHDL,
        ScreenResult.SIMULATE,
        ScreenResult.QUIT,
    }
    assert len(members) == 4


def test_dialogresult_has_two_distinct_members():
    assert DialogResult.RETRY is not DialogResult.BACK


def test_screen_and_dialog_back_are_disjoint():
    """Both enums have a BACK, but as separate types they never compare equal —
    so the two decision spaces can't be confused at runtime (mypy blocks it too)."""
    assert ScreenResult.BACK != DialogResult.BACK


# ── ErrorDialog producer ─────────────────────────────────────────────────────


def _make_dialog(headless_pygame):
    from fpga_sim.ui.error_dialog import ErrorDialog

    screen = headless_pygame.display.set_mode((1024, 700))
    dlg = ErrorDialog(screen, "VHDL Error", "something went wrong")
    dlg._draw()  # populates _retry_rect / _back_rect
    return dlg


def test_click_retry_button_returns_retry(headless_pygame):
    dlg = _make_dialog(headless_pygame)
    assert dlg._retry_rect is not None
    assert dlg._click(dlg._retry_rect.center) is DialogResult.RETRY


def test_click_back_button_returns_back(headless_pygame):
    dlg = _make_dialog(headless_pygame)
    assert dlg._back_rect is not None
    assert dlg._click(dlg._back_rect.center) is DialogResult.BACK


def test_click_outside_buttons_returns_none(headless_pygame):
    dlg = _make_dialog(headless_pygame)
    assert dlg._click((0, 0)) is None
