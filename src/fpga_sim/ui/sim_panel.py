"""sim_panel.py – Simulation control strip rendered below the FPGA board.

Draws three zones:
  Left  – live info: board clock, simulated time elapsed, clocks/frame,
          effective simulation rate.
  Center – logarithmic speed slider (0.001× … REAL … MAX, default 0.1×).
           Below REAL: limits sim cycles per frame proportionally.
           At/above REAL: always uses the maximum-cycles cap (full throughput).
  Right  – virtual-clock selector (preset frequencies via [-]/[+]) and
           effective-rate readout.

The ``clk_state`` dict is shared with sim_testbench.  When the virtual
clock is changed via [-]/[+], sim_testbench detects the updated
``period_ns`` value and writes the new half-period to ``dut.clk_half_ns``
on the VHDL sim_wrapper, taking effect within one clock half-period.
"""

from __future__ import annotations

import math
from collections import deque

import pygame

from fpga_sim.ui.constants import DARK_GRAY, GRAY, WHITE, YELLOW, _ui_scale, get_font

# ── Panel height base (pixels at 1.0 scale; actual height scales with window) ─

_PANEL_H_BASE: int = 130

# ── Clock presets (Hz) ────────────────────────────────────────────────────────

_CLOCK_PRESETS_HZ: list[float] = [
    3.3e6,
    8e6,
    12e6,
    16e6,
    25e6,
    50e6,
    100e6,
    125e6,
    200e6,
]

# ── Speed-slider constants ────────────────────────────────────────────────────

_SPEED_MIN: float = 0.001
_SPEED_MAX: float = 10.0
_SPEED_DEFAULT: float = 0.1

_LOG_MIN: float = math.log10(_SPEED_MIN)  # -3
_LOG_MAX: float = math.log10(_SPEED_MAX)  #  1
_LOG_RANGE: float = _LOG_MAX - _LOG_MIN  #  4


# ── Helpers ───────────────────────────────────────────────────────────────────


def _speed_to_frac(speed: float) -> float:
    """Map a speed multiplier to a slider fraction in [0, 1]."""
    clamped = max(_SPEED_MIN, min(_SPEED_MAX, speed))
    return (math.log10(clamped) - _LOG_MIN) / _LOG_RANGE


def _frac_to_speed(frac: float) -> float:
    """Map a slider fraction in [0, 1] to a speed multiplier."""
    return float(10.0 ** (max(0.0, min(1.0, frac)) * _LOG_RANGE + _LOG_MIN))


def _fmt_hz(hz: float) -> str:
    """Format a frequency as a compact MHz string."""
    mhz = hz / 1e6
    if mhz == int(mhz):
        return f"{int(mhz)} MHz"
    return f"{mhz:.4g} MHz"


def _fmt_time(ns: float) -> str:
    """Format a duration in nanoseconds as a human-readable string."""
    if ns < 1_000:
        return f"{ns:.0f} ns"
    us = ns / 1_000
    if us < 1_000:
        return f"{us:.4g} us"
    ms = ns / 1_000_000
    if ms < 1_000:
        return f"{ms:.4g} ms"
    return f"{ns / 1_000_000_000:.4g} s"


# ── SimPanel ──────────────────────────────────────────────────────────────────


class SimPanel:
    """Bottom-strip simulation control panel.

    Parameters
    ----------
    screen:
        The pygame display surface (shared with FPGABoard).
    height:
        Pixel height of the panel strip.
    board_clock_hz:
        Native clock frequency from the selected board definition.
        Used as the starting virtual-clock preset.

    Attributes
    ----------
    clk_state : dict
        Mutable dict with key ``"period_ns"``.  sim_testbench polls this
        after each event loop and writes any change to ``dut.clk_half_ns``,
        taking effect within one VHDL clock half-period.
    speed_factor : float
        Current simulation speed multiplier (0.001 – 10).  Multiplied
        against the elapsed wall-clock time to compute the sim step.
    paused : bool
        When ``True`` the main loop advances simulation by a single
        nanosecond per frame so GHDL stays alive but the design halts.

    """

    def __init__(
        self,
        screen: pygame.Surface,
        height: int,
        board_clock_hz: float,
        board_clocks_hz: list[float] | None = None,
    ) -> None:
        """Initialise the panel with screen surface, pixel height, and board clock.

        Parameters
        ----------
        screen:
            The shared pygame display surface.
        height:
            Pixel height of the panel strip.
        board_clock_hz:
            Native clock frequency from the selected board (used as the initial
            virtual-clock selection and fallback when *board_clocks_hz* is not
            supplied).
        board_clocks_hz:
            Ordered list of clock frequencies (Hz) available on the selected
            board.  When provided the [-]/[+] buttons cycle through these
            instead of the built-in generic preset list.  Pass ``None`` (the
            default) to use the generic preset list.

        """
        self.screen = screen
        self._panel_h_base: int = height
        self._board_clock_hz = board_clock_hz

        # Use the board's actual clock options when provided; fall back to the
        # generic preset list for boards whose clock data is unavailable.
        self._clock_options: list[float] = (
            list(board_clocks_hz) if board_clocks_hz else _CLOCK_PRESETS_HZ
        )

        # Find the closest option to the board's native clock
        self._preset_idx: int = min(
            range(len(self._clock_options)),
            key=lambda i: abs(self._clock_options[i] - board_clock_hz),
        )

        # Shared mutable state read by the dynamic-clock coroutine
        self.clk_state: dict[str, float] = {
            "period_ns": 1e9 / self._clock_options[self._preset_idx],
        }

        self.speed_factor: float = _SPEED_DEFAULT
        self.paused: bool = False
        # stop_requested is set by sim_testbench when the overlay [■ Stop] button
        # is clicked.  Declared here so sim_testbench can read it without coupling
        # to the overlay drawing logic.
        self.stop_requested: bool = False
        # at_max_throughput is set by sim_testbench each frame when the computed
        # sim step equals the cycle cap (i.e. the slider is asking for more work
        # than the cap allows).  The panel uses this to show "MAX SPEED" instead
        # of the requested Nx value, since additional slider movement has no effect.
        self.at_max_throughput: bool = False

        # Running statistics updated by sim_testbench each frame
        self._sim_elapsed_ns: int = 0
        self._clocks_per_frame: float = 0.0

        # Per-frame timing breakdown — 30-frame rolling windows for smooth display
        _w = 30
        self._fps_window: deque[float] = deque(maxlen=_w)
        self._timer_window: deque[float] = deque(maxlen=_w)
        self._draw_window: deque[float] = deque(maxlen=_w)
        self._idle_window: deque[float] = deque(maxlen=_w)
        # Smoothed averages (computed in update_timing, read in _draw_info_zone)
        self._fps: float = 0.0
        self._timer_us: float = 0.0
        self._draw_us: float = 0.0
        self._idle_us: float = 0.0

        # Slider drag state
        self._dragging: bool = False

        # Hit-test rects (populated during draw)
        self._slider_track: pygame.Rect | None = None
        self._slider_handle: pygame.Rect | None = None
        self._minus_rect: pygame.Rect | None = None
        self._plus_rect: pygame.Rect | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def panel_height(self) -> int:
        """Pixel height of the panel, scaled to the current window size.

        Re-evaluated on every access so it stays correct after window resize.
        """
        sw, sh = self.screen.get_size()
        return max(self._panel_h_base, round(self._panel_h_base * _ui_scale(sw, sh)))

    @property
    def current_clock_hz(self) -> float:
        """Current virtual-clock frequency in Hz."""
        return 1e9 / self.clk_state["period_ns"]

    @property
    def effective_hz(self) -> float:
        """Actual measured simulation rate in Hz (clocks/frame × frames/s).

        Returns the throughput-limited real rate, not the requested rate.
        Zero when paused or before the first timing sample arrives.
        """
        if self.paused or self._fps <= 0:
            return 0.0
        return self._clocks_per_frame * self._fps

    def update(self, sim_step_ns: int) -> None:
        """Record that *sim_step_ns* of simulation time just elapsed.

        Call once per main-loop iteration, after await Timer(...).
        """
        self._sim_elapsed_ns += sim_step_ns
        period = self.clk_state["period_ns"]
        self._clocks_per_frame = sim_step_ns / period if period > 0 else 0.0

    def update_timing(
        self,
        fps: float,
        timer_us: float,
        draw_us: float,
        idle_us: float,
    ) -> None:
        """Record per-frame timing breakdown for display in the info zone.

        Parameters
        ----------
        fps:
            Frames per second from ``pygame.time.Clock.get_fps()``.
        timer_us:
            Microseconds spent inside ``await Timer(...)`` (GHDL/NVC step).
        draw_us:
            Microseconds for board draw + panel draw + ``pygame.display.flip``.
        idle_us:
            Microseconds spent in ``board.clock.tick`` (frame-cap sleep).

        """
        self._fps_window.append(fps)
        self._timer_window.append(timer_us)
        self._draw_window.append(draw_us)
        self._idle_window.append(idle_us)
        n = len(self._fps_window)
        self._fps = sum(self._fps_window) / n
        self._timer_us = sum(self._timer_window) / n
        self._draw_us = sum(self._draw_window) / n
        self._idle_us = sum(self._idle_window) / n

    def handle_event(self, event: pygame.event.Event) -> None:
        """Process a single pygame event that may affect the panel."""
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._on_mouse_down(event.pos)
        elif event.type == pygame.MOUSEMOTION:
            self._on_mouse_motion(event.pos)
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self._dragging = False

    def draw(self) -> None:
        """Render the panel onto self.screen.

        Must be called *after* FPGABoard._draw(flip=False) and *before*
        pygame.display.flip() so the panel paints over the board's
        background without being erased by the next fill.
        """
        sw, sh = self.screen.get_size()
        s = _ui_scale(sw, sh)
        ph = max(self._panel_h_base, round(self._panel_h_base * s))
        y0 = sh - ph

        # Panel background + separator line
        bg = (24, 96, 24)
        pygame.draw.rect(self.screen, bg, pygame.Rect(0, y0, sw, self.panel_height))
        pygame.draw.line(self.screen, (80, 160, 80), (0, y0), (sw, y0), 1)

        fs = max(9, round(11 * s))
        font = get_font(fs)
        bold = get_font(fs, bold=True)
        small = get_font(max(8, round(9 * s)))

        zone_w = sw // 3

        self._draw_info_zone(0, y0, zone_w, ph, font, bold, s)
        self._draw_speed_zone(zone_w, y0, zone_w, ph, font, bold, small, s)
        self._draw_clock_zone(zone_w * 2, y0, sw - zone_w * 2, ph, font, bold, s)

    # ── Private event helpers ─────────────────────────────────────────────────

    def _on_mouse_down(self, pos: tuple[int, int]) -> None:
        if self._slider_handle and self._slider_handle.collidepoint(pos):
            self._dragging = True
            return
        if self._slider_track and self._slider_track.collidepoint(pos):
            self._dragging = True
            self._apply_slider_x(pos[0])
            return
        if self._minus_rect and self._minus_rect.collidepoint(pos):
            if self._preset_idx > 0:
                self._preset_idx -= 1
                self.clk_state["period_ns"] = 1e9 / self._clock_options[self._preset_idx]
        if self._plus_rect and self._plus_rect.collidepoint(pos):
            if self._preset_idx < len(self._clock_options) - 1:
                self._preset_idx += 1
                self.clk_state["period_ns"] = 1e9 / self._clock_options[self._preset_idx]

    def _on_mouse_motion(self, pos: tuple[int, int]) -> None:
        if self._dragging and self._slider_track:
            self._apply_slider_x(pos[0])

    def _apply_slider_x(self, x: int) -> None:
        if self._slider_track is None:
            return
        frac = (x - self._slider_track.left) / max(1, self._slider_track.width)
        self.speed_factor = _frac_to_speed(frac)

    # ── Private drawing helpers ───────────────────────────────────────────────

    def _draw_info_zone(
        self,
        x: int,
        y0: int,
        w: int,
        h: int,
        font: pygame.font.Font,
        bold: pygame.font.Font,
        s: float,
    ) -> None:
        lpad = max(10, round(14 * s))
        line_h = font.get_linesize() + max(1, round(2 * s))

        hdr = bold.render("INFO", True, (180, 220, 180))
        self.screen.blit(hdr, (x + lpad, y0 + max(4, round(5 * s))))
        ty = y0 + hdr.get_height() + max(5, round(7 * s))

        total_us = max(1.0, self._timer_us + self._draw_us + self._idle_us)
        g_pct = int(self._timer_us / total_us * 100)
        d_pct = int(self._draw_us / total_us * 100)
        i_pct = 100 - g_pct - d_pct
        rows: list[tuple[str, str, tuple[int, int, int]]] = [
            ("Board clk:", _fmt_hz(self._board_clock_hz), (150, 190, 150)),
            ("Sim time: ", _fmt_time(self._sim_elapsed_ns), WHITE),
            ("Clk/frame:", f"{self._clocks_per_frame:.1f}", WHITE),
            ("Eff. rate:", _fmt_hz(self.effective_hz), (100, 200, 255)),
            ("GUI FPS:  ", f"{self._fps:.1f}", (200, 200, 100)),
            ("G/D/I %:  ", f"{g_pct}/{d_pct}/{i_pct}", (180, 150, 100)),
        ]
        for label, value, color in rows:
            lbl_surf = font.render(label, True, (150, 185, 150))
            val_surf = bold.render(value, True, color)
            self.screen.blit(lbl_surf, (x + lpad, ty))
            self.screen.blit(val_surf, (x + lpad + lbl_surf.get_width() + 4, ty))
            ty += line_h

    def _draw_speed_zone(
        self,
        x: int,
        y0: int,
        w: int,
        h: int,
        font: pygame.font.Font,
        bold: pygame.font.Font,
        small: pygame.font.Font,
        s: float,
    ) -> None:
        hdr = bold.render("SIMULATION SPEED", True, (180, 220, 180))
        self.screen.blit(hdr, (x + (w - hdr.get_width()) // 2, y0 + max(4, round(5 * s))))

        # Track
        margin = max(14, round(20 * s))
        track_top = y0 + max(20, round(28 * s))
        track_h = max(4, round(6 * s))
        track = pygame.Rect(x + margin, track_top, w - 2 * margin, track_h)
        self._slider_track = track
        pygame.draw.rect(self.screen, DARK_GRAY, track, border_radius=2)

        # Filled portion
        frac = _speed_to_frac(self.speed_factor)
        filled_w = max(0, int(track.width * frac))
        if filled_w:
            pygame.draw.rect(
                self.screen,
                (60, 160, 60),
                pygame.Rect(track.left, track.top, filled_w, track_h),
                border_radius=2,
            )

        # Handle knob
        hr = max(6, round(8 * s))
        hx = track.left + int(track.width * frac)
        hy = track.centery
        knob_color = YELLOW if self._dragging else WHITE
        pygame.draw.circle(self.screen, knob_color, (hx, hy), hr)
        pygame.draw.circle(self.screen, DARK_GRAY, (hx, hy), hr, 1)
        self._slider_handle = pygame.Rect(hx - hr, hy - hr, hr * 2, hr * 2)

        # Tick marks + labels.
        # At/above REAL the step is always capped at the max-cycles limit, so
        # the right half of the slider is a "MAX SPEED" zone rather than a
        # linear extension of the rate target.
        ticks: list[tuple[float, str]] = [
            (0.001, "0.001x"),
            (0.01, "0.01x"),
            (0.1, "0.1x"),
            (1.0, "REAL"),
            (10.0, "MAX"),
        ]
        tick_y = track.bottom + max(2, round(3 * s))
        for val, lbl in ticks:
            tf = _speed_to_frac(val)
            tx = track.left + int(track.width * tf)
            col = YELLOW if val == 1.0 else (130, 170, 130)
            pygame.draw.line(self.screen, col, (tx, track.top - 2), (tx, track.bottom + 2), 1)
            t = small.render(lbl, True, col)
            self.screen.blit(t, (tx - t.get_width() // 2, tick_y))

        # Current value (or PAUSED / MAX SPEED), plus actual throughput note.
        # "MAX SPEED" is shown when the cycle cap is reached (at_max_throughput),
        # meaning adjusting the slider further right has no effect.
        # "CPU-limited" appears when the requested rate is not achieved (slider
        # below the cap point but still too fast for the host CPU).
        # For slow boards (< ~576 kHz) REAL genuinely means 1:1 real-time.
        cv_y = tick_y + small.get_linesize() + max(2, round(3 * s))
        if self.paused:
            cv = bold.render("PAUSED", True, (255, 100, 100))
            self.screen.blit(cv, (x + (w - cv.get_width()) // 2, cv_y))
        elif self.at_max_throughput:
            cv = bold.render("MAX SPEED", True, (255, 210, 80))
            self.screen.blit(cv, (x + (w - cv.get_width()) // 2, cv_y))
            if self._fps > 0:
                actual_factor = self._clocks_per_frame * self._fps / self._board_clock_hz
                cv_y2 = cv_y + bold.get_linesize()
                if actual_factor >= 1.0:
                    note = small.render(
                        f"actual {actual_factor:.3g}x  (faster than real-time)",
                        True,
                        (100, 240, 120),
                    )
                else:
                    note = small.render(
                        f"actual {actual_factor:.3g}x  (at max throughput)",
                        True,
                        (140, 200, 140),
                    )
                self.screen.blit(note, (x + (w - note.get_width()) // 2, cv_y2))
        else:
            cv = bold.render(f"{self.speed_factor:.4g}x", True, WHITE)
            self.screen.blit(cv, (x + (w - cv.get_width()) // 2, cv_y))
            # Show actual rate; warn when the requested rate is not achieved
            if self._fps > 0:
                actual_factor = self._clocks_per_frame * self._fps / self._board_clock_hz
                cv_y2 = cv_y + bold.get_linesize()
                if actual_factor < self.speed_factor * 0.9:
                    note = small.render(
                        f"actual {actual_factor:.3g}x  (CPU-limited)",
                        True,
                        (255, 180, 80),
                    )
                else:
                    note = small.render(
                        f"actual {actual_factor:.3g}x",
                        True,
                        (140, 200, 140),
                    )
                self.screen.blit(note, (x + (w - note.get_width()) // 2, cv_y2))

    def _draw_clock_zone(
        self,
        x: int,
        y0: int,
        w: int,
        h: int,
        font: pygame.font.Font,
        bold: pygame.font.Font,
        s: float,
    ) -> None:
        hdr = bold.render("VIRTUAL CLOCK", True, (180, 220, 180))
        self.screen.blit(hdr, (x + (w - hdr.get_width()) // 2, y0 + max(4, round(5 * s))))

        btn_w = max(22, round(30 * s))
        btn_h = max(16, round(20 * s))
        btn_y = y0 + max(20, round(27 * s))
        cx = x + w // 2

        # [-] button
        minus_rect = pygame.Rect(cx - btn_w * 2 - 6, btn_y, btn_w, btn_h)
        can_dec = self._preset_idx > 0
        _draw_btn(self.screen, minus_rect, "-", bold, enabled=can_dec)
        self._minus_rect = minus_rect

        # [+] button
        plus_rect = pygame.Rect(cx + btn_w + 6, btn_y, btn_w, btn_h)
        can_inc = self._preset_idx < len(self._clock_options) - 1
        _draw_btn(self.screen, plus_rect, "+", bold, enabled=can_inc)
        self._plus_rect = plus_rect

        # Current clock label (between buttons)
        clk_surf = bold.render(_fmt_hz(self.current_clock_hz), True, WHITE)
        self.screen.blit(
            clk_surf,
            (
                cx - clk_surf.get_width() // 2,
                btn_y + (btn_h - clk_surf.get_height()) // 2,
            ),
        )

        # Effective rate
        eff_y = btn_y + btn_h + max(3, round(5 * s))
        eff_surf = font.render(f"Eff: {_fmt_hz(self.effective_hz)}", True, (100, 200, 255))
        self.screen.blit(eff_surf, (x + (w - eff_surf.get_width()) // 2, eff_y))


# ── Utility ───────────────────────────────────────────────────────────────────


def _draw_btn(
    screen: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    font: pygame.font.Font,
    *,
    enabled: bool = True,
) -> None:
    """Draw a small rectangular button with a centred label."""
    bg = (55, 80, 55) if enabled else (38, 50, 38)
    border = (90, 130, 90) if enabled else DARK_GRAY
    fg = WHITE if enabled else GRAY
    pygame.draw.rect(screen, bg, rect, border_radius=3)
    pygame.draw.rect(screen, border, rect, 1, border_radius=3)
    surf = font.render(label, True, fg)
    screen.blit(
        surf,
        (
            rect.centerx - surf.get_width() // 2,
            rect.centery - surf.get_height() // 2,
        ),
    )
