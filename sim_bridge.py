"""
sim_bridge.py – Manages GHDL analysis and launches interactive
cocotb simulations with the correct environment on Windows.

Handles the tricky Windows-specific PATH / PYTHONHOME / VPI setup
so that GHDL can load the cocotb VPI module and start Python.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def _find_ghdl():
    """Locate the ghdl executable on PATH."""
    for p in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("ghdl.exe", "ghdl"):
            candidate = Path(p) / name
            if candidate.exists():
                return str(candidate)
    return "ghdl"


def _find_ghdl_lib_dir():
    """Find the directory containing libghdlvpi.dll (sibling of bin/)."""
    ghdl = _find_ghdl()
    ghdl_bin = Path(ghdl).parent
    lib_dir = ghdl_bin.parent / "lib"
    if lib_dir.is_dir():
        return str(lib_dir)
    return str(ghdl_bin)


def analyze_vhdl(vhdl_path, work_dir=None):
    """
    Run GHDL analysis on a VHDL file.
    Returns (ok: bool, detail: str).  On success detail is the work dir.
    """
    ghdl = _find_ghdl()
    work_dir = work_dir or tempfile.mkdtemp(prefix="fpga_sim_")
    try:
        result = subprocess.run(
            [ghdl, "-a", "--std=08", "--workdir=" + work_dir, str(vhdl_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, work_dir
    except FileNotFoundError:
        return False, "GHDL not found. Install: winget install ghdl.ghdl.ucrt64.mcode"
    except subprocess.TimeoutExpired:
        return False, "GHDL analysis timed out."


def _build_sim_env(venv_dir=None):
    """
    Build the environment dict needed for GHDL + cocotb VPI.
    Returns (env_dict, vpi_dll_path).
    """
    venv_dir = Path(venv_dir or (Path(__file__).parent / ".venv"))
    venv_scripts = venv_dir / "Scripts"
    venv_site = venv_dir / "Lib" / "site-packages"
    cocotb_libs = venv_site / "cocotb" / "libs"

    # Determine base Python (non-Store) from venv's pyvenv.cfg
    venv_python = venv_scripts / "python.exe"
    base_python = subprocess.run(
        [str(venv_python), "-c", "import sys; print(sys.base_exec_prefix)"],
        capture_output=True, text=True,
    ).stdout.strip()

    ghdl_bin = str(Path(_find_ghdl()).parent)
    ghdl_lib = _find_ghdl_lib_dir()

    project_dir = str(Path(__file__).parent.resolve())

    env = os.environ.copy()

    # PATH: venv scripts, base python (for python312.dll),
    #        cocotb libs (gpi.dll etc), ghdl lib (libghdlvpi.dll), ghdl bin
    extra_path = os.pathsep.join([
        str(venv_scripts), base_python, str(cocotb_libs),
        ghdl_lib, ghdl_bin,
    ])
    env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")

    # Python embedding
    env["PYTHONHOME"] = base_python
    env["PYTHONPATH"] = os.pathsep.join([
        project_dir,
        str(venv_site),
    ])
    env["PYGPI_PYTHON_BIN"] = str(venv_python)
    env["PYGPI_PYTHON_LIB"] = str(Path(base_python) / "python312.dll")

    # cocotb
    env["TOPLEVEL_LANG"] = "vhdl"

    # Locate VPI DLL
    vpi_dll = str(cocotb_libs / "cocotbvpi_ghdl.dll")

    return env, vpi_dll


def launch_simulation(board_json, vhdl_path, toplevel="blinky",
                      generics=None):
    """
    Launch an interactive GHDL + cocotb simulation.

    Runs GHDL with the VPI module, which loads cocotb, which imports
    sim_testbench.py which runs the pygame interactive loop.

    This call blocks until the simulation exits.
    """
    vhdl_path = Path(vhdl_path).resolve()
    work_dir = tempfile.mkdtemp(prefix="fpga_sim_run_")

    env, vpi_dll = _build_sim_env()

    # Analyze VHDL in work_dir
    ghdl = _find_ghdl()
    subprocess.run(
        [ghdl, "-a", "--std=08", "--workdir=" + work_dir, str(vhdl_path)],
        env=env, check=True, cwd=work_dir,
    )

    # Build ghdl -r command
    cmd = [ghdl, "-r", "--std=08", "--workdir=" + work_dir]

    # Add generics
    for k, v in (generics or {}).items():
        cmd.append(f"-g{k}={v}")

    cmd.append(toplevel)
    cmd.append(f"--vpi={vpi_dll}")

    # Pass board definition and test module via env
    env["COCOTB_TEST_MODULES"] = "sim_testbench"
    env["TOPLEVEL"] = toplevel
    env["FPGA_SIM_BOARD_JSON"] = board_json

    print(f"Starting simulation: {toplevel} from {vhdl_path.name}")
    result = subprocess.run(cmd, env=env, cwd=work_dir)
    return result.returncode == 0
