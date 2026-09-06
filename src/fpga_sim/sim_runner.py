"""Starting the headless simulator child, and the environment it needs (U34, D17).

The last stage: everything analyzed, a wrapper on disk, and a run to start.
That means building an environment the simulator can actually load cocotb in --
PATH, ``LD_LIBRARY_PATH`` or its Windows equivalent, ``PYTHONHOME``,
``PYTHONPATH``, the VPI/VHPI plugin path and libpython itself, all derived from
the *selected* install rather than assumed -- then spawning the child and
holding the handle.

Since single-window (U34) the child is **headless**: it imports no pygame,
creates no window, and streams LED and segment state back over ``sim_link`` to
the launcher, which renders it.  :class:`SimChild` is that handle -- the link,
the process, and a stderr pump that keeps the last lines, so a crash can be
reported in the simulator's own words rather than as a return code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from fpga_sim.paths import REPO_ROOT, SIM_DIR, VENV_DIR
from fpga_sim.sim_backends import _backend
from fpga_sim.sim_config import (
    IS_WINDOWS,
    Simulator,
    WaveConfig,
)
from fpga_sim.sim_link import SimLinkHost, send
from fpga_sim.vhdl_interface import _has_rgb_generic, _has_seg_port
from fpga_sim.waveform import (
    WAVEFORM_ENV,
    WAVEFORM_MEMORIES_ENV,
    _announce_waveform,
    _env_flag,
    _normalize_wave,
    _waveform_path,
)
from fpga_sim.wrapper import _generate_wrapper

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef
    from fpga_sim.conventions import ConventionMatch

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
        site = (
            venv_dir
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )
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
        return str(
            Path(base_python) / f"python{sys.version_info.major}{sys.version_info.minor}.dll"
        )
    else:
        return str(
            Path(base_python)
            / "lib"
            / f"libpython{sys.version_info.major}.{sys.version_info.minor}.so"
        )


def _libpython_via_config(venv_scripts: Path) -> str:
    """Use cocotb-config --libpython to find the Python DLL on Windows.

    ``find_libpython`` may not locate the DLL when Python is installed via
    uv's standalone cache rather than a system installation.  The
    ``cocotb-config`` script, installed into the venv alongside cocotb,
    performs its own resolution and reliably returns the correct path.

    Returns an empty string if the script is absent, times out, or returns
    a path that does not exist on disk.
    """
    script = venv_scripts / "cocotb-config.exe"
    if not script.exists():
        return ""
    try:
        result = subprocess.run(
            [str(script), "--libpython"],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
        )
        path = result.stdout.strip()
        if result.returncode == 0 and path and Path(path).exists():
            return path
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def _build_sim_env(
    simulator: Simulator = "ghdl",
    venv_dir: str | Path | None = None,
    sim_path: str | None = None,
) -> tuple[dict[str, str], str]:
    """Build the environment dict needed for the simulator + cocotb VPI/VHPI.

    *sim_path* is the selected install's resolved binary (U35); the bin/lib dirs
    are derived from it so a non-PATH backend loads its own shared libraries.
    Returns (env_dict, plugin_lib_path).
    """
    venv_dir = Path(venv_dir or VENV_DIR)
    venv_scripts, venv_site, venv_python = _venv_dirs(venv_dir)
    cocotb_libs = venv_site / "cocotb" / "libs"

    base_python = subprocess.run(
        [str(venv_python), "-c", "import sys; print(sys.base_exec_prefix)"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()

    be = _backend(simulator)
    sim_bin, sim_lib = be.sim_bin_lib(sim_path)
    plugin_lib = str(cocotb_libs / be.plugin_lib_name())

    _src_dir = str(REPO_ROOT / "src")
    _sim_dir = str(SIM_DIR)

    env = os.environ.copy()

    if IS_WINDOWS:
        extra_path = os.pathsep.join(
            [
                str(venv_scripts),
                base_python,
                str(cocotb_libs),
                sim_lib,
                sim_bin,
            ]
        )
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
        env["PYTHONHOME"] = base_python
    else:
        extra_path = os.pathsep.join([str(venv_scripts), sim_bin])
        env["PATH"] = extra_path + os.pathsep + env.get("PATH", "")
        ld_extra = os.pathsep.join([str(cocotb_libs), sim_lib, base_python + "/lib"])
        env["LD_LIBRARY_PATH"] = ld_extra + os.pathsep + env.get("LD_LIBRARY_PATH", "")

    env["PYTHONPATH"] = os.pathsep.join([_sim_dir, _src_dir, str(venv_site)])
    env["PYGPI_PYTHON_BIN"] = str(venv_python)
    # On Windows, cocotb-config --libpython resolves the DLL path more reliably
    # than find_libpython when Python is installed via uv's standalone cache.
    if IS_WINDOWS:
        libpython = _libpython_via_config(venv_scripts) or _libpython_name(base_python)
    else:
        libpython = _libpython_name(base_python)
    env["PYGPI_PYTHON_LIB"] = libpython
    env["TOPLEVEL_LANG"] = "vhdl"

    return env, plugin_lib


# ── Run preparation for start_simulation ──────────────────────────────────────


@dataclass
class _SimPrep:
    """Analysis / elaboration / waveform prep for a headless run.

    Built by :func:`_prepare_simulation` and consumed by :func:`start_simulation`.
    ``env`` already carries the vars the child needs (board JSON + metrics
    metadata); :func:`start_simulation` adds the link vars before launching.
    """

    env: dict[str, str]
    cmd: list[str]
    work_dir: str
    generics: dict[str, str]
    wave_cfg: WaveConfig | None
    vhdl_path: Path


def _prepare_simulation(
    board_json: str,
    vhdl_path: str | Path,
    toplevel: str,
    generics: dict[str, str] | None,
    work_dir: str | None,
    simulator: Simulator,
    board_def: BoardDef | None,
    match: ConventionMatch | None,
    waveform: str | None,
    waveform_memories: bool | None,
    sim_path: str | None = None,
    generic_overrides: dict[str, str] | None = None,
) -> _SimPrep:
    """Analyze (if needed), elaborate (NVC), resolve waveform, build the run cmd.

    The prep :func:`start_simulation` runs before spawning the simulator,
    factored into its own helper.  The returned ``env`` holds the vars the
    headless testbench reads (board JSON + metrics metadata); the link vars are
    added by :func:`start_simulation`.  *sim_path* is the selected install's
    resolved binary (U35), threaded into every simulator invocation.
    """
    from fpga_sim.board_loader import BoardDef  # noqa: PLC0415

    vhdl_path = Path(vhdl_path).resolve()
    be = _backend(simulator)
    env, plugin_lib = _build_sim_env(simulator=simulator, sim_path=sim_path)
    generics = dict(generics or {})

    # Resolve board_def from JSON when not passed directly
    if board_def is None and board_json:
        try:
            board_def = BoardDef.from_json(board_json)
        except Exception:  # noqa: BLE001 - fall back to generic sizing
            pass

    # Detect seg port / RGB generic once; used for wrapper selection and
    # NUM_SEGS / NUM_RGB_LEDS injection.
    _vhdl_text = vhdl_path.read_text(encoding="utf-8", errors="ignore")
    _design_has_seg = _has_seg_port(_vhdl_text)
    _design_has_rgb = _has_rgb_generic(_vhdl_text)

    # Add NUM_SEGS generic only when both board and design use 7-seg
    if board_def is not None and board_def.seven_seg is not None and _design_has_seg:
        generics.setdefault("NUM_SEGS", str(board_def.seven_seg.num_digits))

    # NUM_RGB_LEDS is design-gated, not board-gated (U37): whenever the design
    # declares it the wrapper maps it, so it must always be set — 0 on a board
    # without RGB LEDs (which is why the contract requires `natural`).
    if _design_has_rgb:
        generics.setdefault("NUM_RGB_LEDS", str(board_def.num_rgb_leds if board_def else 0))

    if work_dir is None:
        # Fresh run: analyze user file and wrapper from scratch.
        work_dir = tempfile.mkdtemp(prefix="fpga_sim_run_")
        subprocess.run(
            be.analyze_cmd(vhdl_path, work_dir, binary=sim_path), env=env, check=True, cwd=work_dir
        )
        wrapper_path = _generate_wrapper(
            toplevel,
            work_dir,
            board_def=board_def,
            design_has_seg=_design_has_seg,
            match=match,
            design_has_rgb=_design_has_rgb,
            generic_overrides=generic_overrides,
        )
        subprocess.run(
            be.analyze_cmd(wrapper_path, work_dir, binary=sim_path),
            env=env,
            check=True,
            cwd=work_dir,
        )

    # NVC bakes generics into its elaboration artifact, so it re-elaborates with
    # the real values.  GHDL applies generics at -r, but its compiled backends
    # (llvm/gcc) need -e to emit the sim_wrapper executable that -r then runs —
    # in work_dir, where run_cmd's cwd looks for it.  For mcode/llvm-jit (in-
    # memory elaboration) this is a cheap structural re-check.
    elab = subprocess.run(
        be.elaborate_cmd(
            "sim_wrapper", generics if simulator == "nvc" else {}, work_dir, binary=sim_path
        ),
        env=env,
        capture_output=True,
        text=True,
        cwd=work_dir,
        encoding="utf-8",
        errors="replace",
    )
    if elab.returncode != 0:
        raise RuntimeError(elab.stderr.strip() or f"{simulator.upper()} elaboration failed.")

    # Resolve the optional waveform request (off unless enabled).  The env var
    # wins when set, so capture can be turned on headlessly / in CI (U29).
    wave_fmt = _normalize_wave(os.environ.get(WAVEFORM_ENV, "").strip() or waveform)
    wave_cfg: WaveConfig | None = None
    if wave_fmt is not None:
        wave_target = _waveform_path(toplevel, wave_fmt)
        wave_target.parent.mkdir(parents=True, exist_ok=True)
        # U30 "include memories": env wins over the session flag when set.
        env_mem = _env_flag(WAVEFORM_MEMORIES_ENV)
        dump_arrays = env_mem if env_mem is not None else bool(waveform_memories)
        wave_cfg = WaveConfig(str(wave_target), wave_fmt, dump_arrays=dump_arrays)

    # Both backends share the same run_cmd signature; NVC ignores generics (already baked in).
    cmd = be.run_cmd("sim_wrapper", generics, plugin_lib, work_dir, wave=wave_cfg, binary=sim_path)

    # Env vars both the legacy pygame testbench and the headless bridge read.
    env["TOPLEVEL"] = "sim_wrapper"
    env["FPGA_SIM_TOPLEVEL"] = toplevel  # user's entity, for display/metadata
    env["FPGA_SIM_BOARD_JSON"] = board_json
    env["FPGA_SIM_SIMULATOR"] = simulator
    env["FPGA_SIM_VHDL_PATH"] = str(vhdl_path)
    env["FPGA_SIM_GENERICS"] = json.dumps(generics)

    return _SimPrep(env, cmd, work_dir, generics, wave_cfg, vhdl_path)


# ── Single-window headless run handle (U34) ───────────────────────────────────

#: Lines of child stderr kept for the crash dialog.  The reader thread echoes
#: every line to the terminal (today's behavior) and rings this tail for a
#: post-mortem if the child dies before / during connect.
_STDERR_TAIL_LINES = 50


def _pump_stderr(pipe: IO[bytes] | None, tail: deque[str]) -> None:
    """Echo the child's stderr to our stderr and keep a tail ring for crash dialogs.

    Runs on a daemon thread for the child's lifetime; ends at EOF when the child
    closes its stderr (normally, on exit).
    """
    if pipe is None:
        return
    for raw in iter(pipe.readline, b""):
        line = raw.decode(errors="replace").rstrip("\n")
        tail.append(line)
        print(line, file=sys.stderr)
    pipe.close()


@dataclass
class SimChild:
    """Handle for a running headless simulation subprocess (single-window mode).

    :func:`start_simulation` returns one of these instead of blocking: the
    launcher keeps rendering its window and streams signal state over
    :attr:`link` while the child runs headless.  :func:`finish_waveform` consumes
    the capture fields after the run; the UI reads :attr:`link` for live state
    and, on a crash, :attr:`stderr_tail`.
    """

    proc: subprocess.Popen[bytes]
    link: SimLinkHost
    wave_cfg: WaveConfig | None
    generics: dict[str, str]  # finish_waveform needs these for the .gtkw sidecar
    match: ConventionMatch | None
    stderr_tail: deque[str]  # filled by the reader thread
    #: Resolved session auto-open preference; the env var still wins in finish_waveform.
    waveform_open: bool | None = None

    def poll(self) -> int | None:
        """Return the child's exit code, or None while it is still running."""
        return self.proc.poll()

    def stop(self, timeout: float = 5.0) -> int:
        """Stop the child: ``stop`` message -> bounded wait -> terminate -> kill.

        Returns the process exit code.  Safe to call whether or not the child
        ever connected, and more than once.  GHDL/NVC exit codes are unreliable
        on a clean stop, so callers must not infer failure from the return value
        -- use a received ``bye`` / requested-stop instead (see the experiment doc).
        """
        rc = self.proc.poll()
        if rc is not None:
            self.link.close()
            return rc
        # Ask nicely over the link (skipped when the child never connected).
        try:
            if self.link.wait_connected(0.0):
                send(self.link.conn, "stop", {})
        except (RuntimeError, OSError):
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            rc = self.proc.poll()
            if rc is not None:
                self.link.close()
                return rc
            time.sleep(0.02)
        # Still alive after the grace period: escalate.
        self.proc.terminate()
        try:
            rc = self.proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            rc = self.proc.wait()
        self.link.close()
        return rc


def start_simulation(
    board_json: str,
    vhdl_path: str | Path,
    toplevel: str = "blinky",
    generics: dict[str, str] | None = None,
    work_dir: str | None = None,
    simulator: Simulator = "ghdl",
    board_def: BoardDef | None = None,
    speed_factor: float | None = None,
    waveform: str | None = None,
    waveform_open: bool | None = None,
    waveform_memories: bool | None = None,
    match: ConventionMatch | None = None,
    benchmark_secs: float | None = None,
    sim_path: str | None = None,
    generic_overrides: dict[str, str] | None = None,
) -> SimChild:
    """Start a headless simulation child for single-window mode (U34).

    Runs analysis / elaboration / waveform preparation (via
    :func:`_prepare_simulation`), then runs ``sim_testbench`` with no display and
    streams signal state over a :class:`~fpga_sim.sim_link.SimLinkHost` instead of
    opening a window and blocking.  Returns a :class:`SimChild` immediately; the
    caller (the SimulationScreen, or the benchmark) drives the link and calls
    :meth:`SimChild.stop` + :func:`finish_waveform` when done.

    *speed_factor* seeds the child's pacing via ``FPGA_SIM_SPEED`` (the host
    still sends ``speed`` on any slider change).  *benchmark_secs*, when set,
    makes the child free-run (no pacing) for that many wall seconds and then
    self-stop -- used by ``--benchmark`` and the e2e tests.
    """
    prep = _prepare_simulation(
        board_json,
        vhdl_path,
        toplevel,
        generics,
        work_dir,
        simulator,
        board_def,
        match,
        waveform,
        waveform_memories,
        sim_path=sim_path,
        generic_overrides=generic_overrides,
    )
    env = prep.env

    # The link the child connects back to (its listener accepts in the background).
    host = SimLinkHost()
    env.update(host.env_vars())
    env["COCOTB_TEST_MODULES"] = "sim_testbench"
    if speed_factor is not None:
        env["FPGA_SIM_SPEED"] = str(speed_factor)  # pacing seed; avoids a wrong-speed blip
    env.pop("FPGA_SIM_BENCHMARK", None)
    if benchmark_secs is not None and benchmark_secs > 0:
        env["FPGA_SIM_BENCHMARK"] = str(benchmark_secs)  # child free-runs then self-stops

    print(
        f"Starting headless simulation: {toplevel} from {prep.vhdl_path.name} [{simulator.upper()}]"
    )
    proc = subprocess.Popen(prep.cmd, env=env, cwd=prep.work_dir, stderr=subprocess.PIPE)
    tail: deque[str] = deque(maxlen=_STDERR_TAIL_LINES)
    threading.Thread(
        target=_pump_stderr, args=(proc.stderr, tail), daemon=True, name="sim-stderr"
    ).start()
    return SimChild(
        proc=proc,
        link=host,
        wave_cfg=prep.wave_cfg,
        generics=prep.generics,
        match=match,
        stderr_tail=tail,
        waveform_open=waveform_open,
    )


def finish_waveform(child: SimChild) -> None:
    """Run the post-run waveform tail for a finished headless *child*.

    Writes the U28 ``.gtkw`` sidecar, prints the "Waveform written" hint, and
    optionally auto-opens the viewer.  A no-op when capture was off or the dump
    is missing/empty.  Fed entirely from :class:`SimChild` fields, so the caller
    runs it after :meth:`SimChild.stop`.
    """
    _announce_waveform(child.wave_cfg, child.generics, child.match, child.waveform_open)
