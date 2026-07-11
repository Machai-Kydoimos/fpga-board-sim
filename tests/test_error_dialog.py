"""Tests for ErrorDialog: button layout, View-Example behavior, dismiss keys."""

from pathlib import Path
from types import ModuleType

import pygame
import pytest

import fpga_sim.ui.error_dialog as error_dialog_mod
from fpga_sim.ui.error_dialog import ErrorDialog
from fpga_sim.ui.results import DialogResult

EXAMPLE = Path("/repo/hdl/blinky.vhd")


@pytest.fixture(scope="module")
def screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


def _dialog(screen: pygame.Surface, example: Path | None = None) -> ErrorDialog:
    return ErrorDialog(screen, "VHDL Error", "boom\nline two", example_path=example)


# ── Button layout ─────────────────────────────────────────────────────────────


class TestButtons:
    def test_two_buttons_without_example(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._retry_rect is not None
        assert dlg._back_rect is not None
        assert dlg._example_rect is None

    def test_three_buttons_with_example(self, screen):
        dlg = _dialog(screen, EXAMPLE)
        dlg._draw()
        assert dlg._example_rect is not None
        assert dlg._retry_rect is not None
        assert dlg._back_rect is not None
        # Left-to-right order: [View Example] [Try Another File] [Back to Boards]
        assert dlg._example_rect.right <= dlg._retry_rect.left
        assert dlg._retry_rect.right <= dlg._back_rect.left

    def test_buttons_do_not_overlap(self, screen):
        dlg = _dialog(screen, EXAMPLE)
        dlg._draw()
        assert dlg._example_rect is not None and dlg._retry_rect is not None
        assert dlg._back_rect is not None
        assert not dlg._example_rect.colliderect(dlg._retry_rect)
        assert not dlg._retry_rect.colliderect(dlg._back_rect)


# ── Clicks ────────────────────────────────────────────────────────────────────


class TestClicks:
    def test_click_retry(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._retry_rect is not None
        assert dlg._click(dlg._retry_rect.center) is DialogResult.RETRY

    def test_click_back(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._back_rect is not None
        assert dlg._click(dlg._back_rect.center) is DialogResult.BACK

    def test_click_outside_buttons_is_noop(self, screen):
        dlg = _dialog(screen)
        dlg._draw()
        assert dlg._click((0, 0)) is None

    def test_click_example_opens_file_and_stays_open(self, screen, monkeypatch):
        opened: list[Path] = []
        monkeypatch.setattr(error_dialog_mod, "open_with_default_app", opened.append)
        dlg = _dialog(screen, EXAMPLE)
        dlg._draw()
        assert dlg._example_rect is not None
        assert dlg._click(dlg._example_rect.center) is None  # dialog not dismissed
        assert opened == [EXAMPLE]


# ── Keyboard ──────────────────────────────────────────────────────────────────


def _post_keys(pygame_: ModuleType, *keys: int) -> None:
    for key in keys:
        pygame_.event.post(pygame_.event.Event(pygame_.KEYDOWN, key=key))


class TestKeys:
    def test_v_opens_example_then_enter_retries(self, screen, headless_pygame, monkeypatch):
        opened: list[Path] = []
        monkeypatch.setattr(error_dialog_mod, "open_with_default_app", opened.append)
        dlg = _dialog(screen, EXAMPLE)
        _post_keys(headless_pygame, pygame.K_v, pygame.K_RETURN)
        assert dlg.run(headless_pygame.time.Clock()) is DialogResult.RETRY
        assert opened == [EXAMPLE]

    def test_v_ignored_without_example(self, screen, headless_pygame, monkeypatch):
        monkeypatch.setattr(
            error_dialog_mod,
            "open_with_default_app",
            lambda p: pytest.fail("opener must not be called without example_path"),
        )
        dlg = _dialog(screen)
        _post_keys(headless_pygame, pygame.K_v, pygame.K_ESCAPE)
        assert dlg.run(headless_pygame.time.Clock()) is DialogResult.BACK
