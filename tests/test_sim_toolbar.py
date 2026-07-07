"""Unit tests for the U7 in-simulation navigation toolbar (ui/sim_toolbar.py).

The widget is pure draw + hit-test, so it is exercised directly on a headless
surface: geometry (one row, in order, matching the requested corner), the
click → SimExit mapping, and the guarantee that the THEME roles it borrows
exist and render under every selectable theme.
"""

from __future__ import annotations

from types import ModuleType

import pygame

from fpga_sim.sim_bridge import SimExit
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.sim_toolbar import _BUTTONS, SimToolbar
from fpga_sim.ui.theme import THEME_NAMES, Theme, set_theme
from fpga_sim.ui.widgets.button import ButtonStyle

_LEFT, _BOTTOM = 10, 690


def _drawn_toolbar(headless_pygame: ModuleType) -> tuple[SimToolbar, pygame.Rect]:
    screen = headless_pygame.display.set_mode((1024, 700))
    toolbar = SimToolbar()
    rect = toolbar.draw(
        screen, get_font(13, bold=True), left=_LEFT, bottom=_BOTTOM, pad_x=10, pad_y=6, gap=8
    )
    return toolbar, rect


def test_click_before_first_draw_is_a_miss():
    assert SimToolbar().handle_click((5, 5)) is None


def test_draw_lays_out_one_row_left_to_right(headless_pygame):
    toolbar, _rect = _drawn_toolbar(headless_pygame)
    rects = [r for r, _ in toolbar._hit]
    assert len(rects) == 3
    assert rects[0].left == _LEFT
    assert all(r.bottom == _BOTTOM for r in rects)
    assert all(r.height == rects[0].height for r in rects)
    for a, b in zip(rects, rects[1:], strict=False):
        assert a.right < b.left  # ordered, with a gap, no overlap


def test_bounding_rect_covers_all_buttons(headless_pygame):
    toolbar, rect = _drawn_toolbar(headless_pygame)
    assert all(rect.contains(r) for r, _ in toolbar._hit)
    assert rect.left == _LEFT
    assert rect.bottom == _BOTTOM


def test_click_maps_each_button_to_its_intent(headless_pygame):
    toolbar, _rect = _drawn_toolbar(headless_pygame)
    got = [toolbar.handle_click(r.center) for r, _ in toolbar._hit]
    assert got == [SimExit.BACK_TO_BOARDS, SimExit.CHANGE_VHDL, SimExit.RELOAD_VHDL]


def test_click_outside_the_row_is_a_miss(headless_pygame):
    toolbar, rect = _drawn_toolbar(headless_pygame)
    assert toolbar.handle_click((rect.right + 5, rect.centery)) is None
    assert toolbar.handle_click((rect.centerx, rect.top - 5)) is None


def test_button_roles_are_real_theme_button_styles():
    """The borrowed role names must stay valid Theme ButtonStyle fields."""
    for _label, role, _intent in _BUTTONS:
        assert isinstance(getattr(Theme(), role), ButtonStyle)


def test_draws_under_every_theme(headless_pygame, restore_theme):
    """set_theme() swaps THEME in place; the draw-time role reads must follow."""
    for name in THEME_NAMES:
        set_theme(name)
        _drawn_toolbar(headless_pygame)
