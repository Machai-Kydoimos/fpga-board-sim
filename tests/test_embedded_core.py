"""Tests for embedded-core systems.

Stage 0 (see docs/embedded_core_system_plan.md): the vendored mx65 CPU core is
analyzed *alone* under both simulators to confirm it is self-contained and
standard-IEEE clean (no Synopsys packages, no vendor primitives) before any
system is built around it.  Later stages add ROM/generator/integration tests.
"""

import os
import shutil
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
FIRMWARE = PROJECT / "firmware"
FW_BIN = FIRMWARE / "cpu_walking_counter_7seg.bin"

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


# ── Firmware: ca65/ld65 ROM image + embedding ─────────────────────────────────


def test_rom_aggregate_is_sparse():
    """rom_to_vhdl emits non-zero bytes and lets zeros fall through to `others`."""
    from embedded_core.rom_to_vhdl import rom_aggregate

    body = rom_aggregate(bytes([0x78, 0x00, 0xD8]))
    assert '16#000# => x"78"' in body
    assert '16#002# => x"D8"' in body
    assert "16#001#" not in body  # zero byte omitted
    assert 'others => x"00"' in body


def test_firmware_bin_shape():
    """The assembled image is a 2 KB ROM with valid reset/IRQ/NMI vectors."""
    data = FW_BIN.read_bytes()
    assert len(data) == 2048, "ROM image must be exactly 2 KB ($F800-$FFFF)"
    assert data[0x7FC] == 0x00 and data[0x7FD] == 0xF8, "RESET vector must point at $F800"
    assert data[0x7FA] == 0x19 and data[0x7FB] == 0xF8, "NMI vector must point at $F819"
    assert data[0x7FE] == 0x19 and data[0x7FF] == 0xF8, "IRQ/BRK vector must point at $F819"


def test_embedded_rom_matches_firmware_bin():
    """The VHDL ROM constant must reproduce the checked-in .bin verbatim."""
    from embedded_core.rom_to_vhdl import rom_aggregate

    expected = rom_aggregate(FW_BIN.read_bytes())
    assert expected in CPU_SYS.read_text(), (
        "hdl ROM aggregate is out of sync with firmware/*.bin — "
        "regenerate it with scripts/embedded_core/rom_to_vhdl.py"
    )


@pytest.mark.slow
def test_firmware_reassembles_with_ca65():
    """ca65/ld65 reproduce the checked-in .bin from the .s (skipped if cc65 absent)."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 (ca65/ld65) not installed")
    d = Path(tempfile.mkdtemp(prefix="fw_"))
    obj, out = d / "fw.o", d / "fw.bin"
    subprocess.run(
        ["ca65", "--cpu", "6502", "-o", str(obj), str(FIRMWARE / "cpu_walking_counter_7seg.s")],
        check=True,
    )
    subprocess.run(
        ["ld65", "-C", str(FIRMWARE / "cpu_6502.cfg"), "-o", str(out), str(obj)],
        check=True,
    )
    assert out.read_bytes() == FW_BIN.read_bytes(), "ca65/ld65 output drifted from the .bin"
