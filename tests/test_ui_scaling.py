"""Tests for proportional UI scaling: _ui_scale helper, row_h/_hdr properties,
and smoke-render tests at various window sizes."""
import os
import tempfile

import pytest

# ── A. Pure math tests (no display needed) ────────────────────────────────────

from fpga_board import _ui_scale


def test_ui_scale_reference():
    assert _ui_scale(1024, 700) == pytest.approx(1.0)


def test_ui_scale_half():
    assert _ui_scale(512, 350) == pytest.approx(0.5)


def test_ui_scale_double():
    assert _ui_scale(2048, 1400) == pytest.approx(2.0)


def test_ui_scale_uses_min_axis():
    assert _ui_scale(2048, 700) == pytest.approx(1.0)   # height constrains
    assert _ui_scale(1024, 1400) == pytest.approx(1.0)  # width constrains


def test_ui_scale_large():
    assert _ui_scale(1600, 1000) > 1.0


def test_ui_scale_small():
    assert _ui_scale(800, 480) < 1.0


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def headless_pygame():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame
    pygame.init()
    yield pygame
    pygame.quit()


@pytest.fixture(scope="module")
def dummy_screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


# ── B. Property tests ─────────────────────────────────────────────────────────

from fpga_board import BoardSelector, VHDLFilePicker


class TestBoardSelectorProperties:
    def test_row_h_reference(self, dummy_screen):
        sel = BoardSelector([], dummy_screen)
        sel.width, sel.height = 1024, 700
        assert sel.row_h == 48

    def test_hdr_reference(self, dummy_screen):
        sel = BoardSelector([], dummy_screen)
        sel.width, sel.height = 1024, 700
        assert sel._hdr == 80

    def test_row_h_double(self, dummy_screen):
        sel = BoardSelector([], dummy_screen)
        sel.width, sel.height = 2048, 1400
        assert sel.row_h == 96

    def test_hdr_double(self, dummy_screen):
        sel = BoardSelector([], dummy_screen)
        sel.width, sel.height = 2048, 1400
        assert sel._hdr == 160

    def test_row_h_floor(self, dummy_screen):
        sel = BoardSelector([], dummy_screen)
        sel.width, sel.height = 100, 100
        assert sel.row_h >= 32

    def test_hdr_floor(self, dummy_screen):
        sel = BoardSelector([], dummy_screen)
        sel.width, sel.height = 100, 100
        assert sel._hdr >= 56


class TestVHDLFilePickerProperties:
    def test_row_h_reference(self, dummy_screen):
        picker = VHDLFilePicker(dummy_screen, start_dir=tempfile.gettempdir())
        picker.width, picker.height = 1024, 700
        assert picker.row_h == 36

    def test_hdr_reference(self, dummy_screen):
        picker = VHDLFilePicker(dummy_screen, start_dir=tempfile.gettempdir())
        picker.width, picker.height = 1024, 700
        assert picker._hdr == 70

    def test_row_h_double(self, dummy_screen):
        picker = VHDLFilePicker(dummy_screen, start_dir=tempfile.gettempdir())
        picker.width, picker.height = 2048, 1400
        assert picker.row_h == 72

    def test_hdr_double(self, dummy_screen):
        picker = VHDLFilePicker(dummy_screen, start_dir=tempfile.gettempdir())
        picker.width, picker.height = 2048, 1400
        assert picker._hdr == 140

    def test_row_h_floor(self, dummy_screen):
        picker = VHDLFilePicker(dummy_screen, start_dir=tempfile.gettempdir())
        picker.width, picker.height = 100, 100
        assert picker.row_h >= 24

    def test_hdr_floor(self, dummy_screen):
        picker = VHDLFilePicker(dummy_screen, start_dir=tempfile.gettempdir())
        picker.width, picker.height = 100, 100
        assert picker._hdr >= 48


# ── C. Smoke render tests ─────────────────────────────────────────────────────

from board_loader import BoardDef, ComponentInfo
from fpga_board import FPGABoard


def _sample_board_def():
    leds     = [ComponentInfo(f"led{i}",    f"LED{i}",    "", "") for i in range(4)]
    buttons  = [ComponentInfo(f"btn{i}",    f"BTN{i}",    "", "") for i in range(2)]
    switches = [ComponentInfo(f"sw{i}",     f"SW{i}",     "", "") for i in range(4)]
    return BoardDef(
        name="Test Board", class_name="TestBoard",
        vendor="TestVendor", device="TestDevice", package="QFP100",
        leds=leds, buttons=buttons, switches=switches,
    )


@pytest.mark.parametrize("w,h", [
    (800, 480), (1024, 700), (1280, 800), (1600, 1000), (400, 300)
])
def test_board_selector_draws(headless_pygame, w, h):
    screen = headless_pygame.display.set_mode((w, h))
    sel = BoardSelector([], screen)
    sel.width, sel.height = w, h
    sel._draw()  # must not raise


@pytest.mark.parametrize("w,h", [
    (800, 480), (1024, 700), (1280, 800), (1600, 1000), (400, 300)
])
def test_fpga_board_draws(headless_pygame, w, h):
    screen = headless_pygame.display.set_mode((w, h))
    board = FPGABoard(board_def=_sample_board_def(), width=w, height=h)
    board._draw()  # must not raise


def test_fpga_board_accepts_screen_param(headless_pygame):
    """FPGABoard(screen=...) must reuse the surface, not call set_mode."""
    screen = headless_pygame.display.set_mode((1280, 800))
    board = FPGABoard(board_def=_sample_board_def(), screen=screen)
    assert board.width == 1280
    assert board.height == 800
    assert board.screen is screen


def test_layout_leaves_bottom_gap(headless_pygame):
    """Bottom of the lowest component must be above the reserved button area."""
    w, h = 1024, 700
    screen = headless_pygame.display.set_mode((w, h))
    board = FPGABoard(board_def=_sample_board_def(), width=w, height=h)
    s = _ui_scale(w, h)
    bottom_reserve = max(50, round(70 * s))
    all_rects = (
        [led.rect for led in board.leds]
        + [btn.rect for btn in board.buttons]
        + [sw.rect for sw in board.switches]
    )
    # Each component bottom (plus a small label allowance) must stay above the reserve
    label_allowance = 20
    for rect in all_rects:
        assert rect.bottom + label_allowance <= h - bottom_reserve + label_allowance, (
            f"Component rect bottom {rect.bottom} extends into button reserve zone"
        )


@pytest.mark.parametrize("w,h", [
    (800, 480), (1024, 700), (1280, 800), (1600, 1000), (400, 300)
])
def test_vhdl_file_picker_draws(headless_pygame, w, h):
    screen = headless_pygame.display.set_mode((w, h))
    picker = VHDLFilePicker(screen, start_dir=tempfile.gettempdir())
    picker.width, picker.height = w, h
    picker._draw()  # must not raise
