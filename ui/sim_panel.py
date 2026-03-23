"""sim_panel.py – Simulation control strip rendered below the FPGA board.

Draws three zones:
  Left  – live info: board clock, simulated time elapsed, clocks/frame,
          effective simulation rate.
  Center – logarithmic speed slider (0.001× … 10×, default 0.1×).
  Right  – virtual-clock selector (preset frequencies via [-]/[+]),
           effective-rate readout, and a pause toggle.

The ``clk_state`` dict is shared with sim_testbench.  When the virtual
clock is changed via [-]/[+], sim_testbench detects the updated
``period_ns`` value and writes the new half-period to ``dut.clk_half_ns``
on the VHDL sim_wrapper, taking effect within one clock half-period.
"""

from __future__ import annotations

import math

import pygame

from ui.constants import DARK_GRAY, GRAY, WHITE, YELLOW, _ui_scale, get_font

# ── Clock presets (Hz) ────────────────────────────────────────────────────────

_CLOCK_PRESETS_HZ: list[float] = [
    3.3e6, 8e6, 12e6, 16e6, 25e6, 50e6, 100e6, 125e6, 200e6,
]

# ── Speed-slider constants ────────────────────────────────────────────────────

_SPEED_MIN: float = 0.001
_SPEED_MAX: float = 10.0
_SPEED_DEFAULT: float = 0.1

_LOG_MIN: float = math.log10(_SPEED_MIN)   # -3
_LOG_MAX: float = math.log10(_SPEED_MAX)   #  1
_LOG_RANGE: float = _LOG_MAX - _LOG_MIN    #  4


# ── Helpers ───────────────────────────────────────────────────────────────────

def _speed_to_frac(speed: float) -> float:
    """Map a speed multiplier to a slider fraction in [0, 1]."""
    clamped = max(_SPEED_MIN, min(_SPEED_MAX, speed))
    return (math.log10(clamped) - _LOG_MIN) / _LOG_RANGE


def _frac_to_speed(frac: float) -> float:
    """Map a slider fraction in [0, 1] to a speed multiplier."""
    return 10.0 ** (max(0.0, min(1.0, frac)) * _LOG_RANGE + _LOG_MIN)


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
    ) -> None:
        """Initialise the panel with screen surface, pixel height, and board clock."""
        self.screen = screen
        self.panel_height = height
        self._board_clock_hz = board_clock_hz

        # Find the closest preset to the board's native clock
        self._preset_idx: int = min(
            range(len(_CLOCK_PRESETS_HZ)),
            key=lambda i: abs(_CLOCK_PRESETS_HZ[i] - board_clock_hz),
        )

        # Shared mutable state read by the dynamic-clock coroutine
        self.clk_state: dict[str, float] = {
            "period_ns": 1e9 / _CLOCK_PRESETS_HZ[self._preset_idx],
        }

        self.speed_factor: float = _SPEED_DEFAULT
        self.paused: bool = False

        # Running statistics updated by sim_testbench each frame
        self._sim_elapsed_ns: int = 0
        self._clocks_per_frame: float = 0.0

        # Slider drag state
        self._dragging: bool = False

        # Hit-test rects (populated during draw)
        self._slider_track: pygame.Rect | None = None
        self._slider_handle: pygame.Rect | None = None
        self._minus_rect: pygame.Rect | None = None
        self._plus_rect: pygame.Rect | None = None
        self._pause_rect: pygame.Rect | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def current_clock_hz(self) -> float:
        """Current virtual-clock frequency in Hz."""
        return 1e9 / self.clk_state["period_ns"]

    @property
    def effective_hz(self) -> float:
        """Effective simulation rate = virtual_clock × speed_factor."""
        return self.current_clock_hz * (0.0 if self.paused else self.speed_factor)

    def update(self, sim_step_ns: int) -> None:
        """Record that *sim_step_ns* of simulation time just elapsed.

        Call once per main-loop iteration, after await Timer(...).
        """
        self._sim_elapsed_ns += sim_step_ns
        period = self.clk_state["period_ns"]
        self._clocks_per_frame = sim_step_ns / period if period > 0 else 0.0

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
        sw = self.screen.get_width()
        sh = self.screen.get_height()
        y0 = sh - self.panel_height
        s = _ui_scale(sw, sh)

        # Panel background + separator line
        bg = (24, 96, 24)
        pygame.draw.rect(self.screen, bg, pygame.Rect(0, y0, sw, self.panel_height))
        pygame.draw.line(self.screen, (80, 160, 80), (0, y0), (sw, y0), 1)

        fs = max(9, round(11 * s))
        font = get_font(fs)
        bold = get_font(fs, bold=True)
        small = get_font(max(8, round(9 * s)))

        zone_w = sw // 3

        self._draw_info_zone(0, y0, zone_w, self.panel_height, font, bold, s)
        self._draw_speed_zone(zone_w, y0, zone_w, self.panel_height, font, bold, small, s)
        self._draw_clock_zone(zone_w * 2, y0, sw - zone_w * 2, self.panel_height, font, bold, s)

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
                self.clk_state["period_ns"] = 1e9 / _CLOCK_PRESETS_HZ[self._preset_idx]
        if self._plus_rect and self._plus_rect.collidepoint(pos):
            if self._preset_idx < len(_CLOCK_PRESETS_HZ) - 1:
                self._preset_idx += 1
                self.clk_state["period_ns"] = 1e9 / _CLOCK_PRESETS_HZ[self._preset_idx]
        if self._pause_rect and self._pause_rect.collidepoint(pos):
            self.paused = not self.paused

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
        x: int, y0: int, w: int, h: int,
        font: pygame.font.Font,
        bold: pygame.font.Font,
        s: float,
    ) -> None:
        lpad = max(10, round(14 * s))
        line_h = font.get_linesize() + max(1, round(2 * s))

        hdr = bold.render("INFO", True, (180, 220, 180))
        self.screen.blit(hdr, (x + lpad, y0 + max(4, round(5 * s))))
        ty = y0 + hdr.get_height() + max(5, round(7 * s))

        rows: list[tuple[str, str, tuple[int, int, int]]] = [
            ("Board clk:", _fmt_hz(self._board_clock_hz),    (150, 190, 150)),
            ("Sim time: ", _fmt_time(self._sim_elapsed_ns),  WHITE),
            ("Clk/frame:", f"{self._clocks_per_frame:.1f}",  WHITE),
            ("Eff. rate:", _fmt_hz(self.effective_hz),       (100, 200, 255)),
        ]
        for label, value, color in rows:
            lbl_surf = font.render(label, True, (150, 185, 150))
            val_surf = bold.render(value, True, color)
            self.screen.blit(lbl_surf, (x + lpad, ty))
            self.screen.blit(val_surf, (x + lpad + lbl_surf.get_width() + 4, ty))
            ty += line_h

    def _draw_speed_zone(
        self,
        x: int, y0: int, w: int, h: int,
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
                self.screen, (60, 160, 60),
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

        # Tick marks + labels
        ticks: list[tuple[float, str]] = [
            (0.001, "0.001x"),
            (0.01,  "0.01x"),
            (0.1,   "0.1x"),
            (1.0,   "REAL"),
            (10.0,  "10x"),
        ]
        tick_y = track.bottom + max(2, round(3 * s))
        for val, lbl in ticks:
            tf = _speed_to_frac(val)
            tx = track.left + int(track.width * tf)
            col = YELLOW if val == 1.0 else (130, 170, 130)
            pygame.draw.line(self.screen, col,
                             (tx, track.top - 2), (tx, track.bottom + 2), 1)
            t = small.render(lbl, True, col)
            self.screen.blit(t, (tx - t.get_width() // 2, tick_y))

        # Current value (or PAUSED)
        cv_y = tick_y + small.get_linesize() + max(2, round(3 * s))
        if self.paused:
            cv = bold.render("PAUSED", True, (255, 100, 100))
        else:
            cv = bold.render(f"{self.speed_factor:.4g}x", True, WHITE)
        self.screen.blit(cv, (x + (w - cv.get_width()) // 2, cv_y))

    def _draw_clock_zone(
        self,
        x: int, y0: int, w: int, h: int,
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
        can_inc = self._preset_idx < len(_CLOCK_PRESETS_HZ) - 1
        _draw_btn(self.screen, plus_rect, "+", bold, enabled=can_inc)
        self._plus_rect = plus_rect

        # Current clock label (between buttons)
        clk_surf = bold.render(_fmt_hz(self.current_clock_hz), True, WHITE)
        self.screen.blit(clk_surf, (
            cx - clk_surf.get_width() // 2,
            btn_y + (btn_h - clk_surf.get_height()) // 2,
        ))

        # Effective rate
        eff_y = btn_y + btn_h + max(3, round(5 * s))
        eff_surf = font.render(f"Eff: {_fmt_hz(self.effective_hz)}", True, (100, 200, 255))
        self.screen.blit(eff_surf, (x + (w - eff_surf.get_width()) // 2, eff_y))

        # Pause / Resume button
        p_label = "[RESUME]" if self.paused else "[PAUSE]"
        p_w = max(70, round(88 * s))
        p_h = max(15, round(19 * s))
        p_x = x + (w - p_w) // 2
        p_y = eff_y + eff_surf.get_height() + max(3, round(4 * s))
        pause_rect = pygame.Rect(p_x, p_y, p_w, p_h)
        p_bg = (100, 35, 35) if self.paused else (30, 65, 110)
        pygame.draw.rect(self.screen, p_bg, pause_rect, border_radius=3)
        pygame.draw.rect(self.screen, WHITE, pause_rect, 1, border_radius=3)
        pt = font.render(p_label, True, WHITE)
        self.screen.blit(pt, (
            pause_rect.centerx - pt.get_width() // 2,
            pause_rect.centery - pt.get_height() // 2,
        ))
        self._pause_rect = pause_rect


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
    screen.blit(surf, (
        rect.centerx - surf.get_width() // 2,
        rect.centery - surf.get_height() // 2,
    ))
