"""Lint check for sim/sim_testbench.py.

sim_testbench.py imports cocotb and runs inside the simulator subprocess,
so it cannot be imported or executed in the normal pytest environment.
Running ruff here catches issues (undefined names, unused imports, etc.)
that would only surface as runtime crashes inside the simulator.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SIM_TESTBENCH = Path(__file__).resolve().parent.parent / "sim" / "sim_testbench.py"


@pytest.fixture(scope="module")
def ruff():
    path = shutil.which("ruff")
    if path is None:
        pytest.skip("ruff is not installed")
    return path


def test_sim_testbench_no_undefined_names(ruff):
    """sim_testbench.py must have no undefined names (F821) or unused imports (F401)."""
    result = subprocess.run(
        [ruff, "check", "--select=F", str(SIM_TESTBENCH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "ruff F-rules found issues in sim_testbench.py:\n" + result.stdout
    )


def test_sim_testbench_full_lint(ruff):
    """sim_testbench.py must pass the full ruff rule set configured in pyproject.toml."""
    result = subprocess.run(
        [ruff, "check", str(SIM_TESTBENCH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "ruff found issues in sim_testbench.py:\n" + result.stdout
