"""Tests for the three-stage VHDL validation pipeline.

Covers check_vhdl_encoding(), check_vhdl_contract(), and analyze_vhdl()
using the good blinky designs and the dedicated bad_*_blinky fixtures.
"""

from pathlib import Path

import pytest

from fpga_sim.board_loader import BoardDef, ComponentInfo, SevenSegDef
from fpga_sim.sim_bridge import (
    _generate_wrapper,
    add_error_hints,
    analyze_vhdl,
    check_vhdl_contract,
    check_vhdl_encoding,
)
from tests.conftest import _7seg_board, _plain_board

HDL = Path(__file__).resolve().parent.parent / "hdl"


def _contract(path: str | Path, board_def: BoardDef | None = None) -> tuple[bool, str]:
    """(ok, message) from check_vhdl_contract, for the generic-contract assertions.

    U21 B2 changed check_vhdl_contract to return a ContractResult; the tests here
    assert only the ok/message the generic contract has always produced.  The typed
    result and its .match field are covered in tests/test_convention_matcher.py.
    """
    res = check_vhdl_contract(path, board_def=board_def)
    return res.ok, res.message


GOOD_BLINKYS = [
    "blinky.vhd",
    "blinky_alt.vhd",
    "blinky_counter.vhd",
    "blinky_morse.vhd",
    "blinky_pwm.vhd",
    "blinky_walking.vhd",
]


# ── Stage 1: encoding ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("filename", GOOD_BLINKYS)
def test_good_blinky_encoding_pass(filename):
    ok, msg = check_vhdl_encoding(HDL / filename)
    assert ok, f"Unexpected encoding failure in {filename}: {msg}"


def test_bad_encoding_fails_stage1():
    ok, msg = check_vhdl_encoding(HDL / "bad_encoding_blinky.vhdl")
    assert not ok, "Expected encoding check to fail on BOM file"
    assert "BOM" in msg


def test_bad_contract_passes_stage1():
    ok, msg = check_vhdl_encoding(HDL / "bad_contract_blinky.vhdl")
    assert ok, f"Unexpected encoding failure: {msg}"


def test_bad_semantic_passes_stage1():
    ok, msg = check_vhdl_encoding(HDL / "bad_semantic_blinky.vhdl")
    assert ok, f"Unexpected encoding failure: {msg}"


# ── Stage 2: contract ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("filename", GOOD_BLINKYS)
def test_good_blinky_contract_pass(filename):
    ok, msg = _contract(HDL / filename)
    assert ok, f"Unexpected contract failure in {filename}: {msg}"


def test_bad_contract_fails_stage2():
    ok, msg = _contract(HDL / "bad_contract_blinky.vhdl")
    assert not ok, "Expected contract check to fail on mismatched entity"
    assert "mismatch" in msg.lower()


def test_bad_semantic_passes_stage2():
    ok, msg = _contract(HDL / "bad_semantic_blinky.vhdl")
    assert ok, f"Unexpected contract failure: {msg}"


# ── Stage 3: GHDL analysis + elaboration ─────────────────────────────────────


@pytest.mark.slow
@pytest.mark.parametrize("filename", GOOD_BLINKYS)
def test_good_blinky_ghdl_pass(filename, ghdl):
    f = HDL / filename
    ok, detail = analyze_vhdl(f, toplevel=f.stem)
    assert ok, f"GHDL failed on {filename}: {detail}"


@pytest.mark.slow
def test_bad_semantic_fails_stage3(ghdl):
    f = HDL / "bad_semantic_blinky.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem)
    assert not ok, "Expected GHDL analysis to fail on bad_semantic_blinky.vhdl"
    assert "unsigned" in detail.lower()


# ── Error message quality ─────────────────────────────────────────────────────


def test_bad_encoding_error_names_the_bom():
    """The BOM error must tell the user exactly what was detected."""
    _, msg = check_vhdl_encoding(HDL / "bad_encoding_blinky.vhdl")
    assert "BOM" in msg


def test_bad_contract_error_names_found_entity():
    """Mismatch error must include the entity name that was found in the file."""
    _, msg = _contract(HDL / "bad_contract_blinky.vhdl")
    # entity is 'blinky'; error must say so
    assert "blinky" in msg


def test_bad_contract_error_names_expected_stem():
    """Mismatch error must include the filename stem so the user knows the fix."""
    _, msg = _contract(HDL / "bad_contract_blinky.vhdl")
    assert "bad_contract_blinky" in msg


@pytest.mark.slow
def test_analyze_semantic_error_is_nonempty(ghdl):
    """GHDL analysis error for bad_semantic_blinky.vhdl must not be blank."""
    f = HDL / "bad_semantic_blinky.vhdl"
    _, detail = analyze_vhdl(f, toplevel=f.stem)
    assert detail.strip()  # non-empty, human-readable error


# ── bad_* 7-seg fixture checks ────────────────────────────────────────────────


def test_bad_7seg_missing_seg_passes_stage1():
    """bad_contract_7seg_missing_seg.vhdl must be clean ASCII (encoding passes)."""
    ok, msg = check_vhdl_encoding(HDL / "bad_contract_7seg_missing_seg.vhdl")
    assert ok, f"Unexpected encoding failure: {msg}"


def test_bad_7seg_missing_seg_fails_stage2():
    """NUM_SEGS generic without a seg port must be rejected by the contract checker."""
    ok, msg = _contract(HDL / "bad_contract_7seg_missing_seg.vhdl")
    assert not ok, "Expected contract check to fail: NUM_SEGS declared but no seg port"
    assert "NUM_SEGS" in msg
    assert "seg" in msg.lower()


def test_bad_7seg_missing_seg_error_names_fix():
    """The missing-seg error must suggest the correct port declaration."""
    _, msg = _contract(HDL / "bad_contract_7seg_missing_seg.vhdl")
    assert "8 * NUM_SEGS" in msg


def test_bad_7seg_extra_seg_passes_stage1():
    """bad_contract_7seg_extra_seg.vhdl must be clean ASCII (encoding passes)."""
    ok, msg = check_vhdl_encoding(HDL / "bad_contract_7seg_extra_seg.vhdl")
    assert ok, f"Unexpected encoding failure: {msg}"


def test_bad_7seg_extra_seg_passes_stage2():
    """bad_contract_7seg_extra_seg.vhdl must pass the contract check (seg port present)."""
    ok, msg = _contract(HDL / "bad_contract_7seg_extra_seg.vhdl")
    assert ok, f"Unexpected contract rejection: {msg}"


@pytest.mark.slow
def test_bad_7seg_extra_seg_fails_stage3_on_7seg_board(ghdl):
    """Wrong seg port width must cause GHDL elaboration failure on a 7-seg board."""
    f = HDL / "bad_contract_7seg_extra_seg.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=_7seg_board())
    assert not ok, "Expected GHDL to fail: seg port width mismatch in 7-seg wrapper"
    assert detail.strip(), "Error detail must be non-empty"


@pytest.mark.slow
def test_bad_7seg_extra_seg_passes_stage3_on_plain_board(ghdl):
    """Wrong seg port width must not cause failure on a non-7-seg board (seg left open)."""
    f = HDL / "bad_contract_7seg_extra_seg.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=_plain_board())
    assert ok, f"Unexpected GHDL failure on plain board: {detail}"


@pytest.mark.slow
def test_bad_7seg_extra_seg_fails_stage3_on_7seg_board_nvc(nvc):
    """Wrong seg port width must cause NVC elaboration failure during analyze_vhdl."""
    f = HDL / "bad_contract_7seg_extra_seg.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=_7seg_board(), simulator="nvc")
    assert not ok, "Expected NVC to fail: seg port width mismatch in 7-seg wrapper"
    assert detail.strip(), "Error detail must be non-empty"


@pytest.mark.slow
def test_bad_7seg_extra_seg_passes_stage3_on_plain_board_nvc(nvc):
    """Wrong seg port width must not cause NVC failure on a non-7-seg board."""
    f = HDL / "bad_contract_7seg_extra_seg.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=_plain_board(), simulator="nvc")
    assert ok, f"Unexpected NVC failure on plain board: {detail}"


# ── 7-seg contract checks ─────────────────────────────────────────────────────


def test_7seg_board_accepts_standard_design():
    """A 7-seg board must accept a standard design (segments will be dark)."""
    ok, msg = _contract(HDL / "blinky.vhd", board_def=_7seg_board())
    assert ok, f"Unexpected rejection: {msg}"


def test_non7seg_board_accepts_7seg_design():
    """A non-7-seg board must accept a 7-seg design (seg output ignored)."""
    ok, msg = _contract(HDL / "counter_7seg.vhd", board_def=_plain_board())
    assert ok, f"Unexpected rejection: {msg}"


def test_7seg_board_accepts_7seg_design():
    """A 7-seg board must accept a design with a seg port."""
    ok, _ = _contract(HDL / "counter_7seg.vhd", board_def=_7seg_board())
    assert ok


def test_non7seg_board_accepts_standard_design():
    """A non-7-seg board with no board_def must accept a standard design."""
    ok, _ = _contract(HDL / "blinky.vhd", board_def=None)
    assert ok


# ── Wrapper template selection (no GHDL required) ────────────────────────────


def test_generate_wrapper_7seg_has_seg_port(tmp_path):
    """Generated wrapper for a 7-seg board + seg design must contain seg and NUM_SEGS."""
    out = _generate_wrapper(
        "counter_7seg", str(tmp_path), board_def=_7seg_board(), design_has_seg=True
    )
    text = out.read_text()
    assert "seg" in text.lower()
    assert "NUM_SEGS" in text
    assert "counter_7seg" in text


def test_generate_wrapper_non7seg_no_seg_port(tmp_path):
    """Generated wrapper for a standard board must not contain NUM_SEGS."""
    out = _generate_wrapper("blinky", str(tmp_path), board_def=None)
    assert "NUM_SEGS" not in out.read_text()


def test_generate_wrapper_7seg_board_no_seg_design(tmp_path):
    """7-seg board + standard design must not inject seg ports or generics."""
    out = _generate_wrapper("blinky", str(tmp_path), board_def=_7seg_board(), design_has_seg=False)
    assert "NUM_SEGS" not in out.read_text()


# ── GHDL: 7-seg design analysis ───────────────────────────────────────────────

GOOD_7SEG = ["counter_7seg.vhd"]


@pytest.mark.slow
@pytest.mark.parametrize("filename", GOOD_7SEG)
def test_good_7seg_ghdl_pass(filename, ghdl):
    """counter_7seg.vhd must analyze cleanly under GHDL with the 7-seg wrapper."""
    f = HDL / filename
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=_7seg_board())
    assert ok, f"GHDL failed on {filename}: {detail}"


# ── U4: board-aware contract checks ──────────────────────────────────────────


def _rich_7seg_board() -> BoardDef:
    """A 7-seg board with real resource counts (DE10-Lite-like: 10/2/10, 6 digits)."""

    def mk(kind: str, n: int) -> list[ComponentInfo]:
        return [ComponentInfo(kind, kind, i) for i in range(n)]

    return BoardDef(
        "DE10-Lite",
        "DE10LitePlatform",
        leds=mk("led", 10),
        buttons=mk("button", 2),
        switches=mk("switch", 10),
        seven_seg=SevenSegDef(6, True, False, True, False),
    )


def _four_led_board() -> BoardDef:
    """A plain board whose LED count equals the wrapper default width (4)."""
    return BoardDef("Quad", "QuadPlatform", leds=[ComponentInfo("led", "led", i) for i in range(4)])


def _design(name: str, *, generics: str | None = None, ports: str | None = None) -> str:
    """A contract-correct design with overridable generic/port clauses."""
    generics = generics or (
        "    NUM_SWITCHES : positive := 4;\n"
        "    NUM_BUTTONS  : positive := 4;\n"
        "    NUM_LEDS     : positive := 4;\n"
        "    COUNTER_BITS : positive := 24"
    )
    ports = ports or (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0)"
    )
    return (
        "library ieee;\nuse ieee.std_logic_1164.all;\n\n"
        f"entity {name} is\n"
        f"  generic (\n{generics}\n  );\n"
        f"  port (\n{ports}\n  );\n"
        "end entity;\n\n"
        f"architecture rtl of {name} is\nbegin\n  led <= (others => '0');\nend architecture;\n"
    )


def _write(tmp_path: Path, name: str, text: str) -> Path:
    f = tmp_path / f"{name}.vhd"
    f.write_text(text)
    return f


# fixed-width fixture


def test_fixed_width_fixture_encoding_clean():
    ok, msg = check_vhdl_encoding(HDL / "bad_contract_fixed_width.vhdl")
    assert ok, f"Unexpected encoding failure: {msg}"


def test_fixed_width_fixture_fails_stage2_with_board():
    ok, msg = _contract(HDL / "bad_contract_fixed_width.vhdl", board_def=_plain_board())
    assert not ok, "Expected contract check to reject fixed 16-bit led with a board selected"
    assert "led" in msg
    assert "16" in msg
    assert "NUM_LEDS" in msg


def test_fixed_width_fixture_passes_stage2_without_board():
    """Without a board the fixed width cannot be judged at stage 2."""
    ok, msg = _contract(HDL / "bad_contract_fixed_width.vhdl")
    assert ok, f"Unexpected rejection: {msg}"


def test_fixed_width_mismatch_message_names_board_and_count():
    """The flagship U4 message: board name, its LED count, and the generic fix."""
    _, msg = _contract(HDL / "bad_contract_fixed_width.vhdl", board_def=_rich_7seg_board())
    assert "DE10-Lite" in msg
    assert "10 LEDs" in msg
    assert "NUM_LEDS=10" in msg
    assert "led : out std_logic_vector(NUM_LEDS - 1 downto 0)" in msg


def test_fixed_width_matching_board_but_not_default_rejected(tmp_path):
    """A fixed width equal to the board's count still fails pre-launch validation."""
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(9 downto 0)"
    )
    f = _write(tmp_path, "ten_led", _design("ten_led", ports=ports))
    ok, msg = _contract(f, board_def=_rich_7seg_board())
    assert not ok
    assert "matches" in msg.lower()
    assert "NUM_LEDS" in msg


def test_fixed_width_equal_to_default_and_board_accepted(tmp_path):
    """Fixed width == wrapper default == board count works end-to-end: allowed."""
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(3 downto 0)"
    )
    f = _write(tmp_path, "four_led", _design("four_led", ports=ports))
    ok, msg = _contract(f, board_def=_four_led_board())
    assert ok, f"Unexpected rejection: {msg}"


def test_fixed_seg_width_mismatch_names_digits(tmp_path):
    """seg fixed at 32 bits vs a 6-digit board (needs 48) → digit-aware message."""
    generics = (
        "    NUM_SWITCHES : positive := 4;\n"
        "    NUM_BUTTONS  : positive := 4;\n"
        "    NUM_LEDS     : positive := 4;\n"
        "    NUM_SEGS     : positive := 4;\n"
        "    COUNTER_BITS : positive := 32"
    )
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0);\n"
        "    seg : out std_logic_vector(31 downto 0)"
    )
    f = _write(tmp_path, "seg32", _design("seg32", generics=generics, ports=ports))
    ok, msg = _contract(f, board_def=_rich_7seg_board())
    assert not ok
    assert "6-digit" in msg
    assert "48" in msg
    assert "8 * NUM_SEGS" in msg


def test_fixed_seg_width_ignored_on_plain_board(tmp_path):
    """On a board without a 7-seg display the seg port is left open: any width passes."""
    generics = (
        "    NUM_SWITCHES : positive := 4;\n"
        "    NUM_BUTTONS  : positive := 4;\n"
        "    NUM_LEDS     : positive := 4;\n"
        "    NUM_SEGS     : positive := 4;\n"
        "    COUNTER_BITS : positive := 32"
    )
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0);\n"
        "    seg : out std_logic_vector(31 downto 0)"
    )
    f = _write(tmp_path, "seg32p", _design("seg32p", generics=generics, ports=ports))
    ok, msg = _contract(f, board_def=_plain_board())
    assert ok, f"Unexpected rejection: {msg}"


# wrong-direction fixture


def test_wrong_direction_fixture_encoding_clean():
    ok, msg = check_vhdl_encoding(HDL / "bad_contract_wrong_direction.vhdl")
    assert ok, f"Unexpected encoding failure: {msg}"


def test_wrong_direction_fixture_fails_stage2():
    """led : in must be rejected — GHDL/NVC accept it silently, so this is the only guard."""
    ok, msg = _contract(HDL / "bad_contract_wrong_direction.vhdl")
    assert not ok, "Expected contract check to reject led with mode IN"
    assert "OUT" in msg
    assert "led : out std_logic_vector(NUM_LEDS - 1 downto 0)" in msg


def test_wrong_direction_sw_out_fails(tmp_path):
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : out std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0)"
    )
    f = _write(tmp_path, "sw_out", _design("sw_out", ports=ports))
    ok, msg = _contract(f)
    assert not ok
    assert "'sw'" in msg
    assert "IN" in msg


# required generics are now fatal (the wrapper maps all four unconditionally)


def test_missing_generic_is_fatal(tmp_path):
    generics = (
        "    NUM_SWITCHES : positive := 4;\n"
        "    NUM_BUTTONS  : positive := 4;\n"
        "    NUM_LEDS     : positive := 4"
    )
    f = _write(tmp_path, "no_cb", _design("no_cb", generics=generics))
    ok, msg = _contract(f)
    assert not ok, "Expected contract check to reject a design without COUNTER_BITS"
    assert "COUNTER_BITS" in msg
    assert "generic (" in msg  # the message shows the full block to add


def test_missing_all_generics_lists_them(tmp_path):
    text = (
        "library ieee;\nuse ieee.std_logic_1164.all;\n"
        "entity bare is\n  port (\n"
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(3 downto 0);\n"
        "    btn : in  std_logic_vector(3 downto 0);\n"
        "    led : out std_logic_vector(3 downto 0)\n"
        "  );\nend entity;\n"
        "architecture rtl of bare is begin led <= sw; end architecture;\n"
    )
    f = _write(tmp_path, "bare", text)
    ok, msg = _contract(f)
    assert not ok
    for g in ("NUM_SWITCHES", "NUM_BUTTONS", "NUM_LEDS", "COUNTER_BITS"):
        assert g in msg


# extra ports / generics need defaults


def test_extra_input_port_without_default_fails(tmp_path):
    ports = (
        "    clk : in  std_logic;\n"
        "    rst : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0)"
    )
    f = _write(tmp_path, "with_rst", _design("with_rst", ports=ports))
    ok, msg = _contract(f)
    assert not ok
    assert "'rst'" in msg
    assert ":= '0'" in msg  # suggests the default-value fix


def test_extra_input_port_with_default_passes(tmp_path):
    ports = (
        "    clk : in  std_logic;\n"
        "    rst : in  std_logic := '0';\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0)"
    )
    f = _write(tmp_path, "with_rst_d", _design("with_rst_d", ports=ports))
    ok, msg = _contract(f)
    assert ok, f"Unexpected rejection: {msg}"


def test_extra_output_port_passes(tmp_path):
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0);\n"
        "    dbg : out std_logic"
    )
    f = _write(tmp_path, "with_dbg", _design("with_dbg", ports=ports))
    ok, msg = _contract(f)
    assert ok, f"Unexpected rejection: {msg}"


def test_extra_generic_without_default_fails(tmp_path):
    generics = (
        "    NUM_SWITCHES : positive := 4;\n"
        "    NUM_BUTTONS  : positive := 4;\n"
        "    NUM_LEDS     : positive := 4;\n"
        "    COUNTER_BITS : positive := 24;\n"
        "    MY_PARAM     : positive"
    )
    f = _write(tmp_path, "gen_nd", _design("gen_nd", generics=generics))
    ok, msg = _contract(f)
    assert not ok
    assert "'my_param'" in msg


def test_extra_generic_with_default_passes(tmp_path):
    """PRESCALER_BITS-style extra generics with defaults are fine (embedded cores)."""
    generics = (
        "    NUM_SWITCHES   : positive := 4;\n"
        "    NUM_BUTTONS    : positive := 4;\n"
        "    NUM_LEDS       : positive := 4;\n"
        "    COUNTER_BITS   : positive := 24;\n"
        "    PRESCALER_BITS : positive := 16"
    )
    f = _write(tmp_path, "gen_d", _design("gen_d", generics=generics))
    ok, msg = _contract(f)
    assert ok, f"Unexpected rejection: {msg}"


# seg port ↔ NUM_SEGS pairing (board-aware direction)


def test_seg_without_num_segs_fails_on_7seg_board(tmp_path):
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0);\n"
        "    seg : out std_logic_vector(31 downto 0)"
    )
    f = _write(tmp_path, "seg_ng", _design("seg_ng", ports=ports))
    ok, msg = _contract(f, board_def=_7seg_board())
    assert not ok
    assert "NUM_SEGS" in msg


def test_seg_without_num_segs_passes_on_plain_board(tmp_path):
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0);\n"
        "    seg : out std_logic_vector(31 downto 0)"
    )
    f = _write(tmp_path, "seg_ngp", _design("seg_ngp", ports=ports))
    ok, msg = _contract(f, board_def=_plain_board())
    assert ok, f"Unexpected rejection: {msg}"


# parser scoping and comment handling


def test_inner_entity_fixed_widths_ignored(tmp_path):
    """Only the toplevel entity's ports are checked (multi-entity embedded-core files)."""
    inner = (
        "library ieee;\nuse ieee.std_logic_1164.all;\n"
        "entity helper is\n  port (\n"
        "    clk : in  std_logic;\n"
        "    led : out std_logic_vector(7 downto 0)\n"
        "  );\nend entity;\n"
        "architecture rtl of helper is begin led <= (others => '0'); end architecture;\n\n"
    )
    f = _write(tmp_path, "outer", inner + _design("outer"))
    ok, msg = _contract(f, board_def=_rich_7seg_board())
    assert ok, f"Inner entity's fixed led width was wrongly flagged: {msg}"


@pytest.mark.parametrize(
    "filename", ["mx65_walking_counter_7seg.vhd", "t80_walking_counter_7seg.vhd"]
)
def test_committed_embedded_cores_pass_contract(filename):
    """The generated multi-entity designs must pass the parsed contract checks."""
    ok, msg = _contract(HDL / filename, board_def=_7seg_board())
    assert ok, f"Unexpected rejection of {filename}: {msg}"


def test_num_segs_in_comment_does_not_require_seg_port(tmp_path):
    """Comments are stripped before parsing: a NUM_SEGS mention is not a declaration."""
    f = _write(tmp_path, "commented", "-- NUM_SEGS is not used here\n" + _design("commented"))
    ok, msg = _contract(f)
    assert ok, f"Unexpected rejection: {msg}"


# ── U4: contextual hints on analysis stderr ──────────────────────────────────

GHDL_NO_IEEE = 'design.vhd:10:15:error: no declaration for "std_logic"'
NVC_NO_IEEE = "** Error: no visible declaration for STD_LOGIC"
GHDL_BAD_GENERIC = 'sim_wrapper.vhd:50:7:error: generic "NUM_SWITCHES" is not an interface name'
NVC_BAD_GENERIC = "** Error: COUNTER_BITS is not a formal generic of WORK.FOO"
GHDL_PORT_UNCONNECTED = 'sim_wrapper.vhd:48:3:error: port "rst" of mode IN must be connected'
NVC_PORT_UNCONNECTED = (
    "** Error: missing actual for port RST of mode IN without a default expression"
)
GHDL_LENGTH = (
    "sim_wrapper.vhd:59:14:error: mismatching vector length; got 4, expect 10\n"
    "      led => led\n"
    "             ^"
)
NVC_LENGTH = (
    "** Fatal: (init): actual length 36 does not match formal length 32\n"
    "    > /tmp/x/sim_wrapper.vhd:62\n"
    " 62 |       seg => seg,\n"
    "    |       ^^^^^^^^^^ error occurred here"
)


class TestAddErrorHints:
    def test_ghdl_missing_ieee(self):
        out = add_error_hints(GHDL_NO_IEEE)
        assert "Hint:" in out
        assert "library ieee;" in out
        assert out.startswith(GHDL_NO_IEEE)  # original stderr preserved

    def test_nvc_missing_ieee(self):
        out = add_error_hints(NVC_NO_IEEE)
        assert "use ieee.std_logic_1164.all;" in out

    def test_ghdl_missing_generic(self):
        out = add_error_hints(GHDL_BAD_GENERIC)
        assert "Hint:" in out
        assert "NUM_SWITCHES" in out.split("Hint:")[1]

    def test_nvc_missing_generic(self):
        out = add_error_hints(NVC_BAD_GENERIC)
        assert "COUNTER_BITS" in out.split("Hint:")[1]

    def test_ghdl_unconnected_port(self):
        out = add_error_hints(GHDL_PORT_UNCONNECTED)
        assert "rst : in std_logic := '0'" in out

    def test_nvc_unconnected_port(self):
        out = add_error_hints(NVC_PORT_UNCONNECTED)
        assert "rst : in std_logic := '0'" in out

    def test_ghdl_length_mismatch_names_port_and_board(self):
        out = add_error_hints(GHDL_LENGTH, board_def=_rich_7seg_board())
        assert "port 'led'" in out
        assert "DE10-Lite" in out
        assert "NUM_LEDS=10" in out
        assert "led : out std_logic_vector(NUM_LEDS - 1 downto 0)" in out

    def test_nvc_length_mismatch_on_seg_uses_seg_snippet(self):
        out = add_error_hints(NVC_LENGTH, board_def=_rich_7seg_board())
        assert "port 'seg'" in out
        assert "NUM_SEGS=6" in out
        assert "8 * NUM_SEGS" in out

    def test_length_mismatch_without_board_still_hints(self):
        out = add_error_hints(GHDL_LENGTH)
        assert "Hint:" in out
        assert "NUM_LEDS" in out
        assert "provides" not in out  # no board numbers to quote

    def test_unrecognized_message_unchanged(self):
        msg = "some unrelated failure"
        assert add_error_hints(msg, board_def=_rich_7seg_board()) == msg

    def test_empty_message_unchanged(self):
        assert add_error_hints("") == ""


# ── U4: hints ride along real analysis failures (slow) ───────────────────────


@pytest.mark.slow
def test_fixed_width_fixture_stage3_hint_ghdl(ghdl):
    """Without a board the fixture reaches GHDL elaboration; the error gains a hint."""
    f = HDL / "bad_contract_fixed_width.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem)
    assert not ok
    assert "Hint:" in detail
    assert "NUM_LEDS" in detail


@pytest.mark.slow
def test_fixed_width_fixture_stage3_hint_nvc(nvc):
    f = HDL / "bad_contract_fixed_width.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem, simulator="nvc")
    assert not ok
    assert "Hint:" in detail
    assert "NUM_LEDS" in detail


@pytest.mark.slow
def test_extra_seg_stage3_hint_names_seg_ghdl(ghdl):
    """The 9*NUM_SEGS fixture (regex-invisible) gets the seg-specific hint from stderr."""
    f = HDL / "bad_contract_7seg_extra_seg.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=_7seg_board())
    assert not ok
    assert "Hint:" in detail
    assert "8 * NUM_SEGS" in detail


# ── NUM_RGB_LEDS (U37) ────────────────────────────────────────────────────────


def _rgb_board() -> BoardDef:
    """An Arty-shape board: 4 mono LEDs + 4 three-pin RGB LEDs (16 channels)."""
    mono = [ComponentInfo("led", "led", i) for i in range(4)]
    rgb = [ComponentInfo("led", "rgb_led", i, pins=["a", "b", "c"]) for i in range(4)]
    return BoardDef("Arty-ish", "ArtyIsh", leds=mono + rgb)


_RGB_GENERICS = (
    "    NUM_SWITCHES : positive := 4;\n"
    "    NUM_BUTTONS  : positive := 4;\n"
    "    NUM_LEDS     : positive := 4;\n"
    "    NUM_RGB_LEDS : natural  := 0;\n"
    "    COUNTER_BITS : positive := 24"
)


def test_num_rgb_leds_is_a_known_generic(tmp_path):
    """Declaring NUM_RGB_LEDS as natural passes the contract check."""
    f = _write(tmp_path, "rgb_ok", _design("rgb_ok", generics=_RGB_GENERICS))
    ok, msg = _contract(f, board_def=_rgb_board())
    assert ok, f"Unexpected rejection: {msg}"


def test_num_rgb_leds_positive_rejected_with_fix(tmp_path):
    """positive would reject the 0 that boards without RGB LEDs pass."""
    generics = _RGB_GENERICS.replace("NUM_RGB_LEDS : natural  := 0", "NUM_RGB_LEDS : positive := 1")
    f = _write(tmp_path, "rgb_pos", _design("rgb_pos", generics=generics))
    ok, msg = _contract(f, board_def=_plain_board())
    assert not ok
    assert "NUM_RGB_LEDS" in msg
    assert "natural" in msg
    assert "NUM_RGB_LEDS=0" in msg or "pass NUM_RGB_LEDS=0" in msg


def test_fixed_led_width_message_spells_out_channel_math(tmp_path):
    """led fixed at 8 bits on a 16-channel board: the message shows mono + 3 x RGB."""
    ports = (
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(7 downto 0)"
    )
    f = _write(tmp_path, "led8", _design("led8", ports=ports))
    ok, msg = _contract(f, board_def=_rgb_board())
    assert not ok
    assert "16 LED channels" in msg
    assert "3 x 4 RGB" in msg
    assert "NUM_LEDS=16" in msg


def test_wrapper_includes_rgb_generic_when_design_declares_it(tmp_path):
    out = _generate_wrapper("blinky", str(tmp_path), board_def=_rgb_board(), design_has_rgb=True)
    text = out.read_text()
    assert "NUM_RGB_LEDS     : natural  := 0;" in text
    assert "NUM_RGB_LEDS => NUM_RGB_LEDS," in text


def test_wrapper_omits_rgb_generic_by_default(tmp_path):
    out = _generate_wrapper("blinky", str(tmp_path), board_def=_rgb_board())
    assert "NUM_RGB_LEDS" not in out.read_text()
