"""Putting text on the system clipboard, for the two features that offer it.

Extracted from :mod:`fpga_sim.ui.error_dialog`, which had the only copy button
in the app until the inspect overlay (U55) grew a second one.  The contract is
the reason it is worth sharing rather than repeating: **it never raises.**  A
clipboard can be genuinely absent -- no display server, an SDL build without
scrap support, a driver that initializes and then refuses -- and neither caller
can afford to care.  The error dialog is already explaining a failure; the
inspect overlay is a label.  Both report the miss and carry on.

``put_text`` / ``get_text`` initialize the subsystem themselves.  The explicit
``scrap.init()`` the error dialog used to do has been deprecated since
pygame-ce 2.2 and warned on every copy; dropping it is the one behavioral
change in what is otherwise a move, and it is why this is a shared seam
rather than a shared copy.
"""

from __future__ import annotations

import pygame


def copy_to_clipboard(text: str) -> bool:
    """Put *text* on the system clipboard; return False if this platform will not."""
    try:
        pygame.scrap.put_text(text)
    except (pygame.error, NotImplementedError, AttributeError):
        return False
    return True


def read_clipboard() -> str | None:
    """Return the clipboard's text, or None when this platform will not say.

    The read side of the same seam, so a test can prove what a copy actually
    put there rather than trusting that the call was made.  Same contract as
    :func:`copy_to_clipboard`: it never raises.
    """
    try:
        text = pygame.scrap.get_text()
    except (pygame.error, NotImplementedError, AttributeError):
        return None
    return text
