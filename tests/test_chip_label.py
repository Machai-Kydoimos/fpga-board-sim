"""The chip's label stays inside the chip (U56 Phase 1c).

Phase 1c taught the parsers to print each chip's full part number, and 19 of
them -- ``XCZU11EG-FFVF1517-2-I``, ``LFE5UM5G-85F-8BG381C`` -- were wider than
the chip at the default window, so the label ran past its edges.  The label is
now laid out in one place, ``FPGAChip.fit_label``, which both renderers use: a
line too wide for the chip breaks onto two at its own punctuation, and the font
shrinks only when breaking is not enough.

Glyph widths differ by platform (CI has no Consolas), so nothing here assumes
one: the pure tests measure ten pixels a character, and the real-font tests size
each chip from the text it has to hold.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from fpga_sim.ui.components import FPGAChip, wrap_label

if TYPE_CHECKING:
    from types import ModuleType

    import pygame


def _ten_px(text: str) -> int:
    return 10 * len(text)


# ── wrap_label: where a line breaks ──────────────────────────────────────────


def test_text_that_fits_stays_whole() -> None:
    assert wrap_label("XC7A35T", _ten_px, 70) == ["XC7A35T"]


def test_a_part_number_breaks_after_a_dash_which_ends_the_first_line() -> None:
    assert wrap_label("XCZU11EG-FFVF1517-2-I", _ten_px, 130) == ["XCZU11EG-", "FFVF1517-2-I"]


def test_the_break_that_balances_the_two_lines_wins() -> None:
    # Breaks after either dash fit in 140 px; the first leaves the wider line at
    # 11 characters, the second at 13.
    assert wrap_label("LFE5UM5G-85F-8BG381C", _ten_px, 140) == ["LFE5UM5G-", "85F-8BG381C"]
    assert wrap_label("LFE5U-45F-6BG381C", _ten_px, 110) == ["LFE5U-45F-", "6BG381C"]


def test_a_slash_is_a_break_point_too() -> None:
    assert wrap_label("GW2A-LV18PG256C8/I7", _ten_px, 140) == ["GW2A-", "LV18PG256C8/I7"]
    assert wrap_label("ABCDEFGH/IJKLMNOP", _ten_px, 90) == ["ABCDEFGH/", "IJKLMNOP"]


def test_a_space_is_dropped_at_the_break() -> None:
    assert wrap_label("Cologne Chip", _ten_px, 80) == ["Cologne", "Chip"]


def test_a_tie_goes_to_the_longer_first_line() -> None:
    # "AA-" / "BB CC" and "AA-BB" / "CC" both leave a 50 px widest line.
    assert wrap_label("AA-BB CC", _ten_px, 50) == ["AA-BB", "CC"]


def test_none_when_no_single_break_lets_both_lines_fit() -> None:
    assert wrap_label("XC7A100TCSG324", _ten_px, 100) is None, "no break point at all"
    assert wrap_label("XC7A100TCSG324-1", _ten_px, 100) is None, "the only break leaves 150 px"
    assert wrap_label("ABCDEFGHIJ-", _ten_px, 50) is None, "never an empty second line"


# ── FPGAChip.fit_label: one layout, real fonts ───────────────────────────────

_PAD_X = FPGAChip._LABEL_PAD_X
_PAD_Y = FPGAChip._LABEL_PAD_Y


def _chip(device: str, width: int, height: int) -> FPGAChip:
    import pygame

    chip = FPGAChip(vendor="Xilinx", device=device, clock_hz=100e6)
    chip.rect = pygame.Rect(0, 0, width, height)
    return chip


def _font(size: int) -> pygame.font.Font:
    from fpga_sim.ui.constants import get_font

    return get_font(size, bold=True)


def test_a_label_that_fits_is_drawn_as_it_always_was(headless_pygame: ModuleType) -> None:
    chip = _chip("XC7A35T", 400, 200)
    assert chip.fit_label(16) == (16, tuple(chip.label_lines()), True)


def test_a_part_number_too_wide_for_the_chip_breaks_onto_two_lines(
    headless_pygame: ModuleType,
) -> None:
    device = "XCZU11EG-FFVF1517-2-I"
    font = _font(16)
    halves = max(font.size("XCZU11EG-")[0], font.size("FFVF1517-2-I")[0])
    assert halves < font.size(device)[0]
    chip = _chip(device, halves + 2 * _PAD_X, 200)
    label = chip.fit_label(16)
    assert label.size == 16, "breaking was enough, so the font keeps its size"
    assert label.lines == (
        ("vendor", "Xilinx"),
        ("device", "XCZU11EG-"),
        ("device", "FFVF1517-2-I"),
        ("clock", "100 MHz"),
    )
    assert label.fits


def test_the_font_shrinks_only_when_breaking_is_not_enough(headless_pygame: ModuleType) -> None:
    device = "XC7A100TCSG324"  # nowhere to break
    chip = _chip(device, _font(16).size(device)[0] - 1 + 2 * _PAD_X, 200)
    label = chip.fit_label(16)
    assert label.size < 16
    assert ("device", device) in label.lines, "shrunk, not broken"
    assert _font(label.size).size(device)[0] <= chip.rect.width - 2 * _PAD_X
    assert label.fits


def test_a_chip_too_short_for_its_lines_shrinks_the_font(headless_pygame: ModuleType) -> None:
    chip = _chip("XC7A35T", 400, 0)
    chip.rect.height = 3 * _font(16).get_linesize() - 1 + 2 * _PAD_Y  # 3 lines need more
    label = chip.fit_label(16)
    assert label.size < 16
    assert len(label.lines) * _font(label.size).get_linesize() <= chip.rect.height - 2 * _PAD_Y
    assert label.fits


def test_a_chip_too_small_for_any_size_says_so(headless_pygame: ModuleType) -> None:
    label = _chip("XCZU11EG-FFVF1517-2-I", 30, 20).fit_label(16)
    assert label.size == FPGAChip._LABEL_MIN_SIZE
    assert not label.fits, "draw() clips it to the chip"


def test_the_fit_is_measured_once_per_chip_size(headless_pygame: ModuleType) -> None:
    chip = _chip("XCZU11EG-FFVF1517-2-I", 180, 110)
    first = chip.fit_label(16)
    assert chip.fit_label(16) is first
    chip.rect.width = 400
    assert chip.fit_label(16) is not first
    assert chip.fit_label(16).lines[1] == ("device", "XCZU11EG-FFVF1517-2-I")


# ── What is actually drawn ───────────────────────────────────────────────────


@pytest.mark.parametrize("height", [200, 24], ids=["breaks", "clipped"])
def test_nothing_is_drawn_outside_the_chip(headless_pygame: ModuleType, height: int) -> None:
    """Pixels, not the layout's word for it: only the chip and its pin marks are painted."""
    import pygame

    device = "XCZU11EG-FFVF1517-2-I"
    sentinel = (1, 2, 3)
    surface = pygame.Surface((600, 320))
    surface.fill(sentinel)
    chip = _chip(device, int(_font(16).size(device)[0] * 0.7), height)
    chip.rect.center = surface.get_rect().center
    chip.draw(surface, 16)

    reach = FPGAChip._PIN_LENGTH + 1
    surface.fill(sentinel, chip.rect.inflate(2 * reach, 2 * reach))
    untouched = pygame.mask.from_threshold(surface, sentinel, (1, 1, 1, 255))
    assert untouched.count() == surface.get_width() * surface.get_height()


# ── The fleet ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("size", [(1024, 700), (800, 560)])
def test_every_board_label_fits_its_chip(
    headless_pygame: ModuleType, size: tuple[int, int]
) -> None:
    """At the default window and a smaller one, no board's label needs clipping."""
    from fpga_sim.board_loader import discover_boards, get_default_boards_path
    from fpga_sim.ui import FPGABoard
    from fpga_sim.ui.constants import _ui_scale

    w, h = size
    chip_size = max(13, max(10, round(13 * _ui_scale(w, h))) + 3)  # as FPGABoard._draw
    broken = []
    for board in discover_boards(get_default_boards_path()):
        chip = FPGABoard(board_def=board, width=w, height=h).fpga_chip
        label = chip.fit_label(chip_size)
        assert label.fits, board.qualified_name
        if len(label.lines) > len(chip.label_lines()):
            broken.append(board.qualified_name)
    assert broken, "the fleet has part numbers wider than their chips; none broke"
