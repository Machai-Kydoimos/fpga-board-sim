"""Tests for NVC availability and VHDL analysis/simulation.

All tests are skipped automatically when NVC is not installed.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import (
    _build_sim_env,
    _NVCBackend,
    analyze_vhdl,
    detect_simulators,
)
from tests.conftest import _7seg_board

pytestmark = pytest.mark.slow

PROJECT = Path(__file__).resolve().parent.parent
HDL = PROJECT / "hdl"


# ── Availability ──────────────────────────────────────────────────────────────


def test_detect_simulators_returns_list():
    sims = detect_simulators()
    assert isinstance(sims, list)
    assert len(sims) >= 1
    assert all(s in ("ghdl", "nvc") for s in sims)


def test_nvc_found(nvc):
    assert Path(nvc).name.startswith("nvc"), f"Unexpected binary: {nvc}"


def test_nvc_version(nvc):
    """NVC must report a version (sanity-check it runs at all)."""
    result = subprocess.run([nvc, "--version"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "nvc" in result.stdout.lower() or "nvc" in result.stderr.lower()


def test_nvc_in_detect_simulators(nvc):
    assert "nvc" in detect_simulators()


# ── Analysis ──────────────────────────────────────────────────────────────────


def test_blinky_analyzes_ok_with_nvc(nvc):
    blinky = PROJECT / "hdl" / "blinky.vhd"
    ok, detail = analyze_vhdl(str(blinky), simulator="nvc")
    assert ok, f"NVC analysis failed: {detail}"


def test_nvc_analyze_returns_work_dir(nvc):
    blinky = PROJECT / "hdl" / "blinky.vhd"
    ok, detail = analyze_vhdl(str(blinky), simulator="nvc")
    assert ok
    assert Path(detail).is_dir(), f"Expected a work_dir path, got: {detail!r}"


@pytest.mark.parametrize(
    "filename",
    [
        "blinky.vhd",
        "blinky_alt.vhd",
        "blinky_counter.vhd",
        "blinky_morse.vhd",
        "blinky_pwm.vhd",
        "blinky_walking.vhd",
    ],
)
def test_good_blinky_analyzes_with_nvc(nvc, filename):
    f = PROJECT / "hdl" / filename
    ok, detail = analyze_vhdl(f, toplevel=f.stem, simulator="nvc")
    assert ok, f"NVC failed on {filename}: {detail}"


def test_bad_semantic_fails_nvc_analysis(nvc):
    """A file with a missing library import must also fail NVC analysis."""
    f = PROJECT / "hdl" / "bad_semantic_blinky.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem, simulator="nvc")
    assert not ok, "Expected NVC analysis to fail on bad_semantic_blinky.vhdl"


# ── VHPI plugin ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def nvc_sim_env(nvc):
    env, vhpi_lib = _build_sim_env(simulator="nvc")
    return env, vhpi_lib


def test_vhpi_lib_exists(nvc_sim_env):
    _, vhpi_lib = nvc_sim_env
    assert Path(vhpi_lib).is_file(), f"VHPI library not found: {vhpi_lib}"


def test_vhpi_lib_name_contains_nvc(nvc_sim_env):
    _, vhpi_lib = nvc_sim_env
    assert "nvc" in Path(vhpi_lib).name


# ── Simulation ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def nvc_work_dir(nvc, nvc_sim_env):
    """Analyze blinky with NVC into a temp workdir; reused by simulation test."""
    env, _ = nvc_sim_env
    blinky = PROJECT / "hdl" / "blinky.vhd"
    d = tempfile.mkdtemp(prefix="fpga_nvc_ci_")
    subprocess.run(
        _NVCBackend.analyze_cmd(blinky, d),
        env=env,
        check=True,
        cwd=d,
    )
    return d


def test_nvc_analyze_in_workdir(nvc_work_dir):
    assert Path(nvc_work_dir).is_dir()


def test_nvc_cocotb_simulation_passes(nvc, nvc_sim_env, nvc_work_dir):
    env, vhpi_lib = nvc_sim_env

    # Elaborate with generics (NVC requires this before run)
    elab_cmd = _NVCBackend.elaborate_cmd(
        "blinky",
        {"NUM_SWITCHES": "4", "NUM_BUTTONS": "4", "NUM_LEDS": "4", "COUNTER_BITS": "10"},
        nvc_work_dir,
    )
    subprocess.run(elab_cmd, env=env, check=True, cwd=nvc_work_dir)

    # Run with VHPI + stop-time to prevent infinite simulation
    run_cmd = _NVCBackend.run_cmd("blinky", vhpi_lib, nvc_work_dir)
    run_cmd.append("--stop-time=100000ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_blinky"
    run_env["TOPLEVEL"] = "blinky"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=nvc_work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr

    for line in output.splitlines():
        if "PASS=" in line or "FAIL=" in line or line.strip().startswith("PASS "):
            print(line.strip())

    assert "FAIL=0" in output and "PASS=" in output, (
        "cocotb tests did not all pass under NVC.\n" + "\n".join(output.splitlines()[-30:])
    )


# ── 7-seg: NVC analysis and simulation ───────────────────────────────────────


@pytest.fixture(scope="module")
def nvc_7seg_work_dir(nvc, nvc_sim_env):
    """Analyse counter_7seg with the 7-seg wrapper into a fresh temp workdir."""
    bd = _7seg_board()
    d = tempfile.mkdtemp(prefix="fpga_nvc_7seg_")
    ok, detail = analyze_vhdl(
        HDL / "counter_7seg.vhd",
        work_dir=d,
        toplevel="counter_7seg",
        simulator="nvc",
        board_def=bd,
    )
    assert ok, f"NVC 7-seg analysis fixture failed: {detail}"
    return d


def test_7seg_analyzes_with_nvc(nvc, nvc_7seg_work_dir):
    """counter_7seg.vhd must analyse cleanly under NVC using the 7-seg wrapper."""
    assert Path(nvc_7seg_work_dir).is_dir()


def test_7seg_nvc_simulation_passes(nvc, nvc_sim_env, nvc_7seg_work_dir):
    """counter_7seg.vhd must run headlessly under NVC and produce valid seg output.

    Runs test_7seg.py (pure cocotb, no pygame) against the elaborated sim_wrapper,
    mirroring how test_nvc_cocotb_simulation_passes tests blinky.
    """
    env, vhpi_lib = nvc_sim_env

    generics = {
        "NUM_SWITCHES": "4",
        "NUM_BUTTONS": "4",
        "NUM_LEDS": "4",
        "NUM_SEGS": "4",
        "COUNTER_BITS": "32",
    }
    elab_cmd = _NVCBackend.elaborate_cmd("sim_wrapper", generics, nvc_7seg_work_dir)
    subprocess.run(elab_cmd, env=env, check=True, cwd=nvc_7seg_work_dir)

    run_cmd = _NVCBackend.run_cmd("sim_wrapper", vhpi_lib, nvc_7seg_work_dir)
    run_cmd.append("--stop-time=2000000ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_7seg"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(
        run_cmd, env=run_env, cwd=nvc_7seg_work_dir, capture_output=True, text=True
    )
    output = result.stdout + result.stderr

    for line in output.splitlines():
        if "PASS=" in line or "FAIL=" in line or line.strip().startswith("PASS "):
            print(line.strip())

    assert "FAIL=0" in output and "PASS=" in output, (
        "cocotb 7-seg tests did not all pass under NVC.\n" + "\n".join(output.splitlines()[-30:])
    )
