"""VHDLFilePicker: file browser screen for selecting .vhd/.vhdl files.
"""

from pathlib import Path

import pygame

from ui.constants import SEL_BG, SEL_HOVER, SEL_ROW_A, SEL_ROW_B, WHITE, _ui_scale


class VHDLFilePicker:
    """Simple file picker for .vhd/.vhdl files.  Returns path or None."""

    def __init__(self, screen: pygame.Surface, start_dir: Path | str | None = None, preselect_name: str = "") -> None:
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.scroll = 0
        self.hovered = -1
        self.current_dir = Path(start_dir or Path.cwd())
        self._scan()

        if preselect_name:
            for i, (name, _path, is_dir) in enumerate(self.entries):
                if not is_dir and name == preselect_name:
                    self.hovered = i
                    viewport_h = self.height - self._hdr
                    self.scroll = max(
                        0, i * self.row_h - viewport_h // 2 + self.row_h // 2
                    )
                    break

    @property
    def row_h(self) -> int:
        return max(24, round(36 * _ui_scale(self.width, self.height)))

    @property
    def _hdr(self) -> int:
        return max(48, round(70 * _ui_scale(self.width, self.height)))

    def _scan(self):
        """Refresh the file list for current_dir."""
        self.entries = []
        if self.current_dir.parent != self.current_dir:
            self.entries.append(("..", self.current_dir.parent, True))
        try:
            for p in sorted(self.current_dir.iterdir()):
                if p.name.startswith("."):
                    continue
                if p.is_dir():
                    self.entries.append((p.name + "/", p, True))
            for p in sorted(self.current_dir.iterdir()):
                if p.suffix.lower() in (".vhd", ".vhdl"):
                    self.entries.append((p.name, p, False))
        except PermissionError:
            pass

    def run(self, clock):
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
                        result = self._click()
                        if result == "rescan":
                            self.scroll = 0
                            self.hovered = -1
                            continue
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
            self._draw()
            clock.tick(30)

    def _hover(self, pos):
        hdr = self._hdr
        _, y = pos
        if y < hdr:
            self.hovered = -1
            return
        idx = (y - hdr + self.scroll) // self.row_h
        self.hovered = idx if 0 <= idx < len(self.entries) else -1

    def _click(self):
        if 0 <= self.hovered < len(self.entries):
            name, path, is_dir = self.entries[self.hovered]
            if is_dir:
                self.current_dir = path
                self._scan()
                return "rescan"
            return str(path)
        return None

    def _draw(self):
        self.screen.fill(SEL_BG)
        s       = _ui_scale(self.width, self.height)
        title_f = pygame.font.SysFont("consolas", max(13, round(20 * s)), bold=True)
        path_f  = pygame.font.SysFont("consolas", max( 9, round(12 * s)))
        item_f  = pygame.font.SysFont("consolas", max(10, round(14 * s)))

        hdr = self._hdr

        for i, (name, _path, is_dir) in enumerate(self.entries):
            y = hdr + i * self.row_h - self.scroll
            if y + self.row_h < hdr or y > self.height:
                continue
            bg = SEL_HOVER if i == self.hovered else (
                SEL_ROW_A if i % 2 == 0 else SEL_ROW_B)
            pygame.draw.rect(self.screen, bg,
                             (10, y, self.width - 20, self.row_h - 2))
            colour = (180, 180, 255) if is_dir else (220, 255, 220)
            nm = item_f.render(name, True, colour)
            self.screen.blit(nm, (24, y + 8))

        # Header
        pygame.draw.rect(self.screen, SEL_BG, (0, 0, self.width, hdr))
        title = title_f.render("Select VHDL File", True, WHITE)
        self.screen.blit(title, (20, 10))
        pd = path_f.render(str(self.current_dir), True, (150, 150, 150))
        self.screen.blit(pd, (20, 40))

        pygame.display.flip()
