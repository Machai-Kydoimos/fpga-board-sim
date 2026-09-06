"""The two simulator backends and the command lines they build (D17).

One class per engine behind a small ABC (roadmap D2): the shared half --
finding the binary, reporting availability, locating its lib directories --
lives on the base, and each backend overrides only its name and the three
command builders (analyze, elaborate, run).  A third engine (Verilog, U20)
would override the same four things and nothing else.

The differences that matter are all here rather than scattered through the
runner: GHDL resolves generics at run time and NVC bakes them into the
elaboration artifact; GHDL writes ``--vcd=``/``--fst=`` after the toplevel
while NVC takes ``--wave=`` plus ``--format=`` before it; NVC needs an explicit
heap cap on the embedded-core designs.  Split out of ``sim_bridge`` unchanged.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from fpga_sim.sim_config import IS_WINDOWS, Simulator, WaveConfig

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
    def lib_dir(cls, binary: str | None = None) -> str:
        bin_path = Path(binary or cls.find()).resolve().parent
        lib_dir = bin_path.parent / "lib"
        return str(lib_dir) if lib_dir.is_dir() else str(bin_path)

    @classmethod
    def sim_bin_lib(cls, binary: str | None = None) -> tuple[str, str]:
        """Return (bin_dir, lib_dir) for environment setup.

        *binary* is the selected install's resolved path (U35); when omitted it
        falls back to ``cls.find()`` (the PATH default), so a caller that has not
        chosen a specific install still works.
        """
        return str(Path(binary or cls.find()).resolve().parent), cls.lib_dir(binary)

    # Per-simulator specifics — subclasses must override.  The command builders
    # take *binary* (U35): the resolved argv[0] of the selected install, so a
    # non-PATH backend (a specific GHDL code generator) runs from its own path
    # instead of whatever ``find()`` resolves.  ``binary=None`` falls back to
    # ``find()`` for callers that never pick a specific install.
    @staticmethod
    @abstractmethod
    def plugin_lib_name() -> str: ...

    @staticmethod
    @abstractmethod
    def analyze_cmd(vhdl_path: Path, work_dir: str, binary: str | None = None) -> list[str]: ...

    @staticmethod
    @abstractmethod
    def elaborate_cmd(
        toplevel: str, generics: dict[str, str], work_dir: str, binary: str | None = None
    ) -> list[str]: ...

    @staticmethod
    @abstractmethod
    def run_cmd(
        toplevel: str,
        generics: dict[str, str],
        plugin_lib: str,
        work_dir: str,
        wave: WaveConfig | None = None,
        binary: str | None = None,
    ) -> list[str]: ...


#: ``-fsynopsys`` accepts the pre-standard Synopsys packages -- ``std_logic_arith``,
#: ``std_logic_unsigned``, ``std_logic_signed`` -- that GHDL otherwise refuses
#: outright ("use of synopsys package ... needs the -fsynopsys option").  They are
#: non-standard and ``ieee.numeric_std`` is the right thing to teach, but a great
#: deal of course material and vendor example code is written with them, and a
#: student whose instructor's own file will not even *analyze* has no way to tell
#: a broken tool from a broken design.  So the tool accepts them and says so once,
#: gently, rather than refusing (see ``uses_synopsys_packages``).
#:
#: All three commands need it, not just analysis: GHDL's mcode backend elaborates
#: inside ``-r``, so a design analyzed with the flag still fails at elaboration or
#: run without it.  On the compiled backends the extra flag is harmless.
#: NVC accepts these packages with no flag at all.
_SYNOPSYS = ("-fsynopsys",)


class _GHDLBackend(_SimBackend):
    """GHDL simulator backend – uses the VPI interface."""

    NAME: Simulator = "ghdl"

    @staticmethod
    def plugin_lib_name() -> str:
        return "cocotbvpi_ghdl.dll" if IS_WINDOWS else "libcocotbvpi_ghdl.so"

    @staticmethod
    def analyze_cmd(vhdl_path: Path, work_dir: str, binary: str | None = None) -> list[str]:
        # -O2 speeds the llvm (AOT) backend +8-12% on design-bound workloads and
        # is a measured no-op on mcode/llvm-jit, at negligible analyze/elab cost
        # (docs/u25_ghdl_perf_profile.md), so it is passed unconditionally.
        ghdl = binary or _GHDLBackend.find()
        return [ghdl, "-a", "-O2", *_SYNOPSYS, "--std=08", f"--workdir={work_dir}", str(vhdl_path)]

    @staticmethod
    def elaborate_cmd(
        toplevel: str, generics: dict[str, str], work_dir: str, binary: str | None = None
    ) -> list[str]:
        # GHDL takes no generics at -e (the compiled backends reject -g here);
        # they are simulation options, passed after the unit at run (-r) time.
        # -O2: same rationale as analyze_cmd.
        ghdl = binary or _GHDLBackend.find()
        return [ghdl, "-e", "-O2", *_SYNOPSYS, "--std=08", f"--workdir={work_dir}", toplevel]

    @staticmethod
    def run_cmd(
        toplevel: str,
        generics: dict[str, str],
        plugin_lib: str,
        work_dir: str,
        wave: WaveConfig | None = None,
        binary: str | None = None,
    ) -> list[str]:
        cmd = [binary or _GHDLBackend.find(), "-r", *_SYNOPSYS, "--std=08", f"--workdir={work_dir}"]
        cmd.append(toplevel)
        # -g is a *simulation* option: documented (and only reliable) AFTER the
        # unit name ("ghdl -r --std=08 my_unit -gDEPTH=12").  mcode/llvm-jit
        # happen to honor a pre-unit -g too, but the compiled llvm/gcc driver
        # silently drops it there — the design then runs with default generics.
        for k, v in (generics or {}).items():
            cmd.append(f"-g{k}={v}")
        # Silence IEEE assertion noise from the t=0 deltas only (metavalue
        # warnings while cocotb's first input deposits land); anything a
        # design does after time zero still warns normally.
        cmd.append("--asserts=disable-at-0")
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
    def analyze_cmd(vhdl_path: Path, work_dir: str, binary: str | None = None) -> list[str]:
        nvc = binary or _NVCBackend.find()
        return [nvc, f"--work=work:{work_dir}", "--std=2008", "-a", str(vhdl_path)]

    @staticmethod
    def elaborate_cmd(
        toplevel: str, generics: dict[str, str], work_dir: str, binary: str | None = None
    ) -> list[str]:
        """Elaborate with generics (NVC requires generics at elaboration time)."""
        nvc = binary or _NVCBackend.find()
        cmd = [nvc, f"--work=work:{work_dir}", "--std=2008", "-H", _NVC_HEAP, "-e"]
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
        binary: str | None = None,
    ) -> list[str]:
        # generics were baked in at elaboration (-e); ignored here
        cmd = [
            binary or _NVCBackend.find(),
            f"--work=work:{work_dir}",
            "--std=2008",
            "-H",
            _NVC_HEAP,
            "-r",
            # Silence IEEE assertion noise from the t=0 deltas only (metavalue
            # warnings while cocotb's first input deposits land); anything a
            # design does after time zero still warns normally.
            "--ieee-warnings=off-at-0",
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
