"""The cached text renderer: correctness, sharing, and keeping the win.

Every board widget used to re-render its label from the font on *every frame*,
for a string that never changes -- 28 renders per frame on a DE10-Lite, 45 on a
Sword, at ~2.0 us each against ~0.24 us to blit a cached surface. Caching them
made the whole board draw 9.4% / 14.7% faster.

The risk a cache introduces is not speed but **sharing**: one Surface handed to
many callers. So these tests check the two things that could go wrong -- that a
cached render is byte-for-byte what an uncached one would have been, and that
nothing in the draw path mutates the surface it was handed.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pygame
import pytest

from fpga_sim.ui.constants import WHITE, get_font, render_text

_COMPONENTS = Path(__file__).resolve().parent.parent / "src" / "fpga_sim" / "ui" / "components.py"


def _pixels(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGBA")


# ── Correctness ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("text", ["LED0", "SW15", "BTNC", "7", "A"])
def test_cached_render_matches_an_uncached_one(headless_pygame, text):
    """A cached label is byte-for-byte what ``font.render`` would have produced."""
    font = get_font(14)
    assert _pixels(render_text(font, text, WHITE)) == _pixels(font.render(text, True, WHITE))


def test_repeated_calls_return_the_same_surface(headless_pygame):
    """The point of the cache: no second render, not merely an equal result."""
    font = get_font(14)
    assert render_text(font, "LED0", WHITE) is render_text(font, "LED0", WHITE)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (("LED0", WHITE, 14), ("LED1", WHITE, 14)),  # text
        (("LED0", WHITE, 14), ("LED0", (90, 90, 90), 14)),  # color -- e.g. a theme switch
        (("LED0", WHITE, 14), ("LED0", WHITE, 22)),  # font size
    ],
)
def test_every_part_of_the_key_is_distinguishing(headless_pygame, a, b):
    """Nothing may collide: a wrong hit would draw the wrong label, silently."""
    ta, ca, sa = a
    tb, cb, sb = b
    assert render_text(get_font(sa), ta, ca) is not render_text(get_font(sb), tb, cb)


def test_a_theme_color_change_re_renders(headless_pygame, restore_theme):
    """U6: colors are read at draw time, so a theme switch must not serve stale ink."""
    from fpga_sim.ui.theme import THEME, set_theme

    font = get_font(12)
    before_color = THEME.seg_digit_label
    before = render_text(font, "3", before_color)
    set_theme("high-contrast")
    after = render_text(font, "3", THEME.seg_digit_label)
    if THEME.seg_digit_label != before_color:
        assert after is not before
        assert _pixels(after) != _pixels(before)


# ── Sharing: the risk the cache introduces ───────────────────────────────────


_Key = tuple[pygame.font.Font, str, tuple[int, int, int]]


def _keys_used_by(draw: Callable[[], None], monkeypatch: pytest.MonkeyPatch) -> list[_Key]:
    """Record every ``(font, text, color)`` the real draw path asks for.

    Guessing the font size was how the first version of this test fooled itself:
    it probed ``get_font(12)`` while the board draws its labels at 13, so it
    inspected an entry no draw had ever touched and a deliberately corrupting
    mutation sailed straight through. Ask the code instead of predicting it.
    """
    seen: list[_Key] = []

    def spy(font: pygame.font.Font, text: str, color: tuple[int, int, int]) -> pygame.Surface:
        seen.append((font, text, color))
        return render_text(font, text, color)

    # Patched by dotted path: components imports the name, so the module object
    # has no declared attribute for it.
    monkeypatch.setattr("fpga_sim.ui.components.render_text", spy)
    draw()
    monkeypatch.undo()
    return list(dict.fromkeys(seen))


def test_drawing_a_board_does_not_mutate_the_cached_label(headless_pygame, monkeypatch):
    """The shared-surface contract, checked against the real draw path.

    A widget that filled its label surface, or set an alpha or colorkey on it,
    would change what every other widget drawing the same string sees. Nothing
    does today -- this fails the moment something starts.
    """
    from fpga_sim.board_loader import discover_boards, get_default_boards_path
    from fpga_sim.ui import FPGABoard

    bd = next(
        b for b in discover_boards(get_default_boards_path()) if b.class_name == "DE10LitePlatform"
    )
    board = FPGABoard(board_def=bd, width=1024, height=700)

    keys = _keys_used_by(board._draw, monkeypatch)
    assert len(keys) >= 28, f"expected every widget label, saw {len(keys)}"

    # Snapshot *pristine* entries: clear the cache and render each key ourselves
    # before any draw can touch them. Snapshotting after a draw would bake an
    # existing mutation into the baseline and compare the damage with itself.
    render_text.cache_clear()
    pristine = []
    for key in keys:
        surf = render_text(*key)
        pristine.append((key, surf, _pixels(surf), (surf.get_alpha(), surf.get_colorkey())))

    for _ in range(3):
        board._draw()

    for key, surface, pixels, flags in pristine:
        assert render_text(*key) is surface, f"the draw path stopped hitting the cache for {key[1]}"
        assert _pixels(surface) == pixels, f"a draw mutated the shared surface for {key[1]!r}"
        assert (surface.get_alpha(), surface.get_colorkey()) == flags, (
            f"a draw set an alpha or colorkey on the shared surface for {key[1]!r}"
        )


# ── Keeping the win ──────────────────────────────────────────────────────────


def test_no_uncached_text_render_creeps_back_in():
    """Registered exceptions, so a new per-frame ``render`` has to justify itself.

    Every remaining direct ``.render(`` in ``components.py`` is here on purpose;
    a sixth one means somebody re-introduced per-frame text rendering on the
    draw path, which is exactly the cost this cache removed.
    """
    exempt = {
        # Dynamic text -- the measured duty, which changes every frame. Caching
        # it would fill the cache with values never seen again.
        'digits = _get_font(digits_fs).render(f"{duty * 100:.0f}", True, WHITE)',
        'sign = _get_font(sign_fs).render("%", True, WHITE)',
        'txt = _get_font(font_size).render(f"{duty * 100:.0f}%", True, WHITE)',
        # Fit searches, already behind their own caches and run only on resize.
        "<= (t := _get_font(fs).render(sample, True, WHITE).get_bounding_rect()).height",
        't := _get_font(fs, bold=True).render("0", True, WHITE).get_bounding_rect()',
    }
    found = {
        line.strip()
        for line in _COMPONENTS.read_text(encoding="utf-8").splitlines()
        if re.search(r"\.render\(", line)
    }
    assert found == exempt, (
        "text rendering on the draw path changed; route it through render_text() "
        f"or register it here.\nunexpected: {found - exempt}\nmissing: {exempt - found}"
    )
