"""Checks on the cocotb testbench, runnable from outside a simulator.

``sim_testbench.py`` imports cocotb and runs inside the simulator subprocess, so
it is never imported into the pytest process; it is exercised here via ruff
(catching undefined names and unused imports that would only surface as runtime
crashes inside the simulator) and via a clean subprocess import that verifies it
stays pygame-free — the U34 single-window child streams state over ``sim_link``
and must own no window.
"""

import os
import shutil
import subprocess
import sys
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


def test_sim_testbench_is_pygame_free():
    """U34: the testbench must never import pygame (directly or transitively).

    The single-window child streams state over sim_link and must own no window;
    a stray ``fpga_sim.ui`` import would pull in pygame and break that. CI has no
    other way to catch it, so import the module in a clean subprocess and assert
    pygame did not land in ``sys.modules``.
    """
    project = SIM_TESTBENCH.parent.parent
    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(project / "src"), str(project / "sim"), env.get("PYTHONPATH", "")]
    )
    code = "import sim_testbench, sys; print('pygame' in sys.modules)"
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "False"
