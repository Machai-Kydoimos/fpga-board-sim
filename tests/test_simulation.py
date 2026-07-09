"""Tests for cocotb simulation via GHDL subprocess."""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import WaveConfig, _build_sim_env, _GHDLBackend

pytestmark = pytest.mark.slow

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sim_env():
    env, vpi_dll = _build_sim_env()
    return env, vpi_dll


def test_vpi_dll_exists(sim_env):
    _, vpi_dll = sim_env
    assert Path(vpi_dll).is_file(), f"VPI DLL not found: {vpi_dll}"


@pytest.fixture(scope="module")
def work_dir(ghdl, sim_env):
    """Analyze blinky into a temp workdir; reused by simulation test."""
    env, _ = sim_env
    blinky = PROJECT / "hdl" / "blinky.vhd"
    d = tempfile.mkdtemp(prefix="fpga_test_ci_")
    subprocess.run(
        [ghdl, "-a", "--std=08", f"--workdir={d}", str(blinky)],
        env=env,
        check=True,
        cwd=d,
    )
    return d


def test_ghdl_analyze_in_workdir(work_dir):
    assert Path(work_dir).is_dir()


def test_cocotb_simulation_passes(ghdl, sim_env, work_dir):
    env, vpi_dll = sim_env
    cmd = [
        ghdl,
        "-r",
        "--std=08",
        f"--workdir={work_dir}",
        "-gNUM_SWITCHES=4",
        "-gNUM_BUTTONS=4",
        "-gNUM_LEDS=4",
        "-gCOUNTER_BITS=10",
        "blinky",
        f"--vpi={vpi_dll}",
        "--stop-time=100000ns",
    ]
    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_blinky"
    run_env["TOPLEVEL"] = "blinky"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr

    # Surface cocotb result lines in pytest output
    for line in output.splitlines():
        if "PASS=" in line or "FAIL=" in line or line.strip().startswith("PASS "):
            print(line.strip())

    assert "FAIL=0" in output and "PASS=" in output, "cocotb tests did not all pass.\n" + "\n".join(
        output.splitlines()[-30:]
    )


def test_ghdl_vcd_capture_produces_populated_file(ghdl, sim_env, work_dir, tmp_path):
    """U10: adding the wave flag to a real GHDL + cocotb run yields a valid VCD.

    Proves native waveform dumping coexists with the cocotb VPI (the flag is a
    GHDL simulation option, independent of --vpi) and that the design's signals
    land in the file — the roadmap's "done when" for U10.
    """
    env, vpi_dll = sim_env
    vcd = tmp_path / "blinky.vcd"
    generics = {"NUM_SWITCHES": "4", "NUM_BUTTONS": "4", "NUM_LEDS": "4", "COUNTER_BITS": "10"}
    # Build via the real backend so the wave flag under test is exercised.
    cmd = _GHDLBackend.run_cmd(
        "blinky", generics, vpi_dll, work_dir, wave=WaveConfig(str(vcd), "vcd")
    )
    cmd.append("--stop-time=100000ns")  # bound the run

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_blinky"
    run_env["TOPLEVEL"] = "blinky"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")
    result = subprocess.run(cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)

    assert vcd.is_file(), f"VCD not written.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    text = vcd.read_text()
    assert text.strip(), "VCD file is empty"
    assert "$var" in text  # standard VCD signal declarations
    assert "clk" in text and "led" in text  # top-level design signals captured
