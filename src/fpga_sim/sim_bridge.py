"""The simulation pipeline, as one name — now a map of where it lives (D17).

This module used to *be* the pipeline: 3,067 lines and nine unrelated concerns,
2.5x the next-largest file in the project and 22% of ``src/``.  It carried its
own section banners, and those banners were the seams; the split follows them
exactly, so nothing here changed except which file each function sits in.

**Where everything went.**

===========================  ===================================================
:mod:`fpga_sim.sim_config`   the domain's vocabulary — the ``Simulator`` /
                             ``WaveFormat`` / ``DutyMode`` types, ``WaveConfig``,
                             and the duty policy read from the environment
:mod:`fpga_sim.sim_backends` one class per engine: how GHDL and NVC each spell
                             analyze, elaborate and run
:mod:`fpga_sim.sim_discovery` which copies of those engines exist on this
                             machine, and how to tell them apart (U35)
:mod:`fpga_sim.vhdl_interface` reading a design's toplevel ports and generics,
                             judging nothing
:mod:`fpga_sim.conventions`  matching those declarations against a board's own
                             port names (U21 board-native mode)
:mod:`fpga_sim.vhdl_contract` deciding whether a design can run here, and
                             saying why not when it cannot
:mod:`fpga_sim.wrapper`      generating the ``sim_wrapper`` that adapts a design
                             to the testbench's boundary, and ``analyze_vhdl``
:mod:`fpga_sim.waveform`     capturing a run as VCD or FST, and opening it
:mod:`fpga_sim.sim_runner`   the environment the child needs, and the child
                             itself (``start_simulation`` → ``SimChild``)
:mod:`fpga_sim.paths`        where the project's own files live
===========================  ===================================================

**Why this file still exists.**  About thirty-five modules and test files import
from ``sim_bridge`` by name; re-exporting keeps every one of them working and
keeps this change reviewable as a move rather than a rewrite.  New code should
import from the module that owns the name — the map above is the directory —
and the ``__all__`` below is the exhaustive list of what this door still opens.

One thing a re-export cannot forward is **monkeypatching a module global**:
``fpga_sim.sim_bridge.subprocess.run`` and friends now stand in front of nothing.
A test that fakes ``shutil.which``, ``subprocess.run`` or ``WAVEFORM_DIR`` has to
name the module that reads it (``sim_discovery``, ``waveform``, ``sim_runner``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from fpga_sim.conventions import (
    _SIZING_GENERICS,
    ContractResult,
    ConventionMatch,
    NativePort,
    NativeSeg,
    _attempt_convention,
    _best_convention_attempt,
    _native_convention_message,
    _near_miss_convention_message,
    match_convention,
)
from fpga_sim.sim_backends import (
    _NVC_HEAP,
    _backend,
    _GHDLBackend,
    _NVCBackend,
    _SimBackend,
)
from fpga_sim.sim_config import (
    DEFAULT_DUTY_ALGO,
    DEFAULT_DUTY_MODE,
    DUTY_ALGO_ENV,
    DUTY_ALGOS,
    DUTY_ENV,
    IS_WINDOWS,
    DutyMode,
    Simulator,
    WaveConfig,
    WaveFormat,
    resolve_duty_algo,
    resolve_duty_mode,
)
from fpga_sim.sim_discovery import (
    _BACKEND_LABEL,
    _GHDL_VARIANT_GLOBS,
    _SIM_SLUG_BACKEND,
    EXTRA_SIMS_ENV,
    SimulatorInfo,
    _disambiguate_labels,
    _fallback_ghdl,
    _find_ghdl,
    _probe_simulator,
    detect_simulators,
    discover_simulators,
    resolve_simulator_arg,
)
from fpga_sim.sim_runner import (
    _STDERR_TAIL_LINES,
    SimChild,
    _build_sim_env,
    _libpython_name,
    _libpython_via_config,
    _prepare_simulation,
    _pump_stderr,
    _SimPrep,
    _venv_dirs,
    finish_waveform,
    start_simulation,
)
from fpga_sim.vhdl_contract import (
    _check_parsed_contract,
    add_error_hints,
    check_vhdl_contract,
)
from fpga_sim.vhdl_interface import (
    _CONTRACT_PORTS,
    _REQUIRED_GENERICS,
    _REQUIRED_PORTS,
    _WRAPPER_DEFAULT_WIDTHS,
    _board_port_widths,
    _has_rgb_generic,
    _has_seg_port,
    _IfaceDecl,
    _parse_toplevel_interface,
    check_vhdl_encoding,
)
from fpga_sim.waveform import (
    DEFAULT_VIEWER,
    WAVEFORM_DIR,
    WAVEFORM_DIR_ENV,
    WAVEFORM_ENV,
    WAVEFORM_MEMORIES_ENV,
    WAVEFORM_OPEN_ENV,
    WAVEFORM_VIEWER_ENV,
    _announce_waveform,
    _env_flag,
    _gtkw_path,
    _native_gtkw_signals,
    _normalize_wave,
    _open_waveform,
    _viewer_argv,
    _waveform_dir,
    _waveform_path,
    _write_gtkw,
)
from fpga_sim.wrapper import (
    _DUTY_FRAGMENT_DIR,
    _WRAPPER_TEMPLATE,
    _bound_check_probe,
    _duty_channels,
    _duty_fragment,
    _duty_splice,
    _generate_wrapper,
    _name_bound_check_port,
    _native_port_map,
    _render_native_wrapper,
    _render_wrapper,
    analyze_vhdl,
    wrapper_is_stale,
)

#: Names this module re-exports for the ~35 files that import from it.  It is an
#: explicit list rather than a star-import because mypy's strict mode does not
#: treat an imported name as exported unless it is named here -- and because the
#: list is the module's contract with its callers, which is worth writing down.
__all__ = [
    "DEFAULT_DUTY_ALGO",
    "DEFAULT_DUTY_MODE",
    "DUTY_ALGOS",
    "DUTY_ALGO_ENV",
    "DUTY_ENV",
    "IS_WINDOWS",
    "DutyMode",
    "Simulator",
    "WaveConfig",
    "WaveFormat",
    "resolve_duty_algo",
    "resolve_duty_mode",
    # backends
    "_GHDLBackend",
    "_NVCBackend",
    "_SimBackend",
    "_backend",
    "_NVC_HEAP",
    # discovery
    "EXTRA_SIMS_ENV",
    "SimulatorInfo",
    "_BACKEND_LABEL",
    "_GHDL_VARIANT_GLOBS",
    "_SIM_SLUG_BACKEND",
    "_disambiguate_labels",
    "_fallback_ghdl",
    "_find_ghdl",
    "_probe_simulator",
    "detect_simulators",
    "discover_simulators",
    "resolve_simulator_arg",
    # VHDL interface parsing
    "check_vhdl_encoding",
    "_IfaceDecl",
    "_board_port_widths",
    "_has_rgb_generic",
    "_has_seg_port",
    "_parse_toplevel_interface",
    "_REQUIRED_PORTS",
    "_CONTRACT_PORTS",
    "_REQUIRED_GENERICS",
    "_WRAPPER_DEFAULT_WIDTHS",
    # board-native conventions
    "ContractResult",
    "ConventionMatch",
    "NativePort",
    "NativeSeg",
    "match_convention",
    "_attempt_convention",
    "_best_convention_attempt",
    "_native_convention_message",
    "_near_miss_convention_message",
    "_SIZING_GENERICS",
    # the contract itself
    "check_vhdl_contract",
    "add_error_hints",
    "_check_parsed_contract",
    # wrapper generation + analysis
    "analyze_vhdl",
    "wrapper_is_stale",
    "_generate_wrapper",
    "_render_wrapper",
    "_render_native_wrapper",
    "_duty_channels",
    "_duty_fragment",
    "_duty_splice",
    "_bound_check_probe",
    "_name_bound_check_port",
    "_native_port_map",
    "_WRAPPER_TEMPLATE",
    "_DUTY_FRAGMENT_DIR",
    # waveform capture
    "WAVEFORM_DIR",
    "WAVEFORM_DIR_ENV",
    "WAVEFORM_ENV",
    "WAVEFORM_MEMORIES_ENV",
    "WAVEFORM_OPEN_ENV",
    "WAVEFORM_VIEWER_ENV",
    "DEFAULT_VIEWER",
    "_announce_waveform",
    "_env_flag",
    "_gtkw_path",
    "_native_gtkw_signals",
    "_normalize_wave",
    "_open_waveform",
    "_viewer_argv",
    "_waveform_dir",
    "_waveform_path",
    "_write_gtkw",
    # running the child
    "SimChild",
    "start_simulation",
    "finish_waveform",
    "_build_sim_env",
    "_prepare_simulation",
    "_SimPrep",
    "_pump_stderr",
    "_STDERR_TAIL_LINES",
    "_venv_dirs",
    "_libpython_name",
    "_libpython_via_config",
]


# >>> moved to fpga_sim.sim_discovery <<<
# >>> moved to fpga_sim.sim_runner <<<
