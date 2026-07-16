"""sim_bridge.py – Manages VHDL analysis and launches interactive cocotb simulations.

Supports two open-source simulators:
  * GHDL (default)  – VPI interface  (libcocotbvpi_ghdl.so)
  * NVC             – VHPI interface (libcocotbvhpi_nvc.so)

Handles the platform-specific PATH / PYTHONHOME / VPI/VHPI setup
so that the simulator can load the cocotb module and start Python.
Works on both Windows and Linux.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal

from fpga_sim.platform_open import open_with_default_app
from fpga_sim.sim_link import SimLinkHost, send

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef

IS_WINDOWS = sys.platform == "win32"

# Supported simulator backend identifiers.  Using a Literal (rather than a bare
# ``str``) lets mypy reject typos such as ``_backend("gdhl")`` at type-check
# time and gives the simulator domain a single source of truth.  Extend this
# with ``"iverilog"`` when Verilog support (U20) lands.
Simulator = Literal["ghdl", "nvc"]

# Waveform-capture formats the sim run subprocess can dump natively.  ``None``
# (off) is the default throughout; the Settings dialog persists a tri-state
# ``waveform`` session key — ``"off"`` / ``"vcd"`` / ``"fst"`` — which
# ``launch_simulation`` normalizes via :func:`_normalize_wave`.
WaveFormat = Literal["vcd", "fst"]


@dataclass(frozen=True)
class WaveConfig:
    """A resolved waveform-capture request: output path + format + array depth.

    Handed to a backend's ``run_cmd`` when the user enabled capture.  GHDL and
    NVC spell the flags differently (``--vcd=`` / ``--fst=`` after the toplevel
    vs. ``--wave=`` + ``--format=`` before it), so only the abstract format is
    stored here and each backend renders its own flags.

    *dump_arrays* is the U30 "include memories" depth: when set, nested arrays
    and memories (the embedded-core designs' RAM/ROM/registers) are captured
    too.  It is **NVC-only**: NVC skips nested arrays in every format (VCD and
    FST) unless given ``--dump-arrays``, whereas GHDL's FST/GHW writers include
    them by default — so ``_GHDLBackend.run_cmd`` ignores the field.  (GHDL's
    *VCD* writer omits memories with or without a flag; a VCD *can* hold one,
    flattened to a vector var per element, which NVC's VCD writer emits under
    ``--dump-arrays`` but GHDL's does not.)  Off by default, since arrays add
    significant size (see roadmap P13).
    """

    path: str
    fmt: WaveFormat
    dump_arrays: bool = False


class SimExit(Enum):
    """Why the interactive simulation ended — the U7 navigation contract.

    The values are the exact strings ``sim_testbench`` writes to the
    exit-intent file (the path in ``FPGA_SIM_EXIT_INTENT_FILE``) when one of
    the in-simulation toolbar buttons ends the run; nothing is written for a
    plain stop.  :func:`launch_simulation` reads the file back and returns the
    member, so the launcher can route to the selector / picker / a relaunch
    without the subprocess ever touching launcher state.

    A sidecar file is used rather than the process return code: GHDL and NVC
    own their exit codes, so overloading them would conflate "crashed with
    code N" and "user chose action N".  The file is trusted only for a clean
    (returncode 0) exit.
    """

    STOPPED = "stopped"  # ESC / [Stop] (+ legacy window close) — no intent file
    BACK_TO_BOARDS = "back_to_boards"  # [Back to Boards] → board selector
    CHANGE_VHDL = "change_vhdl"  # [Change VHDL] → VHDL file picker
    RELOAD_VHDL = "reload_vhdl"  # [Reload VHDL] → re-analyze same file, relaunch
    QUIT = "quit"  # window X in single-window mode (U34) → exit the whole app


#: Filename of the exit-intent sidecar inside the simulation work dir.
_EXIT_INTENT_NAME = "exit_intent.txt"


def _read_exit_intent(intent_file: Path, returncode: int) -> SimExit:
    """Map a finished sim subprocess to a :class:`SimExit`.

    The intent file is honored only for a clean (*returncode* 0) exit; a
    missing file, an unknown value, or a failed subprocess all mean STOPPED —
    a crash must never be treated as navigation.
    """
    if returncode != 0:
        return SimExit.STOPPED
    try:
        intent = SimExit(intent_file.read_text().strip())
    except (OSError, ValueError):
        return SimExit.STOPPED
    # QUIT is a single-window-only signal (window X, U34); the legacy testbench
    # never writes it to the intent file, so treat a stray "quit" as a plain stop.
    return SimExit.STOPPED if intent is SimExit.QUIT else intent


# ── Simulator backend classes ─────────────────────────────────────────────────


class _SimBackend(ABC):
    """Abstract base for simulator backends.

    The four discovery helpers (``find`` / ``available`` / ``lib_dir`` /
    ``sim_bin_lib``) are shared here: they read ``cls.NAME`` and call
    ``cls.find()``, which works for any backend whose executable name equals its
    ``NAME``.  Subclasses override only ``NAME`` plus the per-simulator command
    builders (``plugin_lib_name`` / ``analyze_cmd`` / ``elaborate_cmd`` /
    ``run_cmd``).  Backends are used as classes, never instantiated.
    """

    NAME: Simulator

    # Shared discovery — the executable name equals NAME for every backend.
    @classmethod
    def find(cls) -> str:
        return shutil.which(cls.NAME) or cls.NAME

    @classmethod
    def available(cls) -> bool:
        return bool(shutil.which(cls.NAME))

    @classmethod
    def lib_dir(cls) -> str:
        bin_path = Path(cls.find()).resolve().parent
        lib_dir = bin_path.parent / "lib"
        return str(lib_dir) if lib_dir.is_dir() else str(bin_path)

    @classmethod
    def sim_bin_lib(cls) -> tuple[str, str]:
        """Return (bin_dir, lib_dir) for environment setup."""
        return str(Path(cls.find()).resolve().parent), cls.lib_dir()

    # Per-simulator specifics — subclasses must override.
    @staticmethod
    @abstractmethod
    def plugin_lib_name() -> str: ...

    @staticmethod
    @abstractmethod
    def analyze_cmd(vhdl_path: Path, work_dir: str) -> list[str]: ...

    @staticmethod
    @abstractmethod
    def elaborate_cmd(toplevel: str, generics: dict[str, str], work_dir: str) -> list[str]: ...

    @staticmethod
    @abstractmethod
    def run_cmd(
        toplevel: str,
        generics: dict[str, str],
        plugin_lib: str,
        work_dir: str,
        wave: WaveConfig | None = None,
    ) -> list[str]: ...


class _GHDLBackend(_SimBackend):
    """GHDL simulator backend – uses the VPI interface."""

    NAME: Simulator = "ghdl"

    @staticmethod
    def plugin_lib_name() -> str:
        return "cocotbvpi_ghdl.dll" if IS_WINDOWS else "libcocotbvpi_ghdl.so"

    @staticmethod
    def analyze_cmd(vhdl_path: Path, work_dir: str) -> list[str]:
        return [_GHDLBackend.find(), "-a", "--std=08", f"--workdir={work_dir}", str(vhdl_path)]

    @staticmethod
    def elaborate_cmd(toplevel: str, generics: dict[str, str], work_dir: str) -> list[str]:
        # GHDL ignores generics here — they are applied at run (-r) time.
        return [_GHDLBackend.find(), "-e", "--std=08", f"--workdir={work_dir}", toplevel]

    @staticmethod
    def run_cmd(
        toplevel: str,
        generics: dict[str, str],
        plugin_lib: str,
        work_dir: str,
        wave: WaveConfig | None = None,
    ) -> list[str]:
        cmd = [_GHDLBackend.find(), "-r", "--std=08", f"--workdir={work_dir}"]
        for k, v in (generics or {}).items():
            cmd.append(f"-g{k}={v}")
        cmd.append(toplevel)
        cmd.append(f"--vpi={plugin_lib}")
        if wave is not None:
            # GHDL simulation options follow the toplevel (like --vpi); the dump
            # format is chosen by the flag name itself (--vcd= / --fst=).
            cmd.append(f"--{wave.fmt}={wave.path}")
            # wave.dump_arrays (U30) needs no flag here: GHDL's FST/GHW writers
            # dump nested arrays/memories by default (its VCD writer omits them,
            # with or without a flag).  The opt-in is NVC-only.
        return cmd


# NVC's global heap defaults to 16 MB, which large designs (deep hierarchies,
# many instances) exhaust mid-elaboration — aborting with a cryptic
# ``** Fatal: (init): out of memory ... increase with the -H option``.  ``-H``
# raises the cap for the design-building phases (``-e`` / ``-r``).  It is a
# ceiling the heap grows into on demand, not an up-front reservation: measured
# peak RSS for a trivial design is unchanged within ~1 MB (only page-table
# metadata scales with the cap).  512m clears NVC's GC high-water mark even for
# very large designs (a synthetic 64-hart RISC-V array needed only ~256m); past
# this the *design-unit* heap (``-M``) limit dominates, so a larger ``-H`` alone
# would not help.  GHDL has no equivalent limit.
_NVC_HEAP = "512m"


class _NVCBackend(_SimBackend):
    """NVC VHDL simulator backend – uses the VHPI interface.

    Key differences from GHDL:
      - Uses ``--work=work:<path>`` instead of ``--workdir=<path>``
      - Uses ``--std=2008`` instead of ``--std=08``
      - Generics are passed at elaboration (``-e``) time, not at run (``-r``) time
      - Plugin loaded via ``--load=<lib>`` (VHPI) instead of ``--vpi=<lib>``
      - Raises the elaboration/run heap cap via ``-H`` (see :data:`_NVC_HEAP`)
    """

    NAME: Simulator = "nvc"

    @staticmethod
    def plugin_lib_name() -> str:
        return "cocotbvhpi_nvc.dll" if IS_WINDOWS else "libcocotbvhpi_nvc.so"

    @staticmethod
    def analyze_cmd(vhdl_path: Path, work_dir: str) -> list[str]:
        return [_NVCBackend.find(), f"--work=work:{work_dir}", "--std=2008", "-a", str(vhdl_path)]

    @staticmethod
    def elaborate_cmd(toplevel: str, generics: dict[str, str], work_dir: str) -> list[str]:
        """Elaborate with generics (NVC requires generics at elaboration time)."""
        cmd = [_NVCBackend.find(), f"--work=work:{work_dir}", "--std=2008", "-H", _NVC_HEAP, "-e"]
        for k, v in (generics or {}).items():
            cmd.extend(["-g", f"{k}={v}"])
        cmd.append(toplevel)
        return cmd

    @staticmethod
    def run_cmd(
        toplevel: str,
        generics: dict[str, str],
        plugin_lib: str,
        work_dir: str,
        wave: WaveConfig | None = None,
    ) -> list[str]:
        # generics were baked in at elaboration (-e); ignored here
        cmd = [
            _NVCBackend.find(),
            f"--work=work:{work_dir}",
            "--std=2008",
            "-H",
            _NVC_HEAP,
            "-r",
            f"--load={plugin_lib}",
        ]
        if wave is not None:
            # NVC run options precede the toplevel; format is an explicit flag.
            cmd += [f"--wave={wave.path}", f"--format={wave.fmt}"]
            if wave.dump_arrays:
                # U30: NVC skips nested arrays/memories by default; opt them in so
                # the embedded-core designs' RAM/ROM/registers land in the trace.
                cmd.append("--dump-arrays")
        cmd.append(toplevel)
        return cmd


def _backend(simulator: Simulator) -> type[_SimBackend]:
    """Return the backend class for the given simulator name."""
    return _NVCBackend if simulator == "nvc" else _GHDLBackend


# ── Public discovery ──────────────────────────────────────────────────────────


def _find_ghdl() -> str:
    """Locate the ghdl executable (kept for backward compatibility)."""
    return _GHDLBackend.find()


def detect_simulators() -> list[Simulator]:
    """Return a list of installed simulator names, e.g. ['ghdl', 'nvc'].

    Always returns at least one entry; falls back to ['ghdl'] even when
    no simulator is found so the error surfaces at analysis time.
    """
    available: list[Simulator] = []
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
        )
        path = result.stdout.strip()
        if result.returncode == 0 and path and Path(path).exists():
            return path
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


# ── VHDL validation (simulator-independent) ───────────────────────────────────


def _has_seg_port(vhdl_text: str) -> bool:
    """Return True if the VHDL text declares a 'seg' output port."""
    return bool(re.search(r"\bseg\s*:\s*out\b", vhdl_text, re.IGNORECASE))


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


# ── Toplevel-interface parsing (contract checks + contextual hints, U4) ──────

_REQUIRED_PORTS = ("clk", "sw", "btn", "led")
_CONTRACT_PORTS = ("clk", "sw", "btn", "led", "seg")
_REQUIRED_GENERICS = ("NUM_SWITCHES", "NUM_BUTTONS", "NUM_LEDS", "COUNTER_BITS")
_PORT_MODES = {"clk": "in", "sw": "in", "btn": "in", "led": "out", "seg": "out"}
_PORT_SNIPPETS = {
    "clk": "clk : in  std_logic",
    "sw": "sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0)",
    "btn": "btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0)",
    "led": "led : out std_logic_vector(NUM_LEDS - 1 downto 0)",
    "seg": "seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)",
}
_PORT_GENERIC = {"sw": "NUM_SWITCHES", "btn": "NUM_BUTTONS", "led": "NUM_LEDS"}
# Port widths produced by sim_wrapper_template.vhd's generic defaults (all 4;
# seg = 8 * 4).  A fixed-width port passes the early elaboration check only at
# exactly these widths, because that check runs with the VHDL defaults.
_WRAPPER_DEFAULT_WIDTHS = {"sw": 4, "btn": 4, "led": 4, "seg": 32}


@dataclass
class _IfaceDecl:
    """One `names : [mode] type [:= default]` declaration from a port/generic clause."""

    names: list[str]  # lowercased identifiers
    mode: str  # "in"/"out"/"inout"/"buffer"/"linkage"; "" for generics
    has_default: bool
    literal_width: int | None  # std_logic_vector with pure-literal bounds, else None


def _strip_vhdl_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _entity_block(text: str, name: str) -> str | None:
    """Return the text between ``entity <name> is`` and its first ``end``."""
    m = re.search(rf"\bentity\s+{re.escape(name)}\s+is\b", text, re.IGNORECASE)
    if m is None:
        return None
    tail = text[m.end() :]
    e = re.search(r"\bend\b", tail, re.IGNORECASE)
    return tail[: e.start()] if e else None


def _clause_body(text: str, keyword: str) -> str | None:
    """Return the balanced parenthesized body of ``<keyword> ( ... )``, or None."""
    m = re.search(rf"\b{keyword}\s*\(", text, re.IGNORECASE)
    if m is None:
        return None
    depth, start = 1, m.end()
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return None  # unbalanced


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split on *sep* occurrences that are outside any parentheses."""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for c in text:
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


def _parse_decls(body: str, *, ports: bool) -> list[_IfaceDecl] | None:
    """Parse a port/generic clause body into declarations; None if unparseable."""
    decls: list[_IfaceDecl] = []
    for part in _split_top_level(body, ";"):
        part = part.strip()
        if not part:
            continue
        head, colon, rest = part.partition(":")
        if not colon:
            return None
        names = [n.strip().lower() for n in head.split(",")]
        if not names or not all(re.fullmatch(r"[a-z_]\w*", n) for n in names):
            return None
        rest = rest.strip()
        mode = ""
        if ports:
            m = re.match(r"(in|out|inout|buffer|linkage)\b", rest, re.IGNORECASE)
            mode = m.group(1).lower() if m else "in"  # implicit port mode is IN
            if m:
                rest = rest[m.end() :].strip()
        type_text = rest.split(":=")[0].strip()
        literal_width = None
        wm = re.fullmatch(
            r"std_logic_vector\s*\(\s*(\d+)\s+(downto|to)\s+(\d+)\s*\)",
            type_text,
            re.IGNORECASE,
        )
        if wm:
            a, kw, b = int(wm.group(1)), wm.group(2).lower(), int(wm.group(3))
            span = a - b if kw == "downto" else b - a
            if span >= 0:
                literal_width = span + 1
        decls.append(_IfaceDecl(names, mode, ":=" in rest, literal_width))
    return decls


def _parse_toplevel_interface(
    text: str, entity_name: str
) -> tuple[list[_IfaceDecl], list[_IfaceDecl]] | None:
    """Parse the toplevel entity's (ports, generics); None if unparseable.

    Scoped to ``entity <entity_name> is … end`` so inner entities of
    multi-entity files (e.g. the embedded-core designs) are never inspected.
    """
    block = _entity_block(_strip_vhdl_comments(text), entity_name)
    if block is None:
        return None
    gbody = _clause_body(block, "generic")
    pbody = _clause_body(block, "port")
    if pbody is None:
        return None
    generics = _parse_decls(gbody, ports=False) if gbody is not None else []
    ports = _parse_decls(pbody, ports=True)
    if ports is None or generics is None:
        return None
    return ports, generics


def _board_port_widths(board_def: BoardDef | None) -> dict[str, int]:
    """Effective wrapper port widths for *board_def*.

    Mirrors ``controller.build_generics()``: resource counts are floored at 1
    (the wrapper's vectors cannot be empty) and ``seg`` is 8 bits per digit.
    """
    if board_def is None:
        return {}
    widths = {
        "sw": max(1, len(board_def.switches)),
        "btn": max(1, len(board_def.buttons)),
        "led": max(1, len(board_def.leds)),
    }
    if board_def.seven_seg is not None:
        widths["seg"] = 8 * board_def.seven_seg.num_digits
    return widths


def _plural(n: int, noun: str) -> str:
    if noun.endswith("h"):  # switch → switches
        return f"{n} {noun}es" if n != 1 else f"{n} {noun}"
    return f"{n} {noun}s" if n != 1 else f"{n} {noun}"


def _check_parsed_contract(
    filename: str,
    ports: list[_IfaceDecl],
    generics: list[_IfaceDecl],
    board_def: BoardDef | None,
) -> tuple[bool, str]:
    """Contract rules over a parsed toplevel interface (helper of check_vhdl_contract)."""
    port_by_name = {n: d for d in ports for n in d.names}
    generic_names = {n for d in generics for n in d.names}
    has_seg = "seg" in port_by_name
    board_7seg = board_def is not None and board_def.seven_seg is not None

    # Required ports
    missing_ports = [p for p in _REQUIRED_PORTS if p not in port_by_name]
    if missing_ports:
        snippet = "\n".join(f"  {_PORT_SNIPPETS[p]};" for p in _REQUIRED_PORTS)
        return False, (
            f"Missing required port(s) in '{filename}': {', '.join(missing_ports)}.\n"
            "The top-level entity must declare:\n"
            f"{snippet}\n"
            "(plus  seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)  to drive a "
            "7-segment display)."
        )

    # Port directions.  Both GHDL and NVC silently accept a wrong-direction
    # contract port (the wrapper's output is simply never driven), so this
    # textual check is the only guard against e.g. `led : in ...`.
    for name in _CONTRACT_PORTS:
        decl = port_by_name.get(name)
        if decl is not None and decl.mode != _PORT_MODES[name]:
            return False, (
                f"Port '{name}' must be mode {_PORT_MODES[name].upper()} but is declared "
                f"{decl.mode.upper()} in '{filename}'.\n"
                f"Declare it as:  {_PORT_SNIPPETS[name]}\n"
                "The board drives clk/sw/btn into the design; led/seg are outputs it displays."
            )

    # NUM_SEGS without a seg port is a contract error: the generic is meaningless alone
    if "num_segs" in generic_names and not has_seg:
        return False, (
            f"'{filename}' declares NUM_SEGS generic but has no 'seg' output port.\n"
            "Add:  seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)"
        )

    # seg port without NUM_SEGS: fatal on 7-seg boards (the 7-seg wrapper maps it)
    if has_seg and board_7seg and "num_segs" not in generic_names:
        assert board_def is not None and board_def.seven_seg is not None
        digits = board_def.seven_seg.num_digits
        return False, (
            f"'{filename}' has a 'seg' port but no NUM_SEGS generic, which "
            f"{board_def.name}'s 7-segment display requires.\n"
            "Add to the generic clause:  NUM_SEGS : positive := 4\n"
            f"(the simulator sets NUM_SEGS={digits} for this board at launch)."
        )

    # Required generics.  The wrapper maps all four unconditionally, so a
    # missing one always fails analysis with a cryptic sim_wrapper.vhd error —
    # report it here with the fix instead.
    missing_generics = [g for g in _REQUIRED_GENERICS if g.lower() not in generic_names]
    if missing_generics:
        lines = [
            "  generic (",
            "    NUM_SWITCHES : positive := 4;",
            "    NUM_BUTTONS  : positive := 4;",
            "    NUM_LEDS     : positive := 4;",
        ]
        if has_seg:
            lines.append("    NUM_SEGS     : positive := 4;")
        lines += ["    COUNTER_BITS : positive := 24", "  );"]
        return False, (
            f"Missing required generic(s) in '{filename}': {', '.join(missing_generics)}.\n"
            "The simulator sizes the design to the board by overriding these at launch, "
            "so the entity must declare them all:\n" + "\n".join(lines)
        )

    # Extra inputs the simulator cannot drive, and generics it will not set:
    # both need a default value or the wrapper instantiation fails.
    for decl in ports:
        for name in decl.names:
            if name in _CONTRACT_PORTS or decl.mode not in ("in", "inout") or decl.has_default:
                continue
            return False, (
                f"Port '{name}' in '{filename}' is not part of the simulator contract "
                "(clk, sw, btn, led, seg), so nothing drives it.\n"
                f"Give it a default value — e.g.  {name} : in std_logic := '0'  — "
                "or remove it."
            )
    known_generics = {g.lower() for g in _REQUIRED_GENERICS} | {"num_segs"}
    for decl in generics:
        for name in decl.names:
            if name not in known_generics and not decl.has_default:
                return False, (
                    f"Generic '{name}' in '{filename}' is not set by the simulator "
                    "(it sets only NUM_SWITCHES, NUM_BUTTONS, NUM_LEDS, NUM_SEGS and "
                    "COUNTER_BITS).\n"
                    f"Give it a default value, e.g.  {name} : positive := 1"
                )

    # Fixed-literal port widths, judged against this board's resources
    widths = _board_port_widths(board_def)
    for name in ("sw", "btn", "led", "seg"):
        decl = port_by_name.get(name)
        if decl is None or decl.literal_width is None or name not in widths:
            continue  # generic-sized, absent, no board, or seg on a board without 7-seg
        expected = widths[name]
        found = decl.literal_width
        assert board_def is not None
        if name == "seg":
            assert board_def.seven_seg is not None
            digits = board_def.seven_seg.num_digits
            have = f"a {digits}-digit 7-segment display (8 * {digits} = {expected} bits)"
            generic_ref = f"NUM_SEGS={digits}"
        else:
            noun = {"sw": "switch", "btn": "button", "led": "LED"}[name]
            have = _plural(expected, noun)
            generic_ref = f"{_PORT_GENERIC[name]}={expected}"
        if found != expected:
            return False, (
                f"Port '{name}' is a fixed {found} bits wide, but {board_def.name} has "
                f"{have}.\n"
                f"The simulator sets {generic_ref} for this board — declare the port as\n"
                f"  {_PORT_SNIPPETS[name]}\n"
                "so the design fits any board."
            )
        if found != _WRAPPER_DEFAULT_WIDTHS[name]:
            # Matches this board, but the pre-launch elaboration check runs with
            # the generic defaults (4 / 4 / 4 / 8*4), so a fixed width ≠ default
            # still fails validation — and would break on any other board.
            return False, (
                f"Port '{name}' is a fixed {found} bits wide. That matches "
                f"{board_def.name} ({have}), but fixed-width ports fail the simulator's "
                "validation and break on other boards.\n"
                f"Declare the port as\n  {_PORT_SNIPPETS[name]}"
            )

    return True, ""


# ── Board-native port-convention matcher (U21) ───────────────────────────────
#
# A board-native VHDL file uses the *board's* port names and fixed widths (e.g.
# DE10-Standard's CLOCK_50 / SW / KEY / LEDR / HEX0..5) instead of the
# simulator's generic clk/sw/btn/led[/seg] contract with NUM_* generics.  These
# fail `_check_parsed_contract` (no `clk`/`btn`/`led`), so when that happens we
# try to recognize the design against the selected board's `port_conventions`.
#
# A full match returns `ok=True` with a `ConventionMatch` on the result, and the
# native wrapper (`_render_native_wrapper`) adapts the design's own port names --
# polarity inversion, zero-extend, per-digit 7-seg packing -- onto the
# simulator's sw/btn/led[/seg] boundary, so the cocotb testbench and run
# mechanics are unchanged.  A partial (near-miss) match is reported precisely
# and rejected, never silently coerced.  The badge and session log consume the
# match too.


@dataclass(frozen=True)
class NativePort:
    """A matched native LED/switch/button bank for one contract role.

    ``names`` holds the board-native port name(s) (original case, as spelled in
    the convention): a single entry for a shared vector (e.g. ``("LEDR",)``) or
    several for a bank of distinct scalar ports (e.g. Nandland Go's
    ``("o_LED_1", ...)``).  ``width`` is the vector width or the scalar count.

    ``scalar_ports`` marks a bank whose ``names`` are each an individual scalar
    port (``std_logic``) rather than one shared vector: either a ``names[]``
    cluster, or a width-1 vector bank the design spelled as a plain scalar (the
    natural ``led : out std_logic`` on a one-LED board).  It -- not
    ``len(names)`` -- drives the per-bit vs whole-vector choice in the wrapper
    port map and the ``.gtkw`` writer, so a single-member scalar cluster is
    handled correctly too.
    """

    names: tuple[str, ...]
    width: int
    active_low: bool = False
    scalar_ports: bool = False


@dataclass(frozen=True)
class NativeSeg:
    """A matched native 7-segment interface (B2 in-scope: ``individual`` style).

    ``names`` are the per-digit port names (e.g. ``("HEX0", ..., "HEX5")``), each
    a ``width_per_digit``-bit vector.  ``digit_enable`` is unused by the in-scope
    styles (it belongs to the ``scan`` style, which B2 declines).
    """

    style: str
    names: tuple[str, ...]
    width_per_digit: int
    active_low: bool = False
    digit_enable: NativePort | None = None


@dataclass(frozen=True)
class ConventionMatch:
    """A design recognized as board-native, with everything B3 needs to wrap it.

    Names are the board-native identifiers from the convention (original case);
    VHDL is case-insensitive, so B3 can emit them verbatim.
    """

    maker: str  # convention slug, e.g. "terasic"
    board_name: str  # BoardDef.name, for messages/badge
    clk: str  # native clock port name, e.g. "CLOCK_50"
    leds: NativePort
    # switches/buttons are optional (U31): a switch-less or button-less board's
    # convention simply omits the role, so the design need not declare it (clk +
    # LEDs are the minimum meaningful board-native demo).
    switches: NativePort | None = None
    buttons: NativePort | None = None
    seven_seg: NativeSeg | None = None
    leds_green: NativePort | None = None  # optional secondary LED bank (e.g. LEDG)


@dataclass(frozen=True)
class ContractResult:
    """Outcome of :func:`check_vhdl_contract`.

    ``ok``/``message`` mirror the former ``(bool, str)`` tuple; ``match`` is the
    board-native recognition (U21) when the design uses a board's native port
    convention — populated even while ``ok`` is False (native execution is B3).
    """

    ok: bool
    message: str = ""
    match: ConventionMatch | None = None


@dataclass(frozen=True)
class _ConventionAttempt:
    """Result of trying one convention block: a full match, or the near-miss detail."""

    maker: str
    board_name: str
    match: ConventionMatch | None  # a complete board-native match, else None
    matched_roles: tuple[str, ...]  # role tags that matched (near-miss scoring)
    problems: tuple[str, ...]  # human-readable missing/mismatched roles


_SIZING_GENERICS = {"num_switches", "num_buttons", "num_leds", "num_segs"}


def _match_native_port(
    mapping: dict[str, Any],
    port_by_name: dict[str, _IfaceDecl],
    mode: str,
) -> NativePort | None:
    """Match a leds/switches/buttons/leds_green convention mapping to native ports.

    Accepts a shared vector (``name`` + ``width``) or a bank of distinct scalars
    (``names``).  Returns None unless the design declares the native port(s) at
    the convention's fixed width, in the expected direction (*mode*).

    A width-1 vector bank also matches a plain scalar port (``std_logic``) -- the
    natural spelling for a one-LED / one-button board -- returning a
    ``scalar_ports`` bank the wrapper associates per element.  A
    ``std_logic_vector(0 downto 0)`` spelling still matches as a (non-scalar)
    vector, so both forms work.
    """
    active_low = bool(mapping.get("active_low", False))
    scalar_names = mapping.get("names")
    if isinstance(scalar_names, list) and scalar_names:
        for nm in scalar_names:
            decl = port_by_name.get(str(nm).lower())
            # names[] members are individual scalar ports by definition; a
            # vector-typed member (literal_width set) is a mismatch caught here,
            # not a cryptic association failure at elaboration.
            if decl is None or decl.mode != mode or decl.literal_width is not None:
                return None
        return NativePort(
            tuple(str(n) for n in scalar_names), len(scalar_names), active_low, scalar_ports=True
        )
    name = mapping.get("name")
    width = mapping.get("width")
    if not isinstance(name, str) or not isinstance(width, int):
        return None
    decl = port_by_name.get(name.lower())
    if decl is None or decl.mode != mode:
        return None  # absent or wrong direction
    if decl.literal_width == width:
        return NativePort((name,), width, active_low)  # exact fixed-width vector
    if width == 1 and decl.literal_width is None:
        # A one-bit bank declared as a plain scalar (`led : out std_logic`):
        # associate it per element in the wrapper (`led => led_uut(0)`).
        return NativePort((name,), 1, active_low, scalar_ports=True)
    return None  # width mismatch


def _match_native_seg(
    seg: dict[str, Any],
    port_by_name: dict[str, _IfaceDecl],
) -> NativeSeg | None:
    """Match an ``individual``-style 7-seg convention to native per-digit ports.

    B2 supports only the ``individual`` style (one fixed-width vector per digit,
    e.g. HEX0..n) — the only style present in canonical board data.  Other styles
    (``packed_vector``/``per_segment_scalars``/``scan``/``serial``) decline here
    and are left to the generic path / U22 / a later B3 extension.
    """
    if seg.get("style") != "individual":
        return None
    names = seg.get("names")
    wpd = seg.get("width_per_digit")
    if not isinstance(names, list) or not names or not isinstance(wpd, int):
        return None
    for nm in names:
        decl = port_by_name.get(str(nm).lower())
        if decl is None or decl.mode != "out" or decl.literal_width != wpd:
            return None
    return NativeSeg("individual", tuple(str(n) for n in names), wpd, bool(seg.get("active_low")))


def _attempt_convention(
    maker: str,
    block: dict[str, Any],
    board_def: BoardDef,
    port_by_name: dict[str, _IfaceDecl],
) -> _ConventionAttempt:
    """Try to match one maker's convention block against the parsed interface."""
    problems: list[str] = []
    matched: list[str] = []

    clk_port: str | None = None
    clk_name = block.get("clk")
    if isinstance(clk_name, str):
        decl = port_by_name.get(clk_name.lower())
        if decl is not None and decl.mode == "in":
            clk_port = clk_name
            matched.append("clk")
    if clk_port is None:
        problems.append(f"clock '{clk_name}'" if isinstance(clk_name, str) else "clock")

    leds = _match_native_port(block.get("leds") or {}, port_by_name, "out")
    (matched if leds is not None else problems).append("led" if leds is not None else "LEDs")

    # Switches / buttons are matched only when the convention declares the role
    # (U31): most FPGA boards have no switches, so a switch-less convention
    # neither requires nor adapts an `sw` bank -- exactly as `seg` is conditional
    # on the board having a display.  The requirement keys off the *convention*
    # (the native-name source of truth), not the board's physical resources, so a
    # board whose convention has not captured its switches yet simply cannot drive
    # them natively rather than never matching.  A declared-but-unmatched bank is
    # a near-miss.
    sw_declared = bool(block.get("switches"))
    btn_declared = bool(block.get("buttons"))
    switches = (
        _match_native_port(block.get("switches") or {}, port_by_name, "in") if sw_declared else None
    )
    buttons = (
        _match_native_port(block.get("buttons") or {}, port_by_name, "in") if btn_declared else None
    )
    if sw_declared:
        (matched if switches is not None else problems).append(
            "sw" if switches is not None else "switches"
        )
    if btn_declared:
        (matched if buttons is not None else problems).append(
            "btn" if buttons is not None else "buttons"
        )

    # 7-seg is required only when the board physically has a display.
    seven_seg: NativeSeg | None = None
    board_seg = board_def.seven_seg
    if board_seg is not None:
        seven_seg = _match_native_seg(block.get("seven_seg") or {}, port_by_name)
        (matched if seven_seg is not None else problems).append(
            "seg" if seven_seg is not None else "7-segment display"
        )

    # Secondary LED bank (e.g. LEDG): captured when the design declares it, but
    # never required -- like the generic wrapper leaving `seg` dark, an unused
    # second bank does not block a match.
    leds_green: NativePort | None = None
    green = block.get("leds_green")
    if isinstance(green, dict):
        leds_green = _match_native_port(green, port_by_name, "out")

    # U31: a *default-less* input the convention does not map would be left
    # unbound in the wrapper's uut port map (an elaboration error), so a native
    # design that declares one is a near-miss.  An extra input carrying a default
    # expression is legal unassociated in both GHDL and NVC -- exactly as the
    # generic path allows one (`_check_parsed_contract`) -- so it does not block a
    # match.  Unmapped *outputs* are fine too: the wrapper leaves them `open`
    # (dark), as the DE0 example leaves its split-DP HEXn_DP scalars open.
    # (Names in port_by_name are already lowercased.)
    consumed = {clk_port.lower()} if clk_port is not None else set()
    for port in (leds, switches, buttons, leds_green):
        if port is not None:
            consumed.update(n.lower() for n in port.names)
    if seven_seg is not None:
        consumed.update(n.lower() for n in seven_seg.names)
        if seven_seg.digit_enable is not None:
            consumed.update(n.lower() for n in seven_seg.digit_enable.names)
    extra = sorted(
        n
        for n, d in port_by_name.items()
        if n not in consumed and d.mode == "in" and not d.has_default
    )
    if extra:
        problems.append(f"unmapped input port(s): {', '.join(extra)}")

    match: ConventionMatch | None = None
    if (
        clk_port is not None
        and leds is not None
        and (not sw_declared or switches is not None)
        and (not btn_declared or buttons is not None)
        and (board_seg is None or seven_seg is not None)
        and not extra
    ):
        match = ConventionMatch(
            maker=maker,
            board_name=board_def.name,
            clk=clk_port,
            leds=leds,
            switches=switches,
            buttons=buttons,
            seven_seg=seven_seg,
            leds_green=leds_green,
        )
    return _ConventionAttempt(maker, board_def.name, match, tuple(matched), tuple(problems))


# Convention match precedence.  Authoritative blocks -- vendor-canonical or
# hand-authored (``naming`` absent or ``"canonical"``) -- are tried before a
# ``"framework-derived"`` guess (U32), so ground-truth data added for a board
# later wins even if a port name overlaps a derived block.  A stable sort keyed
# on this rank alone leaves same-rank blocks in their on-disk order.
_CONVENTION_NAMING_RANK = {"canonical": 0, "framework-derived": 1}


def _convention_precedence(item: tuple[str, Any]) -> int:
    """Sort key: authoritative conventions before framework-derived ones."""
    _maker, block = item
    naming = block.get("naming", "canonical") if isinstance(block, dict) else "canonical"
    return _CONVENTION_NAMING_RANK.get(naming, 0)


def _best_convention_attempt(
    ports: list[_IfaceDecl],
    generics: list[_IfaceDecl],
    board_def: BoardDef | None,
) -> _ConventionAttempt | None:
    """Best board-native match attempt across the board's canonical conventions.

    Returns the first *full* match, else the closest near-miss, else None (no
    board / no conventions / the design is structurally a generic-contract one).
    Conventions are tried authoritative-first (see ``_CONVENTION_NAMING_RANK``).
    """
    if board_def is None or not board_def.port_conventions:
        return None
    # A design that declares the simulator's own sizing generics is a generic
    # design that failed the contract for some other reason -- not board-native.
    generic_names = {n for d in generics for n in d.names}
    if generic_names & _SIZING_GENERICS:
        return None
    port_by_name = {n: d for d in ports for n in d.names}
    best: _ConventionAttempt | None = None
    ordered = sorted(board_def.port_conventions.items(), key=_convention_precedence)
    for maker, block in ordered:
        if not isinstance(block, dict):
            continue
        # Schema: absent `naming` means canonical; only skip explicitly renamed
        # ("project-derived") blocks, whose names aren't the board's native ones.
        if block.get("naming", "canonical") == "project-derived":
            continue
        attempt = _attempt_convention(maker, block, board_def, port_by_name)
        if attempt.match is not None:
            return attempt
        if best is None or len(attempt.matched_roles) > len(best.matched_roles):
            best = attempt
    return best


def match_convention(
    ports: list[_IfaceDecl],
    generics: list[_IfaceDecl],
    board_def: BoardDef | None,
) -> ConventionMatch | None:
    """Recognize a board-native VHDL interface against *board_def*'s conventions.

    Pure (no I/O).  Returns a :class:`ConventionMatch` when the parsed toplevel
    interface fully matches one of the board's canonical port conventions by name
    + fixed width + direction (native designs use fixed widths, not NUM_*
    generics), else None.  This is the detection half of U21's board-native VHDL
    support; the wrapper that runs such a design lands in B3.
    """
    attempt = _best_convention_attempt(ports, generics, board_def)
    return attempt.match if attempt is not None else None


def _role_span(port: NativePort) -> str:
    """Compact port label for a native role, e.g. 'LEDR' or 'o_LED_1..o_LED_4'."""
    if len(port.names) == 1:
        return port.names[0]
    return f"{port.names[0]}..{port.names[-1]}"


def _native_convention_message(match: ConventionMatch, filename: str) -> str:
    """Info message for a design recognized as board-native (U21 B3: runs).

    ``check_vhdl_contract`` returns this with ``ok=True``; the launcher does not
    show it as an error, but it is carried on the result for the analysis spinner
    and session log (B3b) and for tests.
    """
    parts = [match.clk]
    if match.switches is not None:
        parts.append(_role_span(match.switches))
    if match.buttons is not None:
        parts.append(_role_span(match.buttons))
    parts.append(_role_span(match.leds))
    if match.seven_seg is not None:
        segs = match.seven_seg.names
        parts.append(segs[0] if len(segs) == 1 else f"{segs[0]}..{segs[-1]}")
    seg = "/seg" if match.seven_seg is not None else ""
    return (
        f"'{filename}' matches {match.board_name}'s board-native '{match.maker}' port "
        f"convention ({', '.join(parts)}); running it board-native — the simulator adapts "
        f"these to its clk/sw/btn/led{seg} boundary."
    )


def _near_miss_convention_message(attempt: _ConventionAttempt, filename: str) -> str:
    """User-facing message for a design that partially matches a board convention."""
    return (
        f"'{filename}' is close to {attempt.board_name}'s board-native '{attempt.maker}' "
        f"interface but does not fully match it "
        f"(missing/mismatched: {', '.join(attempt.problems)}).\n"
        "Fix those ports to run it board-native, or use the generic clk/sw/btn/led "
        "contract (see hdl/blinky.vhd)."
    )


def check_vhdl_contract(
    path: str | Path,
    board_def: BoardDef | None = None,
) -> ContractResult:
    """Stage 2: contract validation (text-based, no simulator needed).

    Parses the toplevel entity's port/generic clauses and checks them against
    the design contract — board-aware when *board_def* is given (fixed widths
    are compared to the board's resource counts).  Falls back to the legacy
    whole-text scan when the interface cannot be parsed, so exotic-but-valid
    formatting is never rejected on parser limitations alone.

    When the generic contract fails, the design is checked against the board's
    board-native port conventions (U21): a full native match returns ``ok=True``
    with a precise message and the :class:`ConventionMatch` on the result (the
    native wrapper adapts its ports onto the sw/btn/led[/seg] boundary at run
    time), while a partial match is rejected with a near-miss message naming the
    convention.

    Returns a :class:`ContractResult`.
    """
    path = Path(path)
    stem = path.stem.lower()
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        return ContractResult(False, f"Cannot read file: {e}")

    # Check entity name matches filename
    entities = re.findall(r"entity\s+(\w+)\s+is", text, re.IGNORECASE)
    if not entities:
        return ContractResult(
            False,
            f"No entity declaration found in '{path.name}'.\n"
            "The file must contain: entity <name> is ... end entity;",
        )
    entity_names_lower = [e.lower() for e in entities]
    if stem not in entity_names_lower:
        found = ", ".join(f"'{e}'" for e in entities)
        return ContractResult(
            False,
            f"Entity name mismatch: found {found} but filename is '{path.name}'.\n"
            f"Rename the file to '{entities[0]}{path.suffix}' or rename the entity to '{stem}'.",
        )

    parsed = _parse_toplevel_interface(text, stem)
    if parsed is not None:
        ok, msg = _check_parsed_contract(path.name, parsed[0], parsed[1], board_def)
        if ok:
            return ContractResult(True)
        # Generic contract failed -- is this instead a board-native design?
        attempt = _best_convention_attempt(parsed[0], parsed[1], board_def)
        if attempt is not None and attempt.match is not None:
            # U21 B3: a full native match runs -- the native wrapper adapts the
            # board's own port names to the sw/btn/led/seg boundary.
            return ContractResult(
                True, _native_convention_message(attempt.match, path.name), attempt.match
            )
        if attempt is not None and len(attempt.matched_roles) >= 2:
            return ContractResult(False, _near_miss_convention_message(attempt, path.name))
        return ContractResult(False, msg)

    # ── Legacy whole-text fallback (interface not parseable) ──────────────

    # Check required ports
    missing_ports = [
        p for p in _REQUIRED_PORTS if not re.search(r"\b" + p + r"\b", text, re.IGNORECASE)
    ]
    if missing_ports:
        return ContractResult(
            False,
            f"Missing required port(s) in '{path.name}': {', '.join(missing_ports)}.\n"
            "The top-level entity must have ports: clk, sw, btn, led.",
        )

    # NUM_SEGS without a seg port is a contract error: the generic is meaningless alone
    if re.search(r"\bNUM_SEGS\b", text, re.IGNORECASE) and not _has_seg_port(text):
        return ContractResult(
            False,
            f"'{path.name}' declares NUM_SEGS generic but has no 'seg' output port.\n"
            "Add:  seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)",
        )

    # Warn (non-fatal) about missing generics
    missing_generics = [
        g for g in _REQUIRED_GENERICS if not re.search(r"\b" + g + r"\b", text, re.IGNORECASE)
    ]
    if missing_generics:
        print(f"[warn] Missing generics (will use VHDL defaults): {', '.join(missing_generics)}")

    return ContractResult(True)


def add_error_hints(message: str, board_def: BoardDef | None = None) -> str:
    """Append actionable "Hint:" lines to a simulator analysis/elaboration error.

    Recognizes the GHDL and NVC wordings of the failure modes a contract-
    violating design produces (missing IEEE header, unmapped generics, extra
    unconnected ports, vector-length mismatches) and explains the fix in terms
    of the design contract — with the board's real resource counts when
    *board_def* is given.  Unrecognized messages pass through unchanged.
    """
    if not message.strip():
        return message
    hints: list[str] = []

    # GHDL: no declaration for "std_logic" / NVC: no visible declaration for STD_LOGIC
    if re.search(r"no (?:visible )?declaration for \"?std_logic", message, re.IGNORECASE):
        hints.append(
            "Add the IEEE library header at the top of the file:\n"
            "  library ieee;\n"
            "  use ieee.std_logic_1164.all;"
        )

    # GHDL: generic "NUM_LEDS" is not an interface name
    # NVC:  NUM_LEDS is not a formal generic of WORK.FOO
    m = re.search(
        r"generic \"(\w+)\" is not an interface name|(\w+) is not a formal generic",
        message,
        re.IGNORECASE,
    )
    if m:
        name = (m.group(1) or m.group(2)).upper()
        hints.append(
            f"The simulator sets the generic {name} at launch, so the top-level entity "
            "must declare it (with a default value). The standard generics are "
            "NUM_SWITCHES, NUM_BUTTONS, NUM_LEDS and COUNTER_BITS, plus NUM_SEGS for "
            "designs that drive a 7-segment display."
        )

    # GHDL: port "rst" of mode IN must be connected
    # NVC:  missing actual for port RST of mode IN without a default expression
    m = re.search(
        r"port \"(\w+)\" of mode IN must be connected"
        r"|missing actual for port (\w+) of mode IN",
        message,
        re.IGNORECASE,
    )
    if m:
        name = (m.group(1) or m.group(2)).lower()
        hints.append(
            f"The simulator drives only the contract ports (clk, sw, btn, led, seg), so "
            f"the extra input port '{name}' is left unconnected. Give it a default value "
            f"— e.g.  {name} : in std_logic := '0'  — or remove it."
        )

    # GHDL: mismatching vector length; got 4, expect 10
    # NVC:  actual length 10 does not match formal length 4
    if re.search(
        r"mismatching vector length|actual length \d+ does not match formal length",
        message,
        re.IGNORECASE,
    ):
        # The simulator echoes the failing wrapper association (e.g. "led => led").
        pm = re.search(r"\b(sw|btn|led|seg)\s*=>", message)
        port = pm.group(1) if pm else None
        widths = _board_port_widths(board_def)
        lines = ["Port widths must come from the generics"]
        if port:
            lines[0] += f" — the mismatch is on port '{port}'"
        lines[0] += "."
        if board_def is not None and widths:
            parts = [f"{_PORT_GENERIC[p]}={widths[p]}" for p in ("sw", "btn", "led")]
            if "seg" in widths:
                assert board_def.seven_seg is not None
                digits = board_def.seven_seg.num_digits
                parts.append(f"NUM_SEGS={digits} (seg is 8 * {digits} = {widths['seg']} bits)")
            lines.append(f"{board_def.name} provides {', '.join(parts)}.")
        lines.append(f"Declare the port with its generic:  {_PORT_SNIPPETS[port or 'led']}")
        lines.append(
            "(This validation step elaborates with the generic defaults, so the lengths "
            "reported above can differ from the board's.)"
        )
        hints.append("\n".join(lines))

    if not hints:
        return message
    return message + "".join(f"\n\nHint: {h}" for h in hints)


# ── Simulation infrastructure ─────────────────────────────────────────────────

_WRAPPER_TEMPLATE: Path = Path(__file__).parent.parent.parent / "sim" / "sim_wrapper_template.vhd"


def _native_port_map(port: NativePort, sig: str) -> list[str]:
    """Association line(s) tying a native LED/switch/button bank to wrapper signal *sig*.

    A shared vector maps whole (``LEDR => led_uut``); a scalar-port bank maps each
    element (``o_LED_1 => led_uut(0)``, ...) -- including a one-bit bank the design
    spelled as a scalar (``led => led_uut(0)``).  Keyed on ``scalar_ports``, not
    ``len(names)``, so a single-member scalar cluster still maps per element.
    """
    if port.scalar_ports:
        return [f"{name} => {sig}({k})" for k, name in enumerate(port.names)]
    return [f"{port.names[0]} => {sig}"]


def _render_native_wrapper(
    toplevel: str, match: ConventionMatch, board_def: BoardDef | None = None
) -> str:
    """Render a ``sim_wrapper`` that runs a board-native design (U21 B3).

    The design uses the board's native port names + fixed widths (no ``NUM_*``
    generics), so the wrapper adapts them to the simulator's ``sw/btn/led[/seg]``
    boundary via intermediate signals:

    * the native clock port is driven by the VHDL free-running ``clk``;
    * switches/buttons are buffered (inverted when the convention is active-low)
      and fed to the native inputs;
    * LED outputs are read back and inverted onto ``led`` when active-low;
    * an ``individual``-style 7-seg is packed per digit into ``seg`` as the
      active-high ``{dp, g..a}`` byte the display expects (dp forced off).

    The entity, generics, top ports and clock process are identical to the generic
    wrapper (so ``launch_simulation``/``run_cmd``/``_write_gtkw``/the cocotb
    testbench are unchanged); only the architecture body differs -- a
    generic-map-less uut with native names.  Generic *defaults* are baked to the
    board's widths so ``analyze_vhdl``'s default-generic early elaboration lines the
    top ports up with the native uut's fixed widths (no "defaults dance").
    """
    sw, btn, led, seg, green = (
        match.switches,
        match.buttons,
        match.leds,
        match.seven_seg,
        match.leds_green,
    )
    decls: list[str] = []  # architecture declarative signals
    assigns: list[str] = []  # concurrent assignments (adapters)
    pmap: list[str] = [f"{match.clk} => clk"]  # uut port-map association lines

    # Switches / buttons: buffer (invert if active-low) then feed the native
    # inputs.  An absent bank (U31 partial interface) leaves the wrapper's top
    # `sw`/`btn` port present (cocotb still drives it) but unconnected to the uut,
    # mirroring the generic path's NUM_* floor of 1 for a bank-less board.
    # The wrapper's NUM_* boundary is the board's full resource count, which can
    # exceed the convention bank width -- e.g. a litex board whose rgb_led inflate
    # NUM_LEDS past the user_led bank, or more board buttons than the primary bank.
    # Inputs take the low boundary bits; the LED output zero-extends the bank onto
    # the wider boundary so uncovered board LEDs stay dark.  For a board whose count
    # equals the bank width (every Terasic example) these reduce to the plain form.
    for role, port, wrapper_port in (("sw", sw, "sw"), ("btn", btn, "btn")):
        if port is None:
            continue
        sig = f"{role}_uut"
        inv = "not " if port.active_low else ""
        decls.append(f"  signal {sig} : std_logic_vector({port.width} - 1 downto 0);")
        assigns.append(f"  {sig} <= {inv}{wrapper_port}({port.width} - 1 downto 0);")
        pmap += _native_port_map(port, sig)

    # LEDs: read the native bank back (invert when active-low) and zero-extend it
    # onto the board `led` boundary -- board LEDs the convention omits stay dark.
    led_inv = "not " if led.active_low else ""
    decls.append(f"  signal led_uut : std_logic_vector({led.width} - 1 downto 0);")
    assigns.append(f"  led <= std_logic_vector(resize(unsigned({led_inv}led_uut), NUM_LEDS));")
    pmap += _native_port_map(led, "led_uut")

    # Secondary green bank (rare): captured so the output has a driver, not shown --
    # like the generic wrapper leaving `seg` dark on a non-7-seg design.
    if green is not None:
        decls.append(f"  signal ledg_uut : std_logic_vector({green.width} - 1 downto 0);")
        pmap += _native_port_map(green, "ledg_uut")

    # 7-seg (individual style): each digit is a wpd-bit vector packed into seg's byte.
    if seg is not None:
        wpd = seg.width_per_digit
        inv = "not " if seg.active_low else ""
        for i, name in enumerate(seg.names):
            sig = f"hex{i}_uut"
            decls.append(f"  signal {sig} : std_logic_vector({wpd} - 1 downto 0);")
            assigns.append(f"  seg({8 * i + wpd - 1} downto {8 * i}) <= {inv}{sig};")
            if wpd < 8:  # remaining high bits of the digit byte (e.g. dp) -> off
                assigns.append(f"  seg({8 * i + 7} downto {8 * i + wpd}) <= (others => '0');")
            pmap.append(f"{name} => {sig}")

    # Generic *defaults* mirror ``build_generics`` (the board's resource counts,
    # floored at 1) so ``analyze_vhdl``'s default-generic elaboration validates the
    # same NUM_* widths the run passes -- which, for a litex board whose rgb_led
    # inflate the LED count past the user_led bank, differ from the bank widths.
    # Without a board (hermetic wrapper-gen unit tests) fall back to the bank widths.
    if board_def is not None:
        num_sw_def = max(1, len(board_def.switches))
        num_btn_def = max(1, len(board_def.buttons))
        num_led_def = max(1, len(board_def.leds))
    else:
        num_sw_def = sw.width if sw is not None else 1
        num_btn_def = btn.width if btn is not None else 1
        num_led_def = led.width

    seg_generic = [f"    NUM_SEGS         : positive := {len(seg.names)};"] if seg else []
    seg_port = ["    seg         : out std_logic_vector(8 * NUM_SEGS - 1 downto 0);"] if seg else []
    lines = [
        "-- sim_wrapper.vhd (board-native, generated by sim_bridge.py -- U21 B3)",
        f"-- Design '{toplevel}' uses {match.board_name}'s native '{match.maker}' port names.",
        "-- Adapts polarity + 7-seg packing to the sw/btn/led[/seg] boundary so the cocotb",
        "-- testbench and waveform tooling see the usual contract ports.",
        "",
        "library ieee;",
        "use ieee.std_logic_1164.all;",
        "use ieee.numeric_std.all;",  # resize/unsigned for the LED boundary zero-extend
        "",
        "entity sim_wrapper is",
        "  generic (",
        f"    NUM_SWITCHES     : positive := {num_sw_def};",
        f"    NUM_BUTTONS      : positive := {num_btn_def};",
        f"    NUM_LEDS         : positive := {num_led_def};",
        *seg_generic,
        "    COUNTER_BITS     : positive := 24;",
        "    CLK_HALF_NS_INIT : positive := 20",
        "  );",
        "  port (",
        "    sw          : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);",
        "    btn         : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);",
        "    led         : out std_logic_vector(NUM_LEDS     - 1 downto 0);",
        *seg_port,
        "    clk_half_ns : in  natural := CLK_HALF_NS_INIT",
        "  );",
        "end entity;",
        "",
        "architecture rtl of sim_wrapper is",
        "  signal clk : std_logic := '0';",
        *decls,
        "begin",
        "",
        "  clk_proc : process",
        "  begin",
        "    clk <= '0';",
        "    wait for clk_half_ns * 1 ns;",
        "    clk <= '1';",
        "    wait for clk_half_ns * 1 ns;",
        "  end process;",
        "",
        *assigns,
        "",
        f"  uut : entity work.{toplevel}",
        "    port map (",
        "      " + ",\n      ".join(pmap),
        "    );",
        "",
        "end architecture;",
        "",
    ]
    return "\n".join(lines)


def _generate_wrapper(
    toplevel: str,
    work_dir: str,
    board_def: BoardDef | None = None,
    design_has_seg: bool = False,
    match: ConventionMatch | None = None,
) -> Path:
    """Write ``sim_wrapper.vhd`` to *work_dir* with placeholders substituted.

    When both *board_def* has a seven_seg display and the design declares a
    ``seg`` output port, the generated wrapper includes the ``NUM_SEGS``
    generic and ``seg`` port.  Otherwise those lines are omitted.

    When *match* is given the design is board-native (U21 B3): the wrapper
    instantiates it by its native port names + fixed widths (see
    :func:`_render_native_wrapper`).  The generic path (``match is None``) is
    byte-for-byte unchanged.
    """
    out = Path(work_dir) / "sim_wrapper.vhd"
    if match is not None:
        out.write_text(_render_native_wrapper(toplevel, match, board_def))
        return out

    use_seg = board_def is not None and board_def.seven_seg is not None and design_has_seg
    if use_seg:
        seg_generic = "    NUM_SEGS         : positive := 4;\n"
        seg_port = "    seg         : out std_logic_vector(8 * NUM_SEGS - 1 downto 0);\n"
        seg_generic_map = "      NUM_SEGS     => NUM_SEGS,\n"
        seg_port_map = "      seg => seg,\n"
    else:
        seg_generic = ""
        seg_port = ""
        seg_generic_map = ""
        seg_port_map = ""

    content = _WRAPPER_TEMPLATE.read_text().format(
        toplevel=toplevel,
        seg_generic=seg_generic,
        seg_port=seg_port,
        seg_generic_map=seg_generic_map,
        seg_port_map=seg_port_map,
    )
    out.write_text(content)
    return out


def analyze_vhdl(
    vhdl_path: str | Path,
    work_dir: str | None = None,
    toplevel: str | None = None,
    simulator: Simulator = "ghdl",
    board_def: BoardDef | None = None,
    match: ConventionMatch | None = None,
) -> tuple[bool, str]:
    """Analyze the user's VHDL and the generated sim_wrapper.

    Steps:
      1. Analyze the user's VHDL file (``-a``).
      2. Generate ``sim_wrapper.vhd`` and analyze it.
      3. Elaborate ``sim_wrapper`` with VHDL-default generics as an early
         error check.  GHDL resolves generics at run time so the defaults
         used here are discarded.  NVC bakes generics into its elaboration
         artifact, so ``launch_simulation()`` re-elaborates with the real
         board generics before running — but this early check still catches
         structural errors (port-width mismatches, missing libraries, etc.)
         at validation time rather than at simulation launch.

    When *match* is given the design is board-native (U21 B3): the wrapper
    instantiates it by its native port names, and the step-3 default-generic
    elaboration works because the native wrapper bakes the board widths as its
    generic defaults.

    Returns ``(ok: bool, detail: str)``.  On success *detail* is the work dir.
    """
    be = _backend(simulator)
    work_dir = work_dir or tempfile.mkdtemp(prefix="fpga_sim_")
    if toplevel is None:
        toplevel = Path(vhdl_path).stem
    try:
        # Step 1: analyze user's VHDL
        result = subprocess.run(
            be.analyze_cmd(Path(vhdl_path), work_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, add_error_hints(result.stderr.strip(), board_def)

        # Step 2: generate wrapper and analyze it
        _vhdl_text = Path(vhdl_path).read_text(encoding="utf-8", errors="ignore")
        _design_has_seg = _has_seg_port(_vhdl_text)
        wrapper_path = _generate_wrapper(
            toplevel,
            work_dir,
            board_def=board_def,
            design_has_seg=_design_has_seg,
            match=match,
        )
        result2 = subprocess.run(
            be.analyze_cmd(wrapper_path, work_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result2.returncode != 0:
            msg = add_error_hints(result2.stderr.strip(), board_def)
            print(f"[sim_bridge] sim_wrapper analysis failed:\n{msg}", flush=True)
            return False, msg

        # Step 3: early elaboration check — VHDL defaults suffice for structural errors.
        # NVC will re-elaborate with real board generics in launch_simulation().
        elab = subprocess.run(
            be.elaborate_cmd("sim_wrapper", {}, work_dir),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if elab.returncode != 0:
            combined = (result2.stderr + elab.stderr).strip()
            if not combined:
                return False, "Elaboration of sim_wrapper failed."
            return False, add_error_hints(combined, board_def)

        return True, work_dir
    except FileNotFoundError:
        if simulator == "ghdl":
            hint = (
                "winget install ghdl.ghdl.ucrt64.mcode"
                if IS_WINDOWS
                else "apt install ghdl  OR  brew install ghdl"
            )
            return False, f"GHDL not found. Install: {hint}"
        else:
            hint = "brew install nvc  OR  build from source: https://github.com/nickg/nvc"
            return False, f"NVC not found. Install: {hint}"
    except subprocess.TimeoutExpired:
        return False, f"{simulator.upper()} analysis timed out."


def _build_sim_env(
    simulator: Simulator = "ghdl",
    venv_dir: str | Path | None = None,
) -> tuple[dict[str, str], str]:
    """Build the environment dict needed for the simulator + cocotb VPI/VHPI.

    Returns (env_dict, plugin_lib_path).
    """
    venv_dir = Path(venv_dir or (Path(__file__).parent.parent.parent / ".venv"))
    venv_scripts, venv_site, venv_python = _venv_dirs(venv_dir)
    cocotb_libs = venv_site / "cocotb" / "libs"

    base_python = subprocess.run(
        [str(venv_python), "-c", "import sys; print(sys.base_exec_prefix)"],
        capture_output=True,
        text=True,
    ).stdout.strip()

    be = _backend(simulator)
    sim_bin, sim_lib = be.sim_bin_lib()
    plugin_lib = str(cocotb_libs / be.plugin_lib_name())

    _root = Path(__file__).resolve().parent.parent.parent
    _src_dir = str(_root / "src")
    _sim_dir = str(_root / "sim")

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


# ── Waveform capture ──────────────────────────────────────────────────────────

#: Default directory for waveform dumps.  A module attribute (mirroring
#: ``session_config.SESSION_FILE``) so tests can redirect it; overridable at
#: runtime by the ``FPGA_SIM_WAVEFORM_DIR`` env var so a user working in their
#: own project tree can keep captures in-tree.  The resolved path is absolute,
#: so the run subprocess writes there regardless of its temp work-dir cwd.
WAVEFORM_DIR: Path = Path.home() / ".fpga_simulator" / "waveforms"

#: Env var overriding :data:`WAVEFORM_DIR` (blank/unset → the default).
WAVEFORM_DIR_ENV = "FPGA_SIM_WAVEFORM_DIR"

#: Env var enabling capture headlessly / in CI, overriding the session ``waveform``
#: mode when set (blank/unset → the session value).  See :func:`launch_simulation`.
WAVEFORM_ENV = "FPGA_SIM_WAVEFORM"

#: Env var forcing waveform auto-open on/off, overriding the session
#: ``waveform_open`` flag when set (parsed by :func:`_env_flag`).
WAVEFORM_OPEN_ENV = "FPGA_SIM_WAVEFORM_OPEN"

#: Env var forcing the U30 "include memories" depth on/off (NVC ``--dump-arrays``),
#: overriding the session ``waveform_memories`` flag when set (parsed by
#: :func:`_env_flag`).  Lets CI/headless capture the embedded-core RAM/ROM arrays.
WAVEFORM_MEMORIES_ENV = "FPGA_SIM_WAVEFORM_MEMORIES"

#: Env var holding the auto-open command template (see :func:`_viewer_argv`).
WAVEFORM_VIEWER_ENV = "FPGA_SIM_WAVEFORM_VIEWER"

#: Default auto-open command: open GTKWave on the U28 save file (preloaded view).
DEFAULT_VIEWER = "gtkwave {gtkw}"


def _waveform_dir() -> Path:
    """Effective output directory: ``$FPGA_SIM_WAVEFORM_DIR`` or :data:`WAVEFORM_DIR`."""
    override = os.environ.get(WAVEFORM_DIR_ENV, "").strip()
    return Path(override).expanduser() if override else WAVEFORM_DIR


def _normalize_wave(value: str | None) -> WaveFormat | None:
    """Coerce a persisted/CLI waveform value to a WaveFormat, or None (off).

    Anything other than ``"vcd"`` / ``"fst"`` — ``"off"``, ``None``, or junk
    from a hand-edited session file — means no capture.
    """
    if value == "vcd":
        return "vcd"
    if value == "fst":
        return "fst"
    return None


def _waveform_path(entity: str, fmt: WaveFormat, *, now: datetime | None = None) -> Path:
    """Absolute, timestamped output path for a waveform dump of *entity*.

    ``<dir>/<entity>_<YYYY-MM-DD_HH-MM-SS>.<ext>`` under :func:`_waveform_dir`, so
    successive runs of a design accumulate (compare iterations in GTKWave) instead
    of overwriting, and same-named designs from different projects never collide.
    Colons are avoided so the name is valid on Windows.  *now* is injectable so
    tests are deterministic.
    """
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M-%S")
    return _waveform_dir() / f"{entity}_{stamp}.{fmt}"


def _gtkw_path(wave_path: Path) -> Path:
    """Return the GTKWave save-file sibling of a dump: same stem, ``.gtkw`` suffix.

    Pairing by identical stem (``blinky_<stamp>.vcd`` → ``blinky_<stamp>.gtkw``)
    keeps each save file matched to its dump once several timestamped captures
    accumulate.
    """
    return wave_path.with_suffix(".gtkw")


def _native_gtkw_signals(match: ConventionMatch) -> list[str]:
    """GTKWave signal paths for a board-native run: the design's own ports under ``uut``.

    Names are lowercased to match the identifier case GHDL/NVC emit in the dump
    hierarchy.  A shared vector carries a ``[msb:0]`` range; a scalar bank lists
    each scalar; the clock is a scalar.
    """
    scope = "sim_wrapper.uut"

    def _port(port: NativePort) -> list[str]:
        # A scalar-port bank dumps as individual unranged scalars; a shared
        # vector carries a [msb:0] range.  (A one-bit scalar bank has no range,
        # unlike a std_logic_vector(0 downto 0), so key on scalar_ports.)
        if port.scalar_ports:
            return [f"{scope}.{name.lower()}" for name in port.names]
        return [f"{scope}.{port.names[0].lower()}[{port.width - 1}:0]"]

    sigs = [f"{scope}.{match.clk.lower()}"]
    if match.switches is not None:
        sigs += _port(match.switches)
    if match.buttons is not None:
        sigs += _port(match.buttons)
    sigs += _port(match.leds)
    if match.leds_green is not None:
        sigs += _port(match.leds_green)
    if match.seven_seg is not None:
        wpd = match.seven_seg.width_per_digit
        sigs += [f"{scope}.{name.lower()}[{wpd - 1}:0]" for name in match.seven_seg.names]
    return sigs


def _write_gtkw(
    gtkw_path: Path,
    dump_path: Path,
    generics: dict[str, str],
    match: ConventionMatch | None = None,
) -> None:
    """Write a GTKWave save file that preloads the interesting ``sim_wrapper`` signals.

    Opening ``gtkwave <gtkw_path>`` lands the user on clk / sw / btn / led (and
    seg, for 7-seg runs) instead of an empty view with the whole signal tree —
    the U28 convenience atop U10's raw capture.  Signal names mirror the
    hierarchy both backends emit: the elaborated toplevel is ``sim_wrapper`` and
    each vector carries a ``[msb:0]`` range whose width comes from *generics*
    (a port whose generic is absent or unparseable is skipped, so an unusual
    design yields a shorter list rather than a broken line).  ``[dumpfile]`` names
    *dump_path*, so the save file also loads the trace on its own.

    When *match* is given the run is board-native (U21 B3): preselect the design's
    own native ports (``sim_wrapper.uut.<native>``) — the names the user wrote —
    followed by the top-level ``led``/``seg`` so the active-low inversion is
    visible (``uut.ledr`` vs ``led``).
    """
    top = "sim_wrapper"

    def _vector(name: str, width_generic: str, *, scale: int = 1) -> str | None:
        try:
            msb = int(generics[width_generic]) * scale - 1
        except (KeyError, ValueError):
            return None
        return f"{top}.{name}[{msb}:0]" if msb >= 0 else None

    if match is not None:
        signals = _native_gtkw_signals(match)
        signals += [
            s for s in (_vector("led", "NUM_LEDS"), _vector("seg", "NUM_SEGS", scale=8)) if s
        ]
        note = "[*] Preloads the design's native ports (sim_wrapper.uut.*) + board led/seg."
    else:
        signals = [
            p
            for p in (
                f"{top}.clk",
                _vector("sw", "NUM_SWITCHES"),
                _vector("btn", "NUM_BUTTONS"),
                _vector("led", "NUM_LEDS"),
                _vector("seg", "NUM_SEGS", scale=8),  # seg packs 8 bits per digit
            )
            if p is not None
        ]
        note = "[*] Preloads the sim_wrapper top-level ports; load beside the matching dump."

    lines = [
        "[*]",
        "[*] GTKWave save file auto-written by fpga-sim (roadmap U28).",
        note,
        "[*]",
        f'[dumpfile] "{dump_path}"',
        "[timestart] 0",
        "[signals_width] 200",
        "[sst_width] 200",
        f"-{top}",
        *signals,
    ]
    gtkw_path.write_text("\n".join(lines) + "\n")


def _env_flag(name: str) -> bool | None:
    """Parse a boolean env var: ``1/true/yes/on`` → True, ``0/false/no/off`` → False.

    Returns ``None`` when the var is unset or empty, so a caller can fall back to
    another source (blank means "not specified", not "False").
    """
    raw = os.environ.get(name, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _viewer_argv(template: str, dump: Path, gtkw: Path) -> list[str]:
    """Build the auto-open argv from a command *template*.

    ``{dump}`` / ``{gtkw}`` expand to the capture file and its GTKWave save file;
    a template naming neither gets ``{dump}`` appended (so a bare ``surfer`` still
    works).  Tokenized with :func:`shlex.split` (no shell — no injection surface)
    *before* substitution, so a path containing spaces stays one argument.
    """
    if "{dump}" not in template and "{gtkw}" not in template:
        template = f"{template} {{dump}}"

    def _sub(token: str) -> str:
        return token.replace("{dump}", str(dump)).replace("{gtkw}", str(gtkw))

    return [_sub(token) for token in shlex.split(template)]


def _open_waveform(dump: Path, gtkw: Path) -> None:
    """Launch the user's waveform viewer on a produced dump (best-effort, detached).

    The command comes from ``$FPGA_SIM_WAVEFORM_VIEWER`` or :data:`DEFAULT_VIEWER`
    (``gtkwave {gtkw}``).  If its program isn't on PATH — or launching it raises —
    fall back to the OS default handler for the raw dump
    (:func:`~fpga_sim.platform_open.open_with_default_app`), so a viewer the user
    registered without setting the env var still opens.
    """
    template = os.environ.get(WAVEFORM_VIEWER_ENV, "").strip() or DEFAULT_VIEWER
    argv = _viewer_argv(template, dump, gtkw)
    if argv and shutil.which(argv[0]):
        try:
            subprocess.Popen(argv, start_new_session=True)
            return
        except OSError as e:
            print(f"[waveform] could not launch {argv[0]}: {e}", file=sys.stderr, flush=True)
    open_with_default_app(dump)


def _announce_waveform(
    wave_cfg: WaveConfig | None,
    generics: dict[str, str],
    match: ConventionMatch | None,
    waveform_open: bool | None,
) -> None:
    """Post-run waveform tail: gtkw sidecar + hint + optional auto-open.

    A produced, non-empty dump is worth pointing at; a crashed/empty run is not.
    Shared by :func:`launch_simulation` (legacy blocking path) and
    :func:`finish_waveform` (single-window path), so both spell the U28 sidecar
    and U29 auto-open identically.
    """
    if wave_cfg is None:
        return
    wpath = Path(wave_cfg.path)
    if not (wpath.is_file() and wpath.stat().st_size > 0):
        return
    # U28: drop a matching GTKWave save file so the dump opens on the interesting
    # ports (clk/sw/btn/led[/seg]) instead of an empty view.  U21 B3: for a
    # board-native run, preselect the design's own native ports.
    gtkw = _gtkw_path(wpath)
    _write_gtkw(gtkw, wpath, generics, match=match)
    print(f"Waveform written: {wpath}\n  Open it with preloaded signals:  gtkwave {gtkw}")
    # U29: optionally launch the user's viewer on the produced dump.
    env_open = _env_flag(WAVEFORM_OPEN_ENV)
    do_open = env_open if env_open is not None else bool(waveform_open)
    if do_open:
        _open_waveform(wpath, gtkw)


# ── Shared run preparation (launch_simulation + start_simulation) ─────────────


@dataclass
class _SimPrep:
    """Analysis / elaboration / waveform prep shared by both run entry points.

    Built by :func:`_prepare_simulation` and consumed by both
    :func:`launch_simulation` (legacy, blocking) and :func:`start_simulation`
    (single-window, headless).  ``env`` already carries the vars common to both
    paths (board JSON + metrics metadata); each caller adds its path-specific
    vars before launching.
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
) -> _SimPrep:
    """Analyze (if needed), elaborate (NVC), resolve waveform, build the run cmd.

    This is the body :func:`launch_simulation` used to run inline up to the point
    of spawning the simulator, factored out so :func:`start_simulation` reuses it
    verbatim.  The returned ``env`` holds the vars both the legacy pygame
    testbench and the headless bridge read; the legacy/headless-specific vars are
    added by the respective caller.  Behavior for the legacy path is unchanged.
    """
    from fpga_sim.board_loader import BoardDef  # noqa: PLC0415

    vhdl_path = Path(vhdl_path).resolve()
    be = _backend(simulator)
    env, plugin_lib = _build_sim_env(simulator=simulator)
    generics = dict(generics or {})

    # Resolve board_def from JSON when not passed directly
    if board_def is None and board_json:
        try:
            board_def = BoardDef.from_json(board_json)
        except Exception:  # noqa: BLE001 - fall back to generic sizing
            pass

    # Detect seg port once; used for wrapper selection and NUM_SEGS injection.
    _vhdl_text = vhdl_path.read_text(encoding="utf-8", errors="ignore")
    _design_has_seg = _has_seg_port(_vhdl_text)

    # Add NUM_SEGS generic only when both board and design use 7-seg
    if board_def is not None and board_def.seven_seg is not None and _design_has_seg:
        generics.setdefault("NUM_SEGS", str(board_def.seven_seg.num_digits))

    if work_dir is None:
        # Fresh run: analyze user file and wrapper from scratch.
        work_dir = tempfile.mkdtemp(prefix="fpga_sim_run_")
        subprocess.run(be.analyze_cmd(vhdl_path, work_dir), env=env, check=True, cwd=work_dir)
        wrapper_path = _generate_wrapper(
            toplevel, work_dir, board_def=board_def, design_has_seg=_design_has_seg, match=match
        )
        subprocess.run(be.analyze_cmd(wrapper_path, work_dir), env=env, check=True, cwd=work_dir)

    if simulator == "nvc":
        # NVC bakes generics into its elaboration artifact; re-elaborate with real values.
        elab = subprocess.run(
            be.elaborate_cmd("sim_wrapper", generics, work_dir),
            env=env,
            capture_output=True,
            text=True,
            cwd=work_dir,
        )
        if elab.returncode != 0:
            raise RuntimeError(elab.stderr.strip() or "NVC elaboration failed.")

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
    cmd = be.run_cmd("sim_wrapper", generics, plugin_lib, work_dir, wave=wave_cfg)

    # Env vars both the legacy pygame testbench and the headless bridge read.
    env["TOPLEVEL"] = "sim_wrapper"
    env["FPGA_SIM_TOPLEVEL"] = toplevel  # user's entity, for display/metadata
    env["FPGA_SIM_BOARD_JSON"] = board_json
    env["FPGA_SIM_SIMULATOR"] = simulator
    env["FPGA_SIM_VHDL_PATH"] = str(vhdl_path)
    env["FPGA_SIM_GENERICS"] = json.dumps(generics)

    return _SimPrep(env, cmd, work_dir, generics, wave_cfg, vhdl_path)


def launch_simulation(
    board_json: str,
    vhdl_path: str | Path,
    toplevel: str = "blinky",
    generics: dict[str, str] | None = None,
    sim_width: int = 1024,
    sim_height: int = 700,
    work_dir: str | None = None,
    simulator: Simulator = "ghdl",
    board_def: BoardDef | None = None,
    speed_factor: float | None = None,
    theme: str | None = None,
    waveform: str | None = None,
    waveform_open: bool | None = None,
    waveform_memories: bool | None = None,
    match: ConventionMatch | None = None,
) -> SimExit:
    """Launch an interactive simulator + cocotb simulation.

    The actual elaborated/run entity is always ``sim_wrapper`` (generated by
    ``analyze_vhdl()``), which drives the clock from VHDL and instantiates
    the user's entity (*toplevel*) internally.

    GHDL: reuses analysis artifacts from analyze_vhdl(), passes generics
          (including ``CLK_HALF_NS``) inline on the ``-r`` run command.
    NVC:  elaborates ``sim_wrapper`` with generics, then runs.

    If *work_dir* is supplied (from a prior ``analyze_vhdl()`` call) the
    analysis step is skipped — existing artifacts are reused.

    *speed_factor* (when not ``None``) seeds the sim panel's speed slider via
    ``FPGA_SIM_SPEED``; its presence also tells sim_testbench to write the
    slider's final value back to the session file at exit.  Callers that must
    not touch the user's session (benchmark, tests) simply leave it ``None``.

    *theme* (when not ``None``) carries the launcher's active theme name into
    the subprocess via ``FPGA_SIM_THEME``; sim_testbench applies it before
    drawing.  Passed as a plain string so this module stays UI-import-free.

    *waveform* (``"vcd"`` / ``"fst"``; anything else, incl. ``None``, means off)
    enables native simulator waveform capture to a timestamped file under
    ``~/.fpga_simulator/waveforms/`` — or ``$FPGA_SIM_WAVEFORM_DIR`` — (see
    :func:`_waveform_path`).  Capture is a run-command flag on GHDL/NVC and
    independent of cocotb, so ``sim_testbench`` is unaffected; the path is
    printed after a run that produced a non-empty file, for opening in GTKWave.

    ``$FPGA_SIM_WAVEFORM`` (off/vcd/fst) overrides *waveform* when set, so capture
    can be enabled headlessly / in CI.  *waveform_open* — or ``$FPGA_SIM_WAVEFORM_OPEN``,
    which overrides it — then launches a viewer on the produced dump, using the
    command in ``$FPGA_SIM_WAVEFORM_VIEWER`` (default ``gtkwave {gtkw}``); see
    :func:`_open_waveform`.

    *waveform_memories* — or ``$FPGA_SIM_WAVEFORM_MEMORIES``, which overrides it —
    is the U30 "include memories" depth: when on, NVC captures nested arrays and
    memories too (``--dump-arrays``), so the embedded-core designs' RAM/ROM/registers
    appear in the trace.  Applies to NVC, which otherwise skips nested arrays in
    every format (VCD and FST); GHDL's FST/GHW writers already include them (its
    VCD writer omits them, with or without a flag).  Off by default because
    arrays add significant dump size.

    This call blocks until the simulation exits, then returns the
    :class:`SimExit` the user chose via the in-simulation toolbar
    (``SimExit.STOPPED`` for a plain ESC / window-close / [Stop] exit).
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
    )
    env = prep.env
    work_dir = prep.work_dir

    # Exit-intent side channel (see SimExit).  A reused work_dir — the reload
    # path re-analyzes in place — may hold a stale intent from the previous
    # run, so always start from a clean slate.
    intent_file = Path(work_dir) / _EXIT_INTENT_NAME
    intent_file.unlink(missing_ok=True)

    # Legacy-window-only env: the pygame testbench module, window geometry, and
    # the exit-intent path (the shared metadata vars are set in _prepare_simulation).
    env["COCOTB_TEST_MODULES"] = "sim_testbench"
    env["FPGA_SIM_WIDTH"] = str(sim_width)
    env["FPGA_SIM_HEIGHT"] = str(sim_height)
    env["FPGA_SIM_EXIT_INTENT_FILE"] = str(intent_file)
    if speed_factor is not None:
        env["FPGA_SIM_SPEED"] = str(speed_factor)
    if theme is not None:
        env["FPGA_SIM_THEME"] = theme
    # U21 B3: board-native run metadata (badge + session log, consumed by B3b).
    if match is not None:
        native_meta: dict[str, Any] = {
            "maker": match.maker,
            "board_name": match.board_name,
            "leds_active_low": match.leds.active_low,
            "has_seg": match.seven_seg is not None,
            "seg_active_low": match.seven_seg.active_low if match.seven_seg else False,
        }
        # Absent banks (U31) omit their *_active_low key -- sim_testbench's
        # _active_low_roles reads via .get(), so an omitted role is simply not
        # listed in the board-native active-low note.
        if match.switches is not None:
            native_meta["switches_active_low"] = match.switches.active_low
        if match.buttons is not None:
            native_meta["buttons_active_low"] = match.buttons.active_low
        env["FPGA_SIM_NATIVE_CONVENTION"] = json.dumps(native_meta)

    print(f"Starting simulation: {toplevel} from {prep.vhdl_path.name} [{simulator.upper()}]")
    result = subprocess.run(prep.cmd, env=env, cwd=work_dir)

    # A produced, non-empty dump is worth pointing at; a crashed/empty run is not.
    _announce_waveform(prep.wave_cfg, prep.generics, match, waveform_open)

    return _read_exit_intent(intent_file, result.returncode)


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
) -> SimChild:
    """Start a headless simulation child for single-window mode (U34).

    Shares all analysis / elaboration / waveform preparation with
    :func:`launch_simulation` (via :func:`_prepare_simulation`), but instead of
    opening a window and blocking, it runs ``sim_testbench_bridge`` with no
    display and streams signal state over a
    :class:`~fpga_sim.sim_link.SimLinkHost`.  Returns a :class:`SimChild`
    immediately; the caller (the SimulationScreen, or the benchmark) drives the
    link and calls :meth:`SimChild.stop` + :func:`finish_waveform` when done.

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
    )
    env = prep.env

    # The link the child connects back to (its listener accepts in the background).
    host = SimLinkHost()
    env.update(host.env_vars())
    env["COCOTB_TEST_MODULES"] = "sim_testbench_bridge"
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
    optionally auto-opens the viewer -- exactly as :func:`launch_simulation` does
    inline.  A no-op when capture was off or the dump is missing/empty.  Fed
    entirely from :class:`SimChild` fields, so the caller runs it after
    :meth:`SimChild.stop`.
    """
    _announce_waveform(child.wave_cfg, child.generics, child.match, child.waveform_open)
