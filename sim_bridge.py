"""
sim_bridge.py – Manages GHDL analysis and launches interactive
cocotb simulations.

Handles the platform-specific PATH / PYTHONHOME / VPI setup
so that GHDL can load the cocotb VPI module and start Python.
Works on both Windows and Linux.
"""

import os
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def _find_ghdl():
    """Locate the ghdl executable."""
    found = shutil.which("ghdl")
    if found:
        return found
    return "ghdl"


def _find_ghdl_lib_dir():
    """Find the directory containing the GHDL VPI shared library."""
    ghdl = _find_ghdl()
    ghdl_bin = Path(ghdl).resolve().parent
    # Standard layout: bin/ and lib/ are siblings
    lib_dir = ghdl_bin.parent / "lib"
    if lib_dir.is_dir():
        return str(lib_dir)
    return str(ghdl_bin)


def _venv_dirs(venv_dir):
    """Return (scripts_dir, site_packages_dir, python_exe) for a venv."""
    venv_dir = Path(venv_dir)
    if IS_WINDOWS:
        scripts = venv_dir / "Scripts"
        site = venv_dir / "Lib" / "site-packages"
        python = scripts / "python.exe"
    else:
        scripts = venv_dir / "bin"
        site = venv_dir / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        python = scripts / "python"
    return scripts, site, python


def _vpi_lib_name():
    """Return the platform-specific cocotb VPI library filename for GHDL."""
    return "cocotbvpi_ghdl.dll" if IS_WINDOWS else "libcocotbvpi_ghdl.so"


def _libpython_name(base_python):
    """Return the path to the Python shared library."""
    # Try find_libpython first (installed as a dependency)
    try:
        import find_libpython
        found = find_libpython.find_libpython()
        if found:
            return found
    except ImportError:
        pass
    # Fallback
    if IS_WINDOWS:
        return str(Path(base_python) / f"python{sys.version_info.major}{sys.version_info.minor}.dll")
    else:
        return str(Path(base_python) / "lib" / f"libpython{sys.version_info.major}.{sys.version_info.minor}.so")


def check_vhdl_encoding(path) -> tuple:
    """
    Stage 1: encoding check (no GHDL needed).
    Returns (ok: bool, message: str).
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        return False, f"Cannot read file: {e}"

    if raw[:3] == b"\xef\xbb\xbf":
        return False, (
            f"UTF-8 BOM detected in '{path.name}'.\n"
            "Save the file without BOM (UTF-8 without BOM / ASCII)."
        )

    for lineno, line in enumerate(raw.split(b"\n"), start=1):
        for byte in line:
            if byte > 127:
                return False, (
                    f"Non-ASCII byte (0x{byte:02X}) on line {lineno} of '{path.name}'.\n"
                    "VHDL source must be plain ASCII or UTF-8 without BOM."
                )

    return True, ""


def check_vhdl_contract(path) -> tuple:
    """
    Stage 2: contract validation (text-based, no GHDL needed).
    Returns (ok: bool, message: str).
    """
    path = Path(path)
    stem = path.stem.lower()
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        return False, f"Cannot read file: {e}"

    # Check entity name matches filename
    entities = re.findall(r'entity\s+(\w+)\s+is', text, re.IGNORECASE)
    if not entities:
        return False, (
            f"No entity declaration found in '{path.name}'.\n"
            "The file must contain: entity <name> is ... end entity;"
        )
    entity_names_lower = [e.lower() for e in entities]
    if stem not in entity_names_lower:
        found = ", ".join(f"'{e}'" for e in entities)
        return False, (
            f"Entity name mismatch: found {found} but filename is '{path.name}'.\n"
            f"Rename the file to '{entities[0]}.vhd' or rename the entity to '{stem}'."
        )

    # Check required ports
    required_ports = ["clk", "sw", "btn", "led"]
    missing_ports = [p for p in required_ports
                     if not re.search(r'\b' + p + r'\b', text, re.IGNORECASE)]
    if missing_ports:
        return False, (
            f"Missing required port(s) in '{path.name}': {', '.join(missing_ports)}.\n"
            "The top-level entity must have ports: clk, sw, btn, led."
        )

    # Warn (non-fatal) about missing generics — just log, don't fail
    required_generics = ["NUM_SWITCHES", "NUM_BUTTONS", "NUM_LEDS", "COUNTER_BITS"]
    missing_generics = [g for g in required_generics
                        if not re.search(r'\b' + g + r'\b', text, re.IGNORECASE)]
    if missing_generics:
        print(f"[warn] Missing generics (will use VHDL defaults): {', '.join(missing_generics)}")

    return True, ""


def analyze_vhdl(vhdl_path, work_dir=None, toplevel=None):
    """
    Run GHDL analysis and elaboration on a VHDL file.
    Returns (ok: bool, detail: str).  On success detail is the work dir.
    """
    ghdl = _find_ghdl()
    work_dir = work_dir or tempfile.mkdtemp(prefix="fpga_sim_")
    if toplevel is None:
        toplevel = Path(vhdl_path).stem
    try:
        result = subprocess.run(
            [ghdl, "-a", "--std=08", "--workdir=" + work_dir, str(vhdl_path)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()

        elab = subprocess.run(
            [ghdl, "-e", "--std=08", f"--workdir={work_dir}", toplevel],
            capture_output=True, text=True, timeout=30,
        )
        if elab.returncode != 0:
            combined = (result.stderr + elab.stderr).strip()
            return False, combined or f"Elaboration failed for entity '{toplevel}'."

        return True, work_dir
    except FileNotFoundError:
        hint = ("winget install ghdl.ghdl.ucrt64.mcode" if IS_WINDOWS
                else "apt install ghdl  OR  brew install ghdl")
        return False, f"GHDL not found. Install: {hint}"
    except subprocess.TimeoutExpired:
        return False, "GHDL analysis timed out."


def _build_sim_env(venv_dir=None):
    """
    Build the environment dict needed for GHDL + cocotb VPI.
    Returns (env_dict, vpi_lib_path).
    """
    venv_dir = Path(venv_dir or (Path(__file__).parent / ".venv"))
    venv_scripts, venv_site, venv_python = _venv_dirs(venv_dir)
    cocotb_libs = venv_site / "cocotb" / "libs"

    # Determine base Python from the venv
    base_python = subprocess.run(
        [str(venv_python), "-c", "import sys; print(sys.base_exec_prefix)"],
        capture_output=True, text=True,
    ).stdout.strip()

    ghdl_bin = str(Path(_find_ghdl()).resolve().parent)
    ghdl_lib = _find_ghdl_lib_dir()

    project_dir = str(Path(__file__).parent.resolve())

    env = os.environ.copy()

    if IS_WINDOWS:
        # Windows needs all DLL directories on PATH
        extra_path = os.pathsep.join([
            str(venv_scripts), base_python, str(cocotb_libs),
            ghdl_lib, ghdl_bin,
        ])
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
        env["PYTHONHOME"] = base_python
    else:
        # Linux: add to PATH and LD_LIBRARY_PATH
        extra_path = os.pathsep.join([str(venv_scripts), ghdl_bin])
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
        ld_extra = os.pathsep.join([str(cocotb_libs), ghdl_lib, base_python + "/lib"])
        env["LD_LIBRARY_PATH"] = ld_extra + os.pathsep + env.get("LD_LIBRARY_PATH", "")

    env["PYTHONPATH"] = os.pathsep.join([project_dir, str(venv_site)])
    env["PYGPI_PYTHON_BIN"] = str(venv_python)
    env["PYGPI_PYTHON_LIB"] = _libpython_name(base_python)
    env["TOPLEVEL_LANG"] = "vhdl"

    vpi_lib = str(cocotb_libs / _vpi_lib_name())

    return env, vpi_lib


def launch_simulation(board_json, vhdl_path, toplevel="blinky",
                      generics=None, sim_width=1024, sim_height=700):
    """
    Launch an interactive GHDL + cocotb simulation.

    Runs GHDL with the VPI module, which loads cocotb, which imports
    sim_testbench.py which runs the pygame interactive loop.

    This call blocks until the simulation exits.
    """
    vhdl_path = Path(vhdl_path).resolve()
    work_dir = tempfile.mkdtemp(prefix="fpga_sim_run_")

    env, vpi_lib = _build_sim_env()

    # Analyze VHDL in work_dir
    ghdl = _find_ghdl()
    subprocess.run(
        [ghdl, "-a", "--std=08", "--workdir=" + work_dir, str(vhdl_path)],
        env=env, check=True, cwd=work_dir,
    )

    # Build ghdl -r command
    cmd = [ghdl, "-r", "--std=08", "--workdir=" + work_dir]

    for k, v in (generics or {}).items():
        cmd.append(f"-g{k}={v}")

    cmd.append(toplevel)
    cmd.append(f"--vpi={vpi_lib}")

    # Pass board definition and test module via env
    env["COCOTB_TEST_MODULES"] = "sim_testbench"
    env["TOPLEVEL"] = toplevel
    env["FPGA_SIM_BOARD_JSON"] = board_json
    env["FPGA_SIM_WIDTH"]  = str(sim_width)
    env["FPGA_SIM_HEIGHT"] = str(sim_height)

    print(f"Starting simulation: {toplevel} from {vhdl_path.name}")
    result = subprocess.run(cmd, env=env, cwd=work_dir)
    return result.returncode == 0
