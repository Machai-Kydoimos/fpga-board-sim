"""Tests for generate_board_images CLI: theme parsing, listing, and output routing.

The generation runs invoke the module in a subprocess (`python -m`) rather
than calling ``main()`` in-process, because ``main()`` ends with
``pygame.quit()`` — running that inside the pytest process would strand the
session-scoped ``headless_pygame`` fixture's ``get_font`` cache (see
tests/conftest.py).
"""

from __future__ import annotations

import subprocess
import sys
from argparse import ArgumentTypeError

import pytest

from fpga_sim.generate_board_images import _parse_themes, print_theme_list
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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


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
