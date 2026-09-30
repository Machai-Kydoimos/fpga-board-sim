"""Every CI job names its Python; none inherits the runner image's.

A ``setup-uv`` step without ``python-version`` leaves the choice to uv, and on a
hosted runner uv takes the image's ``/usr/bin/python3`` -- which the image
decides, not this repository.  ``ubuntu-latest`` moving from Ubuntu 24.04 to
26.04 (scheduled for 2026-10-19 to 11-19, actions/runner-images#14748) turns
that from 3.12 into 3.14, and while the rollout mixes the two images an
unpinned job alternates between them from one run to the next.

Lint & type-check is where that bites.  mypy's *target* is pinned in
pyproject.toml, but mypy checks against the packages installed in whatever
environment it runs in, and those depend on the interpreter: ``tomli`` is
installed only below 3.11, which has already turned a local green into a CI
red (#421).  Both 3.12 and 3.14 were green on the 26.04 trial (#448); naming
the version keeps the result from depending on which image a run lands on.

``install-docs.yml`` is deliberately outside this rule.  It rehearses a
student's install, and a student's uv takes whatever ``python3`` their machine
has -- so there the image's interpreter is the thing under test.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

PROJECT = Path(__file__).parent.parent
CI_WORKFLOW = PROJECT / ".github" / "workflows" / "ci.yml"


def _setup_uv_steps() -> list[tuple[str, dict[str, Any]]]:
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    return [
        (job_id, step)
        for job_id, job in workflow["jobs"].items()
        for step in job.get("steps", [])
        if str(step.get("uses", "")).startswith("astral-sh/setup-uv@")
    ]


def test_ci_installs_python_through_setup_uv():
    """Guards the test below: a renamed action would make it pass vacuously."""
    assert _setup_uv_steps(), "no astral-sh/setup-uv step found in ci.yml"


def test_every_setup_uv_step_names_its_python():
    unpinned = [
        job_id
        for job_id, step in _setup_uv_steps()
        if not step.get("with", {}).get("python-version")
    ]
    assert not unpinned, (
        f"{unpinned} would run on the runner image's python3; "
        'give each setup-uv step a python-version (e.g. "3.12")'
    )
