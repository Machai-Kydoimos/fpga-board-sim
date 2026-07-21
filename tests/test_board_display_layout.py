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


# ── LED bank clustering (U36) ─────────────────────────────────────────────────


def _two_color_board() -> BoardDef:
    """18 red LEDR + 9 green LEDG, with a canonical convention for the labels."""
    return BoardDef(
        name="TwoColor",
        class_name="TwoColor",
        leds=[ComponentInfo("led", "led", i, []) for i in range(18)]
        + [ComponentInfo("led", "led_g", i, []) for i in range(9)],
        port_conventions={
            "terasic": {
                "leds": {"name": "LEDR", "width": 18},
                "leds_green": {"name": "LEDG", "width": 9},
                "naming": "canonical",
            }
        },
    )


def _rgb_board() -> BoardDef:
    return BoardDef(
        name="RgbBoard",
        class_name="RgbBoard",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)]
        + [ComponentInfo("led", "rgb_led", i, ["a", "b", "c"]) for i in range(2)],
    )


def _banks(fb: FPGABoard) -> list[tuple[str, int]]:
    return [(label, len(widgets)) for label, widgets in fb._led_banks]


def test_single_bank_labeled_leds(headless_pygame: ModuleType) -> None:
    from fpga_sim.ui import FPGABoard

    scr = headless_pygame.display.set_mode((1024, 700))
    fb = FPGABoard(board_def=_plain_board(), screen=scr, width=1024, height=700)
    assert _banks(fb) == [("LEDs", 4)]


def test_two_color_rows_cluster_with_convention_labels(headless_pygame: ModuleType) -> None:
    from fpga_sim.ui import FPGABoard

    scr = headless_pygame.display.set_mode((1024, 700))
    fb = FPGABoard(board_def=_two_color_board(), screen=scr, width=1024, height=700)
    assert _banks(fb) == [("LEDR", 18), ("LEDG", 9)]
    # widgets are the actual LED objects, sliced in order
    assert fb._led_banks[0][1][0] is fb.leds[0]
    assert fb._led_banks[1][1][0] is fb.leds[18]


def test_rgb_clusters_separately(headless_pygame: ModuleType) -> None:
    from fpga_sim.ui import FPGABoard

    scr = headless_pygame.display.set_mode((1024, 700))
    fb = FPGABoard(board_def=_rgb_board(), screen=scr, width=1024, height=700)
    assert _banks(fb) == [("LEDs", 4), ("RGB", 2)]


def test_bank_labels_anchored_and_banks_stack_vertically(headless_pygame: ModuleType) -> None:
    from fpga_sim.ui import FPGABoard

    scr = headless_pygame.display.set_mode((1280, 800))
    fb = FPGABoard(board_def=_two_color_board(), screen=scr, width=1280, height=800)
    assert [label for label, _x, _y in fb._led_label_pos] == ["LEDR", "LEDG"]
    # LEDG sits on a row block below LEDR, and every LED is the same size
    assert fb._led_banks[1][1][0].rect.top > fb._led_banks[0][1][0].rect.top
    sizes = {led.rect.size for _lbl, ws in fb._led_banks for led in ws}
    assert len(sizes) == 1


def _small_banks_board() -> BoardDef:
    """A mono pair plus three single-color banks (Black Ice-ish)."""
    return BoardDef(
        name="Small",
        class_name="Small",
        leds=[ComponentInfo("led", "led", i, []) for i in range(2)]
        + [ComponentInfo("led", n, 0, []) for n in ("led_r", "led_g", "led_b")],
    )


def test_small_led_banks_share_a_row_when_wide(headless_pygame: ModuleType) -> None:
    from fpga_sim.ui import FPGABoard

    scr = headless_pygame.display.set_mode((1280, 800))
    fb = FPGABoard(board_def=_small_banks_board(), screen=scr, width=1280, height=800)
    row_ys = {y for _lbl, _x, y in fb._led_label_pos}
    assert len(fb._led_banks) == 4  # led, led_r, led_g, led_b
    assert len(row_ys) < 4  # they flow-pack onto fewer rows than banks


def test_switches_wrap_into_balanced_non_overlapping_rows(headless_pygame: ModuleType) -> None:
    from fpga_sim.ui import FPGABoard

    board = BoardDef(
        name="S",
        class_name="S",
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(18)],
    )
    scr = headless_pygame.display.set_mode((760, 700))  # narrow enough to wrap
    fb = FPGABoard(board_def=board, screen=scr, width=760, height=700)
    rows: dict[int, list[object]] = {}
    for sw in fb.switches:
        rows.setdefault(sw.rect.top, []).append(sw)
    counts = [len(v) for v in rows.values()]
    assert len(rows) >= 2  # 18 switches wrapped to multiple rows
    assert max(counts) - min(counts) <= 1  # columns balanced across the rows
    tops = sorted(rows)
    assert tops[1] - tops[0] >= fb.switches[0].rect.height  # rows do not overlap
