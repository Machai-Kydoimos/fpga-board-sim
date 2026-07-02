"""Integration tests for the hand-written stopwatch_7seg.vhd design.

Elaborates and runs sim/test_stopwatch.py under both GHDL and NVC, mirroring
the elaborate-then-run pattern tests/test_embedded_core.py uses for the
embedded-core designs (stopwatch is hand-written RTL, not generated, so it
gets its own file rather than living in that embedded-core-scoped module).
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import _build_sim_env, _GHDLBackend, _NVCBackend, analyze_vhdl
from tests.conftest import _7seg_board

PROJECT = Path(__file__).resolve().parent.parent
STOPWATCH = PROJECT / "hdl" / "stopwatch_7seg.vhd"

_GENERICS = {
    "NUM_SWITCHES": "4",
    "NUM_BUTTONS": "4",
    "NUM_LEDS": "4",
    "NUM_SEGS": "4",
    "COUNTER_BITS": "17",
}

# The run tests below require exactly this many cocotb PASSes (with FAIL=0) so a
# zero-test run can't false-pass. Keep in sync with sim/test_stopwatch.py.
_STOPWATCH_TEST_COUNT = 1


def test_stopwatch_vhd_exists():
    assert STOPWATCH.is_file(), f"Stopwatch design missing: {STOPWATCH}"


@pytest.mark.slow
def test_stopwatch_runs_nvc(nvc):
    """The stopwatch design runs end-to-end under NVC (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="stopwatch_nvc_")
    ok, detail = analyze_vhdl(
        STOPWATCH,
        work_dir=work_dir,
        toplevel="stopwatch_7seg",
        simulator="nvc",
        board_def=_7seg_board(),
    )
    assert ok, f"NVC analyze failed: {detail}"

    env, vhpi_lib = _build_sim_env(simulator="nvc")
    subprocess.run(
        _NVCBackend.elaborate_cmd("sim_wrapper", _GENERICS, work_dir),
        env=env,
        check=True,
        cwd=work_dir,
    )
    run_cmd = _NVCBackend.run_cmd("sim_wrapper", _GENERICS, vhpi_lib, work_dir)
    run_cmd.append("--stop-time=3200000ns")  # cold-static + start + advance + stop + reset

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_stopwatch"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_STOPWATCH_TEST_COUNT}" in output, (
        "cocotb stopwatch suite did not pass under NVC.\n" + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_stopwatch_runs_ghdl(ghdl):
    """The stopwatch design runs end-to-end under GHDL (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="stopwatch_ghdl_")
    ok, detail = analyze_vhdl(
        STOPWATCH,
        work_dir=work_dir,
        toplevel="stopwatch_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator="ghdl")
    run_cmd = _GHDLBackend.run_cmd("sim_wrapper", _GENERICS, plugin_lib, work_dir)
    run_cmd.append("--stop-time=3200000ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_stopwatch"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_STOPWATCH_TEST_COUNT}" in output, (
        "cocotb stopwatch suite did not pass under GHDL.\n" + "\n".join(output.splitlines()[-30:])
    )
