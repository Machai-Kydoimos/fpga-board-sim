"""Tests for cocotb simulation via GHDL subprocess."""
import os
import subprocess
import tempfile
from pathlib import Path
import pytest
from sim_bridge import analyze_vhdl, _find_ghdl, _build_sim_env

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ghdl():
    return _find_ghdl()


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
        env=env, check=True, cwd=d,
    )
    return d


def test_ghdl_analyze_in_workdir(work_dir):
    assert Path(work_dir).is_dir()


def test_cocotb_simulation_passes(ghdl, sim_env, work_dir):
    env, vpi_dll = sim_env
    cmd = [
        ghdl, "-r", "--std=08", f"--workdir={work_dir}",
        "-gNUM_SWITCHES=4", "-gNUM_BUTTONS=4", "-gNUM_LEDS=4", "-gCOUNTER_BITS=10",
        "blinky", f"--vpi={vpi_dll}",
        "--stop-time=100000ns",
    ]
    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_blinky"
    run_env["TOPLEVEL"] = "blinky"
    run_env["PYTHONPATH"] = (
        str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")
    )

    result = subprocess.run(cmd, env=run_env, cwd=work_dir,
                            capture_output=True, text=True)
    output = result.stdout + result.stderr

    # Surface cocotb result lines in pytest output
    for line in output.splitlines():
        if "PASS=" in line or "FAIL=" in line or line.strip().startswith("PASS "):
            print(line.strip())

    assert "FAIL=0" in output and "PASS=" in output, (
        "cocotb tests did not all pass.\n"
        + "\n".join(output.splitlines()[-30:])
    )
