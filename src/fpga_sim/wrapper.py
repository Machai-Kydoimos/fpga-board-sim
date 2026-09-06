"""Writing the sim_wrapper that stands between a design and the testbench (D17).

Every run analyzes two files: the user's design, and a generated
``sim_wrapper`` that instantiates it and presents the one boundary the cocotb
testbench knows -- ``clk`` / ``sw`` / ``btn`` / ``led`` / ``seg``.  That
indirection is what lets three quite different designs run through one
unchanged testbench: a generic-contract design (the wrapper is nearly a
pass-through), a board-native one (the wrapper renames the ports, inverts
active-low banks and packs the display), and, in Full duty mode, either of
those with a per-channel on-time integrator spliced in so brightness is
*measured* rather than sampled.

:func:`analyze_vhdl` is the whole validation pipeline as the user meets it:
analyze the design, generate and analyze the wrapper, then elaborate as an
early structural check.  :func:`wrapper_is_stale` compares the wrapper a run
*would* generate against the one on disk, so a changed board, duty mode or
generic re-analyzes and an unchanged one does not.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING

from fpga_sim.conventions import ConventionMatch, NativePort
from fpga_sim.paths import SIM_DIR
from fpga_sim.pinmap import PinMapMatch
from fpga_sim.sim_backends import _backend
from fpga_sim.sim_config import (
    IS_WINDOWS,
    DutyMode,
    Simulator,
    resolve_duty_algo,
    resolve_duty_mode,
)
from fpga_sim.vhdl_contract import add_error_hints
from fpga_sim.vhdl_interface import (
    _has_rgb_generic,
    _has_seg_port,
)

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef

#: Swappable duty-integrator splice fragments, one file per splice point per
#: algorithm (U9); selected by ``FPGA_SIM_DUTY_ALGO``.
_DUTY_FRAGMENT_DIR: Path = SIM_DIR / "duty"

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
    pinmap: PinMapMatch | None = None,
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
    if pinmap is not None:
        return _render_pinmap_wrapper(toplevel, pinmap, board_def, duty=mode)
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
    pinmap: PinMapMatch | None = None,
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
            pinmap=pinmap,
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
    pinmap: PinMapMatch | None = None,
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
            pinmap=pinmap,
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


#: What counts as a design file beside the picked one.
_VHDL_SUFFIXES = (".vhd", ".vhdl")

#: Ceilings on the sibling sweep.  A lab folder holds a handful of files; a
#: directory holding sixty is not a lab folder, and grinding through it one
#: subprocess at a time would look exactly like a hang.
_MAX_SIBLINGS = 60
_ANALYZE_TIMEOUT_S = 30

#: Total wall-clock the sibling sweep may spend before it gives up and lets the
#: design speak for itself.  Measured on the worst folder that ships here --
#: `hdl/`, 18 files and 29k lines including the embedded cores -- the sweep is
#: 0.22 s on GHDL mcode and 0.38 s on NVC, against the 5-10 s the whole
#: analysis takes.  This is three orders of magnitude of headroom, and exists
#: only so that a pathological folder degrades into "your design did not
#: compile" instead of into a hang.
_SWEEP_BUDGET_S = 45


def find_siblings(vhdl_path: str | Path) -> list[Path]:
    """List the other VHDL files in the picked design's folder, in a stable order.

    One folder is one project (see ``docs/writing_designs.md``), so everything
    beside the design is available to it.  Nothing is parsed here: which of
    these the design actually needs is decided by the analyzer, not by us.
    """
    design = Path(vhdl_path)
    folder = design.parent
    if not folder.is_dir():
        return []
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    out = [
        p
        for p in entries
        if p.is_file() and p.suffix.lower() in _VHDL_SUFFIXES and p.resolve() != design.resolve()
    ]
    return out[:_MAX_SIBLINGS]


def analyze_siblings(
    vhdl_path: str | Path,
    work_dir: str,
    simulator: Simulator = "ghdl",
    sim_path: str | None = None,
) -> tuple[list[Path], dict[Path, str]]:
    """Analyze the design's neighbors into the same library, to a fixpoint (U51).

    Real work is not one file.  The course's Lab 3 ships ``counter.vhd`` as a
    separate sub-entity, every lab folder holds a ``testbench.vhd``, and the
    second course's student projects are nine sources and five testbenches.

    Two decisions carry this function.

    **Order is discovered by retrying, not by parsing.**  A VHDL file must be
    analyzed after everything it depends on, and working that out properly
    means understanding ``use`` clauses, component declarations, configurations
    and library aliases.  Retrying until a pass adds nothing reaches the same
    answer with none of that: each round analyzes what is left, and anything
    whose dependencies just landed now succeeds.  Worst case is one round per
    dependency level, which for a lab folder is two or three.

    **A neighbor that will not compile is irrelevant, not fatal.**  Two of the
    three course testbenches do not compile as shipped, and they sit right
    beside the design they test.  Refusing to run the student's design because
    the *instructor's* testbench is broken would be indefensible, so a failing
    sibling is recorded and dropped.  If the picked design actually needed it,
    the design's own analysis fails next and reports its own error -- which is
    the message that helps.

    Returns ``(analyzed, failures)``: the siblings that compiled, in the order
    they compiled, and a ``path -> stderr`` map for those that never did.
    """
    be = _backend(simulator)
    pending = find_siblings(vhdl_path)
    analyzed: list[Path] = []
    errors: dict[Path, str] = {}
    deadline = time.monotonic() + _SWEEP_BUDGET_S
    while pending:
        progressed: list[Path] = []
        still: list[Path] = []
        for sibling in pending:
            if time.monotonic() > deadline:
                still.append(sibling)
                continue
            try:
                result = subprocess.run(
                    be.analyze_cmd(sibling, work_dir, binary=sim_path),
                    capture_output=True,
                    text=True,
                    timeout=_ANALYZE_TIMEOUT_S,
                    encoding="utf-8",
                    errors="replace",
                )
            except (OSError, subprocess.SubprocessError) as e:
                errors[sibling] = str(e)
                continue
            if result.returncode == 0:
                progressed.append(sibling)
            else:
                errors[sibling] = result.stderr.strip()
                still.append(sibling)
        if not progressed:
            break  # fixpoint: nothing left can be made to compile
        if time.monotonic() > deadline:
            break
        analyzed.extend(progressed)
        for done in progressed:
            errors.pop(done, None)
        pending = still
    return analyzed, errors


def analyze_vhdl(
    vhdl_path: str | Path,
    work_dir: str | None = None,
    toplevel: str | None = None,
    simulator: Simulator = "ghdl",
    board_def: BoardDef | None = None,
    match: ConventionMatch | None = None,
    sim_path: str | None = None,
    duty: DutyMode | None = None,
    pinmap: PinMapMatch | None = None,
) -> tuple[bool, str]:
    """Analyze the user's VHDL and the generated sim_wrapper.

    Steps:
      1. Analyze the user's VHDL file (``-a``).  If that fails, analyze the
         other VHDL files in its folder (U51) to a fixpoint and try again --
         lazily, because on a code-generating backend a sweep is expensive and
         the overwhelming majority of designs are one file.
      2. Generate ``sim_wrapper.vhd`` and analyze it.
      3. Elaborate ``sim_wrapper`` with VHDL-default generics as an early
         error check (retrying once after a sibling sweep, since a *component*
         instantiation with default binding fails here rather than at step 1).
         GHDL resolves generics at run time so the defaults
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
        # Step 1: analyze the user's VHDL.  Alone first -- see _analyze_one.
        swept = False

        def _sweep() -> bool:
            """Analyze the folder's other files, once. True if it had not run."""
            nonlocal swept
            if swept:
                return False
            swept = True
            analyze_siblings(vhdl_path, work_dir, simulator=simulator, sim_path=sim_path)
            return True

        def _analyze_design() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                be.analyze_cmd(Path(vhdl_path), work_dir, binary=sim_path),
                capture_output=True,
                text=True,
                timeout=_ANALYZE_TIMEOUT_S,
                encoding="utf-8",
                errors="replace",
            )

        result = _analyze_design()
        if result.returncode != 0:
            # It may be a multi-file design (U51).  Sweeping the folder is only
            # worth doing *here*, on a path that has already failed: on GHDL's
            # AOT LLVM backend an analyze compiles, so an unconditional sweep of
            # a folder like `hdl/` (18 files, 29.7k lines) cost 139 s -> 663 s
            # in CI while buying nothing for the single-file designs that are
            # the overwhelming majority.  Measured, after an eager version was
            # written and merged into a branch on the strength of the mcode and
            # NVC numbers alone, where it is genuinely free.
            if _sweep():
                result = _analyze_design()
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
            pinmap=pinmap,
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
        def _elaborate() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                be.elaborate_cmd("sim_wrapper", {}, work_dir, binary=sim_path),
                capture_output=True,
                text=True,
                timeout=_ANALYZE_TIMEOUT_S,
                cwd=work_dir,
                encoding="utf-8",
                errors="replace",  # GHDL's compiled backends emit an executable here
            )

        elab = _elaborate()
        if elab.returncode != 0 and _sweep():
            # The second place a missing neighbor surfaces: a *component*
            # instantiation with default binding analyzes fine on its own and
            # only fails to bind here.  This is why the sweep cannot simply hang
            # off step 1.
            elab = _elaborate()
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


def _render_pinmap_wrapper(
    toplevel: str,
    match: PinMapMatch,
    board_def: BoardDef | None = None,
    duty: DutyMode = "off",
) -> str:
    """Render a ``sim_wrapper`` for a design mapped through its constraint file (U53).

    The same entity, generics, boundary ports and clock process as the other two
    wrappers -- so the cocotb testbench, the waveform writer and the run
    mechanics are untouched -- with an architecture body built from the pin map
    instead of from names.  Every association is already decided by then, so the
    body is a list of single-bit assignments rather than bank logic:

    * an input bit reads its switch or button, inverted where the *board* says
      that resource is active-low;
    * an output bit drives its LED channel, or the ``{dp, g..a}`` byte position
      of its digit;
    * a scanned display is demultiplexed combinationally, as U22 does -- digit
      *d*'s byte shows the shared segment lines only while its enable is
      asserted, unlatched, so Full duty measures the honest 1/N brightness;
    * a port nothing binds is tied low (an input) or left ``open`` (an output).

    Every boundary bit is driven explicitly, including the ones this design
    never touches.  It makes the wrapper long and the reasoning short: a bit
    with no design behind it is dark because a line says so, not because
    nothing assigned it.
    """
    widths = match.port_widths
    board_leds = board_def.num_led_channels if board_def is not None else 0
    seg_def = board_def.seven_seg if board_def is not None else None
    digits = seg_def.num_digits if seg_def is not None else 0

    decls: list[str] = []
    assigns: list[str] = []
    pmap: list[str] = []

    duty_channels = _duty_channels(duty, has_seg=digits > 0)
    splice = _duty_splice(duty_channels)
    measured = {port for port, _ in duty_channels}
    led_out = "led_int" if "led" in measured else "led"
    seg_out = "seg_int" if "seg" in measured else "seg"

    def signal_of(port: str) -> str:
        return f"{port}_uut"

    # One signal per design port, at the width the design declared.
    driven_ports = {b.port for b in match.inputs} | {b.port for b in match.outputs}
    for port, width in match.widths:
        if port == match.clock_port:
            pmap.append(f"{port} => clk")
            continue
        if port in match.open_outputs:
            pmap.append(f"{port} => open")
            continue
        if port not in driven_ports and port not in match.tied_inputs:
            continue  # an input carrying its own default: leave it to the design
        sig = signal_of(port)
        decls.append(
            f"  signal {sig} : std_logic;"
            if width is None
            else f"  signal {sig} : std_logic_vector({width} - 1 downto 0);"
        )
        pmap.append(f"{port} => {sig}")

    def bit_of(port: str, bit: int | None) -> str:
        return signal_of(port) if bit is None else f"{signal_of(port)}({bit})"

    # Inputs: read the board resource, inverted where the board is active-low.
    for binding in match.inputs:
        source = f"{binding.role.kind}({binding.role.index})"
        inv = "not " if binding.role.active_low else ""
        assigns.append(f"  {bit_of(binding.port, binding.bit)} <= {inv}{source};")
    for port in match.tied_inputs:
        width = widths.get(port)
        value = "'0'" if width is None else "(others => '0')"
        assigns.append(f"  {signal_of(port)} <= {value};  -- no pin assignment")

    # Outputs: LED channels first, one line per boundary channel.
    led_source: dict[int, str] = {}
    for binding in match.outputs:
        if binding.role.kind == "led":
            inv = "not " if binding.role.active_low else ""
            led_source[binding.role.index] = f"{inv}{bit_of(binding.port, binding.bit)}"
    dark = "'0'"
    for channel in range(max(board_leds, 1)):
        assigns.append(f"  {led_out}({channel}) <= {led_source.get(channel, dark)};")

    # The display.  A directly-driven digit takes its segment straight; a
    # scanned one shows the shared lines only while its own enable is asserted.
    if digits:
        enables: dict[int, str] = {}
        for binding in match.outputs:
            if binding.role.kind == "digit_enable":
                active = "= '0'" if binding.role.active_low else "= '1'"
                enables[binding.role.index] = f"{bit_of(binding.port, binding.bit)} {active}"
        shared: dict[int, str] = {}
        per_digit: dict[tuple[int, int], str] = {}
        dp_shared = ""
        dp_digit: dict[int, str] = {}
        for binding in match.outputs:
            role = binding.role
            inv = "not " if role.active_low else ""
            expr = f"{inv}{bit_of(binding.port, binding.bit)}"
            if role.kind == "seg" and role.segment is not None:
                if role.digit is None:
                    shared[role.segment] = expr
                else:
                    per_digit[(role.digit, role.segment)] = expr
            elif role.kind == "dp":
                if role.digit is None:
                    dp_shared = expr
                else:
                    dp_digit[role.digit] = expr
        off = "'0'"
        for digit in range(digits):
            for segment in range(7):
                bit = 8 * digit + segment
                if shared:
                    gate = enables.get(digit)
                    src = shared.get(segment, off)
                    expr = f"{src} when {gate} else {off}" if gate else off
                else:
                    expr = per_digit.get((digit, segment), off)
                assigns.append(f"  {seg_out}({bit}) <= {expr};")
            dp_bit = 8 * digit + 7
            if shared:
                gate = enables.get(digit)
                expr = f"{dp_shared} when {gate} else {off}" if (dp_shared and gate) else off
            else:
                expr = dp_digit.get(digit, off)
            assigns.append(f"  {seg_out}({dp_bit}) <= {expr};")

    num_sw = max(1, len(board_def.switches) if board_def is not None else 1)
    num_btn = max(1, len(board_def.buttons) if board_def is not None else 1)
    num_led = max(1, board_leds)
    seg_generic = [f"    NUM_SEGS         : positive := {digits};"] if digits else []
    seg_port = (
        ["    seg         : out std_logic_vector(8 * NUM_SEGS - 1 downto 0);"] if digits else []
    )

    lines = [
        "-- sim_wrapper.vhd (pin map, generated by fpga_sim.wrapper -- U53)",
        f"-- Design '{toplevel}' is bound to {match.board_name} by {match.source},",
        "-- so its own port names carry no meaning here: every association below",
        "-- comes from a pin the constraint file named and the board recognized.",
        "",
        "library ieee;",
        "use ieee.std_logic_1164.all;",
        # Not used by the assignments below, which are all single bits -- but the
        # U9 duty integrator spliced in for Full measurement is written in
        # numeric_std, and it is spliced into *this* design unit.  The user's
        # design has its own context clause and is unaffected either way.
        "use ieee.numeric_std.all;",
        "",
        "entity sim_wrapper is",
        "  generic (",
        f"    NUM_SWITCHES     : positive := {num_sw};",
        f"    NUM_BUTTONS      : positive := {num_btn};",
        f"    NUM_LEDS         : positive := {num_led};",
        *seg_generic,
        "    COUNTER_BITS     : positive := 24;",
        "    CLK_HALF_NS_INIT : positive := 20",
        "  );",
        "  port (",
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
