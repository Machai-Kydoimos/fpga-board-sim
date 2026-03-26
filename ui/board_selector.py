"""BoardSelector screen: full-screen board picker with search filter and scrolling."""

import pygame

from board_loader import BoardDef
from ui.constants import SEL_BG, SEL_HOVER, SEL_ROW_A, SEL_ROW_B, WHITE, _ui_scale, get_font


class BoardSelector:
    """Full-screen picker.  Returns the chosen BoardDef, or None on quit."""

    def __init__(
        self,
        boards: list[BoardDef],
        screen: pygame.Surface,
        preselect_class: str = "",
    ) -> None:
        """Initialise the selector with a board list and optional pre-selected class name."""
        self.boards = boards
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.scroll = 0
        self.hovered = -1
        self.filter_text = ""

        if preselect_class:
            idx = next((i for i, b in enumerate(boards)
                        if b.class_name == preselect_class), -1)
            if idx >= 0:
                self.hovered = idx
                viewport_h = self.height - self._hdr
                self.scroll = max(
                    0, idx * self.row_h - viewport_h // 2 + self.row_h // 2
                )

    @property
    def row_h(self) -> int:
        """Return the pixel height of each board-list row."""
        return max(32, round(48 * _ui_scale(self.width, self.height)))

    @property
    def _hdr(self) -> int:
        return max(56, round(80 * _ui_scale(self.width, self.height)))

    def _filtered(self) -> list[BoardDef]:
        if not self.filter_text:
            return self.boards
        ft = self.filter_text.lower()
        return [b for b in self.boards
                if ft in b.name.lower() or ft in b.class_name.lower()]

    def run(self, clock: pygame.time.Clock) -> BoardDef | None:
        """Run the event loop and return the selected BoardDef, or None on quit."""
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                elif ev.type == pygame.WINDOWRESIZED:
                    self.width, self.height = ev.x, ev.y
                    self.scroll = 0
                elif ev.type == pygame.MOUSEMOTION:
                    self._hover(ev.pos)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if ev.button == 1:
                        result = self._click(ev.pos)
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        step = max(20, round(self.row_h * 3))
                        self.scroll = max(0, self.scroll - step)
                    elif ev.button == 5:
                        step = max(20, round(self.row_h * 3))
                        self.scroll += step
                elif ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        return None
                    elif ev.key == pygame.K_BACKSPACE:
                        self.filter_text = self.filter_text[:-1]
                        self.scroll = 0
                    elif ev.unicode and ev.unicode.isprintable():
                        self.filter_text += ev.unicode
                        self.scroll = 0

            self._draw()
            clock.tick(30)

    def _hover(self, pos: tuple[int, int]) -> None:
        hdr = self._hdr
        _, y = pos
        if y < hdr:
            self.hovered = -1
            return
        idx = (y - hdr + self.scroll) // self.row_h
        f = self._filtered()
        self.hovered = idx if 0 <= idx < len(f) else -1

    def _click(self, pos: tuple[int, int]) -> BoardDef | None:
        self._hover(pos)
        f = self._filtered()
        if 0 <= self.hovered < len(f):
            return f[self.hovered]
        return None

    def _draw(self) -> None:
        self.screen.fill(SEL_BG)
        s = _ui_scale(self.width, self.height)
        title_f  = get_font(max(14, round(22 * s)), bold=True)
        item_f   = get_font(max(11, round(15 * s)))
        detail_f = get_font(max( 9, round(11 * s)))

        hdr = self._hdr
        filtered = self._filtered()

        for i, b in enumerate(filtered):
            y = hdr + i * self.row_h - self.scroll
            if y + self.row_h < hdr or y > self.height:
                continue
            bg = SEL_HOVER if i == self.hovered else (
                SEL_ROW_A if i % 2 == 0 else SEL_ROW_B)
            pygame.draw.rect(self.screen, bg,
                             (10, y, self.width - 20, self.row_h - 2))
            nm = item_f.render(b.name, True, (220, 220, 255))
            self.screen.blit(nm, (20, y + 4))
            sm = detail_f.render(b.summary, True, (150, 150, 150))
            self.screen.blit(sm, (20, y + 26))

        # Header overlay (hides items that scrolled behind header)
        pygame.draw.rect(self.screen, SEL_BG, (0, 0, self.width, hdr))
        title = title_f.render("FPGA Simulator \u2014 Select Board", True, WHITE)
        self.screen.blit(title, (20, 12))

        stxt = (f"Filter: {self.filter_text}_"
                if self.filter_text else "Type to filter boards...")
        srch = item_f.render(stxt, True, (180, 180, 180))
        pygame.draw.rect(self.screen, (50, 50, 60),
                         (20, 48, self.width - 140, 24), border_radius=3)
        self.screen.blit(srch, (26, 50))
        cnt = detail_f.render(f"{len(filtered)} boards", True, (120, 120, 120))
        self.screen.blit(cnt, (self.width - 100, 52))

        pygame.display.flip()
