"""Tests for the three-stage VHDL validation pipeline.

Covers check_vhdl_encoding(), check_vhdl_contract(), and analyze_vhdl()
using the good blinky designs and the dedicated bad_*_blinky fixtures.
"""
from pathlib import Path
import pytest
from sim_bridge import analyze_vhdl, check_vhdl_encoding, check_vhdl_contract, _find_ghdl

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


def test_bad_ghdl_passes_stage1():
    ok, msg = check_vhdl_encoding(HDL / "bad_ghdl_blinky.vhdl")
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


def test_bad_ghdl_passes_stage2():
    ok, msg = check_vhdl_contract(HDL / "bad_ghdl_blinky.vhdl")
    assert ok, f"Unexpected contract failure: {msg}"


# ── Stage 3: GHDL analysis + elaboration ─────────────────────────────────────

@pytest.mark.parametrize("filename", GOOD_BLINKYS)
def test_good_blinky_ghdl_pass(filename, ghdl):
    f = HDL / filename
    ok, detail = analyze_vhdl(f, toplevel=f.stem)
    assert ok, f"GHDL failed on {filename}: {detail}"


def test_bad_ghdl_fails_stage3(ghdl):
    f = HDL / "bad_ghdl_blinky.vhdl"
    ok, detail = analyze_vhdl(f, toplevel=f.stem)
    assert not ok, "Expected GHDL analysis to fail on bad_ghdl_blinky.vhdl"
    assert "unsigned" in detail.lower()
