"""Themed raster icons for board widgets (roadmap U44).

One narrow entry point -- :func:`latch_icon` -- so the *source* of an icon is an
implementation detail. Today it is a CC0 PNG under ``ui/assets/``; swapping it
for an SVG, a different pack, or hand-drawn geometry touches this module and
nothing else.

Every function here **returns None rather than raising** when an icon cannot be
produced: a missing, unreadable, or absurdly-sized asset must degrade to the
caller's own fallback (``components.Button`` falls back to its inset ring), not
take the board down. That is what keeps a decorative asset off the critical
path.

The shipped icons are monochrome-plus-alpha, so they are recolored here through
the alpha mask (``BLEND_RGBA_MULT``) instead of shipping one file per theme.

Results are cached per ``(name, size, color)``. Rasterizing costs ~0.02 ms, but
a board redraws every frame and a cache turns "cheap" into "free"; sizes change
only on resize, so the cache stays tiny in practice.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pygame

#: Where the packaged assets live (shipped inside the wheel, see pyproject).
_ASSET_DIR = Path(__file__).resolve().parent / "assets"

#: Below this the glyph stops reading as a shape and becomes a smudge -- the
#: #367 lesson applied to icons: decide legibility by an explicit floor, never
#: by whatever the host happens to render.
MIN_ICON_PX: int = 7

#: Above this an icon would dominate a widget rather than annotate it.
MAX_ICON_PX: int = 256


@lru_cache(maxsize=64)
def _load(name: str) -> pygame.Surface | None:
    """Load ``assets/<name>.png`` once, or None if it cannot be read."""
    path = _ASSET_DIR / f"{name}.png"
    try:
        surface = pygame.image.load(str(path))
    except (pygame.error, OSError):
        return None
    # convert_alpha() needs a display; without one, the unconverted surface
    # still blits correctly (just slower), which matters for headless tests.
    try:
        return surface.convert_alpha()
    except pygame.error:
        return surface


@lru_cache(maxsize=128)
def icon(name: str, size: int, color: tuple[int, int, int]) -> pygame.Surface | None:
    """Return *name* scaled to ``size`` px square and tinted *color*, else None.

    None means "draw your fallback": the asset is missing or unreadable, or
    *size* is outside the range where the glyph reads as itself.
    """
    if not MIN_ICON_PX <= size <= MAX_ICON_PX:
        return None
    source = _load(name)
    if source is None:
        return None
    scaled = pygame.transform.smoothscale(source, (size, size))
    tinted = pygame.Surface((size, size), pygame.SRCALPHA)
    tinted.fill((*color, 255))
    tinted.blit(scaled, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return tinted


def latch_icon(size: int, color: tuple[int, int, int]) -> pygame.Surface | None:
    """Return the latched-button padlock, or None to use the caller's fallback.

    A closed padlock rather than, say, a down-arrow: the arrow reads as a
    *direction label* on the d-pad boards (the 13-button ULX3S has
    ``UP0``/``DOWN0``/``LEFT0``/``RIGHT0``), which is exactly where an
    on-widget marker matters most.
    """
    return icon("locked", size, color)


def clear_cache() -> None:
    """Drop every cached surface (tests, and a theme swap that changes ink)."""
    icon.cache_clear()
    _load.cache_clear()
