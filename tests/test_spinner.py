"""Tests for the analysis spinner (U2): color lerp, overlay render, threaded run.

``SpinnerOverlay`` is pure rendering (tested headlessly like the other
dialogs); ``run_with_spinner`` drives a worker thread and the frame loop, so
its tests assert the observable contract — the result is returned, exceptions
propagate, the work runs off the main thread, and a window-close during the
wait is re-posted.
"""

import threading
import time

import pytest

from fpga_sim.ui.constants import lerp_rgb as _lerp
from fpga_sim.ui.spinner import SpinnerOverlay, run_with_spinner


@pytest.fixture(scope="module")
def screen(headless_pygame):
    return headless_pygame.display.set_mode((1024, 700))


@pytest.fixture(autouse=True)
def _clean_events(headless_pygame):
    """Keep the global pygame event queue isolated between tests."""
    headless_pygame.event.clear()
    yield
    headless_pygame.event.clear()


# ── Color interpolation ───────────────────────────────────────────────────────


class TestLerp:
    def test_endpoints(self):
        assert _lerp((0, 0, 0), (255, 255, 255), 0.0) == (0, 0, 0)
        assert _lerp((0, 0, 0), (255, 255, 255), 1.0) == (255, 255, 255)

    def test_midpoint(self):
        assert _lerp((10, 20, 30), (40, 50, 60), 0.5) == (25, 35, 45)

    def test_clamps_out_of_range(self):
        assert _lerp((0, 0, 0), (255, 255, 255), -1.0) == (0, 0, 0)
        assert _lerp((0, 0, 0), (255, 255, 255), 2.0) == (255, 255, 255)

    def test_returns_int_triple(self):
        c = _lerp((10, 20, 30), (40, 50, 60), 0.5)
        assert len(c) == 3 and all(isinstance(v, int) for v in c)


# ── Overlay rendering ─────────────────────────────────────────────────────────


class TestSpinnerOverlay:
    def test_draw_populates_panel_rect(self, screen):
        ov = SpinnerOverlay(screen, "Analyzing blinky.vhd…", "Running GHDL…")
        assert ov._panel_rect is None
        ov.draw()
        assert ov._panel_rect is not None
        assert screen.get_rect().contains(ov._panel_rect)

    def test_draw_without_detail(self, screen):
        # Single-line variant must render and still produce a valid panel.
        ov = SpinnerOverlay(screen, "Analyzing blinky.vhd…")
        ov.draw()
        assert ov._panel_rect is not None
        assert screen.get_rect().contains(ov._panel_rect)

    def test_panel_is_centered(self, screen):
        ov = SpinnerOverlay(screen, "Analyzing x.vhd…", "detail")
        ov.draw()
        assert ov._panel_rect is not None
        sw, sh = screen.get_size()
        assert abs(ov._panel_rect.centerx - sw // 2) <= 1
        assert abs(ov._panel_rect.centery - sh // 2) <= 1

    @pytest.mark.parametrize("ticks", [0, 100, 450, 899, 900, 1234])
    def test_animation_phase_varies_without_error(
        self, screen, headless_pygame, monkeypatch, ticks
    ):
        # The spinner phase is read from the clock; every phase must render cleanly.
        monkeypatch.setattr(headless_pygame.time, "get_ticks", lambda: ticks)
        SpinnerOverlay(screen, "Analyzing…").draw()

    def test_handle_resize_rebuilds_background(self, screen):
        ov = SpinnerOverlay(screen, "x")
        ov.handle_resize(640, 480)
        assert ov._bg.get_size() == (640, 480)


# ── Threaded run loop ─────────────────────────────────────────────────────────


class TestRunWithSpinner:
    def test_returns_work_result(self, screen, headless_pygame):
        clock = headless_pygame.time.Clock()
        assert run_with_spinner(screen, clock, "x", lambda: (True, "/tmp/work")) == (
            True,
            "/tmp/work",
        )

    def test_propagates_exception(self, screen, headless_pygame):
        clock = headless_pygame.time.Clock()

        def boom():
            raise ValueError("analysis blew up")

        with pytest.raises(ValueError, match="analysis blew up"):
            run_with_spinner(screen, clock, "x", boom)

    def test_work_called_exactly_once(self, screen, headless_pygame):
        clock = headless_pygame.time.Clock()
        calls: list[int] = []
        run_with_spinner(screen, clock, "x", lambda: calls.append(1))
        assert calls == [1]

    def test_work_runs_off_main_thread(self, screen, headless_pygame):
        clock = headless_pygame.time.Clock()
        main_id = threading.get_ident()
        seen: dict[str, int] = {}

        def work():
            seen["tid"] = threading.get_ident()
            return None

        run_with_spinner(screen, clock, "x", work)
        assert seen["tid"] != main_id

    def test_slow_work_animates_and_returns(self, screen, headless_pygame):
        # A multi-frame wait exercises the draw loop and still returns the value.
        clock = headless_pygame.time.Clock()

        def work():
            time.sleep(0.1)
            return "done"

        assert run_with_spinner(screen, clock, "Analyzing…", work, detail="Running…") == "done"

    def test_quit_during_wait_is_reposted(self, screen, headless_pygame):
        pg = headless_pygame
        clock = pg.time.Clock()
        pg.event.post(pg.event.Event(pg.QUIT))

        def work():
            time.sleep(0.1)  # keep the loop alive long enough to consume the QUIT
            return None

        run_with_spinner(screen, clock, "x", work)
        assert pg.QUIT in [e.type for e in pg.event.get()]
