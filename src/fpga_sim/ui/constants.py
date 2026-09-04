"""Shared UI primitives: the base neutral palette, fonts, and the scaling helper.

The neutral colors here (WHITE / BLACK / GRAY / …) are the raw palette; the
semantic color *roles* the renderer reads live in :mod:`fpga_sim.ui.theme`.
Neutrals stay here (not in theme.py) to keep the import graph acyclic: theme.py
imports ``ButtonStyle`` from ``ui.widgets.button``, which imports ``WHITE`` here.
"""

from __future__ import annotations

import functools

import pygame

# ── Base neutral palette ─────────────────────────────────────────────
# Raw neutrals reused across the UI; semantic color roles live in theme.py.
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
GRAY = (180, 180, 180)
DARK_GRAY = (80, 80, 80)
YELLOW = (255, 230, 50)


def lerp_rgb(c0: tuple[int, int, int], c1: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    """Linear-interpolate between two RGB colors (*t* clamped to [0, 1]).

    Lives here rather than in theme.py so both the spinner's arc fade and the
    duty-driven LED/segment brightness (U9) share one implementation; the
    ``RGB`` alias itself lives in ``ui.widgets.button``, which imports *this*
    module, so the parameters are spelled as plain tuples to keep the import
    graph acyclic.
    """
    t = max(0.0, min(1.0, t))
    return (
        round(c0[0] + (c1[0] - c0[0]) * t),
        round(c0[1] + (c1[1] - c0[1]) * t),
        round(c0[2] + (c1[2] - c0[2]) * t),
    )


# ── UI scaling ────────────────────────────────────────────────────────
_BASE_W, _BASE_H = 1024, 700


def _ui_scale(w: int, h: int) -> float:
    """Linear scale factor relative to the 1024×700 reference (= 1.0).

    Uses the smaller axis ratio so no dimension overflows the window.
    """
    return min(w / _BASE_W, h / _BASE_H)


@functools.lru_cache(maxsize=128)
def get_font(size: int, bold: bool = False) -> pygame.font.Font:
    """Return a cached Consolas font at *size* px (bold optional).

    ``pygame.font.SysFont`` can take ~0.3 ms per call; caching by (size, bold)
    cuts the per-frame cost to a single dict lookup when the window is not
    being resized.
    """
    return pygame.font.SysFont("consolas", size, bold=bold)


@functools.lru_cache(maxsize=512)
def render_text(font: pygame.font.Font, text: str, color: tuple[int, int, int]) -> pygame.Surface:
    """Return a cached antialiased render of *text* in *color*.

    Every board widget re-rendered its label from the font on **every frame**,
    for a string that never changes: 28 renders per frame on a DE10-Lite, 45 on
    a Sword.  Measured at ~2.0 us each against ~0.24 us to blit a cached
    surface, that is ~52 us and ~83 us of avoidable work per frame -- more than
    the LED halos cost.  Caching by ``(font, text, color)`` is the same trick
    :func:`get_font` plays one level down, and needs no quantization because the
    text is constant.

    Antialiasing is not a parameter: every caller in the tree renders
    antialiased, and a flag nobody varies is a key nobody needs.

    **The returned Surface is shared -- blit it, never mutate it.**  A caller
    that filled it, or set its alpha or colorkey, would change what every other
    widget drawing the same label sees.  Reading (``get_rect`` /
    ``get_bounding_rect``) is fine, which is all any caller does today, and
    ``test_drawing_a_board_does_not_mutate_the_cached_label`` fails the moment
    one does not.

    The color is part of the key, so a theme switch renders afresh rather than
    serving the old palette -- callers still read ``THEME`` at draw time (U6).
    Like ``get_font``'s, this cache holds objects that a ``pygame.quit()``
    invalidates; nothing in the app quits before exit, and the test suite keeps
    pygame alive for the session for exactly that reason.
    """
    return font.render(text, True, color)
