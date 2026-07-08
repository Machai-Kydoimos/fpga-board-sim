"""Tooltip: a small hover panel showing a component's net name, pin, and direction.

Palette roles are read from ``THEME`` at draw time (never captured) so a
``set_theme()`` swap restyles the tooltip.  It reuses the shared info-panel
roles (``panel_bg`` / ``panel_border_info`` / ``header_text`` / ``body_text`` /
``dim_text``) so it matches the help and settings overlays in every theme.
"""

from __future__ import annotations

import pygame

from fpga_sim.board_loader import ComponentInfo
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.theme import THEME

_PAD = 8  # inner padding around the text block
_ROW_GAP = 3  # vertical gap between rows
_COL_GAP = 6  # gap between a field's prefix and its value
_CURSOR_GAP = 14  # offset from the cursor to the nearest box corner
_HEADER_PT = 15
_BODY_PT = 13


def tooltip_rows(label: str, info: ComponentInfo | None) -> list[tuple[str, str]]:
    """Return ``(prefix, value)`` rows for a component; the header has no prefix.

    The first row is always the component *label* (its header).  Net name, pin,
    and direction are appended from *info* when present; rows whose value is
    empty are omitted, so a component with no pin metadata yields just a header.
    """
    rows: list[tuple[str, str]] = [("", label)]
    if info is not None:
        if info.name:
            rows.append(("Net", info.name))
        if info.pins:
            rows.append(("Pin" if len(info.pins) == 1 else "Pins", ", ".join(info.pins)))
        if info.direction:
            rows.append(("Dir", info.direction))
    return rows


class Tooltip:
    """A small hover panel positioned near the cursor and clamped on-screen."""

    def draw(
        self,
        surface: pygame.Surface,
        anchor: tuple[int, int],
        label: str,
        info: ComponentInfo | None,
    ) -> pygame.Rect:
        """Draw the tooltip for *label* / *info* near *anchor*; return its rect."""
        header_f = get_font(_HEADER_PT, bold=True)
        body_f = get_font(_BODY_PT)

        # Render every row up front so the block can be measured before placement.
        # Each entry is (prefix_surface_or_None, value_surface).
        rendered: list[tuple[pygame.Surface | None, pygame.Surface]] = []
        for prefix, value in tooltip_rows(label, info):
            if prefix:
                rendered.append(
                    (
                        body_f.render(prefix, True, THEME.dim_text),
                        body_f.render(value, True, THEME.body_text),
                    )
                )
            else:
                rendered.append((None, header_f.render(value, True, THEME.header_text)))

        # Share one prefix column width so the values line up.
        prefix_w = max((p.get_width() for p, _ in rendered if p is not None), default=0)
        block_w = 0
        block_h = 0
        for p, v in rendered:
            row_w = v.get_width() if p is None else prefix_w + _COL_GAP + v.get_width()
            block_w = max(block_w, row_w)
            block_h += v.get_height() + _ROW_GAP
        block_h -= _ROW_GAP  # no trailing gap after the last row

        w = block_w + 2 * _PAD
        h = block_h + 2 * _PAD

        # Prefer below-right of the cursor; flip at the right / bottom edges, then
        # clamp so the box is always fully on-screen.
        sw, sh = surface.get_size()
        mx, my = anchor
        x = mx + _CURSOR_GAP
        y = my + _CURSOR_GAP
        if x + w > sw:
            x = mx - _CURSOR_GAP - w
        if y + h > sh:
            y = my - _CURSOR_GAP - h
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        rect = pygame.Rect(x, y, w, h)

        pygame.draw.rect(surface, THEME.panel_bg, rect, border_radius=6)
        pygame.draw.rect(surface, THEME.panel_border_info, rect, 1, border_radius=6)

        ty = y + _PAD
        for p, v in rendered:
            if p is None:
                surface.blit(v, (x + _PAD, ty))
            else:
                surface.blit(p, (x + _PAD, ty))
                surface.blit(v, (x + _PAD + prefix_w + _COL_GAP, ty))
            ty += v.get_height() + _ROW_GAP
        return rect
