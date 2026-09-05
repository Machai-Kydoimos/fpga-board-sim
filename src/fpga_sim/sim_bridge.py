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
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import IO, TYPE_CHECKING

from fpga_sim.paths import REPO_ROOT, SIM_DIR, VENV_DIR
from fpga_sim.platform_open import open_with_default_app
from fpga_sim.sim_link import SimLinkHost, send

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef

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

#: Swappable duty-integrator fragments, one file per splice point per algorithm.
_DUTY_FRAGMENT_DIR: Path = SIM_DIR / "duty"

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
]


# >>> moved to fpga_sim.sim_discovery <<<
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


# >>> moved to fpga_sim.vhdl_interface <<<
# >>> moved to fpga_sim.vhdl_contract <<<
# ── Simulation infrastructure ─────────────────────────────────────────────────

_WRAPPER_TEMPLATE: Path = SIM_DIR / "sim_wrapper_template.vhd"

#: Placeholder names the duty splice fills in; all empty outside Full mode.
_DUTY_PLACEHOLDERS = ("numeric_use", "duty_ports", "duty_decls", "duty_body")


def _duty_channels(mode: DutyMode, *, has_seg: bool) -> list[tuple[str, str]]:
    """List the monitored output vectors for *mode*: ``(port, channel-count expression)``.

    Segments are LEDs, so a 7-seg run measures ``seg`` on the same machinery
    (8 channels per digit).  Off and Color-only monitor nothing.
    """
    if mode != "full":
        return []
    channels = [("led", "NUM_LEDS")]
    if has_seg:
        channels.append(("seg", "8 * NUM_SEGS"))
    return channels


def _duty_fragment(part: str, prefix: str, count: str) -> str:
    """Render one splice fragment of the active algorithm for a monitored vector.

    ``{p}`` is the port name (``led`` / ``seg``) and ``{n}`` its channel-count
    expression, spliced verbatim into VHDL — ``48 * 8 * NUM_SEGS - 1`` parses as
    intended, so no parenthesizing is needed.
    """
    text = (_DUTY_FRAGMENT_DIR / f"{resolve_duty_algo()}.{part}.vhd.frag").read_text(
        encoding="utf-8"
    )
    return text.format(p=prefix, n=count)


def _duty_splice(channels: list[tuple[str, str]]) -> dict[str, str]:
    """Build the wrapper's duty placeholders for the monitored *channels*.

    Both wrapper paths (generic template and :func:`_render_native_wrapper`)
    consume this one dict, so the integrator is identical either way: the
    measured output is routed through an internal ``<port>_int`` signal that the
    per-channel processes watch, and the port itself becomes a pass-through.

    An empty *channels* list yields empty strings for every placeholder, which
    is what makes Off / Color-only a genuine zero-cost path: the generated
    wrapper is byte-identical to the pre-U9 one, not merely equivalent.
    """
    if not channels:
        return dict.fromkeys(_DUTY_PLACEHOLDERS, "")
    bodies = [
        f"  {p} <= {p}_int;\n" + _duty_fragment("body", p, n).rstrip("\n") for p, n in channels
    ]
    return {
        "numeric_use": "use ieee.numeric_std.all;\n",  # unsigned/resize for the accumulators
        "duty_ports": "".join(_duty_fragment("ports", p, n) for p, n in channels),
        "duty_decls": "".join(
            f"  signal {p}_int : std_logic_vector({n} - 1 downto 0);\n" for p, n in channels
        ),
        "duty_body": "\n" + "\n\n".join(bodies) + "\n",
    }


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
    toplevel: str,
    match: ConventionMatch,
    board_def: BoardDef | None = None,
    duty: DutyMode = "off",
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
      active-high ``{dp, g..a}`` byte the display expects (dp forced off);
    * a ``scan``-style 7-seg (U22) is combinationally demultiplexed: digit i's
      byte shows the shared segment lines (+ dp) only while its digit enable
      is active -- unlatched, so the duty engine integrates the honest 1/N
      scan brightness and a stopped scan shows its one lit digit.

    The entity, generics, top ports and clock process are identical to the generic
    wrapper (so ``start_simulation``/``run_cmd``/``_write_gtkw``/the cocotb
    testbench are unchanged); only the architecture body differs -- a
    generic-map-less uut with native names.  Generic *defaults* are baked to the
    board's widths so ``analyze_vhdl``'s default-generic early elaboration lines the
    top ports up with the native uut's fixed widths (no "defaults dance").

    In Full measurement mode (U9) the same duty integrator the generic template
    splices is appended here, watching the boundary ``led``/``seg`` values —
    i.e. *after* the active-low inversion and the 7-seg packing, so a native
    design's measured duty is the brightness the board actually shows.
    """
    sw, btn, led, seg, green, rgb = (
        match.switches,
        match.buttons,
        match.leds,
        match.seven_seg,
        match.leds_green,
        match.leds_rgb,
    )
    decls: list[str] = []  # architecture declarative signals
    assigns: list[str] = []  # concurrent assignments (adapters)
    pmap: list[str] = [f"{match.clk} => clk"]  # uut port-map association lines

    # U9 duty splice.  Measured outputs are produced into ``<port>_int`` and the
    # port becomes a pass-through emitted by the splice body; unmeasured ones are
    # assigned directly, exactly as before.  ``numeric_use`` is ignored here: the
    # native wrapper already uses numeric_std for the LED zero-extend.
    duty_channels = _duty_channels(duty, has_seg=seg is not None)
    splice = _duty_splice(duty_channels)
    measured = {port for port, _ in duty_channels}
    led_out = "led_int" if "led" in measured else "led"
    seg_out = "seg_int" if "seg" in measured else "seg"

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

    # LEDs: read the native bank(s) back (invert when active-low) onto the board
    # `led` boundary -- board LEDs the convention omits stay dark.  Boundary
    # channel layout (U37): mono channels occupy the low bits, then (r,g,b) per
    # RGB site; MONO is where the RGB block starts.
    mono = (
        board_def.num_led_channels - 3 * board_def.num_rgb_leds
        if board_def is not None
        else (led.width if led is not None else 0)
    )
    if rgb is None:
        # No RGB bank matched: the mono bank zero-extends over the whole
        # boundary (RGB channel bits, if any, stay dark) -- the pre-U38 form.
        assert led is not None  # the match floor: at least one of leds/leds_rgb
        led_inv = "not " if led.active_low else ""
        decls.append(f"  signal led_uut : std_logic_vector({led.width} - 1 downto 0);")
        assigns.append(
            f"  {led_out} <= std_logic_vector(resize(unsigned({led_inv}led_uut), NUM_LEDS));"
        )
        pmap += _native_port_map(led, "led_uut")
    else:
        # RGB bank matched (U38): assemble the boundary from slices -- each bit
        # must have exactly one driver, so the mono resize covers only the mono
        # block and any channels past both banks are explicitly dark.
        if led is not None:
            led_inv = "not " if led.active_low else ""
            decls.append(f"  signal led_uut : std_logic_vector({led.width} - 1 downto 0);")
            assigns.append(
                f"  {led_out}({mono} - 1 downto 0) <= "
                f"std_logic_vector(resize(unsigned({led_inv}led_uut), {mono}));"
            )
            pmap += _native_port_map(led, "led_uut")
        elif mono > 0:
            assigns.append(f"  {led_out}({mono} - 1 downto 0) <= (others => '0');")
        rgb_inv = "not " if rgb.active_low else ""
        decls.append(f"  signal rgbch_uut : std_logic_vector({rgb.width} - 1 downto 0);")
        assigns.append(
            f"  {led_out}({mono} + {rgb.width} - 1 downto {mono}) <= {rgb_inv}rgbch_uut;"
        )
        pmap += _native_port_map(rgb, "rgbch_uut")
        if board_def is not None and mono + rgb.width < max(1, board_def.num_led_channels):
            assigns.append(
                f"  {led_out}(NUM_LEDS - 1 downto {mono + rgb.width}) <= (others => '0');"
            )

    # Secondary green bank (rare): captured so the output has a driver, not shown --
    # like the generic wrapper leaving `seg` dark on a non-7-seg design.
    if green is not None:
        decls.append(f"  signal ledg_uut : std_logic_vector({green.width} - 1 downto 0);")
        pmap += _native_port_map(green, "ledg_uut")

    # 7-seg (individual style): each digit is a wpd-bit vector packed into seg's byte.
    if seg is not None and seg.style == "individual":
        wpd = seg.width_per_digit
        inv = "not " if seg.active_low else ""
        for i, name in enumerate(seg.names):
            sig = f"hex{i}_uut"
            decls.append(f"  signal {sig} : std_logic_vector({wpd} - 1 downto 0);")
            assigns.append(f"  {seg_out}({8 * i + wpd - 1} downto {8 * i}) <= {inv}{sig};")
            if wpd < 8:  # remaining high bits of the digit byte (e.g. dp) -> off
                assigns.append(f"  {seg_out}({8 * i + 7} downto {8 * i + wpd}) <= (others => '0');")
            pmap.append(f"{name} => {sig}")

    # 7-seg (scan style, U22): the design drives the physical multiplexed
    # interface -- shared segment lines + digit enables (+ shared dp).  The
    # demux is deliberately combinational and UNLATCHED: digit i's boundary
    # byte shows the (polarity-corrected) segment lines only while its enable
    # is active, so the duty engine integrates the honest 1/N scan brightness
    # and a stopped scan shows the one lit digit -- exactly the real hardware.
    if seg is not None and seg.style == "scan":
        assert seg.digit_enable is not None  # scan matches always carry the enable
        wpd = seg.width_per_digit
        digits = seg.num_digits
        seg_inv = "not " if seg.active_low else ""
        en_inv = "not " if seg.digit_enable.active_low else ""
        decls.append(f"  signal scanseg_uut : std_logic_vector({wpd} - 1 downto 0);")
        decls.append(f"  signal scanseg_on  : std_logic_vector({wpd} - 1 downto 0);")
        decls.append(f"  signal scanen_uut  : std_logic_vector({digits} - 1 downto 0);")
        decls.append(f"  signal scanen_on   : std_logic_vector({digits} - 1 downto 0);")
        if seg.scalar_segments:
            pmap += [f"{name} => scanseg_uut({k})" for k, name in enumerate(seg.names)]
        else:
            pmap.append(f"{seg.names[0]} => scanseg_uut")
        pmap += _native_port_map(seg.digit_enable, "scanen_uut")
        assigns.append(f"  scanseg_on <= {seg_inv}scanseg_uut;")
        assigns.append(f"  scanen_on  <= {en_inv}scanen_uut;")
        if seg.dp is not None:
            decls.append("  signal scandp_uut : std_logic;")
            decls.append("  signal scandp_on  : std_logic;")
            pmap.append(f"{seg.dp} => scandp_uut")
            # dp shares the segment drive polarity (one active_low per side).
            assigns.append(f"  scandp_on  <= {seg_inv}scandp_uut;")
        for i in range(digits):
            assigns.append(
                f"  {seg_out}({8 * i + wpd - 1} downto {8 * i}) <= "
                f"scanseg_on when scanen_on({i}) = '1' else (others => '0');"
            )
            if wpd < 7:  # unused segment bits below dp (no current board)
                assigns.append(f"  {seg_out}({8 * i + 6} downto {8 * i + wpd}) <= (others => '0');")
            if seg.dp is not None:
                assigns.append(
                    f"  {seg_out}({8 * i + 7}) <= scandp_on when scanen_on({i}) = '1' else '0';"
                )
            else:
                assigns.append(f"  {seg_out}({8 * i + 7}) <= '0';")

    # Generic *defaults* mirror ``build_generics`` (the board's resource counts,
    # floored at 1) so ``analyze_vhdl``'s default-generic elaboration validates the
    # same NUM_* widths the run passes -- which, for a litex board whose rgb_led
    # inflate the LED count past the user_led bank, differ from the bank widths.
    # Without a board (hermetic wrapper-gen unit tests) fall back to the bank widths.
    if board_def is not None:
        num_sw_def = max(1, len(board_def.switches))
        num_btn_def = max(1, len(board_def.buttons))
        # Channels, not components (U37): mirrors build_generics so analyze_vhdl
        # validates the same led width the run passes. A native design only
        # drives the banks its convention names; RGB channel bits stay dark.
        num_led_def = max(1, board_def.num_led_channels)
    else:
        num_sw_def = sw.width if sw is not None else 1
        num_btn_def = btn.width if btn is not None else 1
        num_led_def = max(
            1, (led.width if led is not None else 0) + (rgb.width if rgb is not None else 0)
        )

    # num_digits, NOT len(names): a scan match's names are the shared segment
    # lines (7), while the boundary packs one byte per *digit* (enable width).
    seg_generic = [f"    NUM_SEGS         : positive := {seg.num_digits};"] if seg else []
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
        # All-zero defaults keep the pre-deposit t=0 deltas metavalue-free,
        # mirroring the generic template (and the U9 accumulator ports).
        "    sw          : in  std_logic_vector(NUM_SWITCHES - 1 downto 0) := (others => '0');",
        "    btn         : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0) := (others => '0');",
        "    led         : out std_logic_vector(NUM_LEDS     - 1 downto 0);",
        *seg_port,
        *splice["duty_ports"].splitlines(),
        "    clk_half_ns : in  natural := CLK_HALF_NS_INIT",
        "  );",
        "end entity;",
        "",
        "architecture rtl of sim_wrapper is",
        "  signal clk : std_logic := '0';",
        *decls,
        *splice["duty_decls"].splitlines(),
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
        *splice["duty_body"].splitlines(),
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


def _render_wrapper(
    toplevel: str,
    board_def: BoardDef | None = None,
    design_has_seg: bool = False,
    match: ConventionMatch | None = None,
    duty: DutyMode | None = None,
    design_has_rgb: bool = False,
) -> str:
    """Render the ``sim_wrapper.vhd`` text for these inputs, writing nothing.

    When both *board_def* has a seven_seg display and the design declares a
    ``seg`` output port, the generated wrapper includes the ``NUM_SEGS``
    generic and ``seg`` port.  Otherwise those lines are omitted.

    When the design declares the ``NUM_RGB_LEDS`` generic (*design_has_rgb*,
    U37) the wrapper declares and maps it the same way — no new port; RGB
    channels are ordinary ``led`` bits, mono-first per the contract layout.

    When *match* is given the design is board-native (U21 B3): the wrapper
    instantiates it by its native port names + fixed widths (see
    :func:`_render_native_wrapper`).

    *duty* selects the U9 measurement mode (default: :func:`resolve_duty_mode`).
    In Off and Color-only mode both paths emit exactly what they emitted before
    U9 — byte-for-byte — so measurement is a cost only when it is asked for.

    Split out from :func:`_generate_wrapper` so the same text can be produced
    *without* clobbering a work dir's existing wrapper, which is what lets
    :func:`wrapper_is_stale` compare the artifact instead of enumerating the
    inputs that feed it (#386).  It is deliberately pure: same inputs, same
    bytes, no I/O beyond reading the fixed templates.
    """
    mode = resolve_duty_mode(duty)
    if match is not None:
        return _render_native_wrapper(toplevel, match, board_def, duty=mode)

    use_seg = board_def is not None and board_def.seven_seg is not None and design_has_seg
    splice = _duty_splice(_duty_channels(mode, has_seg=use_seg))
    led_sig = "led_int" if mode == "full" else "led"
    if use_seg:
        seg_generic = "    NUM_SEGS         : positive := 4;\n"
        seg_port = "    seg         : out std_logic_vector(8 * NUM_SEGS - 1 downto 0);\n"
        seg_generic_map = "      NUM_SEGS     => NUM_SEGS,\n"
        seg_port_map = f"      seg => {'seg_int' if mode == 'full' else 'seg'},\n"
    else:
        seg_generic = ""
        seg_port = ""
        seg_generic_map = ""
        seg_port_map = ""
    if design_has_rgb:
        rgb_generic = "    NUM_RGB_LEDS     : natural  := 0;\n"
        rgb_generic_map = "      NUM_RGB_LEDS => NUM_RGB_LEDS,\n"
    else:
        rgb_generic = ""
        rgb_generic_map = ""

    content = _WRAPPER_TEMPLATE.read_text(encoding="utf-8").format(
        toplevel=toplevel,
        seg_generic=seg_generic,
        seg_port=seg_port,
        seg_generic_map=seg_generic_map,
        seg_port_map=seg_port_map,
        rgb_generic=rgb_generic,
        rgb_generic_map=rgb_generic_map,
        led_sig=led_sig,
        **splice,
    )
    return content


def _generate_wrapper(
    toplevel: str,
    work_dir: str,
    board_def: BoardDef | None = None,
    design_has_seg: bool = False,
    match: ConventionMatch | None = None,
    duty: DutyMode | None = None,
    design_has_rgb: bool = False,
) -> Path:
    """Write :func:`_render_wrapper`'s output to ``work_dir/sim_wrapper.vhd``."""
    out = Path(work_dir) / "sim_wrapper.vhd"
    out.write_text(
        _render_wrapper(
            toplevel,
            board_def=board_def,
            design_has_seg=design_has_seg,
            match=match,
            duty=duty,
            design_has_rgb=design_has_rgb,
        ),
        encoding="utf-8",
    )
    return out


def wrapper_is_stale(
    work_dir: str | Path,
    toplevel: str,
    *,
    vhdl_path: str | Path,
    board_def: BoardDef | None = None,
    match: ConventionMatch | None = None,
    duty: DutyMode | None = None,
) -> bool:
    """Report whether *work_dir*'s ``sim_wrapper.vhd`` differs from today's render.

    Compares the **artifact**, not the inputs that produce it.  The wrapper is a
    deterministic function of the toplevel, the board, the native match, whether
    the design declares ``seg`` / ``NUM_RGB_LEDS``, and the U9 duty mode and
    algorithm.  Enumerating those at the call site would make every future
    wrapper-affecting input one more thing somebody must remember to add there —
    a trap by construction.  Re-rendering and diffing covers all of them at
    once, including inputs nobody has invented yet, and cannot drift: the thing
    compared is the thing used (#386).

    ``design_has_seg`` / ``design_has_rgb`` are re-derived from *vhdl_path*
    exactly as :func:`analyze_vhdl` derives them, so an edit that adds or drops
    a ``seg`` port counts as staleness too.

    Anything unreadable — no wrapper, a missing design file, an undecodable work
    dir — reports stale, failing toward re-analysis rather than toward running a
    wrapper we cannot vouch for.

    The user's own analyzed ``.vhd`` is deliberately *not* covered: its object
    code shares this work dir, but noticing edits to it belongs to the
    [Reload VHDL] path, not here.
    """
    try:
        current = (Path(work_dir) / "sim_wrapper.vhd").read_text(encoding="utf-8")
        vhdl_text = Path(vhdl_path).read_text(encoding="utf-8", errors="ignore")
        expected = _render_wrapper(
            toplevel,
            board_def=board_def,
            design_has_seg=_has_seg_port(vhdl_text),
            match=match,
            duty=duty,
            design_has_rgb=_has_rgb_generic(vhdl_text),
        )
    except (OSError, UnicodeDecodeError):
        return True
    return current != expected


def _name_bound_check_port(message: str, work_dir: str) -> str:
    """Augment a compiled-backend bound-check message so the port can be named.

    GHDL's llvm/gcc backends report a width violation as
    ``"bound check failure at <path>/sim_wrapper.vhd:NN"`` — only a line number,
    unlike mcode's ``"mismatching vector length … led => led"``.  Read that
    wrapper line (a ``port => port`` association) and append it, so
    :func:`add_error_hints` finds the ``led``/``seg``/``sw``/``btn`` port and
    emits the identical port-width hint every backend gets.
    """
    m = re.search(r"sim_wrapper\.vhd:(\d+)", message)
    if m is None:
        return message
    try:
        wrapper_lines = (
            (Path(work_dir) / "sim_wrapper.vhd").read_text(encoding="utf-8").splitlines()
        )
    except OSError:
        return message
    lineno = int(m.group(1))
    if not 1 <= lineno <= len(wrapper_lines):
        return message
    return f"{message}\n{wrapper_lines[lineno - 1].strip()}"


def _bound_check_probe(work_dir: str) -> str | None:
    """Run the compiled ``sim_wrapper`` for zero time to surface a bound check.

    GHDL's compiled backends (llvm/gcc) compile the wrapper at ``-e`` without
    evaluating array bounds, so a width mismatch that mcode / llvm-jit reject
    in-memory during the early ``-e`` check instead fails only when the emitted
    executable runs.  When ``-e`` produced a ``sim_wrapper`` executable (the
    compiled-backend signature — in-memory backends emit none), run it with
    ``--stop-time=0fs`` so that rejection surfaces at *load* time too, giving
    every backend the same load-time error + hint.

    Returns the normalized error message on failure, or ``None`` when there is
    no executable (mcode / llvm-jit: the ``-e`` check already covered bounds) or
    the design elaborates cleanly.
    """
    exe_name = "sim_wrapper.exe" if IS_WINDOWS else "sim_wrapper"
    exe = Path(work_dir) / exe_name
    if not (exe.exists() and os.access(exe, os.X_OK)):
        return None  # in-memory elaboration: the early -e check already ran the bounds
    try:
        probe = subprocess.run(
            [f".{os.sep}{exe_name}", "--stop-time=0fs"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=work_dir,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired):
        return None  # cannot run it: defer to the (passed) -e result
    # GHDL writes the bound-check line to stdout; keep stderr too for robustness.
    output = f"{probe.stdout}\n{probe.stderr}".strip()
    if probe.returncode == 0 and "error during elaboration" not in output:
        return None  # elaborates + runs cleanly for zero time
    return _name_bound_check_port(output, work_dir)


def analyze_vhdl(
    vhdl_path: str | Path,
    work_dir: str | None = None,
    toplevel: str | None = None,
    simulator: Simulator = "ghdl",
    board_def: BoardDef | None = None,
    match: ConventionMatch | None = None,
    sim_path: str | None = None,
    duty: DutyMode | None = None,
) -> tuple[bool, str]:
    """Analyze the user's VHDL and the generated sim_wrapper.

    Steps:
      1. Analyze the user's VHDL file (``-a``).
      2. Generate ``sim_wrapper.vhd`` and analyze it.
      3. Elaborate ``sim_wrapper`` with VHDL-default generics as an early
         error check.  GHDL resolves generics at run time so the defaults
         used here are discarded.  NVC bakes generics into its elaboration
         artifact, so ``start_simulation()`` re-elaborates with the real
         board generics before running — but this early check still catches
         structural errors (port-width mismatches, missing libraries, etc.)
         at validation time rather than at simulation launch.

    When *match* is given the design is board-native (U21 B3): the wrapper
    instantiates it by its native port names, and the step-3 default-generic
    elaboration works because the native wrapper bakes the board widths as its
    generic defaults.

    *duty* pins the U9 measurement mode of the generated wrapper; left unset it
    resolves exactly as the run path does (:func:`resolve_duty_mode`), so the
    wrapper analyzed here is the one ``start_simulation`` goes on to elaborate
    from this same work dir.

    Returns ``(ok: bool, detail: str)``.  On success *detail* is the work dir.
    """
    be = _backend(simulator)
    work_dir = work_dir or tempfile.mkdtemp(prefix="fpga_sim_")
    if toplevel is None:
        toplevel = Path(vhdl_path).stem
    try:
        # Step 1: analyze user's VHDL
        result = subprocess.run(
            be.analyze_cmd(Path(vhdl_path), work_dir, binary=sim_path),
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
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
            duty=duty,
            design_has_rgb=_has_rgb_generic(_vhdl_text),
        )
        result2 = subprocess.run(
            be.analyze_cmd(wrapper_path, work_dir, binary=sim_path),
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if result2.returncode != 0:
            msg = add_error_hints(result2.stderr.strip(), board_def)
            print(f"[sim_bridge] sim_wrapper analysis failed:\n{msg}", flush=True)
            return False, msg

        # Step 3: early elaboration check — VHDL defaults suffice for structural errors.
        # NVC will re-elaborate with real board generics in start_simulation().
        elab = subprocess.run(
            be.elaborate_cmd("sim_wrapper", {}, work_dir, binary=sim_path),
            capture_output=True,
            text=True,
            timeout=30,
            cwd=work_dir,
            encoding="utf-8",
            errors="replace",  # GHDL's compiled backends emit an executable here
        )
        if elab.returncode != 0:
            combined = (result2.stderr + elab.stderr).strip()
            if not combined:
                return False, "Elaboration of sim_wrapper failed."
            return False, add_error_hints(combined, board_def)

        # Step 3b (U35): compiled GHDL backends (llvm/gcc) don't evaluate array
        # bounds at -e, so run the emitted executable for zero time to catch a
        # width violation at load time — parity with mcode's in-memory -e check.
        probe_err = _bound_check_probe(work_dir)
        if probe_err is not None:
            return False, add_error_hints(probe_err, board_def)

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
#: mode when set (blank/unset → the session value).  See :func:`start_simulation`.
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
    if match.leds is not None:
        sigs += _port(match.leds)
    if match.leds_rgb is not None:
        sigs += _port(match.leds_rgb)
    if match.leds_green is not None:
        sigs += _port(match.leds_green)
    if match.seven_seg is not None:
        seg = match.seven_seg
        if seg.style == "scan":
            # Shared segment lines: unranged scalars (CA..CG) or one vector,
            # then the dp scalar and the digit-enable bank.
            if seg.scalar_segments:
                sigs += [f"{scope}.{name.lower()}" for name in seg.names]
            else:
                sigs.append(f"{scope}.{seg.names[0].lower()}[{seg.width_per_digit - 1}:0]")
            if seg.dp is not None:
                sigs.append(f"{scope}.{seg.dp.lower()}")
            if seg.digit_enable is not None:
                sigs += _port(seg.digit_enable)
        else:
            wpd = seg.width_per_digit
            sigs += [f"{scope}.{name.lower()}[{wpd - 1}:0]" for name in seg.names]
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
    gtkw_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    Called by :func:`finish_waveform` after a headless run to spell the U28
    sidecar and U29 auto-open.
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
