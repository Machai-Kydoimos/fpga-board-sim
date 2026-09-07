"""Guard: the simulator speed ratios agree wherever they are printed.

``docs/install.md`` has always owned the "choosing a simulator" table.  The
README now repeats the ratios, because that is where somebody actually decides
what to install -- install.md is read once, before any of it means anything --
and a number duplicated is a number that drifts.  The board-count guard next
door exists because eight copies of one count aged silently for four weeks;
this is the same failure waiting to happen with four copies of a ratio.

So the README's figures must be a **subset** of install.md's.  Subset, not
equality: install.md is free to carry more detail (startup cost, the
arithmetic-heavy caveat, the from-source rows) and the README deliberately
carries less.  What it may not do is carry a *different* number.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fpga_sim.paths import REPO_ROOT

#: A ratio as either file writes it: "1x", "~3.5-6x", "~1.2-1.4x".  The en dash
#: is what the docs actually use; a plain hyphen is accepted so a future edit
#: typed on a normal keyboard is compared rather than silently skipped.
_RATIO = re.compile(r"~?\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?\s*x\b")


def _ratios(path: Path) -> set[str]:
    """Every speed ratio in *path*, normalized so formatting is not the subject."""
    text = path.read_text(encoding="utf-8")
    return {
        m.group(0).replace("–", "-").replace(" ", "").lstrip("~") for m in _RATIO.finditer(text)
    }


@pytest.fixture(scope="module")
def install_ratios() -> set[str]:
    return _ratios(REPO_ROOT / "docs" / "install.md")


def test_install_md_still_states_the_ratios() -> None:
    """If the source table is reworded away, this guard must fail loudly.

    A guard that silently passes because it found nothing to compare is worse
    than no guard, so the anchor is asserted rather than assumed.
    """
    assert _ratios(REPO_ROOT / "docs" / "install.md") >= {"3.5-6x", "1.2-1.4x", "2.3-4.3x"}


def test_the_readme_quotes_no_ratio_install_md_does_not(install_ratios: set[str]) -> None:
    readme = _ratios(REPO_ROOT / "README.md")
    assert readme, "the README's quick start is supposed to carry the ratios"
    drifted = readme - install_ratios
    assert not drifted, (
        f"README.md quotes {sorted(drifted)}, which docs/install.md does not. "
        "install.md owns these numbers; update it first, or fix the README."
    )
