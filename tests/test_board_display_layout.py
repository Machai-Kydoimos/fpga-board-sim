"""Layout regression tests for FPGABoard's footer-space reservation (U34).

Single-window simulation hides the preview footer but keeps the board laid out
in the same place by reserving that bottom strip (``reserve_footer_space``) for
its own overlays.  These tests pin that the reserved layout is pixel-identical
to the footer-shown layout at any window size — so components do not jump when a
simulation starts, at reduced size or full screen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fpga_sim.board_loader import BoardDef, ComponentInfo, SevenSegDef

if TYPE_CHECKING:
    from types import ModuleType

    from fpga_sim.ui import FPGABoard

_Box = tuple[str, tuple[int, int], tuple[int, int]]


def _plain_board() -> BoardDef:
    return BoardDef(
        name="Test Board",
        class_name="TestBoard",
        vendor="TestVendor",
        device="TestDevice",
        package="QFP100",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(3)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(4)],
    )


def _seg_board() -> BoardDef:
    return BoardDef(
        name="Test 7-Seg Board",
        class_name="TestSegBoard",
        vendor="TestVendor",
        device="TestDevice",
        package="QFP100",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(3)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(4)],
        seven_seg=SevenSegDef(4, True, False, True, False),
    )


def _boxes(fb: FPGABoard) -> list[_Box]:
    """The topleft + size of every laid-out component, in a stable order."""
    boxes: list[_Box] = [("chip", fb.fpga_chip.rect.topleft, fb.fpga_chip.rect.size)]
    for i, led in enumerate(fb.leds):
        boxes.append((f"led{i}", led.rect.topleft, led.rect.size))
    for i, btn in enumerate(fb.buttons):
        boxes.append((f"btn{i}", btn.rect.topleft, btn.rect.size))
    for i, sw in enumerate(fb.switches):
        boxes.append((f"sw{i}", sw.rect.topleft, sw.rect.size))
    for i, seg in enumerate(getattr(fb, "_seven_segs", [])):
        boxes.append((f"seg{i}", seg.rect.topleft, seg.rect.size))
    return boxes


@pytest.mark.parametrize("size", [(800, 600), (1024, 700), (1280, 800), (1600, 900), (1920, 1080)])
@pytest.mark.parametrize("board_factory", [_plain_board, _seg_board], ids=["plain", "seven_seg"])
def test_reserved_footer_layout_matches_shown_footer(
    headless_pygame: ModuleType, size: tuple[int, int], board_factory: object
) -> None:
    """Footer-hidden-but-reserved lays out exactly like footer-shown, at every size."""
    from fpga_sim.ui import FPGABoard

    w, h = size
    scr = headless_pygame.display.set_mode((w, h))
    board = board_factory()  # type: ignore[operator]
    preview = FPGABoard(board_def=board, screen=scr, width=w, height=h, show_footer=True)
    sim = FPGABoard(
        board_def=board, screen=scr, width=w, height=h, show_footer=False, reserve_footer_space=True
    )
    assert _boxes(sim) == _boxes(preview)


def test_hidden_footer_without_reserve_still_moves(headless_pygame: ModuleType) -> None:
    """Meaningfulness guard: with the footer hidden and no reserve, the board does shift."""
    from fpga_sim.ui import FPGABoard

    scr = headless_pygame.display.set_mode((1024, 700))
    board = _plain_board()
    preview = FPGABoard(board_def=board, screen=scr, width=1024, height=700, show_footer=True)
    sim = FPGABoard(board_def=board, screen=scr, width=1024, height=700, show_footer=False)
    assert _boxes(sim) != _boxes(preview)
