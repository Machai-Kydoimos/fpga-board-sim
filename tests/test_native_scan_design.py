"""Runs the headless cocotb suite for the U22 native scan designs (Phase E).

End-to-end over the product path and the *real* Phase D board data: the
matcher recognizes ``hdl/native/{nexys4ddr,basys3}_scan.vhd`` against the
regenerated ``boards/digilent-xdc`` JSONs, ``analyze_vhdl`` emits + analyzes
the native scan wrapper in **Full duty mode**, and ``sim/test_native_scan.py``
asserts the measured duties (1/N scan brightness, dp gating, lamp test)
through the wrapper's U9 accumulators — under both GHDL and NVC.

Generics passed at elaborate/run mirror the native wrapper's *baked defaults*
(the board's resource counts), keeping the analyze-time and run-time
structures identical — the mcode consistency rule.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.board_loader import BoardDef
from fpga_sim.sim_bridge import (
    Simulator,
    _backend,
    _build_sim_env,
    analyze_vhdl,
    check_vhdl_contract,
)

PROJECT = Path(__file__).resolve().parent.parent
NATIVE = PROJECT / "hdl" / "native"

_COCOTB_TESTS = 4
_STOP_TIME = "--stop-time=2000000ns"

#: (toplevel, board JSON, digits, boundary LED channels).  NUM_LEDS is the
#: board's channel count (Nexys: 16 mono + 2x3 RGB the design leaves dark).
_DESIGNS = [
    ("nexys4ddr_scan", "digilent-xdc/nexys_4_ddr.json", 8, 22),
    ("basys3_scan", "digilent-xdc/basys_3.json", 4, 16),
]


def _generics(digits: int, led_channels: int) -> dict[str, str]:
    return {
        "NUM_SWITCHES": "16",
        "NUM_BUTTONS": "5",
        "NUM_LEDS": str(led_channels),
        "NUM_SEGS": str(digits),
        "CLK_HALF_NS_INIT": "5",  # 10 ns period: 128-clock digit slot = 1.28 us
    }


def _run_scan_suite(toplevel: str, board_rel: str, digits: int, leds: int, sim: Simulator) -> None:
    """Match + analyze (Full duty) + run sim/test_native_scan.py against sim_wrapper."""
    backend_cls = _backend(sim)
    design = NATIVE / f"{toplevel}.vhd"
    bd = BoardDef.from_json((PROJECT / "boards" / board_rel).read_text())

    res = check_vhdl_contract(design, board_def=bd)
    assert res.ok and res.match is not None, f"{toplevel} did not match: {res.message}"
    seg = res.match.seven_seg
    assert seg is not None and seg.style == "scan" and seg.num_digits == digits

    work_dir = tempfile.mkdtemp(prefix=f"scan_{sim}_")
    ok, detail = analyze_vhdl(
        design,
        work_dir=work_dir,
        toplevel=toplevel,
        simulator=sim,
        board_def=bd,
        match=res.match,
        duty="full",  # the suite reads the U9 seg accumulators
    )
    assert ok, f"{sim.upper()} analyze failed: {detail}"

    generics = _generics(digits, leds)
    env, plugin_lib = _build_sim_env(simulator=sim)
    if sim == "nvc":
        # NVC bakes generics in at elaboration; GHDL applies them at -r.
        subprocess.run(
            backend_cls.elaborate_cmd("sim_wrapper", generics, work_dir),
            env=env,
            check=True,
            cwd=work_dir,
        )
    run_cmd = backend_cls.run_cmd("sim_wrapper", generics, plugin_lib, work_dir)
    run_cmd.append(_STOP_TIME)

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_native_scan"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_COCOTB_TESTS}" in output, (
        f"native scan cocotb suite did not pass for {toplevel} under {sim.upper()}.\n"
        + "\n".join(output.splitlines()[-40:])
    )


@pytest.mark.slow
@pytest.mark.parametrize(("toplevel", "board_rel", "digits", "leds"), _DESIGNS)
def test_scan_cocotb_suite_ghdl(ghdl, toplevel, board_rel, digits, leds):
    _run_scan_suite(toplevel, board_rel, digits, leds, "ghdl")


@pytest.mark.slow
@pytest.mark.parametrize(("toplevel", "board_rel", "digits", "leds"), _DESIGNS)
def test_scan_cocotb_suite_nvc(nvc, toplevel, board_rel, digits, leds):
    _run_scan_suite(toplevel, board_rel, digits, leds, "nvc")
