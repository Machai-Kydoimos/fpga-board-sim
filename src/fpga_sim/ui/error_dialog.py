"""ErrorDialog: modal error overlay with scrollable message and retry/back buttons."""

import pygame

from fpga_sim.ui.constants import SEL_BG, WHITE, _ui_scale, get_font


class ErrorDialog:
    """Modal error dialog drawn over a dimmed snapshot of the current screen.

    Sized to ~1/3 of the main window area (2/3 wide, 1/2 tall).
    run() returns 'retry' (Try Another File) or 'back' (Back to Boards).
    """

    def __init__(self, screen: pygame.Surface, title: str, message: str) -> None:
        """Initialise the dialog with a screen snapshot, title, and message text."""
        self.screen = screen
        self.title = title
        self.message = message
        self._bg = screen.copy()
        self._scroll = 0
        self._retry_rect: pygame.Rect | None = None
        self._back_rect: pygame.Rect | None = None

    def run(self, clock: pygame.time.Clock) -> str:
        """Run the event loop and return 'retry' or 'back'."""
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return "back"
                elif ev.type == pygame.WINDOWRESIZED:
                    # Rebuild background at new size so the dim overlay fills correctly
                    self._bg = pygame.Surface((ev.x, ev.y))
                    self._bg.fill(SEL_BG)
                    self._scroll = 0
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return "back"
                    elif ev.key == pygame.K_RETURN:
                        return "retry"
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result:
                            return result
                    elif ev.button == 4:
                        self._scroll = max(0, self._scroll - 60)
                    elif ev.button == 5:
                        self._scroll += 60

            self._draw()
            clock.tick(30)

    def _click(self, pos: tuple[int, int]) -> str | None:
        if self._retry_rect and self._retry_rect.collidepoint(pos):
            return "retry"
        if self._back_rect and self._back_rect.collidepoint(pos):
            return "back"
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
        pygame.draw.rect(self.screen, (30, 30, 40), panel_rect, border_radius=10)
        pygame.draw.rect(self.screen, (200, 60, 60), panel_rect, 2, border_radius=10)

        # Title
        t = title_f.render(self.title, True, (255, 100, 100))
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
            surf = body_f.render(line, True, (220, 220, 220))
            self.screen.blit(surf, (px + pad, ly))
        self.screen.set_clip(None)

        # Scroll indicator
        if body_h > viewport_h:
            sb_x = px + panel_w - 8
            thumb_h = max(20, viewport_h * viewport_h // body_h)
            thumb_y = body_top + (self._scroll * (viewport_h - thumb_h) // max(1, max_scroll))
            pygame.draw.rect(
                self.screen,
                (80, 80, 100),
                pygame.Rect(sb_x, body_top, 5, viewport_h),
                border_radius=2,
            )
            pygame.draw.rect(
                self.screen,
                (160, 160, 200),
                pygame.Rect(sb_x, thumb_y, 5, thumb_h),
                border_radius=2,
            )

        # Buttons
        btn_y = py + panel_h - btns_h + btn_gap
        retry_w = btn_f.size("Try Another File")[0] + pad
        back_w = btn_f.size("Back to Boards")[0] + pad
        total_btn_w = retry_w + btn_gap + back_w
        btn_start_x = px + (panel_w - total_btn_w) // 2

        mouse = pygame.mouse.get_pos()

        self._retry_rect = pygame.Rect(btn_start_x, btn_y, retry_w, btn_h)
        retry_hov = self._retry_rect.collidepoint(mouse)
        pygame.draw.rect(
            self.screen,
            (40, 110, 40) if retry_hov else (25, 70, 25),
            self._retry_rect,
            border_radius=6,
        )
        pygame.draw.rect(self.screen, WHITE, self._retry_rect, 2, border_radius=6)
        rt = btn_f.render("Try Another File", True, WHITE)
        self.screen.blit(rt, rt.get_rect(center=self._retry_rect.center))

        self._back_rect = pygame.Rect(btn_start_x + retry_w + btn_gap, btn_y, back_w, btn_h)
        back_hov = self._back_rect.collidepoint(mouse)
        pygame.draw.rect(
            self.screen,
            (90, 40, 40) if back_hov else (55, 25, 25),
            self._back_rect,
            border_radius=6,
        )
        pygame.draw.rect(self.screen, (200, 100, 100), self._back_rect, 2, border_radius=6)
        bt = btn_f.render("Back to Boards", True, WHITE)
        self.screen.blit(bt, bt.get_rect(center=self._back_rect.center))

        # Keyboard shortcut hint below the panel
        hint_f = get_font(max(12, round(14 * s)))
        hint = hint_f.render(
            "Enter: Try Another File    Esc: Back to Boards", True, (140, 140, 140)
        )
        self.screen.blit(hint, hint.get_rect(centerx=px + panel_w // 2, top=py + panel_h + 8))

        pygame.display.flip()
