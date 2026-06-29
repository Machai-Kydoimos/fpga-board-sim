"""Tests for embedded-core systems.

Stage 0 (see docs/embedded_core_system_plan.md): the vendored mx65 CPU core is
analyzed *alone* under both simulators to confirm it is self-contained and
standard-IEEE clean (no Synopsys packages, no vendor primitives) before any
system is built around it.  Later stages add ROM/generator/integration tests.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import (
    _build_sim_env,
    _GHDLBackend,
    _NVCBackend,
    analyze_vhdl,
    check_vhdl_encoding,
)
from tests.conftest import _7seg_board

PROJECT = Path(__file__).resolve().parent.parent
MX65 = PROJECT / "scripts" / "embedded_core" / "cores" / "mx65.vhd"
CPU_SYS = PROJECT / "hdl" / "cpu_walking_counter_7seg.vhd"

# Upstream commit the vendored copy is pinned to (recorded in the file header).
MX65_PINNED_COMMIT = "d65d81d4f8031e194bd8410133b9036db7e58794"

# Resource generics for the Stage-1 system (>=4 LEDs to exercise the LED reg,
# >=2 digits to exercise the per-digit indexed write loop).
_CPU_GENERICS = {
    "NUM_SWITCHES": "4",
    "NUM_BUTTONS": "4",
    "NUM_LEDS": "4",
    "NUM_SEGS": "4",
    "COUNTER_BITS": "24",
}


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


# ── Stage 1: the single-file CPU system elaborates + runs ─────────────────────


def test_cpu_system_present_and_clean():
    assert CPU_SYS.is_file(), f"Stage-1 system missing: {CPU_SYS}"
    ok, msg = check_vhdl_encoding(CPU_SYS)
    assert ok, msg


@pytest.mark.slow
def test_cpu_system_elaborates_ghdl(ghdl):
    """The single-file system + generated wrapper analyzes/elaborates under GHDL."""
    ok, detail = analyze_vhdl(
        CPU_SYS,
        toplevel="cpu_walking_counter_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL elaborate failed: {detail}"


@pytest.mark.slow
def test_cpu_system_runs_nvc(nvc):
    """Static firmware drives LED0 + every digit='0' under NVC (cocotb smoke)."""
    work_dir = tempfile.mkdtemp(prefix="cpu_nvc_")
    ok, detail = analyze_vhdl(
        CPU_SYS,
        work_dir=work_dir,
        toplevel="cpu_walking_counter_7seg",
        simulator="nvc",
        board_def=_7seg_board(),
    )
    assert ok, f"NVC analyze failed: {detail}"

    env, vhpi_lib = _build_sim_env(simulator="nvc")
    subprocess.run(
        _NVCBackend.elaborate_cmd("sim_wrapper", _CPU_GENERICS, work_dir),
        env=env,
        check=True,
        cwd=work_dir,
    )
    run_cmd = _NVCBackend.run_cmd("sim_wrapper", _CPU_GENERICS, vhpi_lib, work_dir)
    run_cmd.append("--stop-time=100000ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_smoke"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and "PASS=" in output, (
        "cocotb Stage-1 smoke did not pass under NVC.\n" + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_cpu_system_runs_ghdl(ghdl):
    """Static firmware drives LED0 + every digit='0' under GHDL (cocotb smoke)."""
    work_dir = tempfile.mkdtemp(prefix="cpu_ghdl_")
    ok, detail = analyze_vhdl(
        CPU_SYS,
        work_dir=work_dir,
        toplevel="cpu_walking_counter_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator="ghdl")
    run_cmd = _GHDLBackend.run_cmd("sim_wrapper", _CPU_GENERICS, plugin_lib, work_dir)
    run_cmd.append("--stop-time=100000ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_smoke"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and "PASS=" in output, (
        "cocotb Stage-1 smoke did not pass under GHDL.\n" + "\n".join(output.splitlines()[-30:])
    )
