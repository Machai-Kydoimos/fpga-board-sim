"""Tests for the three-stage VHDL validation pipeline.

Covers check_vhdl_encoding(), check_vhdl_contract(), and analyze_vhdl()
using the good blinky designs and the dedicated bad_*_blinky fixtures.
"""

from pathlib import Path

import pytest

from fpga_sim.sim_bridge import (
    _WRAPPER_7SEG_TEMPLATE,
    _WRAPPER_TEMPLATE,
    _choose_wrapper_template,
    _find_ghdl,
    _generate_wrapper,
    analyze_vhdl,
    check_vhdl_contract,
    check_vhdl_encoding,
)

HDL = Path(__file__).resolve().parent.parent / "hdl"

GOOD_BLINKYS = [
    "blinky.vhd",
    "blinky_alt.vhd",
    "blinky_counter.vhd",
    "blinky_morse.vhd",
    "blinky_pwm.vhd",
    "blinky_walking.vhd",
]


@pytest.fixture(scope="module")
def ghdl():
    import shutil

    if not shutil.which("ghdl"):
        pytest.skip("GHDL is not installed")
    return _find_ghdl()


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
    ok, msg = check_vhdl_contract(HDL / filename)
    assert ok, f"Unexpected contract failure in {filename}: {msg}"


def test_bad_contract_fails_stage2():
    ok, msg = check_vhdl_contract(HDL / "bad_contract_blinky.vhdl")
    assert not ok, "Expected contract check to fail on mismatched entity"
    assert "mismatch" in msg.lower()


def test_bad_semantic_passes_stage2():
    ok, msg = check_vhdl_contract(HDL / "bad_semantic_blinky.vhdl")
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
    _, msg = check_vhdl_contract(HDL / "bad_contract_blinky.vhdl")
    # entity is 'blinky'; error must say so
    assert "blinky" in msg


def test_bad_contract_error_names_expected_stem():
    """Mismatch error must include the filename stem so the user knows the fix."""
    _, msg = check_vhdl_contract(HDL / "bad_contract_blinky.vhdl")
    assert "bad_contract_blinky" in msg


@pytest.mark.slow
def test_analyze_semantic_error_is_nonempty(ghdl):
    """GHDL analysis error for bad_semantic_blinky.vhdl must not be blank."""
    f = HDL / "bad_semantic_blinky.vhdl"
    _, detail = analyze_vhdl(f, toplevel=f.stem)
    assert detail.strip()  # non-empty, human-readable error


# ── 7-seg contract checks ─────────────────────────────────────────────────────


def _7seg_board() -> "object":
    from fpga_sim.board_loader import BoardDef, SevenSegDef

    return BoardDef("DE0", "DE0Platform", seven_seg=SevenSegDef(4, True, False, True, False))


def _plain_board() -> "object":
    from fpga_sim.board_loader import BoardDef

    return BoardDef("Arty", "ArtyPlatform")


def test_7seg_board_accepts_standard_design():
    """A 7-seg board must accept a standard design (segments will be dark)."""
    ok, msg = check_vhdl_contract(HDL / "blinky.vhd", board_def=_7seg_board())
    assert ok, f"Unexpected rejection: {msg}"


def test_non7seg_board_accepts_7seg_design():
    """A non-7-seg board must accept a 7-seg design (seg output ignored)."""
    ok, msg = check_vhdl_contract(HDL / "counter_7seg.vhd", board_def=_plain_board())
    assert ok, f"Unexpected rejection: {msg}"


def test_7seg_board_accepts_7seg_design():
    """A 7-seg board must accept a design with a seg port."""
    ok, _ = check_vhdl_contract(HDL / "counter_7seg.vhd", board_def=_7seg_board())
    assert ok


def test_non7seg_board_accepts_standard_design():
    """A non-7-seg board with no board_def must accept a standard design."""
    ok, _ = check_vhdl_contract(HDL / "blinky.vhd", board_def=None)
    assert ok


# ── Wrapper template selection (no GHDL required) ────────────────────────────


def test_choose_wrapper_template_non_7seg():
    """Without a 7-seg board, the standard wrapper template must be selected."""
    assert _choose_wrapper_template(None) == _WRAPPER_TEMPLATE


def test_choose_wrapper_template_7seg():
    """With a 7-seg board and a seg-bearing design, the 7-seg template is selected."""
    bd = _7seg_board()
    assert _choose_wrapper_template(bd, design_has_seg=True) == _WRAPPER_7SEG_TEMPLATE


def test_choose_wrapper_template_7seg_board_no_seg_design():
    """7-seg board + standard design must still use the standard template."""
    bd = _7seg_board()
    assert _choose_wrapper_template(bd, design_has_seg=False) == _WRAPPER_TEMPLATE


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


# ── GHDL: 7-seg design analysis ───────────────────────────────────────────────

GOOD_7SEG = ["counter_7seg.vhd"]


@pytest.mark.slow
@pytest.mark.parametrize("filename", GOOD_7SEG)
def test_good_7seg_ghdl_pass(filename, ghdl):
    """counter_7seg.vhd must analyse cleanly under GHDL with the 7-seg wrapper."""
    f = HDL / filename
    ok, detail = analyze_vhdl(f, toplevel=f.stem, board_def=_7seg_board())
    assert ok, f"GHDL failed on {filename}: {detail}"
