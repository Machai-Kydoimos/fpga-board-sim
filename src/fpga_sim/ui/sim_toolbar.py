"""SimToolbar: the in-simulation navigation toolbar (roadmap U7).

Three buttons drawn along the bottom-left of the simulation screen —
[Back to Boards] · [Change VHDL] · [Reload VHDL] — mirroring the launcher
footer's color language (board navigation = teal, VHDL loading = blue,
(re)starting = green) by reusing the same THEME ButtonStyle roles, so every
theme that styles the launcher styles this toolbar for free.

The widget is deliberately dumb: it draws and hit-tests.  A click resolves to
a :class:`~fpga_sim.sim_bridge.SimExit`, which ``sim/sim_testbench.py`` writes
to the exit-intent file for the launcher to act on (see
``launch_simulation``); the toolbar itself never touches processes or files,
which keeps it unit-testable under a headless display.
"""

from __future__ import annotations

import pygame

from fpga_sim.sim_bridge import SimExit
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.widgets import draw_button
from fpga_sim.ui.widgets.button import ButtonStyle

#: (label, THEME ButtonStyle role, resulting intent) per button, in draw order.
#: Roles are stored by *name* and resolved at draw time so a set_theme() swap
#: restyles the toolbar (never capture ``THEME.<field>`` at import — U6).
_BUTTONS: tuple[tuple[str, str, SimExit], ...] = (
    ("Back to Boards", "btn_select_board", SimExit.BACK_TO_BOARDS),
    ("Change VHDL", "btn_load_vhdl", SimExit.CHANGE_VHDL),
    ("Reload VHDL", "btn_start_sim", SimExit.RELOAD_VHDL),
)


class SimToolbar:
    """Draw the three navigation buttons and map clicks to :class:`SimExit`.

    ``draw()`` lays the row out fresh every frame (the sim window is
    resizable), recording each button's rect; ``handle_click()`` hit-tests
    against the rects of the most recent draw and returns the matching
    intent, or ``None`` before the first draw / for a miss.
    """

    def __init__(self) -> None:
        """Start with no hit targets; ``draw()`` populates them each frame."""
        self._hit: list[tuple[pygame.Rect, SimExit]] = []

    def draw(  # noqa: PLR0913 — geometry knobs mirror the sim overlay's button math
        self,
        screen: pygame.Surface,
        font: pygame.font.Font,
        *,
        left: int,
        bottom: int,
        pad_x: int,
        pad_y: int,
        gap: int,
    ) -> pygame.Rect:
        """Draw the button row with its bottom-left corner at (*left*, *bottom*).

        Buttons share one height derived from *font* (matching the Pause/Stop
        overlay buttons, which use the same padding values).  Returns the
        bounding rect of the whole row so the caller can stack other overlay
        elements above it.
        """
        mouse = pygame.mouse.get_pos()
        btn_h = font.get_height() + 2 * pad_y
        x = left
        self._hit = []
        for label, role, intent in _BUTTONS:
            style: ButtonStyle = getattr(THEME, role)
            rect = pygame.Rect(x, bottom - btn_h, font.size(label)[0] + 2 * pad_x, btn_h)
            draw_button(screen, rect, label, font, style, hovered=rect.collidepoint(mouse))
            self._hit.append((rect, intent))
            x = rect.right + gap
        return self._hit[0][0].unionall([r for r, _ in self._hit[1:]])

    def handle_click(self, pos: tuple[int, int]) -> SimExit | None:
        """Return the intent for a left-click at *pos*, or ``None`` on a miss."""
        for rect, intent in self._hit:
            if rect.collidepoint(pos):
                return intent
        return None
