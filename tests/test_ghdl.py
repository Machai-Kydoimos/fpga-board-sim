"""Tests for GHDL availability and VHDL analysis."""

from pathlib import Path

import pytest

from fpga_sim.sim_bridge import analyze_vhdl

pytestmark = pytest.mark.slow

PROJECT = Path(__file__).resolve().parent.parent


def test_ghdl_found(ghdl):
    assert Path(ghdl).name.startswith("ghdl"), f"Unexpected binary: {ghdl}"


def test_blinky_vhd_exists():
    assert (PROJECT / "hdl" / "blinky.vhd").is_file()


def test_blinky_analyzes_ok(ghdl):
    blinky = PROJECT / "hdl" / "blinky.vhd"
    ok, detail = analyze_vhdl(str(blinky))
    assert ok, f"GHDL analysis failed: {detail}"
