"""Guard: the board counts printed in user-facing docs match the real fleet.

Adding one board (the DE4, #345) silently aged **eight** separate numbers across
three files, and nobody noticed for four weeks. Prose has no compiler; this test
is the compiler.

Two layers, because they fail on different mistakes:

1. **Registered claims** — each sentence that quotes a count is registered here
   as a literal snippet with the count templated in. A wrong number breaks the
   lookup, and so does a *reworded* sentence: that is deliberate, so whoever
   rewrites the prose has to come here and re-register the claim rather than
   quietly dropping it out from under the guard.
2. **A sweep** of the same files for any three-digit board count that disagrees
   with the fleet, which catches a *new* claim someone adds without registering
   it. Three digits, so "the 9 Intel boards" (a filtered subset, not the fleet)
   is not swept up with it.

Only files that describe the product **as it is today** are covered. CHANGELOG
entries, ``roadmap_delivered.md``, and completed plan documents quote the counts
that were true when they were written and must never be "corrected".
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fpga_sim.board_loader import discover_boards, get_default_boards_path

_REPO_ROOT = Path(__file__).resolve().parent.parent

#: Docs that must describe the fleet as it stands right now.
_LIVE_DOCS = ("README.md", "docs/user_guide.md", "docs/writing_designs.md")

#: Sentences quoting the fleet size, as literal snippets with the count
#: templated in.  ``{boards}`` = total fleet, ``{conv}`` = boards carrying a
#: ``port_conventions`` block.
_CLAIMS: tuple[tuple[str, str], ...] = (
    ("README.md", "**{boards} real FPGA board"),
    ("README.md", "one of **{boards} boards**"),
    ("README.md", "**{boards} real FPGA boards**"),
    ("README.md", "narrow the {boards}-board list"),
    ("README.md", "**{conv} of the {boards} boards**"),
    ("docs/user_guide.md", "A list of {boards} FPGA boards"),
    ("docs/user_guide.md", "only 6 of {boards} have more than 10"),
    ("docs/writing_designs.md", "**{conv} of the {boards} boards**"),
)

#: A three-digit count immediately qualifying "board(s)" -- "285 boards",
#: "285 real FPGA boards", "285-board list".  In "266 of the 285 boards" only
#: 285 matches, which is right: 266 is a different quantity.
_SWEEP = re.compile(r"\b(\d{3})[- ](?:real )?(?:FPGA )?boards?\b")


@pytest.fixture(scope="module")
def fleet() -> dict[str, int]:
    boards = discover_boards(get_default_boards_path())
    return {
        "boards": len(boards),
        "conv": sum(1 for b in boards if b.port_conventions),
    }


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize(("rel", "template"), _CLAIMS, ids=lambda v: v.replace(" ", "_"))
def test_registered_claim_quotes_the_live_count(rel, template, fleet):
    """Each registered sentence must appear with today's numbers in it."""
    wanted = template.format(**fleet)
    if wanted in _read(rel):
        return
    # Say *why* it is missing: a stale number reads very differently from a
    # rewritten sentence, and the fixes are different.
    loose = re.escape(template).replace(r"\{boards\}", r"\d+").replace(r"\{conv\}", r"\d+")
    found = re.search(loose, _read(rel))
    if found:
        pytest.fail(
            f"{rel} still says {found.group(0)!r}; the fleet is now "
            f"{fleet['boards']} boards, {fleet['conv']} with conventions. "
            f"Expected {wanted!r}."
        )
    pytest.fail(
        f"{rel} no longer contains the registered claim {template!r}. If the "
        f"sentence was reworded, re-register it in _CLAIMS; if the claim was "
        f"removed on purpose, delete its entry."
    )


@pytest.mark.parametrize("rel", _LIVE_DOCS)
def test_no_unregistered_board_count_has_gone_stale(rel, fleet):
    """Sweep for a board count nobody registered -- the way #345 got away."""
    stale = sorted({int(n) for n in _SWEEP.findall(_read(rel))} - {fleet["boards"]})
    assert not stale, (
        f"{rel} quotes board count(s) {stale}, but the fleet is "
        f"{fleet['boards']}. Fix the number, and register the sentence in "
        f"_CLAIMS so it cannot drift again."
    )


def test_the_conventions_count_is_a_strict_subset(fleet):
    """Sanity-check the derivation itself, not just the prose."""
    assert 0 < fleet["conv"] <= fleet["boards"]
