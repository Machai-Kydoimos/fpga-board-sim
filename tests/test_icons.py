"""Tests for the themed icon loader (:mod:`fpga_sim.ui.icons`, U44).

The contract that matters is the **fallback**: a decorative asset must never be
load-bearing, so every failure path has to return None rather than raise, and
the caller has to draw something sensible when it does.
"""

from __future__ import annotations

import pytest

from fpga_sim.ui import icons


@pytest.fixture(autouse=True)
def _clear_icon_cache():
    """Each test starts cold — the module caches by (name, size, color)."""
    icons.clear_cache()
    yield
    icons.clear_cache()


# ── The happy path ───────────────────────────────────────────────────────────


def test_latch_icon_renders_at_a_normal_size(headless_pygame):
    surf = icons.latch_icon(24, (20, 60, 20))
    assert surf is not None
    assert surf.get_size() == (24, 24)


def test_icon_is_tinted_to_the_requested_color(headless_pygame):
    """The shipped asset is monochrome + alpha, recolored through the mask."""
    surf = icons.latch_icon(32, (255, 0, 128))
    assert surf is not None
    opaque = [
        surf.get_at((x, y))
        for x in range(surf.get_width())
        for y in range(surf.get_height())
        if surf.get_at((x, y)).a > 250
    ]
    assert opaque, "the padlock should have solid pixels at 32px"
    # BLEND_RGBA_MULT is an 8-bit multiply, so a channel lands within a couple
    # of levels of the target rather than exactly on it (255*254/255 -> 253).
    for px in opaque:
        for got, want in zip((px.r, px.g, px.b), (255, 0, 128), strict=True):
            assert abs(got - want) <= 3, f"{(px.r, px.g, px.b)} is not ~(255, 0, 128)"


def test_the_asset_actually_ships(headless_pygame):
    """Guard the packaging: the PNG must exist next to the module."""
    assert (icons._ASSET_DIR / "locked.png").is_file()


# ── Every failure path returns None ──────────────────────────────────────────


@pytest.mark.parametrize("size", [0, 1, icons.MIN_ICON_PX - 1])
def test_too_small_declines(headless_pygame, size):
    """Below the floor the glyph is a smudge; say so instead of drawing one."""
    assert icons.latch_icon(size, (0, 0, 0)) is None


def test_too_large_declines(headless_pygame):
    assert icons.latch_icon(icons.MAX_ICON_PX + 1, (0, 0, 0)) is None


def test_at_the_floor_exactly_it_renders(headless_pygame):
    assert icons.latch_icon(icons.MIN_ICON_PX, (0, 0, 0)) is not None


def test_missing_asset_returns_none_rather_than_raising(headless_pygame, tmp_path, monkeypatch):
    """A missing or unreadable asset must degrade, never take the board down."""
    monkeypatch.setattr(icons, "_ASSET_DIR", tmp_path)
    icons.clear_cache()
    assert icons.latch_icon(24, (0, 0, 0)) is None


def test_corrupt_asset_returns_none_rather_than_raising(headless_pygame, tmp_path, monkeypatch):
    (tmp_path / "locked.png").write_bytes(b"this is not a PNG")
    monkeypatch.setattr(icons, "_ASSET_DIR", tmp_path)
    icons.clear_cache()
    assert icons.latch_icon(24, (0, 0, 0)) is None


def test_unknown_icon_name_returns_none(headless_pygame):
    assert icons.icon("no-such-icon", 24, (0, 0, 0)) is None


# ── Caching ──────────────────────────────────────────────────────────────────


def test_identical_requests_are_cached(headless_pygame):
    a = icons.latch_icon(20, (1, 2, 3))
    b = icons.latch_icon(20, (1, 2, 3))
    assert a is b


def test_size_and_color_are_part_of_the_key(headless_pygame):
    base = icons.latch_icon(20, (1, 2, 3))
    assert icons.latch_icon(21, (1, 2, 3)) is not base
    assert icons.latch_icon(20, (9, 9, 9)) is not base


def test_clear_cache_forces_a_reload(headless_pygame):
    a = icons.latch_icon(20, (1, 2, 3))
    icons.clear_cache()
    assert icons.latch_icon(20, (1, 2, 3)) is not a
