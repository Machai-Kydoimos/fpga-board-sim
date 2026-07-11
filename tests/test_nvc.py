"""Tests for NVC availability and VHDL analysis/simulation.

All tests are skipped automatically when NVC is not installed.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import (
    WaveConfig,
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
    run_cmd = _NVCBackend.run_cmd(
        "blinky",
        {"NUM_SWITCHES": "4", "NUM_BUTTONS": "4", "NUM_LEDS": "4", "COUNTER_BITS": "10"},
        vhpi_lib,
        nvc_work_dir,
    )
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


def test_nvc_fst_capture_produces_populated_file(nvc, nvc_sim_env, nvc_work_dir, tmp_path):
    """U10: NVC --wave + --format=fst produces a valid FST alongside the VHPI run.

    The NVC/FST counterpart to test_ghdl_vcd_capture_produces_populated_file:
    proves the backend's wave flags work in a real cocotb run (FST is binary, so
    only presence + non-emptiness are asserted; the GHDL/VCD test checks content).
    """
    env, vhpi_lib = nvc_sim_env
    fst = tmp_path / "blinky.fst"
    generics = {"NUM_SWITCHES": "4", "NUM_BUTTONS": "4", "NUM_LEDS": "4", "COUNTER_BITS": "10"}
    subprocess.run(
        _NVCBackend.elaborate_cmd("blinky", generics, nvc_work_dir),
        env=env,
        check=True,
        cwd=nvc_work_dir,
    )
    run_cmd = _NVCBackend.run_cmd(
        "blinky", generics, vhpi_lib, nvc_work_dir, wave=WaveConfig(str(fst), "fst")
    )
    run_cmd.append("--stop-time=100000ns")  # bound the run

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_blinky"
    run_env["TOPLEVEL"] = "blinky"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")
    result = subprocess.run(run_cmd, env=run_env, cwd=nvc_work_dir, capture_output=True, text=True)

    assert fst.is_file(), f"FST not written.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert fst.stat().st_size > 0, "FST file is empty"


def test_nvc_dump_arrays_captures_embedded_core_memory(nvc, nvc_sim_env, tmp_path):
    """U30: --dump-arrays makes the mx65 RAM memory appear in an NVC capture.

    The roadmap "done when": with "include memories" on, an embedded-core dump
    under NVC contains the RAM/ROM array signals NVC skips by default.  Runs the
    smallest embedded core (mx65_hello_7seg) standalone — sim_wrapper self-clocks,
    so no cocotb is needed — and captures VCD (text, so the per-cell array vars
    are greppable).  Both runs reuse one elaboration; the with/without pair proves
    the flag is what pulls the memory in (NVC otherwise omits it in every format).
    """
    env, vhpi_lib = nvc_sim_env
    work_dir = tempfile.mkdtemp(prefix="fpga_nvc_u30_")
    ok, detail = analyze_vhdl(
        HDL / "mx65_hello_7seg.vhd",
        work_dir=work_dir,
        toplevel="mx65_hello_7seg",
        simulator="nvc",
        board_def=_7seg_board(),
    )
    assert ok, f"NVC embedded-core analysis failed: {detail}"

    # PRESCALER_BITS is an inner-core generic, not a sim_wrapper one, so it is not passed.
    generics = {
        "NUM_SWITCHES": "4",
        "NUM_BUTTONS": "4",
        "NUM_LEDS": "4",
        "NUM_SEGS": "4",
        "COUNTER_BITS": "18",
    }
    subprocess.run(
        _NVCBackend.elaborate_cmd("sim_wrapper", generics, work_dir),
        env=env,
        check=True,
        cwd=work_dir,
    )

    def ram_cell_count(*, dump_arrays: bool) -> int:
        out = tmp_path / f"mx65_hello_{int(dump_arrays)}.vcd"
        cmd = _NVCBackend.run_cmd(
            "sim_wrapper",
            generics,
            vhpi_lib,
            work_dir,
            wave=WaveConfig(str(out), "vcd", dump_arrays=dump_arrays),
        )
        # Standalone dump: drop the cocotb VHPI plugin (wrapper self-clocks), bound the run.
        cmd = [a for a in cmd if not a.startswith("--load=")]
        cmd.append("--stop-time=20us")
        result = subprocess.run(cmd, env=env, cwd=work_dir, capture_output=True, text=True)
        assert out.is_file(), f"VCD (dump_arrays={dump_arrays}) not written.\n{result.stderr}"
        text = out.read_text(errors="ignore")
        # NVC expands the cpu_ram memory into per-cell vars ram[0][7:0]..ram[N-1][7:0].
        return sum(1 for line in text.splitlines() if "$var" in line and "ram[" in line)

    assert ram_cell_count(dump_arrays=True) > 100, "RAM memory not captured with --dump-arrays"
    assert ram_cell_count(dump_arrays=False) == 0, "RAM memory must be absent without --dump-arrays"


# ── 7-seg: NVC analysis and simulation ───────────────────────────────────────


@pytest.fixture(scope="module")
def nvc_7seg_work_dir(nvc, nvc_sim_env):
    """Analyze counter_7seg with the 7-seg wrapper into a fresh temp workdir."""
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
    """counter_7seg.vhd must analyze cleanly under NVC using the 7-seg wrapper."""
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

    run_cmd = _NVCBackend.run_cmd("sim_wrapper", generics, vhpi_lib, nvc_7seg_work_dir)
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
