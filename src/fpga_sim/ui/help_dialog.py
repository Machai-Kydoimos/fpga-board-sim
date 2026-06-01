"""HelpDialog: modal help / about overlay (F1 · ``?`` · the ``(?)`` button).

A single blocking overlay — modelled on :class:`~fpga_sim.ui.error_dialog.ErrorDialog`'s
snapshot-dim-centred-panel structure — that teaches the workflow, lists the
keyboard shortcuts, and summarises the VHDL design contract.  It runs its own
event loop so no keystroke leaks into the screen beneath it.

The shortcut legend is rendered from the module-level :data:`SHORTCUTS` table,
which is the single source of truth: when a future key lands (U14 ``P`` pause,
U15 compact mode, …) it is added here and the overlay updates automatically,
so the legend cannot drift away from the real handlers.

``draw_help_button`` / :data:`HELP_BUTTON_STYLE` render the ``(?)`` trigger
button that the board selector and preview share (via the D4 button helper).
"""

from __future__ import annotations

import pygame

from fpga_sim.ui.constants import SEL_BG, _ui_scale, get_font
from fpga_sim.ui.widgets import ButtonStyle, draw_button

# ── Palette (info-blue accents, vs ErrorDialog's red) ────────────────────────
_PANEL_BG = (30, 30, 40)
_PANEL_BORDER = (90, 130, 200)
_TITLE_COLOR = (150, 200, 255)
_HEADER_COLOR = (140, 205, 150)
_BODY_COLOR = (220, 220, 220)
_KEY_COLOR = (255, 225, 120)
_DIM_COLOR = (150, 150, 160)
_SCROLL_TRACK = (80, 80, 100)
_SCROLL_THUMB = (160, 160, 200)

_STYLE_CLOSE = ButtonStyle(bg=(45, 50, 70), bg_hover=(65, 75, 110))

#: Style for the ``(?)`` trigger button shared by the selector header and the
#: preview corner.  Large radius → the square hit-rect renders as a circle.
HELP_BUTTON_STYLE = ButtonStyle(
    bg=(45, 50, 70),
    bg_hover=(70, 85, 120),
    border=(120, 135, 170),
    radius=99,
)

# ── Content (data-driven; the legend's single source of truth) ───────────────
WORKFLOW: list[tuple[str, str]] = [
    ("1", "Select a board — type to filter, ↑/↓ to move, Enter or click to choose."),
    (
        "2",
        "Preview — click switches and buttons, pick the simulator (GHDL/NVC), "
        "then Load a VHDL file.",
    ),
    ("3", "Pick a VHDL file — choose a .vhd/.vhdl design (start with hdl/blinky.vhd)."),
    ("4", "Run — switches and buttons drive the inputs; LEDs and 7-seg show live outputs."),
]

#: (keys, description) — rendered into the shortcut legend.  Add new keys here.
SHORTCUTS: list[tuple[str, str]] = [
    ("F1  ?", "Open this help overlay"),
    ("Esc", "Back / cancel (every screen)"),
    ("↑ ↓", "Move the selection (board & file lists)"),
    ("PgUp PgDn", "Jump a page (board & file lists)"),
    ("Enter", "Select board · open folder · pick file · start sim"),
    ("Type", "Filter the board list"),
    ("Wheel", "Scroll the board & file lists"),
    ("R", "Reset switches & buttons (preview & sim)"),
    ("S", "Toggle the stats panel (simulation)"),
]

CONTRACT: list[str] = [
    "The entity name must match the filename (blinky.vhd → entity blinky).",
    "Ports: clk, sw, btn, led — plus seg on 7-segment boards.",
    "Generics NUM_SWITCHES / NUM_BUTTONS / NUM_LEDS / COUNTER_BITS (and NUM_SEGS on "
    "7-seg boards) are set to match the selected board.",
    "Working examples: hdl/blinky.vhd  ·  7-seg: hdl/counter_7seg.vhd",
]

# A drawn row: (height, [(surface, x-offset), ...]).
_Row = tuple[int, list[tuple[pygame.Surface, int]]]


def _wrap(text: str, font: pygame.font.Font, max_w: int) -> list[str]:
    """Greedy word-wrap *text* to *max_w* px; never returns an empty list."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        test = (current + " " + word).strip()
        if not current or font.size(test)[0] <= max_w:
            current = test
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


class HelpDialog:
    """Modal help overlay drawn over a dimmed snapshot of the current screen.

    ``run()`` blocks until the user dismisses it (Esc / F1 / ``?``, the Close
    button, or a click outside the panel) and then returns ``None``.
    """

    def __init__(self, screen: pygame.Surface) -> None:
        """Snapshot *screen* for the dimmed backdrop and reset scroll state."""
        self.screen = screen
        self._bg = screen.copy()
        self._scroll = 0
        self._close_rect: pygame.Rect | None = None
        self._panel_rect: pygame.Rect | None = None

    @staticmethod
    def _is_dismiss_key(ev: pygame.event.Event) -> bool:
        """Return True when *ev* is a key that closes the overlay (Esc/F1/``?``)."""
        return ev.key in (pygame.K_ESCAPE, pygame.K_F1) or ev.unicode == "?"

    def run(self, clock: pygame.time.Clock) -> None:
        """Run the blocking event loop until the overlay is dismissed."""
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    return
                if ev.type == pygame.WINDOWRESIZED:
                    self._bg = pygame.Surface((ev.x, ev.y))
                    self._bg.fill(SEL_BG)
                    self._scroll = 0
                elif ev.type == pygame.KEYDOWN:
                    if self._is_dismiss_key(ev):
                        return
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        if self._click(ev.pos):
                            return
                    elif ev.button == 4:
                        self._scroll = max(0, self._scroll - 50)
                    elif ev.button == 5:
                        self._scroll += 50
            self._draw()
            clock.tick(30)

    def _click(self, pos: tuple[int, int]) -> bool:
        """Return True when *pos* dismisses the overlay (Close button or outside)."""
        if self._close_rect and self._close_rect.collidepoint(pos):
            return True
        return bool(self._panel_rect and not self._panel_rect.collidepoint(pos))

    def _build_rows(
        self,
        content_w: int,
        header_f: pygame.font.Font,
        body_f: pygame.font.Font,
        key_f: pygame.font.Font,
    ) -> list[_Row]:
        """Render all help content into a flat list of (height, segments) rows."""
        rows: list[_Row] = []
        line_h = body_f.get_linesize() + 2
        head_h = header_f.get_linesize() + max(3, line_h // 3)
        spacer = max(4, line_h // 2)

        def header(text: str) -> None:
            rows.append((head_h, [(header_f.render(text, True, _HEADER_COLOR), 0)]))

        def body(text: str, indent: int = 0) -> None:
            for line in _wrap(text, body_f, content_w - indent):
                rows.append((line_h, [(body_f.render(line, True, _BODY_COLOR), indent)]))

        # Workflow — numbered, with a hanging indent on wrapped continuations.
        header("Workflow")
        for num, desc in WORKFLOW:
            nsurf = body_f.render(f"{num}.", True, _KEY_COLOR)
            indent = nsurf.get_width() + max(6, body_f.size(" ")[0])
            for i, line in enumerate(_wrap(desc, body_f, content_w - indent)):
                lsurf = body_f.render(line, True, _BODY_COLOR)
                segs = [(nsurf, 0), (lsurf, indent)] if i == 0 else [(lsurf, indent)]
                rows.append((line_h, segs))
        rows.append((spacer, []))

        # Keyboard shortcuts — two aligned columns (key, description).
        header("Keyboard shortcuts")
        key_col_w = max(key_f.size(k)[0] for k, _ in SHORTCUTS) + body_f.size("MM")[0]
        for keys, desc in SHORTCUTS:
            ksurf = key_f.render(keys, True, _KEY_COLOR)
            dsurf = body_f.render(desc, True, _BODY_COLOR)
            rows.append((line_h, [(ksurf, 0), (dsurf, key_col_w)]))
        rows.append((spacer, []))

        # VHDL design contract.
        header("VHDL design contract")
        for line in CONTRACT:
            body(line)
        return rows

    def _draw(self) -> None:
        sw, sh = self.screen.get_size()
        s = _ui_scale(sw, sh)
        pad = max(16, round(24 * s))
        gap = max(8, round(12 * s))

        title_f = get_font(max(20, round(26 * s)), bold=True)
        header_f = get_font(max(15, round(19 * s)), bold=True)
        body_f = get_font(max(13, round(16 * s)))
        key_f = get_font(max(13, round(16 * s)), bold=True)
        btn_f = get_font(max(15, round(18 * s)), bold=True)

        panel_w = min(sw - 2 * pad, max(480, round(720 * s)))
        content_w = panel_w - 2 * pad

        rows = self._build_rows(content_w, header_f, body_f, key_f)
        content_h = sum(h for h, _ in rows)

        btn_h = max(34, round(44 * s))
        title_h = title_f.get_linesize()
        # Fixed chrome (everything but the scrollable content); content fills the rest.
        chrome_h = pad * 2 + title_h + gap * 2 + btn_h
        viewport_h = max(body_f.get_linesize(), min(content_h, round(sh * 0.9) - chrome_h))
        panel_h = chrome_h + viewport_h

        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2
        self._panel_rect = pygame.Rect(px, py, panel_w, panel_h)

        # Dimmed backdrop.
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(self._bg, (0, 0))
        self.screen.blit(overlay, (0, 0))

        # Panel.
        pygame.draw.rect(self.screen, _PANEL_BG, self._panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, _PANEL_BORDER, self._panel_rect, 2, border_radius=10)

        # Title.
        self.screen.blit(
            title_f.render("FPGA Simulator — Help", True, _TITLE_COLOR), (px + pad, py + pad)
        )

        # Scrollable content.
        content_top = py + pad + title_h + gap
        max_scroll = max(0, content_h - viewport_h)
        self._scroll = max(0, min(self._scroll, max_scroll))

        self.screen.set_clip(pygame.Rect(px + pad, content_top, content_w, viewport_h))
        y = content_top - self._scroll
        for h, segs in rows:
            if y + h >= content_top and y <= content_top + viewport_h:
                for surf, dx in segs:
                    self.screen.blit(surf, (px + pad + dx, y))
            y += h
        self.screen.set_clip(None)

        # Scrollbar (only when content overflows the viewport).
        if content_h > viewport_h:
            sb_x = px + panel_w - 8
            thumb_h = max(20, viewport_h * viewport_h // content_h)
            thumb_y = content_top + (self._scroll * (viewport_h - thumb_h) // max(1, max_scroll))
            pygame.draw.rect(
                self.screen,
                _SCROLL_TRACK,
                pygame.Rect(sb_x, content_top, 5, viewport_h),
                border_radius=2,
            )
            pygame.draw.rect(
                self.screen, _SCROLL_THUMB, pygame.Rect(sb_x, thumb_y, 5, thumb_h), border_radius=2
            )

        # Close button.
        btn_w = btn_f.size("Close")[0] + pad * 2
        bx = px + (panel_w - btn_w) // 2
        by = content_top + viewport_h + gap
        self._close_rect = pygame.Rect(bx, by, btn_w, btn_h)
        draw_button(
            self.screen,
            self._close_rect,
            "Close",
            btn_f,
            _STYLE_CLOSE,
            hovered=self._close_rect.collidepoint(pygame.mouse.get_pos()),
        )

        # Dismiss hint below the panel.
        hint_f = get_font(max(12, round(14 * s)))
        hint = hint_f.render("Esc / F1 / ?  or click outside to close", True, _DIM_COLOR)
        self.screen.blit(hint, hint.get_rect(centerx=px + panel_w // 2, top=py + panel_h + 8))

        pygame.display.flip()


def draw_help_button(
    surface: pygame.Surface, *, right: int, top: int, size: int, mouse: tuple[int, int]
) -> pygame.Rect:
    """Draw the circular ``(?)`` trigger button and return its hit-rect.

    Anchored by its top-right corner at (*right*, *top*); *size* is the square
    side.  Hover is resolved from *mouse* against the button's own rect.  Both
    the selector header and the preview corner call this so the affordance
    looks identical on every launcher screen.
    """
    rect = pygame.Rect(right - size, top, size, size)
    font = get_font(max(12, round(size * 0.6)), bold=True)
    draw_button(surface, rect, "?", font, HELP_BUTTON_STYLE, hovered=rect.collidepoint(mouse))
    return rect
