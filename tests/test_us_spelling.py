"""Guard: the tree is written in US English, as CONTRIBUTING requires.

CONTRIBUTING has asked for US spelling since the project started, but nothing
enforced it, so the tree drifted: by the time this guard was written there were
**21 British spellings across 19 files** — nine of them one template's word,
copied into eight generated designs.

Two rules shape the word list, both learned the hard way:

1. **Exact words, never prefixes.** ``analys*`` looks like a tidy pattern and is
   wrong: ``analysis`` and ``analyses`` are correct US English, and the naive
   pattern reports ~19 of them in ``controller.py`` alone. Every entry below is
   a whole word, matched between word boundaries.
2. **Register exceptions as line text, not as files.** Blanket-skipping
   ``CONTRIBUTING.md`` because it quotes ``colour`` as a counterexample would
   have hidden a real ``signalling`` further down the same file — which is
   exactly what happened when this was first surveyed. Only the two
   counterexample lines are exempt, so the rest of the file stays covered.

This is a **suite-level** check rather than a pre-commit hook, per the #348
lesson: hooks fire only on staged files, so a hook and a test catch different
failures. A hook would miss a British spelling that arrives inside a file the
committer never staged — a regenerated design, say.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parent.parent

#: British spellings, as whole words. Case-insensitive at match time, so
#: ``Colour`` and ``COLOUR`` are caught too.
BRITISH_SPELLINGS: tuple[str, ...] = (
    "analyse",
    "analysed",
    "analysing",
    "behaviour",
    "behaviours",
    "cancelled",
    "cancelling",
    "catalogue",
    "centre",
    "centred",
    "centres",
    "colour",
    "coloured",
    "colours",
    "defence",
    "favourite",
    "fibre",
    "flavour",
    "fuelled",
    "grey",
    "greyed",
    "greys",
    "initialise",
    "initialised",
    "initialises",
    "initialising",
    "labelled",
    "labelling",
    "licence",
    "litre",
    "metre",
    "modelled",
    "modelling",
    "neighbour",
    "normalise",
    "normalised",
    "optimise",
    "optimised",
    "optimising",
    "organisation",
    "organise",
    "organised",
    "programme",
    "realise",
    "realised",
    "recognise",
    "recognised",
    "serialise",
    "serialised",
    "signalling",
    "standardise",
    "standardised",
    "theatre",
    "travelled",
    "travelling",
    "utilise",
    "utilised",
    "visualise",
    "visualised",
)

#: Deliberately absent: ``analyses`` and ``analysis`` are correct US English
#: (the plural of "analysis"), and the tree uses ``analyses`` three times that
#: way.  ``dialogue`` is standard in US English too and the UI uses it.

_PATTERN = re.compile(rf"\b({'|'.join(BRITISH_SPELLINGS)})\b", re.IGNORECASE)

#: Whole files outside the rule, with the reason each one is.
_EXEMPT_FILES: dict[str, str] = {
    # A record of what shipped, quoted as it was written; correcting it would
    # rewrite history rather than fix a document anyone reads for style.
    "CHANGELOG.md": "release history is never rewritten",
    # The one file that must contain the words it bans: they are its word list
    # and its fixtures.  Found by CI rather than locally, because `git ls-files`
    # cannot see a new test file until it is committed -- so the first local run
    # of a guard like this is green for a reason that expires at `git add`.
    "tests/test_us_spelling.py": "the guard's own word list and fixtures",
}

#: Directories holding verbatim citation strings matched byte-for-byte against
#: a fetched vendor source.  CONTRIBUTING names this as the *one* deliberate
#: exception to the US-English rule: translating or re-spelling an ``evidence[]``
#: entry would break verify-or-omit.  (Nothing in them trips the pattern today,
#: so this exempts a future citation, not a current miss.)
_EXEMPT_DIRS: tuple[str, ...] = (
    "docs/port_convention_sources/",
    "docs/led_color_sources/",
)

#: Individual lines that may contain a British spelling, registered as literal
#: text so a reworded line loses its exemption and comes back here.
_EXEMPT_LINES: dict[str, tuple[str, ...]] = {
    # The style rule states its own counterexamples.
    "CONTRIBUTING.md": (
        "not `Марсоход 3`). Use `color`, `behavior`, `standardize` — not `colour`,",
        "`behaviour`, `standardise`.",
    ),
}


def _tracked_files() -> list[str]:
    """Every git-tracked path, so a new file is covered the moment it is added."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def findings_in(text: str, path: str) -> list[str]:
    """Report ``path:line: word`` for each British spelling outside an exemption."""
    allowed = _EXEMPT_LINES.get(path, ())
    out: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip() in {a.strip() for a in allowed}:
            continue
        out.extend(f"{path}:{lineno}: {m.group(0)}" for m in _PATTERN.finditer(line))
    return out


def _covered(path: str) -> bool:
    return path not in _EXEMPT_FILES and not path.startswith(_EXEMPT_DIRS)


# --- enforcement -------------------------------------------------------------


def test_tree_is_us_english():
    """The check that runs in CI: no British spelling anywhere it is not exempt."""
    findings: list[str] = []
    for rel in _tracked_files():
        if not _covered(rel):
            continue
        try:
            text = (PROJECT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # binary asset, or a path git tracks but we cannot read
        findings.extend(findings_in(text, rel))
    assert not findings, "British spellings (CONTRIBUTING requires US English):\n" + "\n".join(
        findings
    )


# --- the guard's own teeth ---------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "the colour of the LED",
        "Colour is capitalised here",  # case-insensitive, two hits on one line
        "-- Array initialised to zero",
        "it stays greyed until a file is loaded",
        "sim → launcher signalling",
    ],
)
def test_guard_catches_a_deliberate_regression(line):
    assert findings_in(line, "some/file.py"), f"guard missed: {line}"


@pytest.mark.parametrize(
    "line",
    [
        "the analyses below are retained",  # US plural of "analysis"
        "check_vhdl_contract analyses nothing",  # same word, verb sense
        "before this file is analyzed",
        "a greyhound is not a color",  # word boundaries, not prefixes
        "the centered panel",
        "color, behavior, standardize",
    ],
)
def test_guard_does_not_fire_on_correct_us_english(line):
    assert not findings_in(line, "some/file.py"), f"false positive: {line}"


def test_exempt_line_must_match_exactly():
    """A registered exemption covers that line's text, not the whole file."""
    exempt, *_ = _EXEMPT_LINES["CONTRIBUTING.md"]
    assert not findings_in(exempt, "CONTRIBUTING.md")
    # Reword it and the exemption no longer applies...
    assert findings_in(exempt.replace("Use", "Prefer"), "CONTRIBUTING.md")
    # ...and it never applied to any other file.
    assert findings_in(exempt, "README.md")


def test_the_guard_exempts_itself_for_a_real_reason():
    """The self-exemption is not a hole: this file *must* carry British spellings.

    If the word list and fixtures ever moved out of here, the exemption would
    start hiding real prose instead of the data it was written for.
    """
    own = Path(__file__).read_text(encoding="utf-8")
    assert findings_in(own, "elsewhere.py"), (
        "no British spellings left in this file -- the self-exemption is now a hole"
    )
    assert "tests/test_us_spelling.py" in _EXEMPT_FILES


def test_word_list_is_sorted_and_unique():
    """Keeps the list reviewable and makes a duplicate entry obvious."""
    assert list(BRITISH_SPELLINGS) == sorted(BRITISH_SPELLINGS)
    assert len(set(BRITISH_SPELLINGS)) == len(BRITISH_SPELLINGS)


def test_correct_us_words_are_not_in_the_list():
    """The prefix trap, pinned: these are US English and must never be listed."""
    for word in ("analysis", "analyses", "analyzed", "color", "center", "dialogue"):
        assert word not in BRITISH_SPELLINGS
