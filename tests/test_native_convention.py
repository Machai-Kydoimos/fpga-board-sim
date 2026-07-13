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
import sys
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
    assert "led <= not led_uut;" in vhd
    assert "LEDR => led_uut" in vhd
    assert "generic map" not in vhd  # native uut has no NUM_* generics


def test_native_wrapper_active_high_leds_are_not_inverted() -> None:
    vhd = _render_native_wrapper("de10_standard", _de10_match())
    assert "led <= led_uut;" in vhd
    assert "led <= not led_uut;" not in vhd


def test_native_wrapper_inverts_active_low_buttons() -> None:
    vhd = _render_native_wrapper("de25_standard", _de25_match())
    assert "btn_uut <= not btn;" in vhd
    assert "sw_uut <= sw;" in vhd  # SW is active-high: no inversion
    assert "KEY => btn_uut" in vhd


def test_native_wrapper_bakes_board_widths_as_generic_defaults() -> None:
    # analyze_vhdl elaborates at {} defaults, so the defaults must equal the
    # native uut's fixed widths (decision 2 -- no "defaults dance").
    vhd = _render_native_wrapper("de25_standard", _de25_match())
    assert "NUM_SWITCHES     : positive := 10;" in vhd
    assert "NUM_BUTTONS      : positive := 4;" in vhd
    assert "NUM_LEDS         : positive := 10;" in vhd
    assert "NUM_SEGS         : positive := 6;" in vhd


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
    assert "led <= led_uut;" in vhd
    assert "LEDG => led_uut" in vhd
    assert "BUTTON => btn_uut" in vhd


def test_native_wrapper_scalar_led_bank_maps_bit_by_bit() -> None:
    # A bank of distinct scalar ports (no board uses this today, but the matcher
    # can produce it) maps each scalar to one bit of the wrapper's vector.
    m = ConventionMatch(
        maker="acme",
        board_name="Go",
        clk="i_Clk",
        leds=NativePort(("o_LED_1", "o_LED_2", "o_LED_3", "o_LED_4"), 4, False),
        switches=NativePort(("i_SW_1", "i_SW_2"), 2, False),
        buttons=NativePort(("i_BTN_1", "i_BTN_2"), 2, False),
    )
    vhd = _render_native_wrapper("go", m)
    assert "o_LED_1 => led_uut(0)" in vhd
    assert "o_LED_4 => led_uut(3)" in vhd
    assert "i_Clk => clk" in vhd


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
        if any(
            isinstance(b, dict) and b.get("naming", "canonical") != "project-derived"
            for b in pc.values()
        ):
            boards.append(BoardDef.from_json(json.dumps(d)))
    return boards


def _canonical_block(bd: BoardDef) -> dict[str, Any] | None:
    for b in bd.port_conventions.values():
        if isinstance(b, dict) and b.get("naming", "canonical") != "project-derived":
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


def test_partial_convention_extra_input_is_near_miss() -> None:
    # The convention declares no switches; a design that adds an `sw` input would
    # be left unbound in the wrapper's uut port map, so it must NOT full-match.
    ports = [*_synth_iface(_LED_ONLY_BLOCK), _IfaceDecl(["sw"], "in", False, 4)]
    assert match_convention(ports, [], _synth_board(_LED_ONLY_BLOCK)) is None


def test_partial_convention_extra_output_still_matches() -> None:
    # An unmapped *output* is fine -- the wrapper leaves it `open` (dark), like
    # the DE0 example's split-DP HEXn_DP scalars.
    ports = [*_synth_iface(_LED_ONLY_BLOCK), _IfaceDecl(["dbg"], "out", False, 1)]
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
    assert "sw          : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);" in w
    assert "btn         : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);" in w
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


# ── end-to-end: GHDL + NVC analysis of the example designs ───────────────────

_E2E_CASES = [
    ("de25_standard", "custom/de25_standard.json"),
    ("de10_standard", "custom/de10_standard.json"),
    ("de0", "amaranth-boards/de0.json"),
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


# ── B3b: sim_testbench convention parsing (subprocess -- module imports cocotb) ──


def _testbench_native_helpers(env_value: str | None) -> dict[str, Any]:
    """Run sim_testbench's _native_convention/_active_low_roles in a subprocess.

    sim_testbench imports cocotb and is never imported into the pytest process
    (see test_sim_testbench_lint.py), so its env-driven helpers are exercised via
    a subprocess import -- mirroring the FPGA_SIM_THEME handoff test.
    """
    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("SDL_AUDIODRIVER", "dummy")
    if env_value is None:
        env.pop("FPGA_SIM_NATIVE_CONVENTION", None)
    else:
        env["FPGA_SIM_NATIVE_CONVENTION"] = env_value
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PROJECT / "src"), str(PROJECT / "sim"), env.get("PYTHONPATH", "")]
    )
    code = (
        "import json, sim_testbench as t; "
        "c = t._native_convention(); "
        "print(json.dumps({"
        "'is_none': c is None, "
        "'maker': (c or {}).get('maker'), "
        "'roles': (t._active_low_roles(c) if c else None)}))"
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )
    assert r.returncode == 0, r.stderr
    out: dict[str, Any] = json.loads(r.stdout.strip().splitlines()[-1])
    return out


def test_testbench_parses_native_convention_and_active_low_roles() -> None:
    out = _testbench_native_helpers(
        json.dumps(
            {
                "maker": "terasic",
                "board_name": "DE25-Standard",
                "leds_active_low": True,
                "switches_active_low": False,
                "buttons_active_low": True,
                "has_seg": True,
                "seg_active_low": True,
            }
        )
    )
    assert out["is_none"] is False
    assert out["maker"] == "terasic"
    assert out["roles"] == "LED, BTN, HEX"  # SW omitted (active-high)


def test_testbench_generic_run_has_no_convention() -> None:
    out = _testbench_native_helpers(None)
    assert out["is_none"] is True
    assert out["maker"] is None
