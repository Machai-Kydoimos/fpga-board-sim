"""Board-data drift tripwire: prove the committed boards match their pinned upstreams.

Re-syncs every generated source **in place** at the commit its
``_sync_metadata.json`` records (in place, because a fresh-directory re-sync
has no existing files for the A1 merge to fold canonical conventions into —
the known trap), then requires ``git status`` under ``boards/`` to stay
empty.  ``sync_common``'s carry-forward makes a true no-op re-sync
byte-identical, so ANY diff means the committed data no longer matches what
the current parsers produce from the pinned upstream: a parser changed
without a re-sync, or a generated file was hand-edited where a parser owns
it.  Silent drift of exactly this kind accumulated twice before U37's PR-0
cleared it — this check makes it impossible to miss (U38).

Also chains the two registry checks (``sync_port_conventions --check`` and
``sync_led_colors --check``) so CI has a single drift entry point.

Requires a clean ``boards/`` tree to start (otherwise a diff cannot be
attributed) and network access to the pinned raw.githubusercontent.com URLs.
Self-contained CLI, no ``fpga_sim`` dependency.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent
BOARDS_DIR = REPO / "boards"

#: (sync script, boards/ subdirectory) for every generated source.
SOURCES: tuple[tuple[str, str], ...] = (
    ("sync_amaranth_boards.py", "amaranth-boards"),
    ("sync_litex_boards.py", "litex-boards"),
    ("sync_digilent_xdc.py", "digilent-xdc"),
)


def read_pins() -> dict[str, str]:
    """Map each source's boards/ subdirectory to its recorded upstream commit."""
    pins: dict[str, str] = {}
    for _script, subdir in SOURCES:
        meta_path = BOARDS_DIR / subdir / "_sync_metadata.json"
        with meta_path.open() as f:
            pins[subdir] = json.load(f)["source_commit"]
    return pins


def _boards_tree_status() -> str:
    """``git status --porcelain`` output for boards/ (empty string = clean)."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--", "boards/"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def main() -> int:
    """Run the full drift check; 0 = no drift, 1 = drift, 2 = cannot run."""
    dirty = _boards_tree_status()
    if dirty:
        print("boards/ is not clean; commit or stash before checking drift:")
        print(dirty)
        return 2

    pins = read_pins()
    for script, subdir in SOURCES:
        sha = pins[subdir]
        print(f"== re-sync {subdir} at {sha[:12]}", flush=True)
        res = subprocess.run(
            [sys.executable, str(REPO / "scripts" / script), "--ref", sha],
            cwd=REPO,
        )
        if res.returncode != 0:
            print(f"{script} failed (exit {res.returncode})")
            return 2

    drift = _boards_tree_status()
    if drift:
        print("\nBoard-data drift: the pinned re-sync does not reproduce the committed files.")
        print("Either re-sync (parser changed) or revert the hand-edit (parser owns these):")
        subprocess.run(["git", "--no-pager", "diff", "--stat", "--", "boards/"], cwd=REPO)
        subprocess.run(["git", "checkout", "--", "boards/"], cwd=REPO)
        return 1
    print("Board data matches the pinned upstreams.", flush=True)

    for check in (
        [sys.executable, str(REPO / "scripts" / "sync_port_conventions.py"), "--check"],
        [sys.executable, str(REPO / "scripts" / "sync_led_colors.py"), "--check"],
    ):
        print(f"\n== {Path(check[1]).name} --check", flush=True)
        if subprocess.run(check, cwd=REPO).returncode != 0:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
