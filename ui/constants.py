"""Shared UI constants: colours and the scaling helper.

All other ui/ modules import from here so visual parameters have a single
source of truth (both the pygame renderer and the SVG generator stay in sync).
"""

from __future__ import annotations

import functools

import pygame

# ── Colours ──────────────────────────────────────────────────────────
BG_GREEN  = (34, 139, 34)
WHITE     = (255, 255, 255)
BLACK     = (0, 0, 0)
RED_ON    = (255, 30, 30)
RED_OFF   = (80, 0, 0)
GRAY      = (180, 180, 180)
DARK_GRAY = (80, 80, 80)
YELLOW    = (255, 230, 50)
BLUE_ON   = (80, 140, 255)
BLUE_OFF  = (40, 50, 80)
SEL_BG    = (30, 30, 40)
SEL_ROW_A = (40, 40, 50)
SEL_ROW_B = (35, 35, 45)
SEL_HOVER = (50, 70, 50)

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
