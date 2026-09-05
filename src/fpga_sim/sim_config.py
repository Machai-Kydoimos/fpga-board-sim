"""Simulator-domain types and the run policies read from the environment (D17).

Split out of ``sim_bridge`` so every other module in the family can import the
vocabulary without importing the machinery: the backends need
:data:`Simulator` and :class:`WaveConfig`, the wrapper needs :data:`DutyMode`,
and the runner needs all of them.  Nothing here runs a simulator or reads a
design -- these are the names the rest of the family agrees on, plus the two
environment overrides that decide how a run measures itself.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Literal

from fpga_sim.session_config import load_session

IS_WINDOWS = sys.platform == "win32"

# Supported simulator backend identifiers.  Using a Literal (rather than a bare
# ``str``) lets mypy reject typos such as ``_backend("gdhl")`` at type-check
# time and gives the simulator domain a single source of truth.  Extend this
# with ``"iverilog"`` when Verilog support (U20) lands.
Simulator = Literal["ghdl", "nvc"]

# Waveform-capture formats the sim run subprocess can dump natively.  ``None``
# (off) is the default throughout; the Settings dialog persists a tri-state
# ``waveform`` session key — ``"off"`` / ``"vcd"`` / ``"fst"`` — which
# ``start_simulation`` normalizes via :func:`_normalize_wave`.
WaveFormat = Literal["vcd", "fst"]

# Duty-cycle measurement modes (U9).  Measurement is a per-run policy, not a
# fixed cost, because an exact integrator is only free when LED channels are
# sparse (see :func:`_duty_splice`):
#   "off"    no integrator -- the pre-U9 binary path, byte-identical wrapper
#   "color"  no integrator either: LED colors (U36/U37) need no duty, so
#            "colors but no dimming" stays a zero-measurement path
#   "full"   integrator spliced -> brightness + PWM color mixing
# ``FPGA_SIM_DUTY`` overrides the caller's choice, so a benchmark or a CI run
# can pin a mode without touching the session (mirrors ``FPGA_SIM_WAVEFORM``).
DutyMode = Literal["off", "color", "full"]
DUTY_ENV = "FPGA_SIM_DUTY"
DEFAULT_DUTY_MODE: DutyMode = "full"

#: Splice fragments live one file per splice point (``<algo>.ports`` /
#: ``<algo>.body``), so an algorithm is swapped by name rather than by
#: re-plumbing.  Both shipped algorithms export the identical accumulator
#: contract (48-bit ``acc``/``tch`` per channel), so the host math is unchanged
#: either way; they differ only in how the integrator is woken:
#:
#:   ``fix_ns_pc``  one process per channel -- wakes once per channel transition
#:   ``fix_ns_1p``  one process per vector  -- wakes once per instant, rescans N
#:
#: Which is cheaper is a property of the design (see the fragment headers), so
#: ``FPGA_SIM_DUTY_ALGO`` selects it per run and the default below is set from
#: the measured design set.
DUTY_ALGOS = ("fix_ns_pc", "fix_ns_1p")
DEFAULT_DUTY_ALGO = "fix_ns_1p"
DUTY_ALGO_ENV = "FPGA_SIM_DUTY_ALGO"


def resolve_duty_algo() -> str:
    """Resolve which integrator to splice: ``FPGA_SIM_DUTY_ALGO``, else the default.

    An unrecognized name falls back rather than failing the run, matching
    :func:`resolve_duty_mode` -- a typo should not stop a simulation.
    """
    raw = os.environ.get(DUTY_ALGO_ENV, "").strip().lower()
    return raw if raw in DUTY_ALGOS else DEFAULT_DUTY_ALGO


def resolve_duty_mode(mode: DutyMode | None = None) -> DutyMode:
    """Resolve the duty mode: env var, else *mode*, else the session, else default.

    Every wrapper-generating path funnels through here so the wrapper analyzed
    by :func:`analyze_vhdl` and the one elaborated by :func:`_prepare_simulation`
    can never disagree — a mismatch would leave the run reading duty ports that
    the elaborated design does not have.  An unrecognized env value is ignored
    rather than fatal (a typo should not stop a simulation from running).

    The session's ``led_pwm`` preference (U47) is consulted **here**, rather than
    threaded as an argument from the launcher, precisely to keep that funnel
    intact: a future wrapper-generating path that forgot the argument would
    silently disagree with the rest, which is the failure
    :func:`wrapper_is_stale` exists to make impossible. Env still wins, so a
    benchmark or CI run pins the mode without touching the user's session, and
    an explicit *mode* still beats the preference so a caller that means "full"
    gets it.
    """
    raw = os.environ.get(DUTY_ENV, "").strip().lower()
    if raw in ("off", "color", "full"):
        return raw  # type: ignore[return-value]  # narrowed by the membership test
    if mode is not None:
        return mode
    # Only ``false`` turns it off; a missing key means PWM, the historical
    # behavior.  Reading the session is best-effort — load_session() already
    # swallows a missing or corrupt file and returns {}.
    if load_session().get("led_pwm") is False:
        return "off"
    return DEFAULT_DUTY_MODE


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
