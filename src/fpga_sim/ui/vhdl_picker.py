"""VHDLFilePicker: file browser screen for selecting .vhd/.vhdl files."""

from pathlib import Path

import pygame

from fpga_sim.ui._scroll import RowCursorMixin
from fpga_sim.ui.constants import WHITE, _ui_scale, get_font
from fpga_sim.ui.help_dialog import HelpDialog, draw_help_button
from fpga_sim.ui.theme import THEME


class VHDLFilePicker(RowCursorMixin):
    """Simple file picker for .vhd/.vhdl files.  Returns path or None."""

    def __init__(
        self,
        screen: pygame.Surface,
        start_dir: Path | str | None = None,
        preselect_name: str = "",
    ) -> None:
        """Initialize the picker for the given directory, optionally pre-selecting a file."""
        self.screen = screen
        self.width, self.height = screen.get_size()
        self.scroll = 0
        self.hovered = -1
        self.current_dir = Path(start_dir or Path.cwd())
        # Set by F1 / ?; consumed by run() to open the help overlay.
        self._help_requested = False
        #: Hit-rect of the (?) trigger, set at draw time (None before the first frame).
        self._help_rect: pygame.Rect | None = None
        self._scan()

        if preselect_name:
            for i, (name, _path, is_dir) in enumerate(self.entries):
                if not is_dir and name == preselect_name:
                    self.hovered = i
                    viewport_h = self.height - self._hdr
                    self.scroll = max(0, i * self.row_h - viewport_h // 2 + self.row_h // 2)
                    break

    @property
    def row_h(self) -> int:
        """Return the pixel height of each file-list row."""
        return max(24, round(36 * _ui_scale(self.width, self.height)))

    @property
    def _hdr(self) -> int:
        return max(48, round(70 * _ui_scale(self.width, self.height)))

    def _scan(self) -> None:
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

    def run(self, clock: pygame.time.Clock) -> str | None:
        """Run the event loop and return the selected file path, or None on cancel."""
        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return None
                elif ev.type == pygame.DROPFILE:
                    dropped = self._accept_drop(ev.file)
                    if dropped is not None:
                        return dropped
                elif ev.type == pygame.WINDOWRESIZED:
                    self.width, self.height = ev.x, ev.y
                    self.scroll = 0
                elif ev.type == pygame.MOUSEMOTION:
                    self._hover(ev.pos)
                elif ev.type == pygame.MOUSEBUTTONDOWN:
                    if (
                        ev.button == 1
                        and self._help_rect is not None
                        and (self._help_rect.collidepoint(ev.pos))
                    ):
                        self._help_requested = True
                    elif ev.button == 1:
                        result = self._activate()
                        if result is not None:
                            return result
                    elif ev.button == 4:
                        step = max(20, round(self.row_h * 3))
                        self.scroll = max(0, self.scroll - step)
                    elif ev.button == 5:
                        step = max(20, round(self.row_h * 3))
                        self.scroll += step
                elif ev.type == pygame.KEYDOWN:
                    exit_loop, result = self._handle_keydown(ev)
                    if exit_loop:
                        return result
            if self._help_requested:
                self._help_requested = False
                HelpDialog(self.screen).run(clock)
                self._sync_to_surface()
            self._draw()
            clock.tick(30)

    def _sync_to_surface(self) -> None:
        """Re-sync to the live surface size after the help overlay closes.

        A WINDOWRESIZED that arrives while HelpDialog owns the event loop never
        reaches the picker, leaving its cached width/height stale even though
        the display surface has already auto-resized.  Reconcile from the
        surface; reset scroll only on a real size change.
        """
        w, h = self.screen.get_size()
        if (w, h) != (self.width, self.height):
            self.width, self.height = w, h
            self.scroll = 0

    def _activate(self) -> str | None:
        """Act on the hovered row.

        Open a directory (rescans and returns None) or return the selected
        file's path. Returns None when nothing is hovered.
        """
        result = self._click()
        if result == "rescan":
            self.scroll = 0
            self.hovered = -1
            return None
        return result

    def _handle_keydown(self, ev: pygame.event.Event) -> tuple[bool, str | None]:
        """Handle one KEYDOWN event.

        Returns ``(exit_loop, value)``: when ``exit_loop`` is True the caller
        should return ``value`` from :meth:`run` (a file path, or None to
        cancel); when False the loop keeps running.
        """
        if ev.key == pygame.K_ESCAPE:
            return True, None
        if ev.key == pygame.K_F1 or ev.unicode == "?":
            self._help_requested = True
            return False, None
        if ev.key in (pygame.K_UP, pygame.K_DOWN):
            self._move_cursor(-1 if ev.key == pygame.K_UP else 1)
        elif ev.key in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            page = self._page_rows()
            self._move_cursor(-page if ev.key == pygame.K_PAGEUP else page)
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            result = self._activate()
            if result is not None:
                return True, result
        return False, None

    def _hover(self, pos: tuple[int, int]) -> None:
        hdr = self._hdr
        _, y = pos
        if self._help_rect is not None and self._help_rect.collidepoint(pos):
            self.hovered = -1
            return
        if y < hdr:
            self.hovered = -1
            return
        idx = (y - hdr + self.scroll) // self.row_h
        self.hovered = idx if 0 <= idx < len(self.entries) else -1

    def _accept_drop(self, path: str) -> str | None:
        """Handle a file dropped on the window: pick it, or browse to its folder.

        A dropped ``.vhd`` / ``.vhdl`` is *the pick* -- it goes through the same
        encoding, contract and analysis chain a clicked row does, because the
        gesture means the same thing.  A dropped **directory** browses there
        instead, which is the other useful thing to drag, and anything else is
        ignored rather than rejected: dropping a `.qsf` on the file picker is a
        misunderstanding, not an error worth a dialog.
        """
        dropped = Path(path)
        if dropped.is_dir():
            self.current_dir = dropped
            self._scan()
            self.scroll = 0
            self.hovered = -1
            return None
        if dropped.is_file() and dropped.suffix.lower() in (".vhd", ".vhdl"):
            return str(dropped)
        return None

    def _click(self) -> str | None:
        if 0 <= self.hovered < len(self.entries):
            name, path, is_dir = self.entries[self.hovered]
            if is_dir:
                self.current_dir = path
                self._scan()
                return "rescan"
            return str(path)
        return None

    def _row_count(self) -> int:
        """Rows the cursor moves over: the directory listing."""
        return len(self.entries)

    def _draw(self) -> None:
        self.screen.fill(THEME.sel_bg)
        s = _ui_scale(self.width, self.height)
        title_f = get_font(max(13, round(20 * s)), bold=True)
        path_f = get_font(max(9, round(12 * s)))
        item_f = get_font(max(10, round(14 * s)))

        hdr = self._hdr
        max_scroll = max(0, len(self.entries) * self.row_h - (self.height - hdr))
        self.scroll = min(self.scroll, max_scroll)

        for i, (name, _path, is_dir) in enumerate(self.entries):
            y = hdr + i * self.row_h - self.scroll
            if y + self.row_h < hdr or y > self.height:
                continue
            bg = (
                THEME.sel_hover
                if i == self.hovered
                else (THEME.sel_row_a if i % 2 == 0 else THEME.sel_row_b)
            )
            pygame.draw.rect(self.screen, bg, (10, y, self.width - 20, self.row_h - 2))
            color = THEME.dir_entry if is_dir else THEME.file_entry
            nm = item_f.render(name, True, color)
            self.screen.blit(nm, (24, y + 8))

        # Header
        pygame.draw.rect(self.screen, THEME.sel_bg, (0, 0, self.width, hdr))
        title = title_f.render("Select VHDL File", True, WHITE)
        self.screen.blit(title, (20, 10))
        pd = path_f.render(str(self.current_dir), True, THEME.muted_text)
        self.screen.blit(pd, (20, 10 + title_f.get_height() + 4))

        # The picker is where someone arrives with a file of their own, so it is
        # where dropping one has to be discoverable -- otherwise the feature is
        # only found by people who already guessed it exists.
        hint = path_f.render("or drop a .vhd file on this window", True, THEME.muted_text)
        self.screen.blit(hint, (20, 10 + title_f.get_height() + 4 + path_f.get_height() + 2))

        help_size = max(22, round(28 * s))
        self._help_rect = draw_help_button(
            self.screen,
            right=self.width - 20,
            top=8,
            size=help_size,
            mouse=pygame.mouse.get_pos(),
        )

        pygame.display.flip()
