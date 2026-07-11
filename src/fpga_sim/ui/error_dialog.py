"""ErrorDialog: modal error overlay with scrollable message and retry/back buttons."""

import sys
from pathlib import Path

import pygame

from fpga_sim.platform_open import open_with_default_app
from fpga_sim.ui.constants import _ui_scale, get_font
from fpga_sim.ui.results import DialogResult
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.widgets import draw_button


class ErrorDialog:
    """Modal error dialog drawn over a dimmed snapshot of the current screen.

    Sized to ~1/3 of the main window area (2/3 wide, 1/2 tall).
    run() returns DialogResult.RETRY (Try Another File) or
    DialogResult.BACK (Back to Boards).

    When *example_path* is given, a third [View Example] button (and the V key)
    opens that file with the system's default application — the dialog stays
    open so the user can compare it against the error text.
    """

    def __init__(
        self,
        screen: pygame.Surface,
        title: str,
        message: str,
        example_path: Path | None = None,
    ) -> None:
        """Initialize the dialog with a screen snapshot, title, and message text."""
        self.screen = screen
        self.title = title
        self.message = message
        self.example_path = example_path
        print(f"[error] {title}: {message}", file=sys.stderr, flush=True)
        self._bg = screen.copy()
        self._scroll = 0
        self._retry_rect: pygame.Rect | None = None
        self._back_rect: pygame.Rect | None = None
        self._example_rect: pygame.Rect | None = None

    def run(self, clock: pygame.time.Clock) -> DialogResult:
        """Run the event loop and return DialogResult.RETRY or DialogResult.BACK."""
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return DialogResult.BACK
                elif ev.type == pygame.WINDOWRESIZED:
                    # Rebuild background at new size so the dim overlay fills correctly
                    self._bg = pygame.Surface((ev.x, ev.y))
                    self._bg.fill(THEME.sel_bg)
                    self._scroll = 0
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return DialogResult.BACK
                    elif ev.key == pygame.K_RETURN:
                        return DialogResult.RETRY
                    elif ev.key == pygame.K_v and self.example_path is not None:
                        open_with_default_app(self.example_path)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        self._scroll = max(0, self._scroll - 60)
                    elif ev.button == 5:
                        self._scroll += 60

            self._draw()
            clock.tick(30)

    def _click(self, pos: tuple[int, int]) -> DialogResult | None:
        if self._retry_rect and self._retry_rect.collidepoint(pos):
            return DialogResult.RETRY
        if self._back_rect and self._back_rect.collidepoint(pos):
            return DialogResult.BACK
        if self._example_rect and self._example_rect.collidepoint(pos):
            # Opens externally; the dialog stays up so the user can compare.
            assert self.example_path is not None
            open_with_default_app(self.example_path)
        return None

    def _draw(self) -> None:
        sw, sh = self.screen.get_size()
        s = _ui_scale(sw, sh)

        # Dimmed background
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.screen.blit(self._bg, (0, 0))
        self.screen.blit(overlay, (0, 0))

        # Scale everything to the window — panel is ~2/3 wide, content area ~1/3 tall
        pad = max(20, round(28 * s))
        panel_w = round(sw * 2 / 3)
        btn_h = max(38, round(50 * s))
        btn_gap = max(12, round(16 * s))
        btns_h = btn_h + btn_gap * 2

        title_f = get_font(max(20, round(26 * s)), bold=True)
        body_f = get_font(max(16, round(20 * s)))
        btn_f = get_font(max(16, round(20 * s)), bold=True)
        line_h = body_f.get_linesize() + 2

        # Word-wrap message lines to fit panel width
        max_text_w = panel_w - pad * 2
        wrapped = []
        for raw_line in self.message.split("\n"):
            words = raw_line.split(" ") if raw_line else [""]
            current = ""
            for word in words:
                test = (current + " " + word).strip()
                if body_f.size(test)[0] <= max_text_w:
                    current = test
                else:
                    if current:
                        wrapped.append(current)
                    current = word
            wrapped.append(current)

        body_h = len(wrapped) * line_h
        viewport_h = min(body_h, round(sh / 3))
        panel_h = pad + title_f.get_linesize() + pad + viewport_h + btns_h + pad

        px = (sw - panel_w) // 2
        py = (sh - panel_h) // 2

        # Panel background
        panel_rect = pygame.Rect(px, py, panel_w, panel_h)
        pygame.draw.rect(self.screen, THEME.panel_bg, panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, THEME.panel_border_error, panel_rect, 2, border_radius=10)

        # Title
        t = title_f.render(self.title, True, THEME.title_error)
        self.screen.blit(t, (px + pad, py + pad))

        # Scrollable body text
        body_top = py + pad + title_f.get_linesize() + pad
        max_scroll = max(0, body_h - viewport_h)
        self._scroll = min(self._scroll, max_scroll)

        clip = pygame.Rect(px + pad, body_top, max_text_w, viewport_h)
        self.screen.set_clip(clip)
        for i, line in enumerate(wrapped):
            ly = body_top + i * line_h - self._scroll
            if ly + line_h < body_top or ly > body_top + viewport_h:
                continue
            surf = body_f.render(line, True, THEME.body_text)
            self.screen.blit(surf, (px + pad, ly))
        self.screen.set_clip(None)

        # Scroll indicator
        if body_h > viewport_h:
            sb_x = px + panel_w - 8
            thumb_h = max(20, viewport_h * viewport_h // body_h)
            thumb_y = body_top + (self._scroll * (viewport_h - thumb_h) // max(1, max_scroll))
            pygame.draw.rect(
                self.screen,
                THEME.scroll_track,
                pygame.Rect(sb_x, body_top, 5, viewport_h),
                border_radius=2,
            )
            pygame.draw.rect(
                self.screen,
                THEME.scroll_thumb,
                pygame.Rect(sb_x, thumb_y, 5, thumb_h),
                border_radius=2,
            )

        # Buttons: [View Example] (optional) [Try Another File] [Back to Boards]
        btn_y = py + panel_h - btns_h + btn_gap
        buttons = []
        if self.example_path is not None:
            buttons.append(("View Example", THEME.btn_load_vhdl, "_example_rect"))
        buttons += [
            ("Try Another File", THEME.btn_error_retry, "_retry_rect"),
            ("Back to Boards", THEME.btn_error_back, "_back_rect"),
        ]
        widths = [btn_f.size(label)[0] + pad for label, _, _ in buttons]
        total_btn_w = sum(widths) + btn_gap * (len(buttons) - 1)
        bx = px + (panel_w - total_btn_w) // 2

        mouse = pygame.mouse.get_pos()
        self._example_rect = None
        for (label, style, attr), w in zip(buttons, widths, strict=True):
            rect = pygame.Rect(bx, btn_y, w, btn_h)
            setattr(self, attr, rect)
            draw_button(
                self.screen,
                rect,
                label,
                btn_f,
                style,
                hovered=rect.collidepoint(mouse),
            )
            bx += w + btn_gap

        # Keyboard shortcut hint below the panel
        hint_f = get_font(max(12, round(14 * s)))
        hint_text = "Enter: Try Another File    Esc: Back to Boards"
        if self.example_path is not None:
            hint_text = f"V: View Example    {hint_text}"
        hint = hint_f.render(hint_text, True, THEME.footer_hint)
        self.screen.blit(hint, hint.get_rect(centerx=px + panel_w // 2, top=py + panel_h + 8))

        pygame.display.flip()
