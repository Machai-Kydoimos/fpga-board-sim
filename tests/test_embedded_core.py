"""Tests for embedded-core systems.

Stage 0 (see docs/embedded_core_system_plan.md): the vendored mx65 CPU core is
analyzed *alone* under both simulators to confirm it is self-contained and
standard-IEEE clean (no Synopsys packages, no vendor primitives) before any
system is built around it.  Later stages add ROM/generator/integration tests.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import (
    _build_sim_env,
    _GHDLBackend,
    _NVCBackend,
    analyze_vhdl,
    check_vhdl_contract,
    check_vhdl_encoding,
)
from tests.conftest import _7seg_board

PROJECT = Path(__file__).resolve().parent.parent
MX65 = PROJECT / "scripts" / "embedded_core" / "cores" / "mx65.vhd"
MX65_SYS = PROJECT / "hdl" / "mx65_walking_counter_7seg.vhd"
MX65_IRQ_SYS = PROJECT / "hdl" / "mx65_irq_counter_7seg.vhd"
FIRMWARE = PROJECT / "firmware"
MX65_BIN = FIRMWARE / "mx65_walking_counter_7seg.bin"
GENERATOR = PROJECT / "scripts" / "gen_embedded_core.py"
MX65_TOML = PROJECT / "systems" / "mx65_walking_counter_7seg.toml"
MX65_IRQ_BIN = FIRMWARE / "mx65_irq_counter_7seg.bin"
MX65_IRQ_TOML = PROJECT / "systems" / "mx65_irq_counter_7seg.toml"

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

# The run tests below require exactly this many cocotb PASSes (with FAIL=0) so a
# zero-test run can't false-pass.  Keep in sync with the number of @cocotb.test()
# functions in sim/test_cpu_walking.py.
_WALKING_TEST_COUNT = 4


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


def test_mx65_walking_present_and_clean():
    assert MX65_SYS.is_file(), f"Stage-1 system missing: {MX65_SYS}"
    ok, msg = check_vhdl_encoding(MX65_SYS)
    assert ok, msg


@pytest.mark.slow
def test_mx65_walking_elaborates_ghdl(ghdl):
    """The single-file system + generated wrapper analyzes/elaborates under GHDL."""
    ok, detail = analyze_vhdl(
        MX65_SYS,
        toplevel="mx65_walking_counter_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL elaborate failed: {detail}"


@pytest.mark.slow
def test_mx65_walking_runs_nvc(nvc):
    """The walking-counter firmware runs end-to-end under NVC (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="cpu_nvc_")
    ok, detail = analyze_vhdl(
        MX65_SYS,
        work_dir=work_dir,
        toplevel="mx65_walking_counter_7seg",
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
    run_cmd.append("--stop-time=6000000ns")  # ~146 ticks: covers the full walking suite

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_walking"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_WALKING_TEST_COUNT}" in output, (
        "cocotb walking suite did not pass under NVC.\n" + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_mx65_irq_runs_nvc(nvc):
    """The interrupt-driven variant runs the same walking suite under NVC."""
    work_dir = tempfile.mkdtemp(prefix="irq_nvc_")
    ok, detail = analyze_vhdl(
        MX65_IRQ_SYS,
        work_dir=work_dir,
        toplevel="mx65_irq_counter_7seg",
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
    run_cmd.append("--stop-time=6000000ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_walking"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_WALKING_TEST_COUNT}" in output, (
        "cocotb walking suite did not pass under NVC (interrupt-driven design).\n"
        + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_mx65_irq_runs_ghdl(ghdl):
    """The interrupt-driven variant runs the same walking suite under GHDL."""
    work_dir = tempfile.mkdtemp(prefix="irq_ghdl_")
    ok, detail = analyze_vhdl(
        MX65_IRQ_SYS,
        work_dir=work_dir,
        toplevel="mx65_irq_counter_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator="ghdl")
    run_cmd = _GHDLBackend.run_cmd("sim_wrapper", _CPU_GENERICS, plugin_lib, work_dir)
    run_cmd.append("--stop-time=6000000ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_walking"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_WALKING_TEST_COUNT}" in output, (
        "cocotb walking suite did not pass under GHDL (interrupt-driven design).\n"
        + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_mx65_walking_runs_ghdl(ghdl):
    """The walking-counter firmware runs end-to-end under GHDL (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="cpu_ghdl_")
    ok, detail = analyze_vhdl(
        MX65_SYS,
        work_dir=work_dir,
        toplevel="mx65_walking_counter_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator="ghdl")
    run_cmd = _GHDLBackend.run_cmd("sim_wrapper", _CPU_GENERICS, plugin_lib, work_dir)
    run_cmd.append("--stop-time=6000000ns")  # ~146 ticks: covers the full walking suite

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_walking"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_WALKING_TEST_COUNT}" in output, (
        "cocotb walking suite did not pass under GHDL.\n" + "\n".join(output.splitlines()[-30:])
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
    data = MX65_BIN.read_bytes()
    assert len(data) == 2048, "ROM image must be exactly 2 KB ($F800-$FFFF)"
    assert data[0x7FC] == 0x00 and data[0x7FD] == 0xF8, "RESET vector must point at $F800"
    assert data[0x7FA] == 0x2A and data[0x7FB] == 0xF9, "NMI vector -> irq_handler $F92A"
    assert data[0x7FE] == 0x2A and data[0x7FF] == 0xF9, "IRQ vector -> irq_handler $F92A"


def test_embedded_rom_matches_firmware_bin():
    """The VHDL ROM constant must reproduce the checked-in .bin verbatim."""
    from embedded_core.rom_to_vhdl import rom_aggregate

    expected = rom_aggregate(MX65_BIN.read_bytes())
    assert expected in MX65_SYS.read_text(), (
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
        ["ca65", "--cpu", "6502", "-o", str(obj), str(FIRMWARE / "mx65_walking_counter_7seg.s")],
        check=True,
    )
    subprocess.run(
        ["ld65", "-C", str(FIRMWARE / "mx65.cfg"), "-o", str(out), str(obj)],
        check=True,
    )
    assert out.read_bytes() == MX65_BIN.read_bytes(), "ca65/ld65 output drifted from the .bin"


# ── Stage 3: the generator reproduces the committed design ────────────────────


def test_generator_cli_reproduces_committed_design():
    """gen_embedded_core.py reproduces the committed .vhd byte-for-byte (drift guard)."""
    out = Path(tempfile.mkdtemp(prefix="gen_")) / MX65_SYS.name
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--cpu",
            "mx65",
            "--system",
            str(MX65_TOML),
            "--rom",
            str(MX65_BIN),
            "--out",
            str(out),
        ],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == MX65_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/mx65_walking_counter_7seg.vhd — "
        "regenerate it from systems/mx65_walking_counter_7seg.toml + the firmware .bin"
    )


def test_generator_reproduces_irq_design():
    """gen_embedded_core.py reproduces the committed interrupt-driven .vhd byte-for-byte."""
    out = Path(tempfile.mkdtemp(prefix="gen_irq_")) / MX65_IRQ_SYS.name
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--cpu",
            "mx65",
            "--system",
            str(MX65_IRQ_TOML),
            "--rom",
            str(MX65_IRQ_BIN),
            "--out",
            str(out),
        ],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == MX65_IRQ_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/mx65_irq_counter_7seg.vhd — "
        "regenerate it from systems/mx65_irq_counter_7seg.toml + the firmware .bin"
    )


def test_generated_design_passes_contract_and_lists_all_entities():
    """The emitted design names all five entities and passes the simulator contract."""
    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = system_spec.load(MX65_TOML)
    generated = emit(spec, get_plugin(spec.cpu), MX65_BIN.read_bytes())
    for entity in ("mx65", "cpu_rom", "cpu_ram", "cpu_io", "mx65_walking_counter_7seg"):
        assert f"entity {entity} is" in generated, f"generated design missing entity '{entity}'"
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / f"{spec.name}.vhd"
        probe.write_text(generated)
        ok, msg = check_vhdl_encoding(probe)
        assert ok, msg
        ok, msg = check_vhdl_contract(probe)
        assert ok, msg


def test_memory_map_drives_widths_and_decode():
    """The spec's memory map derives the ROM/RAM widths and the address decode."""
    from embedded_core import system_spec

    spec = system_spec.load(MX65_TOML)
    assert (spec.rom.addr_bits, spec.ram.addr_bits, spec.addr_high) == (11, 11, 10)
    assert spec.ram.select_literal() == '"00000"'
    assert spec.io.select_literal() == 'x"E0"'
    assert spec.rom.select_literal() == '"11111"'
    # ...and those decode literals actually appear in the generated top.
    text = MX65_SYS.read_text()
    assert f"cpu_addr(15 downto 11) = {spec.ram.select_literal()}" in text
    assert f"cpu_addr(15 downto 11) = {spec.rom.select_literal()}" in text
    assert spec.io.select_literal() in text
