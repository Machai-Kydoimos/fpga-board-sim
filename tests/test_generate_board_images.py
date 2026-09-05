"""Tests for generate_board_images CLI: theme parsing, listing, and output routing.

The generation runs invoke the module in a subprocess (`python -m`) rather
than calling ``main()`` in-process, because ``main()`` ends with
``pygame.quit()`` — running that inside the pytest process would strand the
session-scoped ``headless_pygame`` fixture's ``get_font`` cache (see
tests/conftest.py).
"""

from __future__ import annotations

import re
import subprocess
import sys
from argparse import ArgumentTypeError
from typing import TYPE_CHECKING

import pygame
import pytest

if TYPE_CHECKING:
    from types import ModuleType

    from fpga_sim.ui import FPGABoard

from fpga_sim.generate_board_images import _parse_themes, _svg_color, print_theme_list
from fpga_sim.ui.theme import THEME_LABELS, THEME_NAMES

# ── _parse_themes ─────────────────────────────────────────────────────────────


class TestParseThemes:
    def test_single_theme(self):
        assert _parse_themes("dark") == ["dark"]

    def test_comma_list_preserves_order(self):
        assert _parse_themes("high-contrast,dark") == ["high-contrast", "dark"]

    def test_all_expands_to_every_theme(self):
        assert _parse_themes("all") == list(THEME_NAMES)

    def test_all_wins_within_a_list(self):
        assert _parse_themes("dark,all") == list(THEME_NAMES)

    def test_case_insensitive_and_whitespace_tolerant(self):
        assert _parse_themes(" Dark , PCB-GREEN ") == ["dark", "pcb-green"]

    def test_duplicates_collapse(self):
        assert _parse_themes("dark,dark") == ["dark"]

    def test_unknown_theme_rejected_with_choices_listed(self):
        with pytest.raises(ArgumentTypeError, match="no-such-theme"):
            _parse_themes("no-such-theme")
        with pytest.raises(ArgumentTypeError, match="pcb-green"):
            _parse_themes("no-such-theme")

    def test_empty_rejected(self):
        # "".split(",") yields [""], so empty input reports an unknown theme —
        # the same shape _parse_formats has; either way it must not pass.
        with pytest.raises(ArgumentTypeError):
            _parse_themes("")
        with pytest.raises(ArgumentTypeError):
            _parse_themes(" , ")


# ── --list-themes ─────────────────────────────────────────────────────────────


def test_print_theme_list_names_labels_and_default(capsys):
    print_theme_list()
    out = capsys.readouterr().out
    for name in THEME_NAMES:
        assert name in out
        assert THEME_LABELS[name] in out
    assert out.count("(default)") == 1
    assert f"{THEME_NAMES[0]}" in out.splitlines()[1]  # default theme listed first


# ── End-to-end output routing (subprocess) ────────────────────────────────────


def _run_generator(*extra_args: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, "-m", "fpga_sim.generate_board_images", *extra_args]
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace"
    )


def test_list_themes_exits_cleanly():
    r = _run_generator("--list-themes")
    assert r.returncode == 0, r.stderr
    for name in THEME_NAMES:
        assert name in r.stdout


def test_single_theme_output_stays_flat(tmp_path):
    out = tmp_path / "out"
    r = _run_generator(
        "--filter", "icestick", "--formats", "png", "--theme", "dark", "--output-dir", str(out)
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Rendering theme 'dark'" in r.stdout
    assert list(out.glob("*.png")), "expected PNGs directly in --output-dir"
    assert not (out / "dark").exists(), "single-theme run must not create a subdirectory"


def test_multi_theme_output_uses_per_theme_subdirs(tmp_path):
    out = tmp_path / "out"
    r = _run_generator(
        "--filter", "icestick", "--formats", "png", "--theme", "all", "--output-dir", str(out)
    )
    assert r.returncode == 0, r.stdout + r.stderr
    for name in THEME_NAMES:
        pngs = list((out / name).glob("*.png"))
        assert pngs, f"expected PNGs under {name}/ subdirectory"
    assert not list(out.glob("*.png")), "multi-theme run must not write to the root"
    # Every theme dir holds the same basenames, and themes render distinct
    # pixels: the same board must not be byte-identical across themes.
    per_theme = {n: sorted(p.name for p in (out / n).glob("*.png")) for n in THEME_NAMES}
    assert len(set(map(tuple, per_theme.values()))) == 1, "basenames must match across themes"
    first = per_theme[THEME_NAMES[0]][0]
    a = (out / THEME_NAMES[0] / first).read_bytes()
    b = (out / "high-contrast" / first).read_bytes()
    assert a != b


# ── SVG honors LED / segment levels ──────────────────────────────────────────
#
# The SVG path is a *second* renderer of the same widgets, and it used to
# hardcode THEME.led_off / THEME.seg_off. That was not merely "unable to show a
# lit board": it disagreed with the PNG of the same board for all 42 boards
# carrying a named LED color (U36), because a colored LED's dark epoxy is tinted
# 12% toward its own hue rather than left at the plain theme off-color.
#
# The fix routes both renderers through one accessor, so the assertion that
# matters is not "the SVG is some particular color" but "the SVG agrees with the
# raster" -- which is what these tests check, at several levels.


def _rgb(pixel: pygame.Color) -> tuple[int, int, int]:
    """The RGB triple of a sampled pixel, dropping alpha for ``_svg_color``."""
    return (pixel[0], pixel[1], pixel[2])


def _svg_led_body(svg: str, cx: int, cy: int) -> str:
    """The fill of the LED body at (cx, cy): the *last* circle drawn there.

    The optional glow circle shares the center and is emitted first, so document
    order distinguishes them -- and that ordering is itself load-bearing (SVG
    paints in document order, so a glow emitted last would cover the LED).
    """
    found: list[str] = re.findall(
        rf'<circle cx="{cx}" cy="{cy}" r="\d+" fill="(#[0-9a-f]{{6}})"', svg
    )
    assert found, f"no circle at ({cx}, {cy})"
    return found[-1]


def _board(headless_pygame: ModuleType, class_name: str) -> FPGABoard:
    from fpga_sim.board_loader import discover_boards, get_default_boards_path
    from fpga_sim.ui import FPGABoard

    bd = next(b for b in discover_boards(get_default_boards_path()) if b.class_name == class_name)
    return FPGABoard(board_def=bd, width=1024, height=700)


@pytest.mark.parametrize("level", [0.0, 0.05, 0.35, 1.0])
def test_svg_led_fill_matches_the_raster(headless_pygame, level):
    """The anti-drift assertion: same widget, same color, whichever renderer."""
    from fpga_sim.generate_board_images import build_svg, render_board_raster

    board = _board(headless_pygame, "DE10LitePlatform")
    board.set_led_level(0, level)
    raster = render_board_raster(board)
    svg = build_svg(board, 1024, 700)

    cx, cy = board.leds[0].rect.center
    expected = _svg_color(_rgb(raster.get_at((cx, cy))))
    assert _svg_led_body(svg, cx, cy) == expected


def test_svg_colored_led_at_rest_is_tinted_not_the_plain_off_color(headless_pygame):
    """The bug that was actually shipping: an all-off colored board disagreed."""
    from fpga_sim.generate_board_images import build_svg
    from fpga_sim.ui.theme import THEME

    board = _board(headless_pygame, "DE10LitePlatform")
    assert board.leds[0]._on_color is not None, "DE10-Lite LEDR is a colored bank (U36)"
    assert all(led.level == 0.0 for led in board.leds), "reset state"

    cx, cy = board.leds[0].rect.center
    body = _svg_led_body(build_svg(board, 1024, 700), cx, cy)
    assert body != _svg_color(THEME.led_off), "the old hardcoded value was wrong here"
    assert body == _svg_color(board.leds[0].display_colors()[0])


def test_svg_uncolored_led_at_rest_is_still_the_theme_off_color(headless_pygame):
    """...while a board without LED colors keeps byte-identical output."""
    from fpga_sim.generate_board_images import build_svg
    from fpga_sim.ui.theme import THEME

    board = _board(headless_pygame, "Genesys2Platform")
    assert board.leds[0]._on_color is None
    cx, cy = board.leds[0].rect.center
    assert _svg_led_body(build_svg(board, 1024, 700), cx, cy) == _svg_color(THEME.led_off)


def test_svg_emits_no_glow_when_every_led_is_dark(headless_pygame):
    """Reset boards must not grow halo elements -- that is what keeps them unchanged."""
    from fpga_sim.generate_board_images import build_svg

    board = _board(headless_pygame, "DE10LitePlatform")
    assert "fill-opacity" not in build_svg(board, 1024, 700)


@pytest.mark.parametrize("level", [1.0, 0.3, 0.05])
def test_svg_glow_appears_when_lit_and_is_drawn_under_the_led(headless_pygame, level):
    """Halo geometry must come from the shared policy, not be restated here.

    Parametrized over brightness because the radius is no longer a constant
    multiple of the body: a dim LED's halo shrinks, and this renderer has to
    shrink with it.  Asserting against ``glow_radius`` rather than against
    ``2 * body_r`` is what makes this a parity check instead of a second copy
    of the formula -- the drift that made the two renderers disagree about
    ``THEME.led_off`` before #396.
    """
    from fpga_sim.generate_board_images import build_svg
    from fpga_sim.ui.components import glow_radius

    board = _board(headless_pygame, "DE10LitePlatform")
    board.set_led_level(0, level)
    svg = build_svg(board, 1024, 700)
    cx, cy = board.leds[0].rect.center
    assert svg.count("fill-opacity") == 1, "one halo, for the one lit LED"
    circles = re.findall(rf'<circle cx="{cx}" cy="{cy}" r="(\d+)"([^/]*)/>', svg)
    assert len(circles) == 2
    glow_r, glow_attrs = circles[0]
    body_r, _ = circles[1]
    assert "fill-opacity" in glow_attrs, "the halo must come first, or it covers the LED"
    _, _, k = board.leds[0].display_colors()
    assert int(glow_r) == glow_radius(int(body_r), k), "halo radius matches LED.draw()"


def test_svg_rgb_puck_mixes_its_channels(headless_pygame):
    """An RGB site is an LED too: its SVG fill is the mixed color, not led_off."""
    from fpga_sim.generate_board_images import build_svg, render_board_raster
    from fpga_sim.ui.components import RGBLED

    board = _board(headless_pygame, "ArtyA7_35Platform")
    puck = next(led for led in board.leds if isinstance(led, RGBLED))
    puck.set_channel("g", 1.0)
    raster = render_board_raster(board)
    cx, cy = puck.rect.center
    expected = _svg_color(_rgb(raster.get_at((cx, cy))))
    assert _svg_led_body(build_svg(board, 1024, 700), cx, cy) == expected


def test_svg_rgb_puck_at_rest_is_unchanged(headless_pygame):
    """max(led_off, 0) is led_off, so a dark puck renders exactly as it used to."""
    from fpga_sim.generate_board_images import build_svg
    from fpga_sim.ui.components import RGBLED
    from fpga_sim.ui.theme import THEME

    board = _board(headless_pygame, "ArtyA7_35Platform")
    puck = next(led for led in board.leds if isinstance(led, RGBLED))
    cx, cy = puck.rect.center
    assert _svg_led_body(build_svg(board, 1024, 700), cx, cy) == _svg_color(THEME.led_off)


def test_svg_segments_follow_their_levels(headless_pygame):
    """Segments are LEDs -- same ramp, same agreement with the widget."""
    from fpga_sim.generate_board_images import build_svg
    from fpga_sim.ui.theme import THEME

    board = _board(headless_pygame, "DE10LitePlatform")
    digit = board._seven_segs[0]
    digit.set_levels([1.0, 0.4] + [0.0] * 6)
    svg = build_svg(board, 1024, 700)
    fills = re.findall(r'<polygon points="[^"]+" fill="(#[0-9a-f]{6})"', svg)

    assert _svg_color(THEME.seg_on) in fills, "segment a is fully lit"
    assert _svg_color(digit.segment_color("b")) in fills, "segment b at 0.4"
    assert _svg_color(THEME.seg_off) in fills, "the unlit segments stay dark"


def test_svg_segments_at_rest_are_all_the_off_color(headless_pygame):
    from fpga_sim.generate_board_images import build_svg
    from fpga_sim.ui.theme import THEME

    board = _board(headless_pygame, "DE10LitePlatform")
    svg = build_svg(board, 1024, 700)
    fills = set(re.findall(r'<polygon points="[^"]+" fill="(#[0-9a-f]{6})"', svg))
    assert fills == {_svg_color(THEME.seg_off)}
