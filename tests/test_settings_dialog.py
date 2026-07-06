"""Tests for SettingsDialog (U5): rects, click actions, session writes, gear button."""

from __future__ import annotations

import json

import pytest

from fpga_sim.session_config import load_session, update_session
from fpga_sim.ui.settings_dialog import SettingsDialog, draw_settings_button
from fpga_sim.ui.sim_panel import SPEED_DEFAULT
from fpga_sim.ui.theme import THEME_NAMES, current_theme_name


@pytest.fixture(autouse=True)
def session_file(tmp_path, monkeypatch):
    """Redirect SESSION_FILE so dialog writes never touch the real user file."""
    target = tmp_path / "session.json"
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", target)
    return target


@pytest.fixture(scope="module")
def screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


# ── Drawing populates hit-rects ───────────────────────────────────────────────


class TestDraw:
    def test_draw_populates_all_rects(self, screen):
        dlg = SettingsDialog(screen)
        assert dlg._panel_rect is None and dlg._close_rect is None
        dlg._draw()
        assert dlg._panel_rect is not None
        for rect in (dlg._close_rect, dlg._theme_rect, dlg._reset_rect, dlg._clear_rect):
            assert rect is not None
            assert dlg._panel_rect.contains(rect)  # every control sits inside the panel

    def test_draw_small_window_keeps_panel_on_screen(self, headless_pygame):
        small = headless_pygame.display.set_mode((640, 480))
        dlg = SettingsDialog(small)
        dlg._draw()
        assert dlg._panel_rect is not None
        assert dlg._panel_rect.width <= 640
        # restore the module-scoped screen size for the other tests
        headless_pygame.display.set_mode((1024, 700))


# ── Click-to-dismiss ──────────────────────────────────────────────────────────


class TestDismiss:
    def test_close_button_dismisses(self, screen):
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._close_rect is not None
        assert dlg._click(dlg._close_rect.center) is True

    def test_click_outside_panel_dismisses(self, screen):
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._click((2, 2)) is True

    def test_click_inside_panel_keeps_open(self, screen):
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._panel_rect is not None
        inside = (dlg._panel_rect.centerx, dlg._panel_rect.top + 5)
        assert dlg._click(inside) is False


# ── Row actions write the session file ────────────────────────────────────────


class TestActions:
    def test_theme_cycle_applies_and_persists(self, screen, session_file, restore_theme):
        """U6: a click on the Theme row applies set_theme() and writes the session."""
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._theme_rect is not None
        assert dlg._click(dlg._theme_rect.center) is False  # stays open
        assert load_session()["theme"] == THEME_NAMES[1]
        assert current_theme_name() == THEME_NAMES[1]  # applied live, not just saved

    def test_theme_cycle_wraps_back_to_default(self, screen, session_file, restore_theme):
        update_session(theme=THEME_NAMES[-1])
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._theme_rect is not None
        dlg._click(dlg._theme_rect.center)
        assert load_session()["theme"] == THEME_NAMES[0]
        assert current_theme_name() == THEME_NAMES[0]

    def test_theme_cycle_full_loop_visits_every_theme(self, screen, session_file, restore_theme):
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._theme_rect is not None
        for expected in (*THEME_NAMES[1:], THEME_NAMES[0]):
            dlg._click(dlg._theme_rect.center)
            assert load_session()["theme"] == expected

    def test_reset_speed_writes_default(self, screen, session_file):
        update_session(speed_factor=2.5)
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._reset_rect is not None
        assert dlg._click(dlg._reset_rect.center) is False  # stays open
        assert load_session()["speed_factor"] == SPEED_DEFAULT
        assert dlg._can_reset_speed() is False  # local copy refreshed

    def test_reset_speed_noop_when_already_default(self, screen, session_file):
        update_session(speed_factor=SPEED_DEFAULT)
        before = session_file.read_text()
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._reset_rect is not None
        dlg._click(dlg._reset_rect.center)
        assert session_file.read_text() == before

    def test_clear_recent_empties_list(self, screen, session_file):
        update_session(recent=[{"board_class": "B", "board_source": "s", "vhdl_path": "a.vhd"}])
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._clear_rect is not None
        assert dlg._click(dlg._clear_rect.center) is False  # stays open
        assert load_session()["recent"] == []
        assert dlg._can_clear_recent() is False

    def test_clear_recent_noop_when_empty(self, screen, session_file):
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._clear_rect is not None
        dlg._click(dlg._clear_rect.center)
        assert not session_file.exists()

    def test_actions_preserve_other_session_keys(self, screen, session_file):
        session_file.write_text(
            json.dumps({"board_class": "KeepMe", "speed_factor": 5.0, "recent": [{"a": 1}]})
        )
        dlg = SettingsDialog(screen)
        dlg._draw()
        assert dlg._reset_rect is not None and dlg._clear_rect is not None
        dlg._click(dlg._reset_rect.center)
        dlg._click(dlg._clear_rect.center)
        assert load_session()["board_class"] == "KeepMe"


# ── Session-derived values are defensive ──────────────────────────────────────


class TestValues:
    def test_speed_defaults_when_absent(self, screen):
        assert SettingsDialog(screen)._speed() == SPEED_DEFAULT

    def test_speed_junk_falls_back(self, screen):
        update_session(speed_factor="fast")
        assert SettingsDialog(screen)._speed() == SPEED_DEFAULT

    def test_recent_count_non_list_is_zero(self, screen):
        update_session(recent="junk")
        assert SettingsDialog(screen)._recent_count() == 0

    def test_theme_name_defaults(self, screen):
        assert SettingsDialog(screen)._theme_name() == THEME_NAMES[0]

    def test_theme_name_junk_falls_back(self, screen):
        update_session(theme=42)
        assert SettingsDialog(screen)._theme_name() == THEME_NAMES[0]

    def test_theme_name_unknown_string_falls_back(self, screen):
        update_session(theme="no-such-theme")
        assert SettingsDialog(screen)._theme_name() == THEME_NAMES[0]

    def test_theme_name_valid_saved_name_is_returned(self, screen):
        update_session(theme=THEME_NAMES[1])
        assert SettingsDialog(screen)._theme_name() == THEME_NAMES[1]


# ── Gear trigger button ───────────────────────────────────────────────────────


class TestGearButton:
    def test_anchored_by_top_right(self, screen):
        rect = draw_settings_button(screen, right=500, top=20, size=30, mouse=(0, 0))
        assert (rect.right, rect.top) == (500, 20)
        assert (rect.width, rect.height) == (30, 30)

    def test_tiny_size_does_not_crash(self, screen):
        draw_settings_button(screen, right=50, top=0, size=8, mouse=(0, 0))
