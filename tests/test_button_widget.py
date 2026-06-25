"""Tests for the shared button widget (ui/widgets/button.py)."""

import pygame
import pytest

from fpga_sim.ui.constants import WHITE, get_font
from fpga_sim.ui.widgets import ButtonStyle, draw_button


@pytest.fixture(scope="module")
def screen(headless_pygame):
    return headless_pygame.display.set_mode((200, 120))


def _fill_rgb(screen, style, **kwargs):
    """Draw a borderless button with an empty label; return the center pixel RGB."""
    screen.fill((1, 2, 3))
    rect = pygame.Rect(20, 20, 120, 60)
    draw_button(screen, rect, "", get_font(14), style, **kwargs)
    return tuple(screen.get_at(rect.center))[:3]


def test_enabled_uses_bg(screen):
    style = ButtonStyle(bg=(10, 20, 30), bg_hover=(40, 50, 60), border_width=0)
    assert _fill_rgb(screen, style) == (10, 20, 30)


def test_hovered_uses_bg_hover(screen):
    style = ButtonStyle(bg=(10, 20, 30), bg_hover=(40, 50, 60), border_width=0)
    assert _fill_rgb(screen, style, hovered=True) == (40, 50, 60)


def test_disabled_uses_bg_disabled(screen):
    style = ButtonStyle(
        bg=(10, 20, 30), bg_hover=(40, 50, 60), bg_disabled=(70, 80, 90), border_width=0
    )
    assert _fill_rgb(screen, style, enabled=False) == (70, 80, 90)


def test_disabled_falls_back_to_bg(screen):
    style = ButtonStyle(bg=(10, 20, 30), bg_hover=(40, 50, 60), border_width=0)
    assert _fill_rgb(screen, style, enabled=False) == (10, 20, 30)


def test_disabled_ignores_hover(screen):
    style = ButtonStyle(
        bg=(10, 20, 30), bg_hover=(40, 50, 60), bg_disabled=(70, 80, 90), border_width=0
    )
    assert _fill_rgb(screen, style, hovered=True, enabled=False) == (70, 80, 90)


def test_draw_button_returns_none(screen):
    style = ButtonStyle(bg=(10, 20, 30), bg_hover=(40, 50, 60))
    rect = pygame.Rect(0, 0, 60, 24)
    font = get_font(14)
    # mypy knows draw_button -> None; keep the runtime contract check explicit.
    result = draw_button(screen, rect, "Hi", font, style)  # type: ignore[func-returns-value]
    assert result is None


def test_style_defaults():
    style = ButtonStyle(bg=(1, 1, 1), bg_hover=(2, 2, 2))
    assert style.fg == WHITE
    assert style.border == WHITE
    assert style.border_width == 2
    assert style.radius == 6
    assert style.bg_disabled is None
    assert style.fg_disabled is None
    assert style.border_disabled is None
