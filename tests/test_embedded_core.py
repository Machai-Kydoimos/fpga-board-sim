"""Tests for embedded-core systems.

Stage 0 (see docs/embedded_core_system_plan.md): the vendored mx65 CPU core is
analyzed *alone* under both simulators to confirm it is self-contained and
standard-IEEE clean (no Synopsys packages, no vendor primitives) before any
system is built around it.  Later stages add ROM/generator/integration tests.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import _GHDLBackend, _NVCBackend, check_vhdl_encoding

PROJECT = Path(__file__).resolve().parent.parent
MX65 = PROJECT / "scripts" / "embedded_core" / "cores" / "mx65.vhd"

# Upstream commit the vendored copy is pinned to (recorded in the file header).
MX65_PINNED_COMMIT = "d65d81d4f8031e194bd8410133b9036db7e58794"


# ── Vendored file integrity (no simulator needed) ─────────────────────────────


def test_mx65_vendored_present():
    assert MX65.is_file(), f"Vendored core missing: {MX65}"


def test_mx65_is_ascii_clean():
    """Must pass the simulator's encoding gate (plain ASCII, no BOM)."""
    ok, msg = check_vhdl_encoding(MX65)
    assert ok, msg


def test_mx65_has_entity_and_license():
    text = MX65.read_text()
    assert "entity mx65 is" in text, "entity mx65 not found"
    # MIT compliance: the permission notice must travel with the vendored core.
    assert "Permission is hereby granted" in text
    assert "Copyright (c) 2022 Steve Teal" in text
    # Provenance pin guards against unrecorded re-vendoring / hand edits.
    assert MX65_PINNED_COMMIT in text


def test_mx65_uses_only_standard_ieee():
    """No Synopsys packages -> analyzable without -fsynopsys (the flow's contract)."""
    text = MX65.read_text().lower()
    for forbidden in ("std_logic_unsigned", "std_logic_arith", "std_logic_signed"):
        assert forbidden not in text, f"core pulls in non-standard package: {forbidden}"


# ── Stage-0 smoke: analyzes alone under each simulator ────────────────────────


@pytest.mark.slow
def test_mx65_analyzes_under_ghdl(ghdl):
    d = tempfile.mkdtemp(prefix="mx65_ghdl_")
    result = subprocess.run(
        _GHDLBackend.analyze_cmd(MX65, d),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"GHDL analysis failed:\n{result.stderr}"


@pytest.mark.slow
def test_mx65_analyzes_under_nvc(nvc):
    d = tempfile.mkdtemp(prefix="mx65_nvc_")
    result = subprocess.run(
        _NVCBackend.analyze_cmd(MX65, d),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"NVC analysis failed:\n{result.stderr}"
