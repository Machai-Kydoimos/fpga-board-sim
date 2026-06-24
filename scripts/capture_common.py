"""Shared helpers for the README capture tools (`capture_demo`, `capture_selector`).

Importable from both the main process (orchestrators) and the simulator
subprocess (``sim/capture_frames``), so it avoids heavy top-level imports —
Pillow and pygame are imported lazily inside the functions that need them.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pygame

# A classic arrow-pointer outline, tip at (0, 0), pointing down-right.
_CURSOR_ARROW = [(0, 0), (0, 22), (5, 17), (9, 26), (13, 24), (9, 15), (16, 15)]


def draw_cursor(surface: pygame.Surface, pos: tuple[float, float], *, pressed: bool) -> None:
    """Draw a faux mouse pointer with its tip at *pos*.

    A pressed pointer turns amber, gets a thicker outline, and grows a click
    ring around the tip, so taps read clearly in the captured GIF.
    """
    import pygame

    x, y = int(pos[0]), int(pos[1])
    if pressed:
        pygame.draw.circle(surface, (255, 196, 64), (x, y), 16, 3)
    pts = [(x + dx, y + dy) for dx, dy in _CURSOR_ARROW]
    fill = (255, 212, 96) if pressed else (250, 250, 250)
    pygame.draw.polygon(surface, fill, pts)
    pygame.draw.polygon(surface, (15, 15, 15), pts, 3 if pressed else 1)


def draw_caption(surface: pygame.Surface, text: str, font: pygame.font.Font) -> None:
    """Draw a centred caption banner near the bottom of *surface* (no-op if empty)."""
    if not text:
        return
    import pygame

    label = font.render(text, True, (255, 255, 255))
    pad_x, pad_y = 16, 9
    w, h = label.get_width() + 2 * pad_x, label.get_height() + 2 * pad_y
    x = (surface.get_width() - w) // 2
    y = surface.get_height() - h - 20
    banner = pygame.Surface((w, h), pygame.SRCALPHA)
    banner.fill((0, 0, 0, 185))
    pygame.draw.rect(banner, (255, 196, 64), banner.get_rect(), 2, border_radius=6)
    surface.blit(banner, (x, y))
    surface.blit(label, (x + pad_x, y + pad_y))


def assemble_gif(
    frame_paths: list[str],
    out: Path,
    *,
    durations: int | list[int],
    colors: int = 128,
) -> None:
    """Quantise the PNG frames and write an optimised looping GIF to *out*.

    *durations* is milliseconds per frame: a single int for a uniform rate, or a
    list with one entry per frame for a scripted timeline.  Requires Pillow
    (in the ``dev`` group).
    """
    from PIL import Image

    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        Image.open(p).convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        for p in frame_paths
    ]
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,  # leave prior frame in place so Pillow stores only changed pixels
    )
