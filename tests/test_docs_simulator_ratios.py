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

The classroom docs are held to the same rule for the same reason.  Both were
drafted quoting a ratio measured on one machine -- honest, reproducible, and
*different* from install.md's range, which would have left a reader holding two
irreconcilable numbers with no way to tell which was stale.  They quote absolute
measured rates and a reproduce command instead, and link install.md for the
comparison; this guard is what keeps a later edit from putting a ratio back.
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


#: Documents that may quote a ratio but do not own one.  Unlike the README these
#: are allowed to quote none at all -- both currently do, deliberately -- so the
#: assertion is one-sided: whatever they say must already be in install.md.
_DEPENDENT_DOCS = ("docs/first_design.md", "docs/troubleshooting.md")


@pytest.mark.parametrize("rel", _DEPENDENT_DOCS)
def test_a_classroom_doc_quotes_no_ratio_install_md_does_not(
    rel: str, install_ratios: set[str]
) -> None:
    drifted = _ratios(REPO_ROOT / rel) - install_ratios
    assert not drifted, (
        f"{rel} quotes {sorted(drifted)}, which docs/install.md does not. "
        "install.md owns these numbers: cite a measured absolute rate with the "
        "command that reproduces it, or link the table -- do not restate a ratio."
    )
