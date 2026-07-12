"""Tests for embedded-core systems.

Stage 0 (see docs/embedded_core_system_plan.md): the vendored mx65 CPU core is
analyzed *alone* under both simulators to confirm it is self-contained and
standard-IEEE clean (no Synopsys packages, no vendor primitives) before any
system is built around it.  Later stages add ROM/generator/integration tests.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from embedded_core.cpu_plugin import CpuPlugin
    from embedded_core.system_spec import SystemSpec

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
REGEN_SCRIPT = PROJECT / "scripts" / "regen_embedded_cores.py"
SYSTEMS_DIR = PROJECT / "systems"
MX65_TOML = PROJECT / "systems" / "mx65_walking_counter_7seg.toml"
MX65_IRQ_BIN = FIRMWARE / "mx65_irq_counter_7seg.bin"
MX65_IRQ_TOML = PROJECT / "systems" / "mx65_irq_counter_7seg.toml"
T80_SYS = PROJECT / "hdl" / "t80_walking_counter_7seg.vhd"
T80_BIN = FIRMWARE / "t80_walking_counter_7seg.bin"
T80_TOML = PROJECT / "systems" / "t80_walking_counter_7seg.toml"
T80_IRQ_SYS = PROJECT / "hdl" / "t80_irq_counter_7seg.vhd"
T80_IRQ_BIN = FIRMWARE / "t80_irq_counter_7seg.bin"
T80_IRQ_TOML = PROJECT / "systems" / "t80_irq_counter_7seg.toml"
T80_PORTIO_SYS = PROJECT / "hdl" / "t80_portio_counter_7seg.vhd"
T80_PORTIO_BIN = FIRMWARE / "t80_portio_counter_7seg.bin"
T80_PORTIO_TOML = PROJECT / "systems" / "t80_portio_counter_7seg.toml"
T80_IRQPORTIO_SYS = PROJECT / "hdl" / "t80_irq_portio_counter_7seg.vhd"
T80_IRQPORTIO_BIN = FIRMWARE / "t80_irq_portio_counter_7seg.bin"
T80_IRQPORTIO_TOML = PROJECT / "systems" / "t80_irq_portio_counter_7seg.toml"
MX65_HELLO_SYS = PROJECT / "hdl" / "mx65_hello_7seg.vhd"
MX65_HELLO_BIN = FIRMWARE / "mx65_hello_7seg.bin"
MX65_HELLO_TOML = PROJECT / "systems" / "mx65_hello_7seg.toml"
MX65_DICE_SYS = PROJECT / "hdl" / "mx65_dice_7seg.vhd"
MX65_DICE_BIN = FIRMWARE / "mx65_dice_7seg.bin"
MX65_DICE_TOML = PROJECT / "systems" / "mx65_dice_7seg.toml"

# Upstream commit the vendored copy is pinned to (recorded in the file header).
MX65_PINNED_COMMIT = "d65d81d4f8031e194bd8410133b9036db7e58794"

# Vendored T80 (Z80) core — multi-file, analyzed/inlined leaf-first.
T80_DIR = PROJECT / "scripts" / "embedded_core" / "cores" / "t80"
T80_FILES = ("T80_Pack", "T80_ALU", "T80_MCode", "T80_Reg", "T80", "T80s")
T80_PINNED_COMMIT = "f7f776b54d67dcd6b19d3b97027dfbc6db6f14f4"

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

# Keep in sync with the number of @cocotb.test() functions in sim/test_cpu_hello.py.
_HELLO_TEST_COUNT = 1

# Keep in sync with the number of @cocotb.test() functions in sim/test_cpu_dice.py.
_DICE_TEST_COUNT = 1


def _firmware_source(spec: SystemSpec, plugin: CpuPlugin) -> str:
    """Read spec's firmware source text (the same file gen_embedded_core.py embeds)."""
    return (FIRMWARE / f"{spec.firmware}{plugin.asm_ext}").read_text()


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


# ── Vendored T80 (Z80) core: integrity + analyzes under both sims ─────────────


def test_t80_vendored_present():
    for name in T80_FILES:
        assert (T80_DIR / f"{name}.vhd").is_file(), f"Vendored T80 file missing: {name}.vhd"
    assert (T80_DIR / "PROVENANCE.md").is_file(), "T80 PROVENANCE.md missing"


def test_t80_is_ascii_clean():
    """Each vendored T80 file must pass the simulator's encoding gate."""
    for name in T80_FILES:
        ok, msg = check_vhdl_encoding(T80_DIR / f"{name}.vhd")
        assert ok, msg


def test_t80_license_and_commit_recorded():
    """The BSD-3 notice travels in each file; the pinned commit is in PROVENANCE."""
    for name in T80_FILES:
        assert "Redistribution and use" in (T80_DIR / f"{name}.vhd").read_text(), (
            f"{name}.vhd is missing its BSD-3 notice"
        )
    assert T80_PINNED_COMMIT in (T80_DIR / "PROVENANCE.md").read_text()


def test_t80_standardized_to_numeric_std():
    """The Synopsys std_logic_unsigned was swapped for the VHDL-2008 standard package."""
    for name in T80_FILES:
        text = (T80_DIR / f"{name}.vhd").read_text().lower()
        assert "std_logic_unsigned" not in text, f"{name} still uses std_logic_unsigned"
        assert "std_logic_arith" not in text, f"{name} uses std_logic_arith"
    for name in ("T80", "T80s"):
        assert "numeric_std_unsigned" in (T80_DIR / f"{name}.vhd").read_text().lower()


@pytest.mark.slow
def test_t80_analyzes_under_ghdl(ghdl):
    """All six files analyze leaf-first under GHDL --std=08 (no -fsynopsys)."""
    d = tempfile.mkdtemp(prefix="t80_ghdl_")
    for name in T80_FILES:
        result = subprocess.run(
            _GHDLBackend.analyze_cmd(T80_DIR / f"{name}.vhd", d), capture_output=True, text=True
        )
        assert result.returncode == 0, f"GHDL analysis of {name} failed:\n{result.stderr}"


@pytest.mark.slow
def test_t80_analyzes_under_nvc(nvc):
    """All six files analyze leaf-first under NVC --std=2008."""
    d = tempfile.mkdtemp(prefix="t80_nvc_")
    for name in T80_FILES:
        result = subprocess.run(
            _NVCBackend.analyze_cmd(T80_DIR / f"{name}.vhd", d), capture_output=True, text=True
        )
        assert result.returncode == 0, f"NVC analysis of {name} failed:\n{result.stderr}"


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
def test_t80_walking_runs_nvc(nvc):
    """The Z80 (T80) walking counter runs the same behavioral suite under NVC."""
    work_dir = tempfile.mkdtemp(prefix="t80_nvc_")
    ok, detail = analyze_vhdl(
        T80_SYS,
        work_dir=work_dir,
        toplevel="t80_walking_counter_7seg",
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
        "cocotb walking suite did not pass under NVC (Z80 design).\n"
        + "\n".join(output.splitlines()[-40:])
    )


@pytest.mark.slow
def test_t80_walking_runs_ghdl(ghdl):
    """The Z80 (T80) walking counter runs the same behavioral suite under GHDL."""
    work_dir = tempfile.mkdtemp(prefix="t80_ghdl_")
    ok, detail = analyze_vhdl(
        T80_SYS,
        work_dir=work_dir,
        toplevel="t80_walking_counter_7seg",
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
        "cocotb walking suite did not pass under GHDL (Z80 design).\n"
        + "\n".join(output.splitlines()[-40:])
    )


def test_generator_reproduces_t80_design():
    """gen_embedded_core.py reproduces the committed Z80 .vhd byte-for-byte."""
    out = Path(tempfile.mkdtemp(prefix="gen_t80_")) / T80_SYS.name
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--cpu",
            "t80",
            "--system",
            str(T80_TOML),
            "--rom",
            str(T80_BIN),
            "--out",
            str(out),
        ],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == T80_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/t80_walking_counter_7seg.vhd — "
        "regenerate it from systems/t80_walking_counter_7seg.toml + the firmware .bin"
    )


# ── Stage 5 (part 3): the Z80 IM 2 (vectored) interrupt design ────────────────


def test_t80_irq_firmware_vector_table():
    """The IM 2 image boots with a jp and populates two distinct ISRs in the $0100 table."""
    data = T80_IRQ_BIN.read_bytes()
    assert data[0] == 0xC3, "IM 2 image must start with a jp (0xC3)"
    timer_isr = data[0x100] | (data[0x101] << 8)  # I:vector table entry for vector $00
    input_isr = data[0x102] | (data[0x103] << 8)  # ...and for vector $02
    assert timer_isr != 0 and input_isr != 0, "IM 2 vector table at $0100 is not populated"
    assert timer_isr != input_isr, "timer and input sources must dispatch to distinct ISRs"


def test_generator_reproduces_t80_irq_design():
    """gen_embedded_core.py reproduces the committed Z80 IM 2 .vhd byte-for-byte."""
    out = Path(tempfile.mkdtemp(prefix="gen_t80irq_")) / T80_IRQ_SYS.name
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--cpu",
            "t80",
            "--system",
            str(T80_IRQ_TOML),
            "--rom",
            str(T80_IRQ_BIN),
            "--out",
            str(out),
        ],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == T80_IRQ_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/t80_irq_counter_7seg.vhd — "
        "regenerate it from systems/t80_irq_counter_7seg.toml + the firmware .bin"
    )


@pytest.mark.slow
def test_t80_irq_runs_nvc(nvc):
    """The Z80 IM 2 (vectored) interrupt design runs the walking suite under NVC."""
    work_dir = tempfile.mkdtemp(prefix="t80irq_nvc_")
    ok, detail = analyze_vhdl(
        T80_IRQ_SYS,
        work_dir=work_dir,
        toplevel="t80_irq_counter_7seg",
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
        "cocotb walking suite did not pass under NVC (Z80 IM 2 design).\n"
        + "\n".join(output.splitlines()[-40:])
    )


@pytest.mark.slow
def test_t80_irq_runs_ghdl(ghdl):
    """The Z80 IM 2 (vectored) interrupt design runs the walking suite under GHDL."""
    work_dir = tempfile.mkdtemp(prefix="t80irq_ghdl_")
    ok, detail = analyze_vhdl(
        T80_IRQ_SYS,
        work_dir=work_dir,
        toplevel="t80_irq_counter_7seg",
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
        "cocotb walking suite did not pass under GHDL (Z80 IM 2 design).\n"
        + "\n".join(output.splitlines()[-40:])
    )


# ── Stage 5 (part 4): the Z80 port-mapped-IO design ───────────────────────────


def test_portio_design_decodes_via_iorq():
    """Port mode splits memory (MREQ) and I/O (IORQ) instead of an address window."""
    text = T80_PORTIO_SYS.read_text()
    assert "sel_io  <= cpu_iorq;" in text, "IO select should come from the I/O cycle"
    assert "cpu_mreq = '1' and cpu_addr" in text, "ROM/RAM selects should be MREQ-qualified"
    assert "cpu_iorq <= (not iorq_n)" in text, "adapter should derive the I/O cycle from IORQ"


def test_generator_reproduces_t80_portio_design():
    """gen_embedded_core.py reproduces the committed Z80 port-IO .vhd byte-for-byte."""
    out = Path(tempfile.mkdtemp(prefix="gen_t80portio_")) / T80_PORTIO_SYS.name
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--cpu",
            "t80",
            "--system",
            str(T80_PORTIO_TOML),
            "--rom",
            str(T80_PORTIO_BIN),
            "--out",
            str(out),
        ],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == T80_PORTIO_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/t80_portio_counter_7seg.vhd — "
        "regenerate it from systems/t80_portio_counter_7seg.toml + the firmware .bin"
    )


@pytest.mark.slow
def test_t80_portio_runs_nvc(nvc):
    """The Z80 port-mapped-IO design runs the walking suite under NVC."""
    work_dir = tempfile.mkdtemp(prefix="t80portio_nvc_")
    ok, detail = analyze_vhdl(
        T80_PORTIO_SYS,
        work_dir=work_dir,
        toplevel="t80_portio_counter_7seg",
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
        "cocotb walking suite did not pass under NVC (Z80 port-IO design).\n"
        + "\n".join(output.splitlines()[-40:])
    )


@pytest.mark.slow
def test_t80_portio_runs_ghdl(ghdl):
    """The Z80 port-mapped-IO design runs the walking suite under GHDL."""
    work_dir = tempfile.mkdtemp(prefix="t80portio_ghdl_")
    ok, detail = analyze_vhdl(
        T80_PORTIO_SYS,
        work_dir=work_dir,
        toplevel="t80_portio_counter_7seg",
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
        "cocotb walking suite did not pass under GHDL (Z80 port-IO design).\n"
        + "\n".join(output.splitlines()[-40:])
    )


# ── Stage 5 (part 5): the Z80 capstone (IM 2 + port-mapped IO together) ────────


def test_capstone_combines_vectored_and_port():
    """The capstone carries BOTH the IM 2 vector supply and the IORQ-based IO decode."""
    text = T80_IRQPORTIO_SYS.read_text()
    assert "irq_vec <= x" in text, "missing the IM 2 vector encoder"
    assert "io_irq_vec when inta" in text, "missing the INTA vector mux"
    assert "sel_io  <= cpu_iorq;" in text, "missing the port-mapped IO decode"


def test_generator_reproduces_t80_irq_portio_design():
    """gen_embedded_core.py reproduces the committed Z80 capstone .vhd byte-for-byte."""
    out = Path(tempfile.mkdtemp(prefix="gen_t80cap_")) / T80_IRQPORTIO_SYS.name
    subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--cpu",
            "t80",
            "--system",
            str(T80_IRQPORTIO_TOML),
            "--rom",
            str(T80_IRQPORTIO_BIN),
            "--out",
            str(out),
        ],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == T80_IRQPORTIO_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/t80_irq_portio_counter_7seg.vhd — "
        "regenerate it from systems/t80_irq_portio_counter_7seg.toml + the firmware .bin"
    )


@pytest.mark.slow
def test_t80_irq_portio_runs_nvc(nvc):
    """The Z80 capstone (IM 2 + port-mapped IO) runs the walking suite under NVC."""
    work_dir = tempfile.mkdtemp(prefix="t80cap_nvc_")
    ok, detail = analyze_vhdl(
        T80_IRQPORTIO_SYS,
        work_dir=work_dir,
        toplevel="t80_irq_portio_counter_7seg",
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
        "cocotb walking suite did not pass under NVC (Z80 capstone).\n"
        + "\n".join(output.splitlines()[-40:])
    )


@pytest.mark.slow
def test_t80_irq_portio_runs_ghdl(ghdl):
    """The Z80 capstone (IM 2 + port-mapped IO) runs the walking suite under GHDL."""
    work_dir = tempfile.mkdtemp(prefix="t80cap_ghdl_")
    ok, detail = analyze_vhdl(
        T80_IRQPORTIO_SYS,
        work_dir=work_dir,
        toplevel="t80_irq_portio_counter_7seg",
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
        "cocotb walking suite did not pass under GHDL (Z80 capstone).\n"
        + "\n".join(output.splitlines()[-40:])
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


# ── The "hello" on-ramp design: static, so a short --stop-time keeps CI cheap ──


@pytest.mark.slow
def test_mx65_hello_runs_nvc(nvc):
    """The hello firmware runs end-to-end under NVC (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="hello_nvc_")
    ok, detail = analyze_vhdl(
        MX65_HELLO_SYS,
        work_dir=work_dir,
        toplevel="mx65_hello_7seg",
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
    run_cmd.append("--stop-time=100000ns")  # static design: 50us settle + 20us hold + margin

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_hello"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_HELLO_TEST_COUNT}" in output, (
        "cocotb hello suite did not pass under NVC.\n" + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_mx65_hello_runs_ghdl(ghdl):
    """The hello firmware runs end-to-end under GHDL (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="hello_ghdl_")
    ok, detail = analyze_vhdl(
        MX65_HELLO_SYS,
        work_dir=work_dir,
        toplevel="mx65_hello_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator="ghdl")
    run_cmd = _GHDLBackend.run_cmd("sim_wrapper", _CPU_GENERICS, plugin_lib, work_dir)
    run_cmd.append("--stop-time=100000ns")  # static design: 50us settle + 20us hold + margin

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_hello"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_HELLO_TEST_COUNT}" in output, (
        "cocotb hello suite did not pass under GHDL.\n" + "\n".join(output.splitlines()[-30:])
    )


# ── The dice design: LFSR peripheral + intentionally unequal ROM/RAM sizes ────


@pytest.mark.slow
def test_mx65_dice_runs_nvc(nvc):
    """The dice firmware runs end-to-end under NVC (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="dice_nvc_")
    ok, detail = analyze_vhdl(
        MX65_DICE_SYS,
        work_dir=work_dir,
        toplevel="mx65_dice_7seg",
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
    run_cmd.append("--stop-time=1500000ns")  # settle + 6 varied presses (<=4 ticks each)

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_dice"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_DICE_TEST_COUNT}" in output, (
        "cocotb dice suite did not pass under NVC.\n" + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_mx65_dice_runs_ghdl(ghdl):
    """The dice firmware runs end-to-end under GHDL (cocotb suite)."""
    work_dir = tempfile.mkdtemp(prefix="dice_ghdl_")
    ok, detail = analyze_vhdl(
        MX65_DICE_SYS,
        work_dir=work_dir,
        toplevel="mx65_dice_7seg",
        simulator="ghdl",
        board_def=_7seg_board(),
    )
    assert ok, f"GHDL analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator="ghdl")
    run_cmd = _GHDLBackend.run_cmd("sim_wrapper", _CPU_GENERICS, plugin_lib, work_dir)
    run_cmd.append("--stop-time=1500000ns")  # settle + 6 varied presses (<=4 ticks each)

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_cpu_dice"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_DICE_TEST_COUNT}" in output, (
        "cocotb dice suite did not pass under GHDL.\n" + "\n".join(output.splitlines()[-30:])
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
    assert data[0x7FA] == 0x2D and data[0x7FB] == 0xF9, "NMI vector -> irq_handler $F92D"
    assert data[0x7FE] == 0x2D and data[0x7FF] == 0xF9, "IRQ vector -> irq_handler $F92D"


def test_embedded_rom_matches_firmware_bin():
    """The VHDL ROM constant must reproduce the checked-in .bin verbatim."""
    from embedded_core.rom_to_vhdl import rom_aggregate

    expected = rom_aggregate(MX65_BIN.read_bytes())
    assert expected in MX65_SYS.read_text(), (
        "hdl ROM aggregate is out of sync with firmware/*.bin — "
        "regenerate it with scripts/embedded_core/rom_to_vhdl.py"
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "stem",
    [
        "mx65_walking_counter_7seg",
        "mx65_irq_counter_7seg",
        "mx65_hello_7seg",
        "mx65_dice_7seg",
    ],
)
def test_firmware_reassembles_with_ca65(stem):
    """ca65/ld65 reproduce the checked-in .bin from the .s (skipped if cc65 absent)."""
    if not (shutil.which("ca65") and shutil.which("ld65")):
        pytest.skip("cc65 (ca65/ld65) not installed")
    d = Path(tempfile.mkdtemp(prefix="fw_"))
    obj, out = d / "fw.o", d / "fw.bin"
    subprocess.run(
        ["ca65", "--cpu", "6502", "-o", str(obj), str(FIRMWARE / f"{stem}.s")],
        check=True,
    )
    subprocess.run(
        ["ld65", "-C", str(FIRMWARE / "mx65.cfg"), "-o", str(out), str(obj)],
        check=True,
    )
    assert out.read_bytes() == (FIRMWARE / f"{stem}.bin").read_bytes(), (
        f"ca65/ld65 output drifted from {stem}.bin"
    )


@pytest.mark.slow
@pytest.mark.parametrize(
    "stem",
    [
        "t80_walking_counter_7seg",
        "t80_irq_counter_7seg",
        "t80_portio_counter_7seg",
        "t80_irq_portio_counter_7seg",
    ],
)
def test_firmware_reassembles_with_z80asm(stem):
    """z88dk z80asm reproduces the checked-in .bin from the .asm (skipped if absent).

    Pinned invocation (z88dk z80asm 2.7.1o glues its value to -o, no space):
    ``z80asm -b -o<stem>.bin <stem>.asm``, run with the .asm copied into a temp
    dir and cwd set there -- z80asm drops .obj/.sym byproducts next to its input.
    """
    if not shutil.which("z80asm"):
        pytest.skip("z88dk z80asm not installed")
    d = Path(tempfile.mkdtemp(prefix="fw_z80_"))
    src = d / f"{stem}.asm"
    src.write_text((FIRMWARE / f"{stem}.asm").read_text())
    out = d / f"{stem}.bin"
    subprocess.run(
        ["z80asm", "-b", f"-o{out.name}", src.name],
        check=True,
        cwd=d,
    )
    assert out.read_bytes() == (FIRMWARE / f"{stem}.bin").read_bytes(), (
        f"z80asm output drifted from {stem}.bin"
    )


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


def test_generator_cli_short_form_infers_cpu_rom_out():
    """--cpu/--rom are inferred from the spec; only --system (+ a tmp --out) is required."""
    out = Path(tempfile.mkdtemp(prefix="gen_shortform_")) / MX65_SYS.name
    subprocess.run(
        [sys.executable, str(GENERATOR), "--system", str(MX65_TOML), "--out", str(out)],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == MX65_SYS.read_text(), (
        "short-form CLI (--system + --out only) drifted from hdl/mx65_walking_counter_7seg.vhd"
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


def test_generator_reproduces_hello_design():
    """gen_embedded_core.py reproduces the committed hello .vhd byte-for-byte."""
    out = Path(tempfile.mkdtemp(prefix="gen_hello_")) / MX65_HELLO_SYS.name
    subprocess.run(
        [sys.executable, str(GENERATOR), "--system", str(MX65_HELLO_TOML), "--out", str(out)],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == MX65_HELLO_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/mx65_hello_7seg.vhd — "
        "regenerate it from systems/mx65_hello_7seg.toml + the firmware .bin"
    )


def test_generator_reproduces_dice_design():
    """gen_embedded_core.py reproduces the committed dice .vhd byte-for-byte."""
    out = Path(tempfile.mkdtemp(prefix="gen_dice_")) / MX65_DICE_SYS.name
    subprocess.run(
        [sys.executable, str(GENERATOR), "--system", str(MX65_DICE_TOML), "--out", str(out)],
        check=True,
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert out.read_text() == MX65_DICE_SYS.read_text(), (
        "gen_embedded_core.py output drifted from hdl/mx65_dice_7seg.vhd — "
        "regenerate it from systems/mx65_dice_7seg.toml + the firmware .bin"
    )


def test_generated_design_passes_contract_and_lists_all_entities():
    """The emitted design names all five entities and passes the simulator contract."""
    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = system_spec.load(MX65_TOML)
    plugin = get_plugin(spec.cpu)
    generated = emit(spec, plugin, MX65_BIN.read_bytes(), _firmware_source(spec, plugin))
    for entity in ("mx65", "cpu_rom", "cpu_ram", "cpu_io", "mx65_walking_counter_7seg"):
        assert f"entity {entity} is" in generated, f"generated design missing entity '{entity}'"
    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / f"{spec.name}.vhd"
        probe.write_text(generated)
        ok, msg = check_vhdl_encoding(probe)
        assert ok, msg
        res = check_vhdl_contract(probe)
        assert res.ok, res.message


def test_memory_map_drives_widths_and_decode():
    """The spec's memory map derives the ROM/RAM widths and the address decode."""
    from embedded_core import system_spec

    spec = system_spec.load(MX65_TOML)
    assert (spec.rom.addr_bits, spec.ram.addr_bits) == (11, 11)
    assert spec.ram.select_literal() == '"00000"'
    assert spec.io.select_literal() == 'x"E0"'
    assert spec.rom.select_literal() == '"11111"'
    # ...and those decode literals actually appear in the generated top.
    text = MX65_SYS.read_text()
    assert f"cpu_addr(15 downto 11) = {spec.ram.select_literal()}" in text
    assert f"cpu_addr(15 downto 11) = {spec.rom.select_literal()}" in text
    assert spec.io.select_literal() in text


# ── Firmware listing + --prescaler-bits generation override ───────────────────


def test_firmware_listing_embedded_for_both_cores():
    """The generated file carries the firmware source as a comment above the ROM constant."""
    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    for toml, rom_bin in ((MX65_HELLO_TOML, MX65_HELLO_BIN), (T80_TOML, T80_BIN)):
        spec = system_spec.load(toml)
        plugin = get_plugin(spec.cpu)
        source = _firmware_source(spec, plugin)
        generated = emit(spec, plugin, rom_bin.read_bytes(), source)
        first_line = source.splitlines()[0].rstrip()
        assert f"-- {first_line}" in generated, f"{spec.name}: firmware listing not embedded"
        assert f"-- Firmware source: firmware/{spec.firmware}{plugin.asm_ext}" in generated, (
            f"{spec.name}: firmware listing header missing"
        )


def test_prescaler_bits_generation_override():
    """spec.generics['prescaler_bits'] (as --prescaler-bits sets it) flows into the generic."""
    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = system_spec.load(MX65_TOML)
    plugin = get_plugin(spec.cpu)
    source = _firmware_source(spec, plugin)
    rom = MX65_BIN.read_bytes()

    unmodified = emit(spec, plugin, rom, source)
    assert "PRESCALER_BITS : positive := 10" in unmodified

    spec.generics["prescaler_bits"] = 14
    overridden = emit(spec, plugin, rom, source)
    assert "PRESCALER_BITS : positive := 14" in overridden


# ── Memory-map validation: power-of-two, alignment, range, overlap, ROM fit ────


@pytest.mark.slow
def test_unequal_rom_ram_sizes_analyze_under_ghdl(ghdl):
    """A spec with independently-sized ROM/RAM regions analyzes cleanly (F11 proof).

    Uses the committed walking-counter .bin only to exercise the address
    widths/decode -- its vectors assume ROM at $F800, so this design is never
    *run*, only analyzed. Phase 6 adds a committed, runnable unequal-size design.
    """
    import dataclasses

    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = dataclasses.replace(
        system_spec.load(MX65_TOML),
        name="mx65_unequal_rom_ram_test",
        rom=system_spec.MemoryRegion(name="rom", base=0xF000, size=0x1000),  # 4 KB (was 2 KB)
    )
    assert spec.rom.addr_bits != spec.ram.addr_bits, "test spec must actually have unequal sizes"

    plugin = get_plugin(spec.cpu)
    generated = emit(spec, plugin, MX65_BIN.read_bytes(), _firmware_source(spec, plugin))
    d = tempfile.mkdtemp(prefix="unequal_ghdl_")
    probe = Path(d) / f"{spec.name}.vhd"
    probe.write_text(generated)
    result = subprocess.run(_GHDLBackend.analyze_cmd(probe, d), capture_output=True, text=True)
    assert result.returncode == 0, f"GHDL analysis failed:\n{result.stderr}"


def test_spec_rejects_non_power_of_two_region_size():
    """A region size that isn't a power of two fails eagerly at spec construction."""
    import dataclasses

    from embedded_core import system_spec

    spec = system_spec.load(MX65_TOML)
    with pytest.raises(ValueError) as exc_info:
        dataclasses.replace(spec, io=system_spec.MemoryRegion(name="io", base=0xE000, size=0x300))
    assert "io" in str(exc_info.value) and "power of two" in str(exc_info.value)


def test_spec_rejects_misaligned_region_base():
    """A region base that isn't a multiple of its own size fails with a named error."""
    import dataclasses

    from embedded_core import system_spec

    spec = system_spec.load(MX65_TOML)
    with pytest.raises(ValueError) as exc_info:
        dataclasses.replace(spec, io=system_spec.MemoryRegion(name="io", base=0xE080, size=0x100))
    assert "io" in str(exc_info.value) and "not aligned" in str(exc_info.value)


def test_port_io_transport_exempts_io_region_from_checks():
    """With io_transport='port', the io region is skipped by alignment/overlap checks.

    The committed t80_portio spec already relies on this (io 0x0000/0x100 sits
    "under" rom 0x0000/0x0800 -- see systems/t80_portio_counter_7seg.toml); this
    test makes the exemption itself the thing under test, rather than relying on
    that spec loading successfully as incidental proof.
    """
    import dataclasses

    from embedded_core import system_spec

    memory_spec = system_spec.load(
        MX65_TOML
    )  # io_transport defaults to "memory"; rom = 0xF800/0x0800
    io_over_rom = system_spec.MemoryRegion(name="io", base=0xF800, size=0x100)  # == rom.base
    with pytest.raises(ValueError, match="overlap"):
        dataclasses.replace(memory_spec, io=io_over_rom)

    port_spec = system_spec.load(T80_PORTIO_TOML)  # rom = 0x0000/0x0800
    io_over_that_rom = system_spec.MemoryRegion(name="io", base=0x0000, size=0x100)  # == rom.base
    dataclasses.replace(port_spec, io=io_over_that_rom)  # must not raise: io exempt in port mode


def test_spec_rejects_overlapping_regions():
    """Two regions occupying the same bytes fail with both region names in the error."""
    import dataclasses

    from embedded_core import system_spec

    spec = system_spec.load(MX65_TOML)  # rom = 0xF800/0x0800
    with pytest.raises(ValueError) as exc_info:
        dataclasses.replace(
            spec, ram=system_spec.MemoryRegion(name="ram", base=0xF800, size=0x0800)
        )
    message = str(exc_info.value)
    assert "ram" in message and "rom" in message and "overlap" in message


def test_spec_rejects_out_of_range_region():
    """A region past the 64 KB address space fails even though it is aligned."""
    import dataclasses

    from embedded_core import system_spec

    spec = system_spec.load(MX65_TOML)
    with pytest.raises(ValueError) as exc_info:
        dataclasses.replace(spec, io=system_spec.MemoryRegion(name="io", base=0x10000, size=0x100))
    assert "io" in str(exc_info.value) and "address space" in str(exc_info.value)


def test_spec_load_rejects_unknown_top_level_key():
    """A typo'd top-level key (e.g. irq_moed) fails loudly instead of being silently ignored."""
    from embedded_core import system_spec

    text = MX65_TOML.read_text().replace('cpu = "mx65"\n', 'cpu = "mx65"\nirq_moed = "simple"\n')
    tmp = Path(tempfile.mkdtemp(prefix="spec_")) / "bad.toml"
    tmp.write_text(text)
    with pytest.raises(ValueError, match="irq_moed"):
        system_spec.load(tmp)


def test_spec_load_rejects_unknown_generic_key():
    """A typo'd key inside [generics] fails loudly instead of being silently ignored."""
    from embedded_core import system_spec

    text = MX65_TOML.read_text().replace("[generics]\n", "[generics]\nbogus_generic = 1\n")
    tmp = Path(tempfile.mkdtemp(prefix="spec_")) / "bad.toml"
    tmp.write_text(text)
    with pytest.raises(ValueError, match="bogus_generic"):
        system_spec.load(tmp)


def test_emit_rejects_oversized_rom_image():
    """A firmware image larger than the rom region's size fails, naming both sizes."""
    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = system_spec.load(MX65_TOML)  # rom.size == 0x0800
    oversized = bytes(spec.rom.size + 1)
    with pytest.raises(ValueError) as exc_info:
        emit(spec, get_plugin(spec.cpu), oversized, "")  # rejected before firmware_source is used
    message = str(exc_info.value)
    assert str(spec.rom.size + 1) in message and str(spec.rom.size) in message


def test_emit_rejects_boots_at_zero_core_with_rom_not_at_zero():
    """A boots-at-zero core (T80) with rom.base != 0 fails at emit time, not load time."""
    import dataclasses

    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = dataclasses.replace(
        system_spec.load(T80_TOML),
        rom=system_spec.MemoryRegion(name="rom", base=0x0800, size=0x0800),
    )
    with pytest.raises(ValueError, match="boots at"):
        emit(spec, get_plugin(spec.cpu), T80_BIN.read_bytes(), "")


def test_emit_rejects_vector_fetch_core_with_rom_not_at_top():
    """A vector-fetch core (mx65) whose rom region doesn't end at 0x10000 fails at emit time."""
    import dataclasses

    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = dataclasses.replace(
        system_spec.load(MX65_TOML),
        rom=system_spec.MemoryRegion(name="rom", base=0xF000, size=0x0800),
    )
    with pytest.raises(ValueError, match="top of memory"):
        emit(spec, get_plugin(spec.cpu), MX65_BIN.read_bytes(), "")


# ── Spec axes: interrupt mode + IO transport ──────────────────────────────────


def test_spec_axes_defaults_and_modes():
    """The polled design defaults to none/memory; the IRQ design uses simple/memory."""
    from embedded_core import system_spec

    walking = system_spec.load(MX65_TOML)
    assert walking.irq_mode == "none" and not walking.irq_driven
    assert walking.io_transport == "memory"

    irq = system_spec.load(MX65_IRQ_TOML)
    assert irq.irq_mode == "simple" and irq.irq_driven
    assert irq.io_transport == "memory"


def test_spec_peripherals_default_empty_and_dice_lists_lfsr():
    """peripherals defaults to () for every existing design; the dice spec lists 'lfsr'."""
    from embedded_core import system_spec

    walking = system_spec.load(MX65_TOML)
    assert walking.peripherals == ()

    dice = system_spec.load(MX65_DICE_TOML)
    assert dice.peripherals == ("lfsr",)


def test_spec_rejects_unknown_axis_values():
    """__post_init__ validates both axes, so bad values fail fast on construction."""
    import dataclasses

    from embedded_core import system_spec

    spec = system_spec.load(MX65_TOML)
    with pytest.raises(ValueError):
        dataclasses.replace(spec, irq_mode="fancy")
    with pytest.raises(ValueError):
        dataclasses.replace(spec, io_transport="spi")
    with pytest.raises(ValueError):
        dataclasses.replace(spec, peripherals=("bogus",))


def test_emit_rejects_unsupported_axis_combos():
    """mx65 supports neither vectored interrupts nor port-mapped IO (both Z80-only)."""
    import dataclasses

    from embedded_core import system_spec
    from embedded_core.cpu_plugin import get_plugin
    from embedded_core.emitter import emit

    spec = system_spec.load(MX65_TOML)
    plugin = get_plugin(spec.cpu)
    rom = MX65_BIN.read_bytes()
    # the mx65 core has no port-mapped-IO adapter (only the Z80/T80 does).
    with pytest.raises(ValueError):
        emit(dataclasses.replace(spec, io_transport="port"), plugin, rom, "")
    # the mx65 core has no vectored-interrupt adapter (only the Z80/T80 does).
    with pytest.raises(ValueError):
        emit(dataclasses.replace(spec, irq_mode="vectored"), plugin, rom, "")


# ── scripts/regen_embedded_cores.py: the one-command regen/check loop ─────────


def test_regen_script_check_mode_clean_tree():
    """In check mode on a clean checkout, every systems/*.toml reports OK and exit is 0."""
    result = subprocess.run(
        [sys.executable, str(REGEN_SCRIPT)],
        cwd=PROJECT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    system_count = len(list(SYSTEMS_DIR.glob("*.toml")))
    lines = [line for line in result.stdout.splitlines() if line]
    assert len(lines) == system_count, f"expected {system_count} systems reported, got: {lines}"
    assert all(line.endswith(": OK") for line in lines), result.stdout
