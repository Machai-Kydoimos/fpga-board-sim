"""Tests for the three-stage VHDL validation pipeline.

Covers check_vhdl_encoding(), check_vhdl_contract(), and analyze_vhdl()
using the good blinky designs and the dedicated bad_*_blinky fixtures.
"""

from pathlib import Path

import pytest

from sim_bridge import _find_ghdl, analyze_vhdl, check_vhdl_contract, check_vhdl_encoding

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
