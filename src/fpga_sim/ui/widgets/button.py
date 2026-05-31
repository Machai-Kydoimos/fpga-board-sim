"""widgets/button.py – Shared rounded-rect button rendering.

A single :func:`draw_button` entry point replaces the open-coded button draws
that had drifted across ``board_display``, ``error_dialog``, ``sim_panel`` and
the simulation overlay (each hand-rolled its own hover handling, border width
and corner radius).  Every button's appearance is declared once as a
:class:`ButtonStyle`; the resting / hover / disabled colour resolution lives
here so all callers behave consistently.
"""

from __future__ import annotations

from dataclasses import dataclass

import pygame

from fpga_sim.ui.constants import WHITE

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class ButtonStyle:
    """Colours and geometry describing one button's appearance.

    ``bg`` / ``fg`` / ``border`` are the resting colours and ``bg_hover`` is
    used while the pointer is over the button.  The ``*_disabled`` colours
    apply when the button is drawn with ``enabled=False``; each falls back to
    its enabled counterpart when left ``None``.
    """

    bg: RGB
    bg_hover: RGB
    fg: RGB = WHITE
    border: RGB = WHITE
    border_width: int = 2
    radius: int = 6
    bg_disabled: RGB | None = None
    fg_disabled: RGB | None = None
    border_disabled: RGB | None = None


def draw_button(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    font: pygame.font.Font,
    style: ButtonStyle,
    *,
    hovered: bool = False,
    enabled: bool = True,
) -> None:
    """Draw a rounded-rect button with a centred label.

    The fill, border and text colours are resolved from *style* according to
    *enabled* and *hovered* (a disabled button ignores *hovered*), then the
    rectangle, its border and the centred *label* are painted onto *surface*.
    """
    if not enabled:
        bg = style.bg_disabled or style.bg
        fg = style.fg_disabled or style.fg
        border = style.border_disabled or style.border
    elif hovered:
        bg, fg, border = style.bg_hover, style.fg, style.border
    else:
        bg, fg, border = style.bg, style.fg, style.border

    pygame.draw.rect(surface, bg, rect, border_radius=style.radius)
    if style.border_width > 0:
        pygame.draw.rect(surface, border, rect, style.border_width, border_radius=style.radius)
    text = font.render(label, True, fg)
    surface.blit(text, text.get_rect(center=rect.center))
