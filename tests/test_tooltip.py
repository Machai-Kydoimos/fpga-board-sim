"""Tests for the hover Tooltip widget (U3)."""

import pygame
import pytest

from fpga_sim.board_loader import ComponentInfo
from fpga_sim.ui.tooltip import Tooltip, tooltip_rows


@pytest.fixture(scope="module")
def surface(headless_pygame):
    return pygame.Surface((800, 600))


def _info() -> ComponentInfo:
    return ComponentInfo("button", "btn_up", 1, ["P17"], direction="i")


# ── tooltip_rows content ─────────────────────────────────────────────────────


def test_rows_header_only_without_info():
    assert tooltip_rows("LED0", None) == [("", "LED0")]


def test_rows_full_info():
    info = ComponentInfo("led", "user_led", 0, ["A8"], direction="o")
    assert tooltip_rows("LED0", info) == [
        ("", "LED0"),
        ("Net", "user_led"),
        ("Pin", "A8"),
        ("Dir", "o"),
    ]


def test_rows_multiple_pins_are_pluralized_and_joined():
    info = ComponentInfo("led", "rgb", 0, ["A8", "B9", "C10"], direction="o")
    rows = dict(tooltip_rows("RGB0", info))
    assert "Pins" in rows and "Pin" not in rows
    assert rows["Pins"] == "A8, B9, C10"


def test_rows_omit_empty_fields():
    # name present but no pins and no direction → header + Net only.
    info = ComponentInfo("switch", "sw", 3, [], direction="")
    assert tooltip_rows("SW3", info) == [("", "SW3"), ("Net", "sw")]


# ── Tooltip.draw placement / clamping ────────────────────────────────────────


@pytest.mark.parametrize("anchor", [(0, 0), (400, 300), (799, 599), (799, 0), (0, 599)])
def test_draw_stays_fully_on_screen(surface, anchor):
    rect = Tooltip().draw(surface, anchor, "BTN1", _info())
    sw, sh = surface.get_size()
    assert rect.left >= 0 and rect.top >= 0
    assert rect.right <= sw and rect.bottom <= sh
    assert rect.width > 0 and rect.height > 0


def test_draw_sits_below_right_of_cursor_in_open_space(surface):
    anchor = (120, 100)
    rect = Tooltip().draw(surface, anchor, "BTN1", _info())
    assert rect.left >= anchor[0]
    assert rect.top >= anchor[1]


def test_draw_flips_left_and_up_near_bottom_right_corner(surface):
    anchor = (799, 599)
    rect = Tooltip().draw(surface, anchor, "BTN1", _info())
    # Box must be placed up-and-left of the cursor, not overflowing the corner.
    assert rect.right <= anchor[0]
    assert rect.bottom <= anchor[1]


def test_draw_header_only_is_shorter_than_full(surface):
    full = Tooltip().draw(surface, (100, 100), "BTN1", _info())
    header_only = Tooltip().draw(surface, (100, 100), "BTN1", None)
    assert header_only.height < full.height
