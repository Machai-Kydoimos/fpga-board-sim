"""An orphaned board says so: the note, the preview banner (U56 Phase 3, plan §4.8).

No real board is orphaned until the bump to upstream heads (Phase 4), so these use
synthetic orphans, one per reason, and assert on what is drawn.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Any

import pytest

from fpga_sim.board_loader import BoardDef, ComponentInfo

if TYPE_CHECKING:
    from types import ModuleType

    from fpga_sim.ui import FPGABoard


def _board(**orphan: Any) -> BoardDef:
    return BoardDef(
        name="Old Board",
        class_name="OldPlatform",
        vendor="Xilinx",
        device="XC7A35T",
        source="litex-boards",
        file_stem="old_board",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", 0, [])],
        **orphan,
    )


_ORPHAN = {
    "upstream_status": "orphaned",
    "orphaned_at_commit": "97186cfc90cca23b",
    "orphaned_at_date": "2026-11-02",
}


# ── The note ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reason", "lead"),
    [
        ("file_removed", "No longer in litex-boards since 2026-11-02 (97186cf)."),
        (
            "no_longer_defined",
            "litex-boards no longer defines this version since 2026-11-02 (97186cf).",
        ),
        (
            "no_simulatable_io",
            "litex-boards lists no LED, switch or button for this board"
            " since 2026-11-02 (97186cf).",
        ),
    ],
)
def test_the_note_says_why_since_when_and_that_the_design_still_runs(reason, lead):
    note = _board(**_ORPHAN, orphaned_reason=reason).orphan_note()
    assert note == (
        f"{lead} Your design still runs on this saved copy; it will not receive upstream fixes."
    )


def test_the_note_names_a_successor_by_the_file_that_opens_it():
    note = _board(**_ORPHAN, orphaned_reason="file_removed", successor="litex-boards/new.json")
    assert note.orphan_note().endswith("Possible successor: litex-boards/new.")


def test_the_note_drops_a_date_or_commit_it_does_not_have():
    no_date = {**_ORPHAN, "orphaned_at_date": ""}
    assert "since 97186cf." in _board(**no_date, orphaned_reason="file_removed").orphan_note()


def test_a_board_upstream_still_defines_has_no_note():
    assert _board().orphan_note() == ""


# ── The preview ───────────────────────────────────────────────────────────────


def _preview(headless_pygame: ModuleType, board: BoardDef) -> FPGABoard:
    from fpga_sim.ui import FPGABoard

    screen = headless_pygame.display.set_mode((1024, 700))
    fb = FPGABoard(board_def=board, screen=screen, width=1024, height=700)
    fb._draw(flip=False)
    return fb


def test_an_orphan_preview_shows_its_note_above_the_board(headless_pygame: ModuleType) -> None:
    from fpga_sim.ui.theme import THEME

    board = _board(**_ORPHAN, orphaned_reason="file_removed")
    fb = _preview(headless_pygame, board)
    banner, help_button = fb._orphan_rect, fb._help_btn_rect
    assert banner is not None and help_button is not None
    assert " ".join(fb._orphan_lines) == board.orphan_note()
    assert banner.top >= help_button.bottom, "below the help and settings icons"
    assert banner.bottom <= fb.fpga_chip.rect.top, "the board starts below it"
    # Drawn, not just laid out: the note's amber is inside the banner.
    pixels = [
        fb.screen.get_at((x, y))[:3]
        for x in range(banner.left, banner.right, 2)
        for y in range(banner.top, banner.bottom, 2)
    ]
    assert tuple(THEME.warning) in pixels


def test_a_board_upstream_still_defines_has_no_banner(headless_pygame: ModuleType) -> None:
    current = _preview(headless_pygame, _board())
    assert current._orphan_rect is None and current._orphan_lines == []


def test_the_banner_moves_only_an_orphan(headless_pygame: ModuleType) -> None:
    """Every other board lays out exactly as before; an orphan's board starts lower."""
    current = _preview(headless_pygame, _board())
    orphan = _preview(
        headless_pygame, dataclasses.replace(_board(**_ORPHAN), orphaned_reason="file_removed")
    )
    assert orphan.fpga_chip.rect.top > current.fpga_chip.rect.top
