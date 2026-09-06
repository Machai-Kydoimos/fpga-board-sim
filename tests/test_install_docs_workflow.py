"""The install-docs workflow must run what the install docs actually say.

`.github/workflows/install-docs.yml` exists to answer one question: does the
install we *document* still work?  Its only claim to authority is that the
commands in it are the commands a reader types.  The moment someone improves a
line in `docs/install.md` and leaves the workflow behind, the workflow is
verifying a command nobody is told to run, and it will keep passing while doing
it -- a green tripwire is worse than none.

So this pins the two together in the direction that rots: every command the
workflow runs *as documentation* must still appear in the document it came
from.  It deliberately does not check the reverse -- the docs carry per-distro
and from-source paths no hosted runner can rehearse, and demanding coverage of
those would only invite the workflow to grow lies.
"""

import re

import yaml

from fpga_sim.paths import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "install-docs.yml"

#: command -> the document that publishes it.  A command listed here is one the
#: workflow runs verbatim *because a reader is told to run it*; the workflow's
#: own plumbing (checkout, PATH exports, summary lines) is not in scope.
DOCUMENTED = {
    "sudo apt install ghdl": "docs/install.md",
    "brew install ghdl": "docs/install.md",
    "brew install nvc": "docs/install.md",
    "winget install ghdl.ghdl.ucrt64.mcode": "docs/install.md",
    "uv sync": "docs/install.md",
    "uv run pytest": "docs/install.md",
    "curl -LsSf https://astral.sh/uv/install.sh | sh": "README.md",
    "winget install --id=astral-sh.uv -e": "README.md",
    (
        "sudo apt install build-essential automake autoconf flex check "
        "llvm-dev pkg-config zlib1g-dev libdw-dev libffi-dev libzstd-dev"
    ): "docs/install.md",
}


def _flatten(text: str) -> str:
    """Join shell/PowerShell line continuations and collapse whitespace.

    The same command is wrapped differently in a fenced doc block and in a YAML
    `run:` body, so comparing raw text would fail on indentation alone.
    """
    # Require the space both shells demand before a continuation, so a
    # closing markdown fence (```) is never mistaken for one.
    text = re.sub(r"(?<= )[\\`]\n\s*", " ", text)  # sh `\` and PowerShell `` ` ``
    return re.sub(r"\s+", " ", text)


def _workflow_commands() -> str:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    runs = [step["run"] for job in doc["jobs"].values() for step in job["steps"] if "run" in step]
    return _flatten("\n".join(runs))


def test_every_documented_command_is_actually_run():
    haystack = _workflow_commands()
    missing = [cmd for cmd in DOCUMENTED if _flatten(cmd) not in haystack]
    assert not missing, f"install-docs.yml no longer runs: {missing}"


def test_every_command_it_runs_is_still_documented():
    for cmd, doc in DOCUMENTED.items():
        text = _flatten((REPO_ROOT / doc).read_text(encoding="utf-8"))
        assert _flatten(cmd) in text, f"{doc} no longer publishes: {cmd!r}"


def test_it_is_scheduled_and_manually_runnable():
    """A tripwire nobody can fire by hand is a tripwire nobody trusts."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = doc[True] if True in doc else doc["on"]  # YAML 1.1 reads `on:` as True
    assert "schedule" in triggers
    assert "workflow_dispatch" in triggers


def test_it_covers_all_three_operating_systems():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    systems = {job["runs-on"].split("-")[0] for job in doc["jobs"].values()}
    assert systems == {"ubuntu", "macos", "windows"}
