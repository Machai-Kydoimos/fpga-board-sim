"""SpinnerOverlay: a non-blocking "working…" overlay with a rotating spinner.

VHDL analysis (:func:`fpga_sim.sim_bridge.analyze_vhdl`) shells out to the
simulator three times and can take several seconds; with no feedback the app
looks frozen.  :func:`run_with_spinner` runs that work on a background thread
and animates this overlay on the main thread until it finishes, then returns
the work's result — so the window keeps repainting (and stays answerable to the
OS) without ever touching the display surface off the main thread.

pygame rendering is **not** thread-safe, so the contract is strict: the worker
callable must not touch pygame (``analyze_vhdl`` only spawns subprocesses and
reads files); all drawing stays here on the calling thread.

Modelled on :class:`~fpga_sim.ui.error_dialog.ErrorDialog`'s snapshot → dim →
centered-panel structure, minus the event-driven controls — there is nothing to
click, and the overlay lives exactly as long as the work does.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

import pygame

from fpga_sim.ui.constants import _ui_scale, get_font
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.widgets.button import RGB

_T = TypeVar("_T")

# Spinner geometry/animation.  The leading dot is brightest and brightness
# fades around the ring, so sweeping a continuous phase reads as smooth
# rotation even though the dots themselves are discrete.
_DOTS = 12
_SPIN_PERIOD_MS = 900  # one full revolution


def _lerp(c0: RGB, c1: RGB, t: float) -> RGB:
    """Linear-interpolate between two RGB colors (*t* clamped to [0, 1])."""
    t = max(0.0, min(1.0, t))
    return (
        round(c0[0] + (c1[0] - c0[0]) * t),
        round(c0[1] + (c1[1] - c0[1]) * t),
        round(c0[2] + (c1[2] - c0[2]) * t),
    )


class SpinnerOverlay:
    """A centered "working…" panel with a rotating dotted spinner.

    Rendering only — :func:`run_with_spinner` owns the worker thread and the
    frame loop.  ``draw()`` paints one frame (the spinner phase is read from the
    pygame clock, so repeated calls animate); ``handle_resize`` keeps the dim
    backdrop matched to the window.
    """

    def __init__(self, screen: pygame.Surface, message: str, detail: str = "") -> None:
        """Snapshot *screen* for the dim backdrop and store the two text lines."""
        self.screen = screen
        self.message = message
        self.detail = detail
        self._bg = screen.copy()
        self._panel_rect: pygame.Rect | None = None

    def handle_resize(self, width: int, height: int) -> None:
        """Rebuild the backdrop after a resize (the panel hides the old one)."""
        self._bg = pygame.Surface((width, height))
        self._bg.fill(THEME.sel_bg)

    def _draw_spinner(self, cx: int, cy: int, ring_r: int, dot_r: int) -> None:
        """Draw the rotating ring of dots centered at (*cx*, *cy*)."""
        phase = (pygame.time.get_ticks() / _SPIN_PERIOD_MS) % 1.0
        for i in range(_DOTS):
            frac = i / _DOTS
            # Brightness peaks at the moving head (frac == phase) and fades
            # backward around the ring → a comet-like sweep.
            t = 1.0 - ((frac - phase) % 1.0)
            ang = 2 * math.pi * frac - math.pi / 2  # start at 12 o'clock
            x = round(cx + ring_r * math.cos(ang))
            y = round(cy + ring_r * math.sin(ang))
            color = _lerp(THEME.spinner_track, THEME.spinner_arc, t)
            pygame.draw.circle(self.screen, color, (x, y), dot_r)

    def draw(self) -> None:
        """Paint one frame: dim backdrop, panel, spinner, and text lines."""
        sw, sh = self.screen.get_size()
        s = _ui_scale(sw, sh)
        pad = max(20, round(28 * s))
        gap = max(10, round(14 * s))
        ring_r = max(14, round(22 * s))
        dot_r = max(2, round(4 * s))
        ring_d = 2 * (ring_r + dot_r)

        msg_f = get_font(max(18, round(22 * s)), bold=True)
        det_f = get_font(max(13, round(16 * s)))
        msg_surf = msg_f.render(self.message, True, THEME.body_text)
        det_surf = det_f.render(self.detail, True, THEME.dim_text) if self.detail else None

        text_w = max(msg_surf.get_width(), det_surf.get_width() if det_surf else 0)
        panel_w = max(ring_d, text_w) + pad * 2
        text_h = msg_surf.get_height() + (gap // 2 + det_surf.get_height() if det_surf else 0)
        panel_h = pad + ring_d + gap + text_h + pad

        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2
        self._panel_rect = pygame.Rect(px, py, panel_w, panel_h)

        # Dim backdrop over the snapshot of the screen beneath.
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(self._bg, (0, 0))
        self.screen.blit(overlay, (0, 0))

        # Panel.
        pygame.draw.rect(self.screen, THEME.panel_bg, self._panel_rect, border_radius=10)
        pygame.draw.rect(
            self.screen, THEME.panel_border_info, self._panel_rect, 2, border_radius=10
        )

        # Spinner, centered horizontally near the top of the panel.
        cx = px + panel_w // 2
        self._draw_spinner(cx, py + pad + ring_r + dot_r, ring_r, dot_r)

        # Text lines, centered under the spinner.
        my = py + pad + ring_d + gap
        self.screen.blit(msg_surf, msg_surf.get_rect(centerx=cx, top=my))
        if det_surf is not None:
            dy = my + msg_surf.get_height() + gap // 2
            self.screen.blit(det_surf, det_surf.get_rect(centerx=cx, top=dy))

        pygame.display.flip()


def run_with_spinner(
    screen: pygame.Surface,
    clock: pygame.time.Clock,
    message: str,
    work: Callable[[], _T],
    *,
    detail: str = "",
) -> _T:
    """Run *work* on a worker thread, animating a spinner until it completes.

    The overlay (*message* plus optional *detail*) is drawn on the calling
    thread at ~30 fps while *work* runs in the background; this returns *work*'s
    result once it finishes, re-raising any exception it raised.  *work* must
    not touch pygame (it runs off the main thread).

    A window-close (``QUIT``) during the wait is remembered and re-posted after
    *work* finishes: the work itself cannot be interrupted mid-flight, but the
    close is then honored by whichever screen regains control.
    """
    overlay = SpinnerOverlay(screen, message, detail)
    pending_quit = False
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(work)
        while not future.done():
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pending_quit = True
                elif ev.type == pygame.WINDOWRESIZED:
                    overlay.handle_resize(ev.x, ev.y)
            overlay.draw()
            clock.tick(30)
    if pending_quit:
        pygame.event.post(pygame.event.Event(pygame.QUIT))
    return future.result()
