"""Tests for the SevenSeg UI widget (components.py)."""

import os

import pygame
import pytest


@pytest.fixture(scope="module")
def surface():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    yield pygame.Surface((400, 300))
    from fpga_sim.ui.constants import get_font

    get_font.cache_clear()
    pygame.quit()


def test_zero_glyph_middle_bar_off():
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(0)
    seg.set_bits(0x3F)  # "0": a,b,c,d,e,f on; g off
    assert seg._seg("a") and seg._seg("f")
    assert not seg._seg("g")
    assert not seg._seg("dp")


def test_one_glyph_only_bc():
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(0)
    seg.set_bits(0x06)  # "1": b,c on
    assert seg._seg("b") and seg._seg("c")
    assert not seg._seg("a") and not seg._seg("g")


def test_all_on_includes_dp():
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(0, has_dp=True)
    seg.set_bits(0xFF)
    for name in ("a", "b", "c", "d", "e", "f", "g", "dp"):
        assert seg._seg(name), f"segment '{name}' should be on"


def test_blank_all_off():
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(0)
    seg.set_bits(0x00)
    for name in ("a", "b", "c", "d", "e", "f", "g"):
        assert not seg._seg(name)


@pytest.mark.parametrize("size", [(24, 38), (48, 76), (96, 152), (200, 320)])
def test_draw_various_sizes_no_crash(surface, size):
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(0, has_dp=True)
    seg.rect = pygame.Rect(10, 10, *size)
    seg.set_bits(0x6D)  # "5"
    seg.draw(surface)


def test_draw_no_dp_with_dp_bit_set_no_crash(surface):
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(0, has_dp=False)
    seg.rect = pygame.Rect(10, 10, 48, 76)
    seg.set_bits(0xFF)  # dp bit set but has_dp=False → no circle drawn
    seg.draw(surface)


def test_set_bits_masks_to_8_bits():
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(0)
    seg.set_bits(0x1FF)  # 9-bit value
    assert seg.bits == 0xFF


def test_index_label_is_digit_index():
    from fpga_sim.ui.components import SevenSeg

    seg = SevenSeg(3)
    assert seg.index == 3
