"""Keyboard cursor and scrolling for the two list screens (roadmap D5 / F15).

The board selector and the VHDL file picker are the same widget wearing
different rows: a scrolling vertical list with a keyboard cursor, arrow and
page navigation, and auto-scroll to keep the cursor in view.  They had grown
byte-identical copies of ``_page_rows`` and ``_ensure_visible``, and a
``_move_cursor`` that differed **only** in where it asked for the row count --
which is exactly one hook, not a second implementation.

The mixin owns the arithmetic; the host owns the rows.  Anything else that
grows a scrolling list should inherit this rather than copy it a third time.
"""

from __future__ import annotations


class RowCursorMixin:
    """Cursor movement and scroll clamping over a host's list of rows.

    The host supplies the geometry it already has -- ``height``, ``scroll``,
    ``hovered``, a ``row_h`` row height and an ``_hdr`` header height -- plus
    :meth:`_row_count`, which is the one thing the two screens disagree about
    (the selector's list is filtered; the picker's is a directory scan).
    """

    # Host state this mixin reads and writes.  Declared so the arithmetic below
    # type-checks without the mixin having to own the constructor.
    height: int
    scroll: int
    hovered: int

    @property
    def row_h(self) -> int:
        """Pixel height of one row (the host defines this)."""
        raise NotImplementedError

    @property
    def _hdr(self) -> int:
        """Pixel height of the header above the rows (the host defines this)."""
        raise NotImplementedError

    def _row_count(self) -> int:
        """How many rows the list currently holds."""
        raise NotImplementedError

    def _page_rows(self) -> int:
        """Return the number of fully visible rows — the Page Up/Down jump distance."""
        viewport_h = self.height - self._hdr
        return max(1, viewport_h // self.row_h)

    def _ensure_visible(self, idx: int) -> None:
        """Scroll the minimum amount needed to bring row ``idx`` fully into view."""
        viewport_h = self.height - self._hdr
        top = idx * self.row_h
        if top < self.scroll:
            self.scroll = top
        elif top + self.row_h > self.scroll + viewport_h:
            self.scroll = top + self.row_h - viewport_h
        self.scroll = max(0, self.scroll)

    def _move_cursor(self, delta: int) -> None:
        """Move the keyboard cursor ``delta`` rows over the list.

        Clamps to the list bounds and auto-scrolls to keep the cursor visible.
        With no current selection, Down enters at the top and Up at the bottom.
        """
        n = self._row_count()
        if n == 0:
            self.hovered = -1
            return
        if self.hovered < 0:
            self.hovered = 0 if delta > 0 else n - 1
        else:
            self.hovered = max(0, min(n - 1, self.hovered + delta))
        self._ensure_visible(self.hovered)
