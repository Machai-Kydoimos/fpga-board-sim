"""Tests for HelpDialog: dismiss logic, rendering, content table, trigger button."""

import pygame
import pytest

from fpga_sim.ui.help_dialog import (
    CONTRACT,
    SHORTCUTS,
    WORKFLOW,
    HelpDialog,
    draw_help_button,
)


@pytest.fixture(scope="module")
def screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


def _key(pygame_, key, unicode=""):
    return pygame_.event.Event(pygame_.KEYDOWN, key=key, unicode=unicode)


# ── Dismiss keys ──────────────────────────────────────────────────────────────


class TestDismissKey:
    def test_escape_dismisses(self, headless_pygame):
        assert HelpDialog._is_dismiss_key(_key(headless_pygame, headless_pygame.K_ESCAPE))

    def test_f1_dismisses(self, headless_pygame):
        assert HelpDialog._is_dismiss_key(_key(headless_pygame, headless_pygame.K_F1))

    def test_question_mark_dismisses(self, headless_pygame):
        # `?` toggles the overlay closed (same trigger that opens it).
        assert HelpDialog._is_dismiss_key(_key(headless_pygame, headless_pygame.K_SLASH, "?"))

    def test_other_key_does_not_dismiss(self, headless_pygame):
        assert not HelpDialog._is_dismiss_key(_key(headless_pygame, headless_pygame.K_a, "a"))

    def test_enter_does_not_dismiss(self, headless_pygame):
        assert not HelpDialog._is_dismiss_key(_key(headless_pygame, headless_pygame.K_RETURN))


# ── Drawing populates hit-rects ───────────────────────────────────────────────


class TestDraw:
    def test_draw_populates_rects(self, screen):
        dlg = HelpDialog(screen)
        assert dlg._close_rect is None and dlg._panel_rect is None
        dlg._draw()
        assert dlg._close_rect is not None
        assert dlg._panel_rect is not None
        # Close button sits inside the panel.
        assert dlg._panel_rect.contains(dlg._close_rect)

    def test_scroll_clamps_after_draw(self, screen):
        dlg = HelpDialog(screen)
        dlg._scroll = 999_999
        dlg._draw()
        # Clamped to a real maximum (content overflows at 1024x700) — well below input.
        assert 0 <= dlg._scroll < 999_999

    def test_scroll_never_negative(self, screen):
        dlg = HelpDialog(screen)
        dlg._scroll = -500
        dlg._draw()
        assert dlg._scroll >= 0


# ── Click-to-dismiss ──────────────────────────────────────────────────────────


class TestClick:
    def test_close_button_dismisses(self, screen):
        dlg = HelpDialog(screen)
        dlg._draw()
        assert dlg._close_rect is not None
        assert dlg._click(dlg._close_rect.center) is True

    def test_click_outside_panel_dismisses(self, screen):
        dlg = HelpDialog(screen)
        dlg._draw()
        assert dlg._click((2, 2)) is True

    def test_click_inside_panel_keeps_open(self, screen):
        dlg = HelpDialog(screen)
        dlg._draw()
        assert dlg._panel_rect is not None
        # A point in the panel's title area — inside the panel, not on Close.
        inside = (dlg._panel_rect.centerx, dlg._panel_rect.top + 50)
        assert dlg._click(inside) is False


# ── Content table (the legend's single source of truth) ───────────────────────


class TestContent:
    def test_shortcuts_well_formed(self):
        assert SHORTCUTS
        for keys, desc in SHORTCUTS:
            assert isinstance(keys, str) and keys
            assert isinstance(desc, str) and desc

    def test_shortcuts_document_their_own_trigger(self):
        # The first row must advertise F1 and `?`, the keys that open the overlay.
        first = SHORTCUTS[0][0]
        assert "F1" in first and "?" in first

    def test_shortcuts_cover_existing_keys(self):
        # Regression guard: the keys that exist at ship time must be listed.
        joined = " ".join(k for k, _ in SHORTCUTS)
        for token in ("Esc", "Enter", "R", "S"):
            assert token in joined

    def test_workflow_is_four_numbered_steps(self):
        assert [num for num, _ in WORKFLOW] == ["1", "2", "3", "4"]
        for _num, desc in WORKFLOW:
            assert desc

    def test_contract_points_at_example(self):
        assert CONTRACT
        assert any("blinky.vhd" in line for line in CONTRACT)


# ── Trigger button ────────────────────────────────────────────────────────────


class TestHelpButton:
    def test_returns_anchored_rect(self, screen):
        rect = draw_help_button(screen, right=1000, top=8, size=28, mouse=(0, 0))
        assert rect == pygame.Rect(972, 8, 28, 28)

    def test_hovered_draw_is_safe(self, screen):
        # Mouse inside the button: must render without error and keep geometry.
        rect = draw_help_button(screen, right=1000, top=8, size=28, mouse=(980, 20))
        assert rect.collidepoint((980, 20))
