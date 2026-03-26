"""Tests for SimPanel: clock options, update_timing rolling averages,
and FPGABoard.set_height_offset()."""
import os

import pytest

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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_panel(dummy_screen, clock_hz=100e6, clocks_hz=None):
    from ui.sim_panel import SimPanel
    return SimPanel(dummy_screen, height=120, board_clock_hz=clock_hz,
                    board_clocks_hz=clocks_hz)


# ── Clock options ─────────────────────────────────────────────────────────────

def test_default_clock_options_are_presets(dummy_screen):
    """Without board_clocks_hz, the panel uses the built-in preset list."""
    from ui.sim_panel import _CLOCK_PRESETS_HZ
    panel = _make_panel(dummy_screen, clock_hz=100e6, clocks_hz=None)
    assert panel._clock_options == _CLOCK_PRESETS_HZ


def test_board_clocks_hz_replaces_presets(dummy_screen):
    """When board_clocks_hz is supplied it replaces the built-in list."""
    custom = [12e6, 48e6, 96e6]
    panel = _make_panel(dummy_screen, clock_hz=48e6, clocks_hz=custom)
    assert panel._clock_options == custom


def test_preset_idx_selects_nearest_clock(dummy_screen):
    """Initial preset index should be the entry closest to board_clock_hz."""
    clocks = [12e6, 48e6, 100e6]
    panel = _make_panel(dummy_screen, clock_hz=50e6, clocks_hz=clocks)
    # 48 MHz is closer to 50 MHz than 12 MHz or 100 MHz
    assert panel._clock_options[panel._preset_idx] == 48e6


def test_clk_state_period_matches_selected_clock(dummy_screen):
    """clk_state['period_ns'] must equal 1e9 / selected_clock_hz."""
    clocks = [12e6, 100e6]
    panel = _make_panel(dummy_screen, clock_hz=100e6, clocks_hz=clocks)
    selected_hz = panel._clock_options[panel._preset_idx]
    assert panel.clk_state["period_ns"] == pytest.approx(1e9 / selected_hz)


# ── update_timing rolling averages ────────────────────────────────────────────

def test_single_update_sets_values(dummy_screen):
    panel = _make_panel(dummy_screen)
    panel.update_timing(fps=60.0, timer_us=800.0, draw_us=150.0, idle_us=50.0)
    assert panel._fps      == pytest.approx(60.0)
    assert panel._timer_us == pytest.approx(800.0)
    assert panel._draw_us  == pytest.approx(150.0)
    assert panel._idle_us  == pytest.approx(50.0)


def test_rolling_average_converges(dummy_screen):
    """After 30 identical frames the average must equal that frame's values."""
    panel = _make_panel(dummy_screen)
    for _ in range(30):
        panel.update_timing(fps=30.0, timer_us=500.0, draw_us=200.0, idle_us=300.0)
    assert panel._fps      == pytest.approx(30.0)
    assert panel._timer_us == pytest.approx(500.0)
    assert panel._draw_us  == pytest.approx(200.0)
    assert panel._idle_us  == pytest.approx(300.0)


def test_panel_height_scales_with_window(headless_pygame):
    """panel_height must grow proportionally when the window is enlarged."""
    from ui.sim_panel import SimPanel, _PANEL_H_BASE
    small = headless_pygame.display.set_mode((1024, 700))
    panel_small = SimPanel(small, height=_PANEL_H_BASE, board_clock_hz=100e6)
    h_small = panel_small.panel_height

    large = headless_pygame.display.set_mode((1920, 1080))
    panel_large = SimPanel(large, height=_PANEL_H_BASE, board_clock_hz=100e6)
    h_large = panel_large.panel_height

    assert h_large > h_small


def test_panel_height_updates_after_resize(headless_pygame):
    """panel_height must reflect the current screen size, not the startup size."""
    from ui.sim_panel import SimPanel, _PANEL_H_BASE
    screen = headless_pygame.display.set_mode((1024, 700))
    panel = SimPanel(screen, height=_PANEL_H_BASE, board_clock_hz=100e6)
    h_before = panel.panel_height

    # Simulate a window resize by changing the display mode on the same panel
    headless_pygame.display.set_mode((1920, 1080))
    h_after = panel.panel_height

    assert h_after > h_before


def test_effective_hz_reflects_actual_throughput(dummy_screen):
    """effective_hz must equal clocks_per_frame × fps, not clock × speed_factor."""
    panel = _make_panel(dummy_screen, clock_hz=100e6)
    # Inject measured data: 9596 clocks/frame at 35 fps = 335,860 Hz actual
    panel.update(9596 * 10)  # sim_step_ns = 9596 cycles × 10 ns/cycle
    for _ in range(5):
        panel.update_timing(fps=35.0, timer_us=27_000.0, draw_us=500.0, idle_us=0.0)
    expected = panel._clocks_per_frame * panel._fps
    assert panel.effective_hz == pytest.approx(expected, rel=1e-3)


def test_effective_hz_zero_when_paused(dummy_screen):
    panel = _make_panel(dummy_screen, clock_hz=100e6)
    panel.update(9596 * 10)
    for _ in range(5):
        panel.update_timing(fps=35.0, timer_us=27_000.0, draw_us=500.0, idle_us=0.0)
    panel.paused = True
    assert panel.effective_hz == 0.0


def test_window_drops_oldest_sample(dummy_screen):
    """After the window fills, old samples are discarded (maxlen=30)."""
    panel = _make_panel(dummy_screen)
    # Fill with 100 µs fps-equivalent
    for _ in range(30):
        panel.update_timing(fps=10.0, timer_us=100.0, draw_us=10.0, idle_us=10.0)
    # Now push 30 frames of 60 fps — the old 10 fps entries must all be gone
    for _ in range(30):
        panel.update_timing(fps=60.0, timer_us=100.0, draw_us=10.0, idle_us=10.0)
    assert panel._fps == pytest.approx(60.0)


# ── FPGABoard.set_height_offset() ─────────────────────────────────────────────

from board_loader import BoardDef, ComponentInfo  # noqa: E402
from ui import FPGABoard  # noqa: E402


def _sample_board():
    leds    = [ComponentInfo(f"led{i}", f"LED{i}", "", "") for i in range(4)]
    buttons = [ComponentInfo(f"btn{i}", f"BTN{i}", "", "") for i in range(2)]
    switches = [ComponentInfo(f"sw{i}", f"SW{i}", "", "") for i in range(4)]
    return BoardDef(
        name="Test Board", class_name="TestBoard",
        vendor="TestVendor", device="TestDevice", package="QFP100",
        leds=leds, buttons=buttons, switches=switches,
    )


def test_set_height_offset_reduces_board_height(headless_pygame):
    """Applying an offset must shrink board.height by that many pixels."""
    screen = headless_pygame.display.set_mode((1024, 700))
    board = FPGABoard(board_def=_sample_board(), screen=screen)
    original_height = board.height
    board.set_height_offset(120)
    assert board.height == original_height - 120


def test_set_height_offset_zero_restores_full_height(headless_pygame):
    """set_height_offset(0) gives the board the full window height."""
    screen = headless_pygame.display.set_mode((1024, 700))
    board = FPGABoard(board_def=_sample_board(), screen=screen)
    board.set_height_offset(120)
    board.set_height_offset(0)
    assert board.height == 700
