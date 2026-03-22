"""sim_bridge.py – Manages VHDL analysis and launches interactive
cocotb simulations.

Supports two open-source simulators:
  * GHDL (default)  – VPI interface  (libcocotbvpi_ghdl.so)
  * NVC             – VHPI interface (libcocotbvhpi_nvc.so)

Handles the platform-specific PATH / PYTHONHOME / VPI/VHPI setup
so that the simulator can load the cocotb module and start Python.
Works on both Windows and Linux.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


# ── Simulator backend classes ─────────────────────────────────────────────────

class _GHDLBackend:
    """GHDL simulator backend – uses the VPI interface."""

    NAME = "ghdl"

    @staticmethod
    def find() -> str:
        return shutil.which("ghdl") or "ghdl"

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("ghdl"))

    @staticmethod
    def lib_dir() -> str:
        bin_path = Path(_GHDLBackend.find()).resolve().parent
        lib_dir = bin_path.parent / "lib"
        return str(lib_dir) if lib_dir.is_dir() else str(bin_path)

    @staticmethod
    def plugin_lib_name() -> str:
        return "cocotbvpi_ghdl.dll" if IS_WINDOWS else "libcocotbvpi_ghdl.so"

    @staticmethod
    def analyze_cmd(vhdl_path: Path, work_dir: str) -> list[str]:
        return [_GHDLBackend.find(), "-a", "--std=08",
                f"--workdir={work_dir}", str(vhdl_path)]

    @staticmethod
    def elaborate_cmd(toplevel: str, work_dir: str) -> list[str]:
        return [_GHDLBackend.find(), "-e", "--std=08",
                f"--workdir={work_dir}", toplevel]

    @staticmethod
    def run_cmd(toplevel: str, generics: dict[str, str], plugin_lib: str, work_dir: str) -> list[str]:
        cmd = [_GHDLBackend.find(), "-r", "--std=08", f"--workdir={work_dir}"]
        for k, v in (generics or {}).items():
            cmd.append(f"-g{k}={v}")
        cmd.append(toplevel)
        cmd.append(f"--vpi={plugin_lib}")
        return cmd

    @staticmethod
    def sim_bin_lib() -> tuple[str, str]:
        """Return (bin_dir, lib_dir) for environment setup."""
        return str(Path(_GHDLBackend.find()).resolve().parent), _GHDLBackend.lib_dir()


class _NVCBackend:
    """NVC VHDL simulator backend – uses the VHPI interface.

    Key differences from GHDL:
      - Uses ``--work=work:<path>`` instead of ``--workdir=<path>``
      - Uses ``--std=2008`` instead of ``--std=08``
      - Generics are passed at elaboration (``-e``) time, not at run (``-r``) time
      - Plugin loaded via ``--load=<lib>`` (VHPI) instead of ``--vpi=<lib>``
    """

    NAME = "nvc"

    @staticmethod
    def find() -> str:
        return shutil.which("nvc") or "nvc"

    @staticmethod
    def available() -> bool:
        return bool(shutil.which("nvc"))

    @staticmethod
    def lib_dir() -> str:
        bin_path = Path(_NVCBackend.find()).resolve().parent
        lib_dir = bin_path.parent / "lib"
        return str(lib_dir) if lib_dir.is_dir() else str(bin_path)

    @staticmethod
    def plugin_lib_name() -> str:
        return "cocotbvhpi_nvc.dll" if IS_WINDOWS else "libcocotbvhpi_nvc.so"

    @staticmethod
    def analyze_cmd(vhdl_path: Path, work_dir: str) -> list[str]:
        return [_NVCBackend.find(), f"--work=work:{work_dir}",
                "--std=2008", "-a", str(vhdl_path)]

    @staticmethod
    def elaborate_cmd(toplevel: str, generics: dict[str, str], work_dir: str) -> list[str]:
        """Elaborate with generics (NVC requires generics at elaboration time)."""
        cmd = [_NVCBackend.find(), f"--work=work:{work_dir}", "--std=2008", "-e"]
        for k, v in (generics or {}).items():
            cmd.extend(["-g", f"{k}={v}"])
        cmd.append(toplevel)
        return cmd

    @staticmethod
    def run_cmd(toplevel: str, plugin_lib: str, work_dir: str) -> list[str]:
        return [_NVCBackend.find(), f"--work=work:{work_dir}",
                "--std=2008", "-r", f"--load={plugin_lib}", toplevel]

    @staticmethod
    def sim_bin_lib() -> tuple[str, str]:
        """Return (bin_dir, lib_dir) for environment setup."""
        return str(Path(_NVCBackend.find()).resolve().parent), _NVCBackend.lib_dir()


def _backend(simulator: str) -> type[_GHDLBackend] | type[_NVCBackend]:
    """Return the backend class for the given simulator name."""
    return _NVCBackend if simulator == "nvc" else _GHDLBackend


# ── Public discovery ──────────────────────────────────────────────────────────

def _find_ghdl():
    """Locate the ghdl executable (kept for backward compatibility)."""
    return _GHDLBackend.find()


def detect_simulators() -> list[str]:
    """Return a list of installed simulator names, e.g. ['ghdl', 'nvc'].

    Always returns at least one entry; falls back to ['ghdl'] even when
    no simulator is found so the error surfaces at analysis time.
    """
    available = []
    if _GHDLBackend.available():
        available.append("ghdl")
    if _NVCBackend.available():
        available.append("nvc")
    return available or ["ghdl"]


# ── Shared helpers ────────────────────────────────────────────────────────────

def _venv_dirs(venv_dir: str | Path) -> tuple[Path, Path, Path]:
    """Return (scripts_dir, site_packages_dir, python_exe) for a venv."""
    venv_dir = Path(venv_dir)
    if IS_WINDOWS:
        scripts = venv_dir / "Scripts"
        site = venv_dir / "Lib" / "site-packages"
        python = scripts / "python.exe"
    else:
        scripts = venv_dir / "bin"
        site = (venv_dir / "lib"
                / f"python{sys.version_info.major}.{sys.version_info.minor}"
                / "site-packages")
        python = scripts / "python"
    return scripts, site, python


def _libpython_name(base_python: str) -> str:
    """Return the path to the Python shared library."""
    try:
        import find_libpython
        found = find_libpython.find_libpython()
        if found:
            return found
    except ImportError:
        pass
    if IS_WINDOWS:
        return str(Path(base_python)
                   / f"python{sys.version_info.major}{sys.version_info.minor}.dll")
    else:
        return str(Path(base_python) / "lib"
                   / f"libpython{sys.version_info.major}.{sys.version_info.minor}.so")


# ── VHDL validation (simulator-independent) ───────────────────────────────────

def check_vhdl_encoding(path: str | Path) -> tuple[bool, str]:
    """Stage 1: encoding check (no simulator needed).
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


def check_vhdl_contract(path: str | Path) -> tuple[bool, str]:
    """Stage 2: contract validation (text-based, no simulator needed).
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
            f"Rename the file to '{entities[0]}{path.suffix}' or rename the entity to '{stem}'."
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

    # Warn (non-fatal) about missing generics
    required_generics = ["NUM_SWITCHES", "NUM_BUTTONS", "NUM_LEDS", "COUNTER_BITS"]
    missing_generics = [g for g in required_generics
                        if not re.search(r'\b' + g + r'\b', text, re.IGNORECASE)]
    if missing_generics:
        print(f"[warn] Missing generics (will use VHDL defaults): {', '.join(missing_generics)}")

    return True, ""


# ── Simulation infrastructure ─────────────────────────────────────────────────

def analyze_vhdl(
    vhdl_path: str | Path,
    work_dir: str | None = None,
    toplevel: str | None = None,
    simulator: str = "ghdl",
) -> tuple[bool, str]:
    """Run analysis (and for GHDL, elaboration) on a VHDL file.

    GHDL: runs ``-a`` then ``-e`` (no generics needed at this stage).
    NVC:  runs ``-a`` only — elaboration is deferred to launch_simulation()
          because NVC requires generics at elaboration time.

    Returns (ok: bool, detail: str).  On success, detail is the work dir.
    """
    be = _backend(simulator)
    work_dir = work_dir or tempfile.mkdtemp(prefix="fpga_sim_")
    if toplevel is None:
        toplevel = Path(vhdl_path).stem
    try:
        result = subprocess.run(
            be.analyze_cmd(Path(vhdl_path), work_dir),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()

        if simulator == "ghdl":
            elab = subprocess.run(
                be.elaborate_cmd(toplevel, work_dir),  # type: ignore[call-arg,arg-type]
                capture_output=True, text=True, timeout=30,
            )
            if elab.returncode != 0:
                combined = (result.stderr + elab.stderr).strip()
                return False, combined or f"Elaboration failed for entity '{toplevel}'."

        return True, work_dir
    except FileNotFoundError:
        if simulator == "ghdl":
            hint = ("winget install ghdl.ghdl.ucrt64.mcode" if IS_WINDOWS
                    else "apt install ghdl  OR  brew install ghdl")
            return False, f"GHDL not found. Install: {hint}"
        else:
            hint = "brew install nvc  OR  build from source: https://github.com/nickg/nvc"
            return False, f"NVC not found. Install: {hint}"
    except subprocess.TimeoutExpired:
        return False, f"{simulator.upper()} analysis timed out."


def _build_sim_env(
    simulator: str = "ghdl",
    venv_dir: str | Path | None = None,
) -> tuple[dict[str, str], str]:
    """Build the environment dict needed for the simulator + cocotb VPI/VHPI.
    Returns (env_dict, plugin_lib_path).
    """
    venv_dir = Path(venv_dir or (Path(__file__).parent / ".venv"))
    venv_scripts, venv_site, venv_python = _venv_dirs(venv_dir)
    cocotb_libs = venv_site / "cocotb" / "libs"

    base_python = subprocess.run(
        [str(venv_python), "-c", "import sys; print(sys.base_exec_prefix)"],
        capture_output=True, text=True,
    ).stdout.strip()

    be = _backend(simulator)
    sim_bin, sim_lib = be.sim_bin_lib()
    plugin_lib = str(cocotb_libs / be.plugin_lib_name())

    project_dir = str(Path(__file__).parent.resolve())

    env = os.environ.copy()

    if IS_WINDOWS:
        extra_path = os.pathsep.join([
            str(venv_scripts), base_python, str(cocotb_libs),
            sim_lib, sim_bin,
        ])
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
        env["PYTHONHOME"] = base_python
    else:
        extra_path = os.pathsep.join([str(venv_scripts), sim_bin])
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
        ld_extra = os.pathsep.join([str(cocotb_libs), sim_lib, base_python + "/lib"])
        env["LD_LIBRARY_PATH"] = ld_extra + os.pathsep + env.get("LD_LIBRARY_PATH", "")

    env["PYTHONPATH"] = os.pathsep.join([project_dir, str(venv_site)])
    env["PYGPI_PYTHON_BIN"] = str(venv_python)
    env["PYGPI_PYTHON_LIB"] = _libpython_name(base_python)
    env["TOPLEVEL_LANG"] = "vhdl"

    return env, plugin_lib


def launch_simulation(
    board_json: str,
    vhdl_path: str | Path,
    toplevel: str = "blinky",
    generics: dict[str, str] | None = None,
    sim_width: int = 1024,
    sim_height: int = 700,
    work_dir: str | None = None,
    simulator: str = "ghdl",
) -> bool:
    """Launch an interactive simulator + cocotb simulation.

    GHDL: reuses analysis artifacts from analyze_vhdl(), passes generics
          inline on the ``-r`` run command.
    NVC:  elaborates with generics first (``-e``), then runs (``-r --load``).

    If work_dir is supplied (from a prior analyze_vhdl() call) the analysis
    step is skipped — existing artifacts are reused.

    This call blocks until the simulation exits.
    """
    vhdl_path = Path(vhdl_path).resolve()
    be = _backend(simulator)
    env, plugin_lib = _build_sim_env(simulator=simulator)
    generics = generics or {}

    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="fpga_sim_run_")
        subprocess.run(
            be.analyze_cmd(vhdl_path, work_dir),
            env=env, check=True, cwd=work_dir,
        )

    if simulator == "nvc":
        # NVC: elaborate with generics, then run (no generics at run time)
        subprocess.run(
            be.elaborate_cmd(toplevel, generics, work_dir),  # type: ignore[call-arg,arg-type]
            env=env, check=True, cwd=work_dir,
        )
        cmd = be.run_cmd(toplevel, plugin_lib, work_dir)  # type: ignore[call-arg,arg-type]
    else:
        # GHDL: run with generics inline
        cmd = be.run_cmd(toplevel, generics, plugin_lib, work_dir)  # type: ignore[call-arg,arg-type]

    env["COCOTB_TEST_MODULES"] = "sim_testbench"
    env["TOPLEVEL"] = toplevel
    env["FPGA_SIM_BOARD_JSON"] = board_json
    env["FPGA_SIM_WIDTH"]  = str(sim_width)
    env["FPGA_SIM_HEIGHT"] = str(sim_height)

    print(f"Starting simulation: {toplevel} from {vhdl_path.name} [{simulator.upper()}]")
    result = subprocess.run(cmd, env=env, cwd=work_dir)
    return result.returncode == 0
