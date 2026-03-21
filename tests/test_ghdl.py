"""Tests for GHDL availability and VHDL analysis."""
import tempfile
import os
from pathlib import Path
import pytest
from sim_bridge import analyze_vhdl, _find_ghdl

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ghdl():
    return _find_ghdl()


def test_ghdl_found(ghdl):
    assert Path(ghdl).name.startswith("ghdl"), f"Unexpected binary: {ghdl}"


def test_blinky_vhd_exists():
    assert (PROJECT / "hdl" / "blinky.vhd").is_file()


def test_blinky_analyzes_ok(ghdl):
    blinky = PROJECT / "hdl" / "blinky.vhd"
    ok, detail = analyze_vhdl(str(blinky))
    assert ok, f"GHDL analysis failed: {detail}"


def test_bad_vhdl_fails_analysis():
    with tempfile.NamedTemporaryFile(suffix=".vhd", delete=False, mode="w") as f:
        f.write("this is not valid VHDL;\n")
        name = f.name
    try:
        ok, detail = analyze_vhdl(name)
        assert not ok, "Expected analysis to fail on invalid VHDL"
    finally:
        os.unlink(name)
