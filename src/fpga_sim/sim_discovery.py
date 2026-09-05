"""Finding the simulators installed on this machine, and telling them apart (D17).

Where :mod:`fpga_sim.sim_backends` knows how to *drive* an engine, this module
knows which copies of it exist.  That is a separate problem because one engine
ships several code generators -- GHDL alone appears as mcode, LLVM and LLVM-JIT
builds, often installed side by side -- and a user picking "GHDL" without
knowing which one is picking blind (U35).  So each candidate binary is probed
for its ``--version`` banner, labeled by the code generator it reports, and
disambiguated when two installs would otherwise share a label.

Discovery is deliberately generous about *where* it looks (PATH, the variant
globs, the session's registered extras, ``FPGA_SIM_EXTRA_SIMS``) and strict
about what it believes: a binary that will not answer ``--version`` is not a
simulator, whatever its name.  Split out of ``sim_bridge`` unchanged.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from fpga_sim.sim_backends import _GHDLBackend, _NVCBackend
from fpga_sim.sim_config import Simulator

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


# ── Simulator discovery / identity (U35) ──────────────────────────────────────
#
# ``detect_simulators`` answers "which *engines* are on PATH"; U35 needs finer
# grain — GHDL ships three interchangeable code generators (mcode / llvm /
# llvm-jit) that differ ~2-6x in speed, and a machine can have several installed
# side by side.  ``SimulatorInfo`` names one concrete install (engine + binary +
# labeled backend); ``discover_simulators`` finds every usable one.  The
# ``Simulator`` engine literal still selects the command builder — this layer
# only adds the *which install* dimension on top.


@dataclass(frozen=True)
class SimulatorInfo:
    """One discovered simulator: an engine plus the concrete binary behind it.

    * ``engine``  — the command-builder selector, ``"ghdl"`` or ``"nvc"`` (feeds
      :func:`_backend`).
    * ``path``    — the resolved absolute path to the binary.
    * ``backend`` — the code generator, parsed from ``--version``:
      ``"mcode"`` / ``"llvm"`` / ``"llvm-jit"`` / ``"nvc"``.
    * ``label``   — short display name (``"GHDL"`` / ``"GHDL-LLVM"`` /
      ``"GHDL-JIT"`` / ``"NVC"``); the preview toggle shows ``SIM: <label>``.
      Duplicates (a backend installed at two paths) get a numeric suffix.
    * ``version`` — the first ``--version`` banner line (shown by ``--list-sims``).
    """

    engine: Simulator
    path: str
    backend: str
    label: str
    version: str


#: Short display label per detected backend (:attr:`SimulatorInfo.label`).  An
#: unrecognized GHDL code generator falls back to the plain ``"GHDL"`` label.
_BACKEND_LABEL: dict[str, str] = {
    "mcode": "GHDL",
    "llvm": "GHDL-LLVM",
    "llvm-jit": "GHDL-JIT",
    "nvc": "NVC",
}

#: Glob patterns for sibling-prefix GHDL installs (``/usr/local/ghdl-llvm`` …).
#: A module attribute so discovery tests can neutralize it; finds nothing on a
#: machine (or OS) without such a layout.
_GHDL_VARIANT_GLOBS: tuple[str, ...] = ("/usr/local/ghdl-*/bin/ghdl",)

#: Env var listing extra simulator binaries (``os.pathsep``-separated), merged
#: into discovery for one-off runs — additive to the session ``extra_simulators``.
EXTRA_SIMS_ENV = "FPGA_SIM_EXTRA_SIMS"


def _probe_simulator(path: str) -> SimulatorInfo | None:
    """Probe a candidate binary's ``--version`` and label its backend.

    Returns a :class:`SimulatorInfo` for a recognized GHDL or NVC binary, else
    ``None`` — a missing, broken, hanging (capped at 5 s), or unrecognized
    binary must never block discovery, so *any* exception means "not a
    simulator" (mirrors ``sim_testbench._simulator_version``).

    GHDL prints its code generator on the third ``--version`` line.  The mcode
    line reads ``"static elaboration, mcode JIT code generator"`` — it contains
    "JIT" too — so ``"mcode"`` is matched *before* ``"LLVM JIT"``, or every
    mcode install is mislabeled as llvm-jit.
    """
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:  # noqa: BLE001 - a missing/hung/broken binary is simply "not a simulator"
        return None
    out = f"{result.stdout or ''}\n{result.stderr or ''}"
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return None
    banner = lines[0]
    resolved = str(Path(path).resolve())
    low = out.lower()
    if banner.lower().startswith("nvc"):
        return SimulatorInfo("nvc", resolved, "nvc", _BACKEND_LABEL["nvc"], banner)
    if banner.lower().startswith("ghdl"):
        if "mcode" in low:
            backend = "mcode"
        elif "llvm jit" in low:
            backend = "llvm-jit"
        elif "llvm" in low and "code generator" in low:
            backend = "llvm"
        else:
            backend = "ghdl"  # unrecognized GHDL codegen (e.g. gcc); still usable
        return SimulatorInfo("ghdl", resolved, backend, _BACKEND_LABEL.get(backend, "GHDL"), banner)
    return None


def _disambiguate_labels(infos: list[SimulatorInfo]) -> list[SimulatorInfo]:
    """Append ``-N`` to labels shared by several entries (a backend at two paths).

    A label carried by exactly one entry is left bare; only genuine collisions
    are suffixed, so the common single-install-per-backend case reads cleanly.
    """
    counts: dict[str, int] = {}
    for info in infos:
        counts[info.label] = counts.get(info.label, 0) + 1
    used: dict[str, int] = {}
    result: list[SimulatorInfo] = []
    for info in infos:
        if counts[info.label] > 1:
            used[info.label] = used.get(info.label, 0) + 1
            result.append(replace(info, label=f"{info.label}-{used[info.label]}"))
        else:
            result.append(info)
    return result


def discover_simulators(extra: list[str] | None = None) -> list[SimulatorInfo]:
    """Discover every usable simulator: PATH defaults, GHDL variants, extras.

    Probes, in order: ``ghdl`` then ``nvc`` on PATH; the distro-named variants
    ``ghdl-mcode`` / ``ghdl-llvm`` / ``ghdl-llvm-jit`` on PATH; sibling-prefix
    installs matching :data:`_GHDL_VARIANT_GLOBS`; then the registered *extra*
    paths (the session's ``extra_simulators``) and any listed in
    :data:`EXTRA_SIMS_ENV`.  Candidates are de-duplicated by
    :func:`os.path.realpath` (first occurrence wins), so the same binary reached
    by two names appears once; unrecognized / broken candidates are skipped
    silently.  Duplicate short labels get a numeric suffix.

    The order is stable — PATH ghdl, PATH nvc, variants, extras — so the default
    engine (whatever ``ghdl`` resolves to on PATH) stays first.
    """
    candidates: list[str] = []
    for name in ("ghdl", "nvc", "ghdl-mcode", "ghdl-llvm", "ghdl-llvm-jit"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    for pattern in _GHDL_VARIANT_GLOBS:
        candidates.extend(sorted(glob.glob(pattern)))
    candidates.extend(extra or [])
    env_extra = os.environ.get(EXTRA_SIMS_ENV, "").strip()
    if env_extra:
        candidates.extend(p for p in env_extra.split(os.pathsep) if p)

    seen: set[str] = set()
    infos: list[SimulatorInfo] = []
    for cand in candidates:
        real = os.path.realpath(cand)
        if real in seen:
            continue
        seen.add(real)  # mark before probing: a broken realpath is not retried
        info = _probe_simulator(cand)
        if info is not None:
            infos.append(info)
    return _disambiguate_labels(infos)


#: CLI ``--sim`` slug → the GHDL code generator it selects (U35).  The bare
#: engine slugs ``ghdl`` / ``nvc`` keep their old meaning ("that engine via
#: PATH") and are handled separately.
_SIM_SLUG_BACKEND: dict[str, str] = {
    "ghdl-mcode": "mcode",
    "ghdl-llvm": "llvm",
    "ghdl-jit": "llvm-jit",
    "ghdl-llvm-jit": "llvm-jit",  # accepted alias for ghdl-jit
}


def resolve_simulator_arg(arg: str | None, discovered: list[SimulatorInfo]) -> SimulatorInfo | None:
    """Resolve a ``--sim`` value (or UI choice) against the *discovered* list.

    Shared by the CLI (``--sim``) and the launcher so both accept the same
    spellings:

    * ``None`` → the default (first discovered = the PATH engine).
    * ``"ghdl"`` / ``"nvc"`` → that engine via PATH (back-compat): the first
      discovered install of the engine (discovery lists the PATH one first).
    * ``"ghdl-mcode"`` / ``"ghdl-llvm"`` / ``"ghdl-jit"`` → the discovered GHDL
      install with that code generator.
    * an absolute path → probe it directly (need not be in *discovered*).

    Returns the matching :class:`SimulatorInfo`, or ``None`` when nothing
    matches (no such engine/variant installed, or the path is not a simulator) —
    the caller formats the error, listing *discovered* as appropriate.
    """
    if not discovered:
        return None
    if not arg:
        return discovered[0]
    if arg in ("ghdl", "nvc"):
        return next((i for i in discovered if i.engine == arg), None)
    if arg in _SIM_SLUG_BACKEND:
        want = _SIM_SLUG_BACKEND[arg]
        return next((i for i in discovered if i.backend == want), None)
    if os.sep in arg or (os.altsep and os.altsep in arg):
        return _probe_simulator(arg)  # a path (absolute or relative)
    return None  # an unknown bare token


def _fallback_ghdl() -> SimulatorInfo:
    """Return a placeholder GHDL entry for when discovery finds nothing installed.

    Mirrors :func:`detect_simulators`'s ``["ghdl"]`` fallback: the launcher still
    starts and the missing-simulator error surfaces at analysis time (argv[0]
    ``"ghdl"`` fails with the install hint) rather than blocking startup.
    """
    return SimulatorInfo("ghdl", "ghdl", "ghdl", "GHDL", "GHDL (not found on PATH)")
