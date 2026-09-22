"""Every pre-commit hook runs the tool version that ``uv.lock`` pins.

The hooks are ``repo: local`` hooks calling ``uv run <tool>`` rather than an
upstream mirror at a pinned ``rev:``, so that one lockfile decides the version
for CI and for a contributor's commit alike.  That holds only while ``uv run``
keeps the tools in step with the lock, and since ``[tool.uv] default-groups =
[]`` a plain ``uv run`` does not: the tools the hooks run live in the ``dev``
group, and ``uv run`` syncs only the default groups -- now none -- without
upgrading or removing anything outside them.  After a lock bump a contributor's hooks
therefore kept running whatever their last ``uv sync --group dev`` installed,
at exit 0 and with nothing printed: on 2026-09-23 one checkout was still
linting with ruff 0.16.6 and rumdl 0.2.67, two Dependabot bumps after CI had
moved to 0.16.8 and 0.2.73.

``uv run --group dev <tool>`` makes each hook sync the dev group first -- a
no-op when nothing changed, an upgrade when something did, an install in a
fresh checkout.  Nothing fails when the flag is missing; the hook just lints with
a different version than CI, which is why the flag gets a test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT = Path(__file__).parent.parent
PRE_COMMIT = PROJECT / ".pre-commit-config.yaml"


def _uv_run_hooks() -> list[dict[str, Any]]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo["hooks"]]
    return [h for h in hooks if h.get("entry", "").split()[:2] == ["uv", "run"]]


def test_there_are_uv_run_hooks_to_check():
    """Guards the guard: an empty selection would pass the test below vacuously."""
    assert _uv_run_hooks(), "no hook entry starts with `uv run` -- update this test"


def test_every_uv_run_hook_syncs_the_dev_group():
    """``--group dev`` has to be a *uv* option, so it sits before the tool.

    ``uv run ruff --group dev`` would hand the flag to ruff instead of uv.
    """
    unsynced = [
        hook["id"] for hook in _uv_run_hooks() if hook["entry"].split()[2:4] != ["--group", "dev"]
    ]
    assert not unsynced, f"these hooks would run whatever tool version the venv holds: {unsynced}"
