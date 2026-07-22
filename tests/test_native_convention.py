"""Tests for U21 B3: running a board-native VHDL design.

B2 detected board-native designs; B3 *runs* them.  ``check_vhdl_contract`` now
returns ``ok=True`` for a full native match, and ``_generate_wrapper`` emits a
native wrapper that adapts the design's own port names (polarity + 7-seg packing)
to the simulator's ``sw/btn/led/seg`` boundary.

Coverage:
  * unit (no simulator): the generated native wrapper's adapters, per polarity /
    7-seg shape, for the three example designs + a synthetic scalar-bank case;
  * the ``.gtkw`` native signal preselection (``sim_wrapper.uut.<native>``);
  * GHDL + NVC end-to-end analysis of each ``hdl/native/*.vhd`` example, plus a
    standalone NVC run proving the active-low-LED inversion (``led == not ledr``);
  * the cross-board safety invariant (no wrong-board load silently flips polarity).
"""

from __future__ import annotations

import glob
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from fpga_sim.board_loader import BoardDef
from fpga_sim.sim_bridge import (
    ConventionMatch,
    NativePort,
    NativeSeg,
    WaveConfig,
    _build_sim_env,
    _GHDLBackend,
    _IfaceDecl,
    _NVCBackend,
    _render_native_wrapper,
    _write_gtkw,
    analyze_vhdl,
    check_vhdl_contract,
    match_convention,
)

PROJECT = Path(__file__).resolve().parent.parent
NATIVE = PROJECT / "hdl" / "native"


# ── synthetic ConventionMatch builders (for hermetic wrapper-gen unit tests) ──


def _de25_match() -> ConventionMatch:
    """DE25-Standard: active-low LEDR (the invert path), active-low KEY, 6 digits."""
    return ConventionMatch(
        maker="terasic",
        board_name="DE25-Standard",
        clk="CLOCK0_50",
        leds=NativePort(("LEDR",), 10, True),
        switches=NativePort(("SW",), 10, False),
        buttons=NativePort(("KEY",), 4, True),
        seven_seg=NativeSeg("individual", tuple(f"HEX{i}" for i in range(6)), 7, True),
    )


def _de10_match() -> ConventionMatch:
    """DE10-Standard: active-HIGH LEDR (no invert), active-low KEY, CLOCK_50."""
    return ConventionMatch(
        maker="terasic",
        board_name="DE10-Standard",
        clk="CLOCK_50",
        leds=NativePort(("LEDR",), 10, False),
        switches=NativePort(("SW",), 10, False),
        buttons=NativePort(("KEY",), 4, True),
        seven_seg=NativeSeg("individual", tuple(f"HEX{i}" for i in range(6)), 7, True),
    )


def _de0_match() -> ConventionMatch:
    """DE0: active-high green LEDG, active-low BUTTON, split-DP HEXn_D, 4 digits."""
    return ConventionMatch(
        maker="terasic",
        board_name="DE0",
        clk="CLOCK_50",
        leds=NativePort(("LEDG",), 10, False),
        switches=NativePort(("SW",), 10, False),
        buttons=NativePort(("BUTTON",), 3, True),
        seven_seg=NativeSeg("individual", tuple(f"HEX{i}_D" for i in range(4)), 7, True),
    )


# ── unit: native wrapper generation ──────────────────────────────────────────


def test_native_wrapper_inverts_active_low_leds() -> None:
    vhd = _render_native_wrapper("de25_standard", _de25_match())
    # LEDs invert (active-low) then zero-extend onto the board's NUM_LEDS boundary.
    assert "led <= std_logic_vector(resize(unsigned(not led_uut), NUM_LEDS));" in vhd
    assert "LEDR => led_uut" in vhd
    assert "generic map" not in vhd  # native uut has no NUM_* generics


def test_native_wrapper_active_high_leds_are_not_inverted() -> None:
    vhd = _render_native_wrapper("de10_standard", _de10_match())
    assert "led <= std_logic_vector(resize(unsigned(led_uut), NUM_LEDS));" in vhd
    assert "not led_uut" not in vhd


def test_native_wrapper_inverts_active_low_buttons() -> None:
    vhd = _render_native_wrapper("de25_standard", _de25_match())
    # Inputs take the low NUM_* boundary bits (bank width may be < board count).
    assert "btn_uut <= not btn(4 - 1 downto 0);" in vhd
    assert "sw_uut <= sw(10 - 1 downto 0);" in vhd  # SW is active-high: no inversion
    assert "KEY => btn_uut" in vhd


def test_native_wrapper_bakes_board_widths_as_generic_defaults() -> None:
    # analyze_vhdl elaborates at {} defaults, so the defaults must equal the
    # native uut's fixed widths (decision 2 -- no "defaults dance").
    vhd = _render_native_wrapper("de25_standard", _de25_match())
    assert "NUM_SWITCHES     : positive := 10;" in vhd
    assert "NUM_BUTTONS      : positive := 4;" in vhd
    assert "NUM_LEDS         : positive := 10;" in vhd
    assert "NUM_SEGS         : positive := 6;" in vhd


def test_native_wrapper_bank_narrower_than_board_boundary() -> None:
    # U32: a litex board whose LED components (4 user_led + 4 rgb_led) exceed the
    # 4-bit user_led bank.  The matcher advertises the bank (4), while the wrapper's
    # NUM_LEDS default is the board's boundary channel count (U37: 4 mono + 3 x 4
    # RGB = 16, matching build_generics / the run) and the bank zero-extends onto
    # it -- board channels the convention omits stay dark.
    arty = PROJECT / "boards" / "litex-boards" / "digilent_arty.json"
    bd = BoardDef.from_json(arty.read_text())
    assert bd.num_led_channels == 16  # 4 mono + 3 * 4 RGB
    res = check_vhdl_contract(NATIVE / "arty_litex.vhd", board_def=bd)
    assert res.ok and res.match is not None
    assert res.match.leds == NativePort(("user_led",), 4, False)  # the bank, not the channels
    vhd = _render_native_wrapper("arty_litex", res.match, bd)
    assert "NUM_LEDS         : positive := 16;" in vhd  # channel count, not the bank width 4
    assert "led <= std_logic_vector(resize(unsigned(led_uut), NUM_LEDS));" in vhd


def test_native_wrapper_packs_active_low_seg_with_dp_off() -> None:
    vhd = _render_native_wrapper("de25_standard", _de25_match())
    assert "seg(6 downto 0) <= not hex0_uut;" in vhd
    assert "seg(7 downto 7) <= (others => '0');" in vhd  # decimal point forced off
    assert "HEX0 => hex0_uut" in vhd
    assert "HEX5 => hex5_uut" in vhd


def test_native_wrapper_de0_maps_segment_ports_leaves_dp_open() -> None:
    vhd = _render_native_wrapper("de0", _de0_match())
    # The 7-bit segment vector is mapped; the separate HEXn_DP scalars are not in
    # the convention's names, so the wrapper leaves them open (unlisted).
    assert "HEX0_D => hex0_uut" in vhd
    assert "HEX3_D => hex3_uut" in vhd
    assert "HEX0_DP" not in vhd
    # LEDG active-high (no invert), BUTTON active-low, green bank is the primary led.
    assert "led <= std_logic_vector(resize(unsigned(led_uut), NUM_LEDS));" in vhd
    assert "LEDG => led_uut" in vhd
    assert "BUTTON => btn_uut" in vhd


def test_native_wrapper_scalar_led_bank_maps_bit_by_bit() -> None:
    # A bank of distinct scalar ports (Nandland Go's o_LED_1.., or any names[]
    # convention) maps each scalar to one bit of the wrapper's vector.
    m = ConventionMatch(
        maker="acme",
        board_name="Go",
        clk="i_Clk",
        leds=NativePort(("o_LED_1", "o_LED_2", "o_LED_3", "o_LED_4"), 4, False, scalar_ports=True),
        switches=NativePort(("i_SW_1", "i_SW_2"), 2, False, scalar_ports=True),
        buttons=NativePort(("i_BTN_1", "i_BTN_2"), 2, False, scalar_ports=True),
    )
    vhd = _render_native_wrapper("go", m)
    assert "o_LED_1 => led_uut(0)" in vhd
    assert "o_LED_4 => led_uut(3)" in vhd
    assert "i_SW_1 => sw_uut(0)" in vhd
    assert "i_BTN_2 => btn_uut(1)" in vhd
    assert "i_Clk => clk" in vhd


def test_native_wrapper_width1_scalar_led_maps_element() -> None:
    # F1: a one-LED board whose design declared `led : out std_logic`.  The
    # scalar_ports bank associates the element (`led => led_uut(0)`) and the
    # one-bit uut vector zero-extends onto the board's NUM_LEDS boundary.
    m = ConventionMatch(
        maker="amaranth",
        board_name="Tiny FPGABX",
        clk="clk16",
        leds=NativePort(("led",), 1, False, scalar_ports=True),
    )
    vhd = _render_native_wrapper("led_blink", m)
    assert "led => led_uut(0)" in vhd  # per element, not `led => led_uut`
    assert "signal led_uut : std_logic_vector(1 - 1 downto 0);" in vhd
    assert "led <= std_logic_vector(resize(unsigned(led_uut), NUM_LEDS));" in vhd


# ── unit: .gtkw native preselection ──────────────────────────────────────────


def test_write_gtkw_native_preselects_uut_ports(tmp_path: Any) -> None:
    gtkw = tmp_path / "de25.gtkw"
    dump = tmp_path / "de25.vcd"
    generics = {"NUM_SWITCHES": "10", "NUM_BUTTONS": "4", "NUM_LEDS": "10", "NUM_SEGS": "6"}
    _write_gtkw(gtkw, dump, generics, match=_de25_match())
    text = gtkw.read_text()
    # the design's own names (lowercased, as GHDL/NVC emit them) under uut
    assert "sim_wrapper.uut.clock0_50" in text
    assert "sim_wrapper.uut.ledr[9:0]" in text
    assert "sim_wrapper.uut.sw[9:0]" in text
    assert "sim_wrapper.uut.key[3:0]" in text
    assert "sim_wrapper.uut.hex0[6:0]" in text
    # plus the board (logical) led so the active-low inversion is visible
    assert "sim_wrapper.led[9:0]" in text


def test_write_gtkw_generic_path_has_no_uut_paths(tmp_path: Any) -> None:
    gtkw = tmp_path / "b.gtkw"
    _write_gtkw(
        gtkw, tmp_path / "b.vcd", {"NUM_SWITCHES": "4", "NUM_BUTTONS": "4", "NUM_LEDS": "4"}
    )
    text = gtkw.read_text()
    assert ".uut." not in text
    assert "sim_wrapper.sw[3:0]" in text


def test_write_gtkw_native_scalar_led_is_unranged(tmp_path: Any) -> None:
    # F1: a scalar_ports LED bank dumps as an unranged scalar (sim_wrapper.uut.led),
    # unlike a std_logic_vector(0 downto 0) which would carry a [0:0] range.
    m = ConventionMatch(
        maker="amaranth",
        board_name="Tiny FPGABX",
        clk="clk16",
        leds=NativePort(("led",), 1, False, scalar_ports=True),
    )
    gtkw = tmp_path / "bx.gtkw"
    _write_gtkw(gtkw, tmp_path / "bx.vcd", {"NUM_LEDS": "1"}, match=m)
    text = gtkw.read_text()
    assert "sim_wrapper.uut.led" in text
    assert "sim_wrapper.uut.led[" not in text  # scalar -> no [msb:0] range
    assert "sim_wrapper.uut.clk16" in text


# ── cross-board safety invariant (no wrong-board silent polarity flip) ───────


def _canonical_boards() -> list[BoardDef]:
    """Every board carrying a canonical (non-project-derived) port convention."""
    boards: list[BoardDef] = []
    for f in glob.glob(str(PROJECT / "boards" / "**" / "*.json"), recursive=True):
        if "schema" in f or "_sync_metadata" in f:
            continue
        try:
            d = json.loads(Path(f).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pc = d.get("port_conventions")
        if not isinstance(pc, dict):
            continue
        # Only vendor-*canonical* conventions: the no-flip invariant is about
        # electrically-identical boards sharing distinctive vendor names (DE23 /
        # DE25).  Framework-derived blocks (U32) use generic names (led / user_led)
        # shared across unrelated boards, where a cross-board match applying the
        # *selected* board's own polarity is correct, not a silent flip.
        if any(
            isinstance(b, dict) and b.get("naming", "canonical") == "canonical" for b in pc.values()
        ):
            boards.append(BoardDef.from_json(json.dumps(d)))
    return boards


def _canonical_block(bd: BoardDef) -> dict[str, Any] | None:
    for b in bd.port_conventions.values():
        if isinstance(b, dict) and b.get("naming", "canonical") == "canonical":
            return b
    return None


def _synth_iface(block: dict[str, Any]) -> list[_IfaceDecl]:
    """The toplevel interface a native design for *block* would declare.

    Some boards carry only a partial convention (e.g. buttons only, from an XDC
    sync); the clock/role is simply omitted, so such a board never full-matches.
    """
    ports: list[_IfaceDecl] = []
    if isinstance(block.get("clk"), str):
        ports.append(_IfaceDecl([block["clk"].lower()], "in", False, None))

    def add(role: str, mode: str) -> None:
        m = block.get(role)
        if not isinstance(m, dict):
            return
        if m.get("names"):
            ports.extend(_IfaceDecl([str(n).lower()], mode, False, None) for n in m["names"])
        elif "name" in m and "width" in m:
            ports.append(_IfaceDecl([str(m["name"]).lower()], mode, False, int(m["width"])))

    add("leds", "out")
    add("switches", "in")
    add("buttons", "in")
    add("leds_green", "out")
    ss = block.get("seven_seg")
    if isinstance(ss, dict) and ss.get("names"):
        wpd = int(ss["width_per_digit"])
        ports.extend(_IfaceDecl([str(n).lower()], "out", False, wpd) for n in ss["names"])
    return ports


def _synth_iface_scalar_width1_leds(block: dict[str, Any]) -> list[_IfaceDecl] | None:
    """``_synth_iface`` variant spelling a width-1 shared-vector LED bank as a
    plain scalar (``led : out std_logic``) rather than std_logic_vector(0 downto 0).

    Returns None when the primary LED bank is not a width-1 ``name``+``width``
    vector (so the two spellings are not distinct).
    """
    leds = block.get("leds")
    if not (isinstance(leds, dict) and "name" in leds and leds.get("width") == 1):
        return None
    name = str(leds["name"]).lower()
    return [
        _IfaceDecl(d.names, d.mode, d.has_default, None) if d.names == [name] else d
        for d in _synth_iface(block)
    ]


def test_no_cross_board_native_match_flips_polarity() -> None:
    """A native file for board X loaded onto board Y never silently flips polarity.

    Synthesize each canonical board's native interface and match it against every
    other board.  Any cross-board *full* match (e.g. the electrically identical
    DE23-Lite / DE25-Standard pair) must agree on active-low polarity for every
    role -- otherwise a wrong-board selection would silently invert LEDs/buttons.
    """
    boards = _canonical_boards()
    assert len(boards) >= 3, "expected several canonical-convention boards"

    flips: list[tuple[str, str, str, bool, bool]] = []
    for bd in boards:
        block = _canonical_block(bd)
        if block is None:
            continue
        ports = _synth_iface(block)
        for other in boards:
            if other.name == bd.name:
                continue
            m = match_convention(ports, [], other)
            if m is None:
                continue
            for role, mport in (("leds", m.leds), ("switches", m.switches), ("buttons", m.buttons)):
                if mport is None:  # U31: absent bank in a partial convention
                    continue
                fm = block.get(role)
                f_low = bool(fm.get("active_low")) if isinstance(fm, dict) else False
                if mport.active_low != f_low:
                    flips.append((bd.name, other.name, role, f_low, mport.active_low))
    assert not flips, (
        f"silent polarity flips across boards (file, board, role, own, applied): {flips}"
    )


def test_every_canonical_board_matches_its_own_synthesized_interface() -> None:
    """Fleet-wide self-consistency: an interface synthesized from a board's own
    convention must match that board.  This guards the matcher against a data or
    logic regression that would break a real board, and encodes U31's additive
    property (relaxing the required-role set never stops a board from matching
    itself).  Boards whose 7-seg style is not ``individual`` (packed_vector / scan
    / serial -- U22 territory) legitimately decline and are skipped.
    """
    boards = _canonical_boards()
    assert len(boards) >= 20
    checked = 0
    failures: list[str] = []
    for bd in boards:
        block = _canonical_block(bd)
        if block is None or not (block.get("clk") and block.get("leds")):
            continue
        seg = block.get("seven_seg") or {}
        if bd.seven_seg is not None and seg.get("style") != "individual":
            continue  # non-individual seg not adaptable yet -> U22
        checked += 1
        if match_convention(_synth_iface(block), [], bd) is None:
            failures.append(bd.name)
        # F1: a width-1 LED bank must also match the natural scalar spelling
        # (`led : out std_logic`), not only std_logic_vector(0 downto 0).
        scalar = _synth_iface_scalar_width1_leds(block)
        if scalar is not None and match_convention(scalar, [], bd) is None:
            failures.append(f"{bd.name} (scalar-led spelling)")
    assert checked >= 20, f"expected many self-checkable boards, got {checked}"
    assert not failures, f"boards that fail to match their own native interface: {failures}"


def test_de10_native_file_on_de25_board_is_near_miss_not_silent_run() -> None:
    # The concrete case: a DE10-Standard native file selected against a DE25 board.
    # The clock names differ (CLOCK_50 vs CLOCK0_50) so it is a near-miss, rejected
    # -- it does not silently run with DE25's active-low LED inversion applied.
    de25 = BoardDef.from_json((PROJECT / "boards/custom/de25_standard.json").read_text())
    res = check_vhdl_contract(NATIVE / "de10_standard.vhd", board_def=de25)
    assert res.ok is False
    assert res.match is None
    assert "DE25-Standard" in res.message
    assert "CLOCK0_50" in res.message


# ── U31: partial-interface board-native support ──────────────────────────────
#
# Most FPGA boards have no switches, so a convention may declare only a subset of
# the clk/led/sw/btn roles.  A design matching just the declared roles runs; the
# wrapper ties off the absent input banks.  No shipped board carries a partial
# convention yet (all are full; U32 will supply partial ones), so these drive it
# with synthetic conventions.


def _synth_board(block: dict[str, Any], *, seven_seg: Any = None) -> BoardDef:
    """A minimal board carrying one canonical ``terasic`` convention *block*."""
    return BoardDef(
        name="SynthBoard",
        class_name="SynthBoard",
        port_conventions={"terasic": block},
        seven_seg=seven_seg,
    )


_LED_ONLY_BLOCK: dict[str, Any] = {"clk": "CLOCK_50", "leds": {"name": "LEDR", "width": 10}}
_LED_BTN_BLOCK: dict[str, Any] = {
    "clk": "CLOCK_50",
    "leds": {"name": "LEDR", "width": 10},
    "buttons": {"name": "KEY", "width": 2, "active_low": True},
}
_LED_SW_BLOCK: dict[str, Any] = {
    "clk": "CLOCK_50",
    "leds": {"name": "LEDR", "width": 10},
    "switches": {"name": "SW", "width": 4},
}

_LED_ONLY_SRC = """\
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity led_blink is
  port (
    CLOCK_50 : in  std_logic;
    LEDR     : out std_logic_vector(9 downto 0)
  );
end entity;

architecture rtl of led_blink is
  signal cnt : unsigned(23 downto 0) := (others => '0');
begin
  process (CLOCK_50)
  begin
    if rising_edge(CLOCK_50) then
      cnt <= cnt + 1;
    end if;
  end process;
  LEDR <= std_logic_vector(cnt(23 downto 14));
end architecture;
"""

_LED_BTN_SRC = """\
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity led_key is
  port (
    CLOCK_50 : in  std_logic;
    KEY      : in  std_logic_vector(1 downto 0);
    LEDR     : out std_logic_vector(9 downto 0)
  );
end entity;

architecture rtl of led_key is
  signal cnt : unsigned(23 downto 0) := (others => '0');
begin
  process (CLOCK_50)
  begin
    if rising_edge(CLOCK_50) then
      if KEY(0) = '0' then
        cnt <= (others => '0');
      else
        cnt <= cnt + 1;
      end if;
    end if;
  end process;
  LEDR <= std_logic_vector(cnt(23 downto 14));
end architecture;
"""

# F1: a one-LED board's natural spelling -- `led : out std_logic`, not a
# std_logic_vector(0 downto 0) -- for Tiny FPGABX (width-1 amaranth bank).
_SCALAR_LED_SRC = """\
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity bx_blink is
  port (
    clk16 : in  std_logic;
    led   : out std_logic
  );
end entity;

architecture rtl of bx_blink is
  signal cnt : unsigned(23 downto 0) := (others => '0');
begin
  process (clk16)
  begin
    if rising_edge(clk16) then
      cnt <= cnt + 1;
    end if;
  end process;
  led <= cnt(23);
end architecture;
"""

# F3: a full native match whose design carries an extra input with a default;
# the wrapper leaves UART_RX unassociated (its default drives it).
_LED_DEFAULT_EXTRA_SRC = """\
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity led_dflt is
  port (
    CLOCK_50 : in  std_logic;
    UART_RX  : in  std_logic := '1';
    LEDR     : out std_logic_vector(9 downto 0)
  );
end entity;

architecture rtl of led_dflt is
  signal cnt : unsigned(23 downto 0) := (others => '0');
begin
  process (CLOCK_50)
  begin
    if rising_edge(CLOCK_50) then
      cnt <= cnt + 1;
    end if;
  end process;
  LEDR <= std_logic_vector(cnt(23 downto 14)) when UART_RX = '1' else (others => '0');
end architecture;
"""


def test_partial_convention_led_only_matches() -> None:
    m = match_convention(_synth_iface(_LED_ONLY_BLOCK), [], _synth_board(_LED_ONLY_BLOCK))
    assert m is not None
    assert m.leds == NativePort(("LEDR",), 10, False)
    assert m.switches is None
    assert m.buttons is None


def test_partial_convention_led_plus_button_matches() -> None:
    m = match_convention(_synth_iface(_LED_BTN_BLOCK), [], _synth_board(_LED_BTN_BLOCK))
    assert m is not None
    assert m.buttons == NativePort(("KEY",), 2, True)
    assert m.switches is None


def test_partial_convention_led_plus_switch_matches() -> None:
    m = match_convention(_synth_iface(_LED_SW_BLOCK), [], _synth_board(_LED_SW_BLOCK))
    assert m is not None
    assert m.switches == NativePort(("SW",), 4, False)
    assert m.buttons is None


def test_canonical_convention_wins_over_framework_derived() -> None:
    # U32: a board can carry both an auto-derived (framework) block and an
    # authoritative (canonical) one that match the same interface.  The canonical
    # block must win -- even though the framework block is listed first on disk --
    # so vendor ground truth added later takes precedence over the derived guess.
    canonical: dict[str, Any] = {"clk": "CLOCK_50", "leds": {"name": "LEDR", "width": 10}}
    framework: dict[str, Any] = {
        "clk": "CLOCK_50",
        "leds": {"name": "LEDR", "width": 10, "active_low": True},
        "naming": "framework-derived",
    }
    bd = BoardDef(
        name="Dual",
        class_name="Dual",
        # framework block deliberately first in insertion order
        port_conventions={"litex": framework, "terasic": canonical},
    )
    m = match_convention(_synth_iface(canonical), [], bd)
    assert m is not None
    assert m.maker == "terasic"  # authoritative block chosen over the framework guess
    assert m.leds.active_low is False  # canonical polarity, not the derived active-low


def test_partial_convention_extra_input_is_near_miss() -> None:
    # The convention declares no switches; a design that adds a *default-less* `sw`
    # input would be left unbound in the wrapper's uut port map, so it must NOT
    # full-match.
    ports = [*_synth_iface(_LED_ONLY_BLOCK), _IfaceDecl(["sw"], "in", False, 4)]
    assert match_convention(ports, [], _synth_board(_LED_ONLY_BLOCK)) is None


def test_partial_convention_extra_input_with_default_matches() -> None:
    # F3: an extra input carrying a default expression is legal unassociated in
    # both GHDL and NVC (as the generic path allows), so it does NOT block a
    # native match -- consistent with `_check_parsed_contract`.
    ports = [*_synth_iface(_LED_ONLY_BLOCK), _IfaceDecl(["uart_rx"], "in", True, None)]
    assert match_convention(ports, [], _synth_board(_LED_ONLY_BLOCK)) is not None


@pytest.mark.parametrize("mode", ["out", "inout", "buffer"])
def test_partial_convention_extra_non_input_still_matches(mode: str) -> None:
    # An unmapped *non-input* port is fine: GHDL and NVC both leave an
    # unassociated out/inout/buffer `open` at elaboration (verified against both
    # toolchains), so the wrapper simply omits it -- like the DE0 example's
    # split-DP HEXn_DP outputs.  Only an unmapped `in` is an unbound port.
    ports = [*_synth_iface(_LED_ONLY_BLOCK), _IfaceDecl(["dbg"], mode, False, 1)]
    assert match_convention(ports, [], _synth_board(_LED_ONLY_BLOCK)) is not None


def test_native_wrapper_ties_off_absent_input_banks() -> None:
    m = ConventionMatch(
        maker="terasic",
        board_name="SynthBoard",
        clk="CLOCK_50",
        leds=NativePort(("LEDR",), 10, False),
    )
    w = _render_native_wrapper("led_blink", m)
    # generics floored to 1 (mirrors controller.build_generics' max(1, ...))
    assert "NUM_SWITCHES     : positive := 1;" in w
    assert "NUM_BUTTONS      : positive := 1;" in w
    # the top sw/btn ports still exist (cocotb reads dut.sw/dut.btn) ...
    assert "sw          : in  std_logic_vector(NUM_SWITCHES - 1 downto 0) := (others => '0');" in w
    assert "btn         : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0) := (others => '0');" in w
    # ... but nothing adapts them and the uut gets no sw/btn association
    assert "sw_uut" not in w
    assert "btn_uut" not in w
    assert "CLOCK_50 => clk" in w
    assert "LEDR => led_uut" in w


def test_partial_match_message_lists_only_declared_roles(tmp_path: Any) -> None:
    vhd = tmp_path / "led_key.vhd"
    vhd.write_text(_LED_BTN_SRC)
    res = check_vhdl_contract(vhd, board_def=_synth_board(_LED_BTN_BLOCK))
    assert res.ok and res.match is not None
    # clk, buttons, LEDs -- no switches placeholder between clk and LEDR
    assert "(CLOCK_50, KEY, LEDR)" in res.message


def test_partial_extra_input_near_miss_message(tmp_path: Any) -> None:
    vhd = tmp_path / "led_extra.vhd"
    vhd.write_text(
        "library ieee;\nuse ieee.std_logic_1164.all;\n"
        "entity led_extra is\n  port (\n"
        "    CLOCK_50 : in  std_logic;\n"
        "    SW       : in  std_logic_vector(3 downto 0);\n"
        "    LEDR     : out std_logic_vector(9 downto 0)\n"
        "  );\nend entity;\n"
        "architecture rtl of led_extra is\nbegin\n  LEDR <= (others => SW(0));\nend architecture;\n"
    )
    res = check_vhdl_contract(vhd, board_def=_synth_board(_LED_ONLY_BLOCK))
    assert res.ok is False
    assert res.match is None
    assert "unmapped input port(s): sw" in res.message
    # F4: names the convention (maker), points at hdl/blinky.vhd, and drops the
    # stale internal ticket ID / "until then" phrasing.
    assert "terasic" in res.message
    assert "hdl/blinky.vhd" in res.message
    assert "U21 B3" not in res.message
    assert "until then" not in res.message


def test_partial_match_gtkw_omits_absent_switch(tmp_path: Any) -> None:
    m = ConventionMatch(
        maker="terasic",
        board_name="SynthBoard",
        clk="CLOCK_50",
        leds=NativePort(("LEDR",), 10, False),
        buttons=NativePort(("KEY",), 2, True),
    )
    gtkw = tmp_path / "p.gtkw"
    _write_gtkw(gtkw, tmp_path / "p.vcd", {"NUM_BUTTONS": "2", "NUM_LEDS": "10"}, match=m)
    text = gtkw.read_text()
    assert "sim_wrapper.uut.ledr[9:0]" in text
    assert "sim_wrapper.uut.key[1:0]" in text
    assert "uut.sw" not in text  # absent bank not preselected


@pytest.mark.slow
def test_partial_native_wrapper_analyzes_under_ghdl(ghdl: str, tmp_path: Any) -> None:
    vhd = tmp_path / "led_blink.vhd"
    vhd.write_text(_LED_ONLY_SRC)
    bd = _synth_board(_LED_ONLY_BLOCK)
    res = check_vhdl_contract(vhd, board_def=bd)
    assert res.ok and res.match is not None
    ok, detail = analyze_vhdl(
        vhd, toplevel="led_blink", simulator="ghdl", board_def=bd, match=res.match
    )
    assert ok, f"GHDL partial-native analysis failed: {detail}"


@pytest.mark.slow
def test_partial_native_wrapper_analyzes_under_nvc(nvc: str, tmp_path: Any) -> None:
    vhd = tmp_path / "led_blink.vhd"
    vhd.write_text(_LED_ONLY_SRC)
    bd = _synth_board(_LED_ONLY_BLOCK)
    res = check_vhdl_contract(vhd, board_def=bd)
    assert res.ok and res.match is not None
    ok, detail = analyze_vhdl(
        vhd, toplevel="led_blink", simulator="nvc", board_def=bd, match=res.match
    )
    assert ok, f"NVC partial-native analysis failed: {detail}"


# ── F1/F3 end-to-end: scalar-led + defaulted-extra designs elaborate ─────────


def _tiny_fpgabx() -> BoardDef:
    return BoardDef.from_json((PROJECT / "boards/amaranth-boards/tiny_fpgabx.json").read_text())


def _write_and_check(
    src: str, top: str, bd: BoardDef, tmp_path: Any
) -> tuple[Path, ConventionMatch]:
    vhd = tmp_path / f"{top}.vhd"
    vhd.write_text(src)
    res = check_vhdl_contract(vhd, board_def=bd)
    assert res.ok and res.match is not None, f"{top} not recognized as native on {bd.name}"
    return vhd, res.match


@pytest.mark.slow
def test_scalar_led_native_analyzes_under_ghdl(ghdl: str, tmp_path: Any) -> None:
    # F1: `led : out std_logic` on a real width-1 board (Tiny FPGABX) elaborates.
    bd = _tiny_fpgabx()
    vhd, m = _write_and_check(_SCALAR_LED_SRC, "bx_blink", bd, tmp_path)
    assert m.leds.scalar_ports is True
    ok, detail = analyze_vhdl(vhd, toplevel="bx_blink", simulator="ghdl", board_def=bd, match=m)
    assert ok, f"GHDL scalar-led native analysis failed: {detail}"


@pytest.mark.slow
def test_scalar_led_native_analyzes_under_nvc(nvc: str, tmp_path: Any) -> None:
    bd = _tiny_fpgabx()
    vhd, m = _write_and_check(_SCALAR_LED_SRC, "bx_blink", bd, tmp_path)
    assert m.leds.scalar_ports is True
    ok, detail = analyze_vhdl(vhd, toplevel="bx_blink", simulator="nvc", board_def=bd, match=m)
    assert ok, f"NVC scalar-led native analysis failed: {detail}"


@pytest.mark.slow
def test_defaulted_extra_input_native_analyzes_under_ghdl(ghdl: str, tmp_path: Any) -> None:
    # F3: a full match with an extra defaulted input elaborates -- the wrapper
    # leaves UART_RX unassociated and its default drives it.
    bd = _synth_board(_LED_ONLY_BLOCK)
    vhd, m = _write_and_check(_LED_DEFAULT_EXTRA_SRC, "led_dflt", bd, tmp_path)
    ok, detail = analyze_vhdl(vhd, toplevel="led_dflt", simulator="ghdl", board_def=bd, match=m)
    assert ok, f"GHDL defaulted-extra native analysis failed: {detail}"


@pytest.mark.slow
def test_defaulted_extra_input_native_analyzes_under_nvc(nvc: str, tmp_path: Any) -> None:
    bd = _synth_board(_LED_ONLY_BLOCK)
    vhd, m = _write_and_check(_LED_DEFAULT_EXTRA_SRC, "led_dflt", bd, tmp_path)
    ok, detail = analyze_vhdl(vhd, toplevel="led_dflt", simulator="nvc", board_def=bd, match=m)
    assert ok, f"NVC defaulted-extra native analysis failed: {detail}"


# ── end-to-end: GHDL + NVC analysis of the example designs ───────────────────

_E2E_CASES = [
    ("de25_standard", "custom/de25_standard.json"),
    ("de10_standard", "custom/de10_standard.json"),
    ("de0", "amaranth-boards/de0.json"),
    # U32: a litex board-native design (LiteX names) whose 8-LED board boundary
    # exceeds its 4-bit user_led bank -- exercises the wrapper's zero-extend under
    # both simulators at the real board-count NUM_LEDS.
    ("arty_litex", "litex-boards/digilent_arty.json"),
]


def _load_native(top: str, rel: str) -> tuple[BoardDef, ConventionMatch]:
    bd = BoardDef.from_json((PROJECT / "boards" / rel).read_text())
    res = check_vhdl_contract(NATIVE / f"{top}.vhd", board_def=bd)
    assert res.ok and res.match is not None, f"{top} not recognized as native on {bd.name}"
    return bd, res.match


@pytest.mark.slow
@pytest.mark.parametrize(("top", "rel"), _E2E_CASES)
def test_native_design_analyzes_under_ghdl(ghdl: str, top: str, rel: str) -> None:
    bd, m = _load_native(top, rel)
    ok, detail = analyze_vhdl(
        NATIVE / f"{top}.vhd", toplevel=top, simulator="ghdl", board_def=bd, match=m
    )
    assert ok, f"GHDL native analysis failed for {top}: {detail}"


@pytest.mark.slow
@pytest.mark.parametrize(("top", "rel"), _E2E_CASES)
def test_native_design_analyzes_under_nvc(nvc: str, top: str, rel: str) -> None:
    bd, m = _load_native(top, rel)
    ok, detail = analyze_vhdl(
        NATIVE / f"{top}.vhd", toplevel=top, simulator="nvc", board_def=bd, match=m
    )
    assert ok, f"NVC native analysis failed for {top}: {detail}"


def _vcd_last_values(text: str) -> dict[str, tuple[int, str]]:
    """Map full hierarchical signal path -> (width, last vector value) from a VCD."""
    scope: list[str] = []
    id2path: dict[str, str] = {}
    id2w: dict[str, int] = {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("$scope"):
            scope.append(s.split()[2])
        elif s.startswith("$upscope"):
            if scope:
                scope.pop()
        elif s.startswith("$var"):
            parts = s.split()
            id2w[parts[3]] = int(parts[2])
            id2path[parts[3]] = ".".join(scope + [parts[4].split("[")[0]])
    last: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("b") and " " in s:
            val, vid = s[1:].split()
            last[vid] = val
    return {p: (id2w[i], last[i]) for i, p in id2path.items() if i in last}


@pytest.mark.slow
def test_native_de25_run_inverts_leds_under_nvc(nvc: str, tmp_path: Any) -> None:
    """Standalone NVC run of the DE25 native wrapper: top led is the inverse of the
    design's active-low uut.ledr, and the native signal is present in the dump
    (which also confirms the lowercase identifier case the .gtkw writer assumes).
    """
    bd, m = _load_native("de25_standard", "custom/de25_standard.json")
    env, vhpi = _build_sim_env(simulator="nvc")
    work = tempfile.mkdtemp(prefix="de25_e2e_")
    ok, detail = analyze_vhdl(
        NATIVE / "de25_standard.vhd",
        work_dir=work,
        toplevel="de25_standard",
        simulator="nvc",
        board_def=bd,
        match=m,
    )
    assert ok, detail

    generics = {
        "NUM_SWITCHES": "10",
        "NUM_BUTTONS": "4",
        "NUM_LEDS": "10",
        "NUM_SEGS": "6",
        "COUNTER_BITS": "18",
        "CLK_HALF_NS_INIT": "10",
    }
    subprocess.run(
        _NVCBackend.elaborate_cmd("sim_wrapper", generics, work), env=env, check=True, cwd=work
    )

    vcd = tmp_path / "de25.vcd"
    cmd = _NVCBackend.run_cmd("sim_wrapper", generics, vhpi, work, wave=WaveConfig(str(vcd), "vcd"))
    cmd = [
        a for a in cmd if not a.startswith("--load=")
    ]  # standalone: no cocotb, wrapper self-clocks
    cmd.append("--stop-time=2us")
    subprocess.run(cmd, env=env, cwd=work, capture_output=True, text=True)
    assert vcd.is_file(), "no VCD produced by the standalone DE25 run"

    vals = _vcd_last_values(vcd.read_text(errors="ignore"))
    led = [p for p in vals if p == "sim_wrapper.led"]
    ledr = [p for p in vals if p.endswith("uut.ledr")]
    assert ledr, f"native uut.ledr signal absent from dump (paths: {sorted(vals)[:15]})"
    assert led, "top-level led signal absent from dump"

    lw, led_val = vals[led[0]]
    rw, ledr_val = vals[ledr[0]]
    led_bits = led_val.rjust(lw, "0")
    ledr_bits = ledr_val.rjust(rw, "0")
    inverted = "".join("1" if c == "0" else "0" for c in ledr_bits)
    assert led_bits == inverted, f"led {led_bits} is not the inverse of ledr {ledr_bits}"


@pytest.mark.slow
def test_native_arty_cocotb_loop_zero_extend_and_switch_xor(ghdl: str, tmp_path: Any) -> None:
    """F8: a real GHDL + cocotb run of arty_litex.vhd on the Digilent Arty.

    Drives the wrapper's ``sw`` and reads back ``led`` through a minimal cocotb
    module (not sim_testbench), exercising the native wrapper's zero-extend (the
    4-bit user_led bank onto the 8-LED board boundary) and the design's
    ``user_led <= count(...) xor user_sw`` adaptation.  Both were verified by
    hand 2026-07-15; this makes the native cocotb loop a permanent regression
    guard (the rest of the suite covers native *analysis*, not a driven run).
    """
    bd = BoardDef.from_json((PROJECT / "boards/litex-boards/digilent_arty.json").read_text())
    vhd = NATIVE / "arty_litex.vhd"
    res = check_vhdl_contract(vhd, board_def=bd)
    assert res.ok and res.match is not None

    work = tempfile.mkdtemp(prefix="arty_f8_")
    ok, detail = analyze_vhdl(
        vhd, work_dir=work, toplevel="arty_litex", simulator="ghdl", board_def=bd, match=res.match
    )
    assert ok, detail

    # Minimal cocotb testbench: drive sw, sample led before/after, write JSON so
    # the assertions live in pytest (clear diagnostics) rather than inside cocotb.
    moddir = tmp_path / "cocotb_mod"
    moddir.mkdir()
    out = tmp_path / "f8.json"
    (moddir / "f8_tb.py").write_text(
        "import json, os\n"
        "import cocotb\n"
        "from cocotb.triggers import Timer\n"
        "\n"
        "\n"
        "@cocotb.test()\n"
        "async def sample(dut):\n"
        "    dut.btn.value = 0\n"
        "    dut.sw.value = 0\n"
        "    await Timer(1, unit='us')\n"
        "    led0 = int(dut.led.value)\n"
        "    dut.sw.value = 0b0101\n"
        "    await Timer(1, unit='us')\n"
        "    led5 = int(dut.led.value)\n"
        "    with open(os.environ['FPGA_SIM_F8_OUT'], 'w') as f:\n"
        "        json.dump({'led0': led0, 'led5': led5}, f)\n"
    )

    env, plugin_lib = _build_sim_env(simulator="ghdl")
    env["FPGA_SIM_F8_OUT"] = str(out)
    env["COCOTB_TEST_MODULES"] = "f8_tb"
    env["TOPLEVEL"] = "sim_wrapper"
    env["PYTHONPATH"] = os.pathsep.join([str(moddir), env["PYTHONPATH"]])
    generics = {
        "NUM_SWITCHES": str(max(1, len(bd.switches))),
        "NUM_BUTTONS": str(max(1, len(bd.buttons))),
        "NUM_LEDS": str(max(1, len(bd.leds))),
        "CLK_HALF_NS_INIT": "10",
    }
    cmd = _GHDLBackend.run_cmd("sim_wrapper", generics, plugin_lib, work)
    proc = subprocess.run(cmd, env=env, cwd=work, capture_output=True, text=True, timeout=180)
    assert out.is_file(), (
        "cocotb module produced no output (did it run?).\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    data = json.loads(out.read_text())
    # Zero-extend: the 4-bit user_led bank leaves the upper 4 board LEDs dark.
    assert (data["led5"] >> 4) == 0, f"upper LED nibble not zero: {data['led5']:#010b}"
    # user_sw XORs the low nibble: setting sw=0b0101 flips exactly those bits.
    assert ((data["led0"] ^ data["led5"]) & 0xF) == 0b0101, (
        f"switches did not XOR the low nibble: led0={data['led0']:#06b} led5={data['led5']:#06b}"
    )


# ── B3b: SimulationScreen native-badge helper (in-process, U34) ──────────────
#
# The badge/active-low note is built by ``simulation_screen._native_active_low``
# straight from the ``ConventionMatch`` -- no FPGA_SIM_NATIVE_CONVENTION env JSON
# and no subprocess, since the launcher owns the match object now.


def test_native_active_low_lists_active_low_roles() -> None:
    """_native_active_low names exactly the roles the convention drives active-low."""
    from fpga_sim.ui.simulation_screen import _native_active_low

    assert _native_active_low(_de25_match()) == "LED, BTN, HEX"  # SW active-high → omitted
    assert _native_active_low(_de10_match()) == "BTN, HEX"  # active-high LEDs → omitted


def test_native_active_low_none_when_all_active_high() -> None:
    from fpga_sim.ui.simulation_screen import _native_active_low

    match = ConventionMatch(
        maker="digilent",
        board_name="Arty",
        clk="clk100",
        leds=NativePort(("led",), 4, False),
        switches=NativePort(("sw",), 4, False),
        buttons=NativePort(("btn",), 4, False),
        seven_seg=None,
    )
    assert _native_active_low(match) == "none"


def test_native_active_low_skips_absent_banks() -> None:
    """U31: an absent switch/button bank (None) contributes no role."""
    from fpga_sim.ui.simulation_screen import _native_active_low

    match = ConventionMatch(
        maker="litex",
        board_name="NeTV2",
        clk="clk100",
        leds=NativePort(("user_led",), 4, True),
        switches=None,
        buttons=None,
        seven_seg=None,
    )
    assert _native_active_low(match) == "LED"
