"""Tests for VHDLFilePicker: scanning, keyboard navigation, and activation."""

import os

import pytest

from fpga_sim.ui.vhdl_picker import VHDLFilePicker

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
def screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


@pytest.fixture
def workdir(tmp_path):
    """A directory with one subdir, two VHDL files, and a non-VHDL file."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.vhd").write_text("-- a\n")
    (tmp_path / "b.vhdl").write_text("-- b\n")
    (tmp_path / "ignore.txt").write_text("nope\n")
    return tmp_path


def _key(pygame, key, unicode=""):
    """Build a synthetic KEYDOWN event."""
    return pygame.event.Event(pygame.KEYDOWN, key=key, unicode=unicode)


# ── Scanning ─────────────────────────────────────────────────────────────────


class TestPickerScan:
    def test_lists_parent_dirs_and_vhd_files_only(self, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        names = [name for name, _path, _is_dir in p.entries]
        assert ".." in names
        assert "sub/" in names
        assert "a.vhd" in names
        assert "b.vhdl" in names
        assert "ignore.txt" not in names

    def test_preselect_sets_cursor(self, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir, preselect_name="b.vhdl")
        name, _path, _is_dir = p.entries[p.hovered]
        assert name == "b.vhdl"


# ── Keyboard navigation ──────────────────────────────────────────────────────


class TestPickerKeyboardNav:
    def test_down_from_unset_selects_first(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        p.hovered = -1
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))
        assert exit_loop is False
        assert result is None
        assert p.hovered == 0

    def test_up_from_unset_selects_last(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        p.hovered = -1
        p._handle_keydown(_key(headless_pygame, headless_pygame.K_UP))
        assert p.hovered == len(p.entries) - 1

    def test_down_clamps_at_end(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        p.hovered = 0
        for _ in range(50):
            p._handle_keydown(_key(headless_pygame, headless_pygame.K_DOWN))
        assert p.hovered == len(p.entries) - 1

    def test_enter_on_file_returns_path(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        idx = next(i for i, (n, _p, _d) in enumerate(p.entries) if n == "a.vhd")
        p.hovered = idx
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is True
        assert result == str(workdir / "a.vhd")

    def test_kp_enter_on_file_returns_path(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        idx = next(i for i, (n, _p, _d) in enumerate(p.entries) if n == "b.vhdl")
        p.hovered = idx
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_KP_ENTER))
        assert exit_loop is True
        assert result == str(workdir / "b.vhdl")

    def test_enter_on_dir_navigates_and_continues(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        idx = next(i for i, (n, _p, _d) in enumerate(p.entries) if n == "sub/")
        p.hovered = idx
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is False
        assert result is None
        assert p.current_dir == workdir / "sub"
        assert p.hovered == -1

    def test_enter_on_parent_navigates_up(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir / "sub")
        assert p.entries[0][0] == ".."
        p.hovered = 0
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is False
        assert result is None
        assert p.current_dir == workdir

    def test_enter_with_no_selection_continues(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        p.hovered = -1
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_RETURN))
        assert exit_loop is False
        assert result is None

    def test_escape_cancels(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_ESCAPE))
        assert exit_loop is True
        assert result is None

    def test_pagedown_moves_by_a_page(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        p.hovered = 0
        page = p._page_rows()
        p._handle_keydown(_key(headless_pygame, headless_pygame.K_PAGEDOWN))
        assert p.hovered == min(page, len(p.entries) - 1)


class TestPickerHelpTrigger:
    def test_f1_requests_help(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        exit_loop, result = p._handle_keydown(_key(headless_pygame, headless_pygame.K_F1))
        assert (exit_loop, result) == (False, None)
        assert p._help_requested is True

    def test_question_mark_requests_help(self, headless_pygame, screen, workdir):
        p = VHDLFilePicker(screen, start_dir=workdir)
        exit_loop, result = p._handle_keydown(
            _key(headless_pygame, headless_pygame.K_SLASH, unicode="?")
        )
        assert (exit_loop, result) == (False, None)
        assert p._help_requested is True
