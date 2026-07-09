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
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

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
    """A resolved waveform-capture request: output path + format.

    Handed to a backend's ``run_cmd`` when the user enabled capture.  GHDL and
    NVC spell the flags differently (``--vcd=`` / ``--fst=`` after the toplevel
    vs. ``--wave=`` + ``--format=`` before it), so only the abstract format is
    stored here and each backend renders its own flags.
    """

    path: str
    fmt: WaveFormat


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

    STOPPED = "stopped"  # ESC / window close / [Stop] — no intent file written
    BACK_TO_BOARDS = "back_to_boards"  # [Back to Boards] → board selector
    CHANGE_VHDL = "change_vhdl"  # [Change VHDL] → VHDL file picker
    RELOAD_VHDL = "reload_vhdl"  # [Reload VHDL] → re-analyze same file, relaunch


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
        return SimExit(intent_file.read_text().strip())
    except (OSError, ValueError):
        return SimExit.STOPPED


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


def check_vhdl_contract(
    path: str | Path,
    board_def: BoardDef | None = None,
) -> tuple[bool, str]:
    """Stage 2: contract validation (text-based, no simulator needed).

    Parses the toplevel entity's port/generic clauses and checks them against
    the design contract — board-aware when *board_def* is given (fixed widths
    are compared to the board's resource counts).  Falls back to the legacy
    whole-text scan when the interface cannot be parsed, so exotic-but-valid
    formatting is never rejected on parser limitations alone.

    Returns (ok: bool, message: str).
    """
    path = Path(path)
    stem = path.stem.lower()
    try:
        text = path.read_text(errors="replace")
    except OSError as e:
        return False, f"Cannot read file: {e}"

    # Check entity name matches filename
    entities = re.findall(r"entity\s+(\w+)\s+is", text, re.IGNORECASE)
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

    parsed = _parse_toplevel_interface(text, stem)
    if parsed is not None:
        return _check_parsed_contract(path.name, parsed[0], parsed[1], board_def)

    # ── Legacy whole-text fallback (interface not parseable) ──────────────

    # Check required ports
    missing_ports = [
        p for p in _REQUIRED_PORTS if not re.search(r"\b" + p + r"\b", text, re.IGNORECASE)
    ]
    if missing_ports:
        return False, (
            f"Missing required port(s) in '{path.name}': {', '.join(missing_ports)}.\n"
            "The top-level entity must have ports: clk, sw, btn, led."
        )

    # NUM_SEGS without a seg port is a contract error: the generic is meaningless alone
    if re.search(r"\bNUM_SEGS\b", text, re.IGNORECASE) and not _has_seg_port(text):
        return False, (
            f"'{path.name}' declares NUM_SEGS generic but has no 'seg' output port.\n"
            "Add:  seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)"
        )

    # Warn (non-fatal) about missing generics
    missing_generics = [
        g for g in _REQUIRED_GENERICS if not re.search(r"\b" + g + r"\b", text, re.IGNORECASE)
    ]
    if missing_generics:
        print(f"[warn] Missing generics (will use VHDL defaults): {', '.join(missing_generics)}")

    return True, ""


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


def _generate_wrapper(
    toplevel: str,
    work_dir: str,
    board_def: BoardDef | None = None,
    design_has_seg: bool = False,
) -> Path:
    """Write ``sim_wrapper.vhd`` to *work_dir* with placeholders substituted.

    When both *board_def* has a seven_seg display and the design declares a
    ``seg`` output port, the generated wrapper includes the ``NUM_SEGS``
    generic and ``seg`` port.  Otherwise those lines are omitted.
    """
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
    out = Path(work_dir) / "sim_wrapper.vhd"
    out.write_text(content)
    return out


def analyze_vhdl(
    vhdl_path: str | Path,
    work_dir: str | None = None,
    toplevel: str | None = None,
    simulator: Simulator = "ghdl",
    board_def: BoardDef | None = None,
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
            toplevel, work_dir, board_def=board_def, design_has_seg=_design_has_seg
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

#: Directory for user-requested waveform dumps.  A module attribute (mirroring
#: ``session_config.SESSION_FILE``) so tests can redirect it; the run subprocess
#: writes here regardless of its temp work-dir cwd because the path is absolute.
WAVEFORM_DIR: Path = Path.home() / ".fpga_simulator" / "waveforms"


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


def _waveform_path(entity: str, fmt: WaveFormat) -> Path:
    """Absolute output path for a waveform dump of *entity* in *fmt*.

    One file per design entity under :data:`WAVEFORM_DIR`, overwritten each run
    (the extension equals the format: ``blinky.vcd`` / ``blinky.fst``).
    """
    return WAVEFORM_DIR / f"{entity}.{fmt}"


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
    enables native simulator waveform capture to
    ``~/.fpga_simulator/waveforms/<toplevel>.<ext>`` (see :func:`_waveform_path`).
    Capture is a run-command flag on GHDL/NVC and independent of cocotb, so
    ``sim_testbench`` is unaffected; the path is printed after a run that
    produced a non-empty file, for opening in GTKWave.

    This call blocks until the simulation exits, then returns the
    :class:`SimExit` the user chose via the in-simulation toolbar
    (``SimExit.STOPPED`` for a plain ESC / window-close / [Stop] exit).
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
        except Exception:
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
        subprocess.run(
            be.analyze_cmd(vhdl_path, work_dir),
            env=env,
            check=True,
            cwd=work_dir,
        )
        wrapper_path = _generate_wrapper(
            toplevel, work_dir, board_def=board_def, design_has_seg=_design_has_seg
        )
        subprocess.run(
            be.analyze_cmd(wrapper_path, work_dir),
            env=env,
            check=True,
            cwd=work_dir,
        )

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

    # Resolve the optional waveform request (off unless the user enabled it).
    wave_fmt = _normalize_wave(waveform)
    wave_cfg: WaveConfig | None = None
    if wave_fmt is not None:
        wave_target = _waveform_path(toplevel, wave_fmt)
        wave_target.parent.mkdir(parents=True, exist_ok=True)
        wave_cfg = WaveConfig(str(wave_target), wave_fmt)

    # Both backends share the same run_cmd signature; NVC ignores generics (already baked in).
    cmd = be.run_cmd("sim_wrapper", generics, plugin_lib, work_dir, wave=wave_cfg)

    # Exit-intent side channel (see SimExit).  A reused work_dir — the reload
    # path re-analyzes in place — may hold a stale intent from the previous
    # run, so always start from a clean slate.
    intent_file = Path(work_dir) / _EXIT_INTENT_NAME
    intent_file.unlink(missing_ok=True)

    env["COCOTB_TEST_MODULES"] = "sim_testbench"
    env["TOPLEVEL"] = "sim_wrapper"
    env["FPGA_SIM_TOPLEVEL"] = toplevel  # user's entity, for display/metadata
    env["FPGA_SIM_BOARD_JSON"] = board_json
    env["FPGA_SIM_WIDTH"] = str(sim_width)
    env["FPGA_SIM_HEIGHT"] = str(sim_height)
    env["FPGA_SIM_EXIT_INTENT_FILE"] = str(intent_file)
    if speed_factor is not None:
        env["FPGA_SIM_SPEED"] = str(speed_factor)
    if theme is not None:
        env["FPGA_SIM_THEME"] = theme
    # Metadata consumed by sim_testbench when FPGA_SIM_METRICS is set
    env["FPGA_SIM_SIMULATOR"] = simulator
    env["FPGA_SIM_VHDL_PATH"] = str(vhdl_path)
    env["FPGA_SIM_GENERICS"] = json.dumps(generics)

    print(f"Starting simulation: {toplevel} from {vhdl_path.name} [{simulator.upper()}]")
    result = subprocess.run(cmd, env=env, cwd=work_dir)

    # A produced, non-empty dump is worth pointing at; a crashed/empty run is not.
    if wave_cfg is not None:
        wpath = Path(wave_cfg.path)
        if wpath.is_file() and wpath.stat().st_size > 0:
            print(f"Waveform written: {wpath}\n  Open it with:  gtkwave {wpath}")

    return _read_exit_intent(intent_file, result.returncode)
