"""The workflow linter stays wired up.

Until actionlint was added, ``.github/workflows/`` had no gate at all: every
pre-commit hook is scoped to python/pyi/markdown/toml, and rumdl additionally
excludes ``.github`` -- so editing ``ci.yml`` ran *zero* hooks and any mistake
waited for a push.  What makes that worth a tripwire is the failure mode: a
workflow can be perfectly valid YAML and still be wrong.  A duplicated key
silently keeps the last value, and an unquoted variable in a ``run:`` block is
a shell bug that no YAML parser can see -- and this workflow does real shell
(curl + sha256 verification, tar extraction, PATH surgery).

Both halves below are plain configuration, so either could be dropped in an
unrelated edit and nothing would fail; the workflow would just quietly stop
being linted.  Both are genuinely needed, because each covers the other's
blind spot: a pre-commit hook only fires on *staged* files, so a broken
``ci.yml`` left sitting in the working tree sails through an unrelated commit
and only CI catches it -- while a workflow malformed badly enough may never
reach its own lint step, which only the hook catches.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

PROJECT = Path(__file__).parent.parent
CI_WORKFLOW = PROJECT / ".github" / "workflows" / "ci.yml"
PRE_COMMIT = PROJECT / ".pre-commit-config.yaml"


def _pyproject() -> dict[str, Any]:
    with (PROJECT / "pyproject.toml").open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    return data


def _hooks() -> list[dict[str, Any]]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return [hook for repo in config["repos"] for hook in repo["hooks"]]


def test_actionlint_is_a_dev_dependency():
    """Pinned by uv.lock like every other tool, so local and CI match."""
    dev = _pyproject()["dependency-groups"]["dev"]
    assert any(spec.startswith("actionlint-py") for spec in dev)


def test_ci_lints_the_workflow():
    """The CI half: the lint job actually invokes actionlint."""
    assert "uv run actionlint" in CI_WORKFLOW.read_text(encoding="utf-8")


def test_pre_commit_runs_actionlint_on_workflow_edits():
    """The local half -- and it must be scoped to catch workflow edits.

    A hook scoped to python/pyi (as every other hook here is) would never fire
    on ``ci.yml``, which is the exact gap this closes.
    """
    hook = next((h for h in _hooks() if h["id"] == "actionlint"), None)
    assert hook is not None, "actionlint pre-commit hook is missing"

    files = hook.get("files", "")
    assert "workflows" in files, f"hook must match workflow paths, got {files!r}"

    # actionlint discovers .github/workflows itself, so passing changed
    # filenames would make it lint a subset while reporting success.
    assert hook.get("pass_filenames") is False


def test_actionlint_hook_is_local_not_a_pinned_rev():
    """Same rationale as ruff/mypy/rumdl: a hook ``rev:`` drifts from uv.lock.

    Dependabot does not track pre-commit revisions, so an upstream-mirror hook
    would silently diverge from the version CI runs.
    """
    hook = next(h for h in _hooks() if h["id"] == "actionlint")
    assert hook["language"] == "system"
    assert hook["entry"].startswith("uv run")
