"""Tests for GHDL availability and VHDL analysis."""
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


