"""Guard: no live doc or script hands ``gh auth token`` to a board sync.

A sync *executes* upstream Python -- the LiteX and Amaranth board files, under a
mock -- so any credential in its environment is reachable from code nobody here
reviewed. ``gh auth token`` prints the contributor's own GitHub token, which
carries the ``repo`` and ``workflow`` scopes. The recipes in ``CONTRIBUTING.md``
said exactly ``GITHUB_TOKEN=$(gh auth token)`` until U56 replaced them with a
token that has no scopes (its plan, section 4.4); this keeps a copy-paste from
bringing them back.

Plan documents and the history files quote the old recipe as a record, so they
are not swept.
"""

from __future__ import annotations

from pathlib import Path

from fpga_sim.paths import REPO_ROOT

#: Records of what was true when written; they must never be "corrected".
_HISTORY = {"CHANGELOG.md", "roadmap_delivered.md"}


def _live_files() -> list[Path]:
    candidates = [
        *REPO_ROOT.glob("*.md"),
        *(REPO_ROOT / "docs").rglob("*.md"),
        *(REPO_ROOT / "scripts").rglob("*.py"),
    ]
    return sorted(
        path
        for path in candidates
        if path.name not in _HISTORY and "plans" not in path.relative_to(REPO_ROOT).parts
    )


def test_the_sweep_covers_the_files_that_had_the_recipe() -> None:
    names = {path.relative_to(REPO_ROOT).as_posix() for path in _live_files()}
    assert "CONTRIBUTING.md" in names
    assert "scripts/check_board_drift.py" in names


def test_no_live_doc_or_script_passes_the_gh_token_to_a_sync() -> None:
    offenders = [
        f"{path.relative_to(REPO_ROOT).as_posix()}:{number}"
        for path in _live_files()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "$(gh auth token)" in line
    ]
    assert not offenders, (
        f"`$(gh auth token)` handed to a sync at {offenders}: a sync executes upstream "
        "code, so use a token with no scopes (CONTRIBUTING.md, 'The sync token')."
    )
