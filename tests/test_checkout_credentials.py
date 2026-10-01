"""No workflow leaves the job's token configured for git after checking out.

``actions/checkout`` defaults to ``persist-credentials: true``: the job's token
stays configured for git until the job ends, so any later step -- the test
suite, the simulators it launches, each third-party action -- can run
authenticated git commands.  No job here pushes, fetches or clones after
checking out, and the drift job reads ``GITHUB_TOKEN`` from ``env:``, so none
of them needs it.  zizmor's ``artipacked`` audit flags the default.

Checked across every workflow file rather than ``ci.yml`` alone, so a job added
anywhere later inherits the rule instead of the default.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).parent.parent / ".github" / "workflows"


def _checkout_steps() -> list[tuple[str, dict[str, Any]]]:
    found = []
    for path in sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")]):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    found.append((f"{path.name}:{job_id}", step))
    return found


def test_workflows_check_out_through_actions_checkout():
    """Guards the test below: a renamed action would make it pass vacuously."""
    assert _checkout_steps(), "no actions/checkout step found in .github/workflows"


def test_no_checkout_persists_credentials():
    # Action inputs are strings, so a quoted "false" counts as much as a bare one.
    persisting = [
        where
        for where, step in _checkout_steps()
        if str(step.get("with", {}).get("persist-credentials", "")).lower() != "false"
    ]
    assert not persisting, (
        f"{persisting} leave the job's token configured for git; "
        "give the checkout `with: persist-credentials: false`"
    )
