"""SettingsDialog: modal settings overlay (the gear button in the board preview).

A blocking overlay — same snapshot-dim-centered-panel structure as
:class:`~fpga_sim.ui.help_dialog.HelpDialog` — whose rows act directly on the
persisted session file (:mod:`fpga_sim.session_config`):

* **Theme** — cycles :data:`~fpga_sim.ui.theme.THEME_NAMES` and applies the
  choice immediately via :func:`~fpga_sim.ui.theme.set_theme` (the launcher
  restores the persisted name at startup).
* **Sim speed** — the speed slider's value as written back by the last
  simulation run, with a [Reset] to the default.
* **Recent files** — how many (board, VHDL) pairs are remembered (U18
  surfaces them in the file picker), with a [Clear].

The board, filters, VHDL file, and window size are persisted automatically by
the launcher, so they need no controls here — a hint line says so.

``draw_settings_button`` renders the gear trigger next to the ``(?)`` help
button in the board preview header.  The gear is drawn with primitives rather
than a font glyph (``⚙``) so it looks identical on every platform.
"""

from __future__ import annotations

import math

import pygame

from fpga_sim.session_config import load_session, update_session
from fpga_sim.ui.constants import _ui_scale, get_font
from fpga_sim.ui.sim_panel import SPEED_DEFAULT
from fpga_sim.ui.theme import THEME, THEME_LABELS, THEME_NAMES, current_theme_name, set_theme
from fpga_sim.ui.widgets import draw_button


def _draw_gear_icon(
    surface: pygame.Surface, center: tuple[int, int], radius: int, color: tuple[int, int, int]
) -> None:
    """Draw an eight-tooth gear glyph: tooth spokes, body disc, hub hole.

    The hub hole is punched in ``THEME.panel_bg`` — visually close enough to
    the button fill in both hover states that the gear reads correctly.
    """
    cx, cy = center
    tooth_w = max(2, round(radius * 0.55))
    for i in range(8):
        ang = math.pi * i / 4
        tip = (cx + radius * math.cos(ang), cy + radius * math.sin(ang))
        pygame.draw.line(surface, color, (cx, cy), tip, tooth_w)
    pygame.draw.circle(surface, color, (cx, cy), max(2, round(radius * 0.78)))
    pygame.draw.circle(surface, THEME.panel_bg, (cx, cy), max(1, round(radius * 0.38)))


def draw_settings_button(
    surface: pygame.Surface, *, right: int, top: int, size: int, mouse: tuple[int, int]
) -> pygame.Rect:
    """Draw the circular gear trigger button and return its hit-rect.

    Anchored by its top-right corner at (*right*, *top*) with square side
    *size*, mirroring :func:`~fpga_sim.ui.help_dialog.draw_help_button` so the
    two header buttons render identically side by side.
    """
    rect = pygame.Rect(right - size, top, size, size)
    font = get_font(max(12, round(size * 0.6)), bold=True)
    style = THEME.btn_settings  # read at draw time so a theme switch restyles the gear
    draw_button(surface, rect, "", font, style, hovered=rect.collidepoint(mouse))
    _draw_gear_icon(surface, rect.center, max(6, round(size * 0.32)), style.fg)
    return rect


class SettingsDialog:
    """Modal settings overlay drawn over a dimmed snapshot of the current screen.

    ``run()`` blocks until the user dismisses it (Esc, the Close button, or a
    click outside the panel) and then returns ``None``.  Row actions write to
    the session file immediately, so there is no OK/Cancel — closing loses
    nothing.
    """

    def __init__(self, screen: pygame.Surface) -> None:
        """Snapshot *screen* for the dimmed backdrop and load the session."""
        self.screen = screen
        self._bg = screen.copy()
        self._session = load_session()
        self._panel_rect: pygame.Rect | None = None
        self._close_rect: pygame.Rect | None = None
        self._theme_rect: pygame.Rect | None = None
        self._reset_rect: pygame.Rect | None = None
        self._clear_rect: pygame.Rect | None = None

    # ── Session-derived row values ────────────────────────────────────────────

    def _theme_name(self) -> str:
        name = self._session.get("theme", "")
        return name if isinstance(name, str) and name in THEME_NAMES else current_theme_name()

    def _speed(self) -> float:
        try:
            return float(self._session.get("speed_factor", SPEED_DEFAULT))
        except (TypeError, ValueError):
            return SPEED_DEFAULT

    def _recent_count(self) -> int:
        recent = self._session.get("recent", [])
        return len(recent) if isinstance(recent, list) else 0

    def _can_cycle_theme(self) -> bool:
        return len(THEME_NAMES) > 1

    def _can_reset_speed(self) -> bool:
        return abs(self._speed() - SPEED_DEFAULT) > 1e-12

    def _can_clear_recent(self) -> bool:
        return self._recent_count() > 0

    # ── Event loop ────────────────────────────────────────────────────────────

    def run(self, clock: pygame.time.Clock) -> None:
        """Run the blocking event loop until the overlay is dismissed."""
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    return
                if ev.type == pygame.WINDOWRESIZED:
                    self._bg = pygame.Surface((ev.x, ev.y))
                    self._bg.fill(THEME.pcb_bg)
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self._click(ev.pos):
                    return
            self._draw()
            clock.tick(30)

    def _click(self, pos: tuple[int, int]) -> bool:
        """Handle a click; return True when it dismisses the overlay."""
        if self._close_rect and self._close_rect.collidepoint(pos):
            return True
        if self._theme_rect and self._theme_rect.collidepoint(pos) and self._can_cycle_theme():
            current = self._theme_name()
            idx = THEME_NAMES.index(current) if current in THEME_NAMES else -1
            chosen = THEME_NAMES[(idx + 1) % len(THEME_NAMES)]
            # Apply live: the dialog restyles on its next frame and the parent
            # screen on close (the dimmed backdrop snapshot keeps the old look).
            set_theme(chosen)
            update_session(theme=chosen)
            self._session = load_session()
            return False
        if self._reset_rect and self._reset_rect.collidepoint(pos) and self._can_reset_speed():
            update_session(speed_factor=SPEED_DEFAULT)
            self._session = load_session()
            return False
        if self._clear_rect and self._clear_rect.collidepoint(pos) and self._can_clear_recent():
            update_session(recent=[])
            self._session = load_session()
            return False
        return bool(self._panel_rect and not self._panel_rect.collidepoint(pos))

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw(self) -> None:
        sw, sh = self.screen.get_size()
        s = _ui_scale(sw, sh)
        pad = max(16, round(24 * s))
        gap = max(8, round(12 * s))

        title_f = get_font(max(20, round(26 * s)), bold=True)
        label_f = get_font(max(14, round(17 * s)), bold=True)
        value_f = get_font(max(13, round(16 * s)))
        btn_f = get_font(max(13, round(16 * s)), bold=True)
        hint_f = get_font(max(12, round(14 * s)))

        theme_name = self._theme_name()
        rows: list[tuple[str, str, str, bool]] = [
            # (label, value, action label, action enabled)
            ("Theme", THEME_LABELS.get(theme_name, theme_name), "Switch", self._can_cycle_theme()),
            ("Sim speed", f"{self._speed():.4g}x", "Reset", self._can_reset_speed()),
            (
                "Recent files",
                f"{self._recent_count()} remembered",
                "Clear",
                self._can_clear_recent(),
            ),
        ]
        hint = "Board, filters, VHDL file and window size are saved automatically."

        row_h = btn_f.get_height() + 14
        title_h = title_f.get_linesize()
        hint_h = hint_f.get_linesize()
        panel_w = min(sw - 2 * pad, max(440, round(600 * s), hint_f.size(hint)[0] + 2 * pad))
        panel_h = pad * 2 + title_h + gap + len(rows) * (row_h + gap) + hint_h + gap + row_h
        px = (sw - panel_w) // 2
        py = max(0, (sh - panel_h) // 2)
        self._panel_rect = pygame.Rect(px, py, panel_w, panel_h)

        # Dimmed backdrop.
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(self._bg, (0, 0))
        self.screen.blit(overlay, (0, 0))

        # Panel.
        pygame.draw.rect(self.screen, THEME.panel_bg, self._panel_rect, border_radius=10)
        pygame.draw.rect(
            self.screen, THEME.panel_border_info, self._panel_rect, 2, border_radius=10
        )

        # Title.
        self.screen.blit(title_f.render("Settings", True, THEME.title_info), (px + pad, py + pad))

        # Rows: label | value | action button (right-aligned).
        mouse = pygame.mouse.get_pos()
        action_w = max(btn_f.size(a)[0] for _, _, a, _ in rows) + 2 * pad
        label_w = max(label_f.size(lbl)[0] for lbl, _, _, _ in rows) + 2 * gap
        y = py + pad + title_h + gap
        action_rects: list[pygame.Rect] = []
        for label, value, action, enabled in rows:
            text_y = y + (row_h - value_f.get_linesize()) // 2
            self.screen.blit(label_f.render(label, True, THEME.header_text), (px + pad, text_y))
            self.screen.blit(
                value_f.render(value, True, THEME.body_text), (px + pad + label_w, text_y)
            )
            rect = pygame.Rect(px + panel_w - pad - action_w, y, action_w, row_h)
            draw_button(
                self.screen,
                rect,
                action,
                btn_f,
                THEME.btn_settings_action,
                hovered=rect.collidepoint(mouse),
                enabled=enabled,
            )
            action_rects.append(rect)
            y += row_h + gap
        self._theme_rect, self._reset_rect, self._clear_rect = action_rects

        # Hint line about the automatically-persisted state.
        self.screen.blit(hint_f.render(hint, True, THEME.dim_text), (px + pad, y))
        y += hint_h + gap

        # Close button.
        btn_w = btn_f.size("Close")[0] + pad * 2
        self._close_rect = pygame.Rect(px + (panel_w - btn_w) // 2, y, btn_w, row_h)
        draw_button(
            self.screen,
            self._close_rect,
            "Close",
            btn_f,
            THEME.btn_help_close,
            hovered=self._close_rect.collidepoint(mouse),
        )

        # Dismiss hint below the panel.
        dismiss = hint_f.render("Esc or click outside to close", True, THEME.dim_text)
        self.screen.blit(dismiss, dismiss.get_rect(centerx=px + panel_w // 2, top=py + panel_h + 8))

        pygame.display.flip()
