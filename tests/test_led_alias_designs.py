"""Run a design written to an LED's upstream alias, end to end (U56 Phase 6).

One board per alias shape, from the real board data: the matcher binds the
design's alias ports, ``analyze_vhdl`` emits and analyzes the native wrapper with
its channel map, and ``sim/test_led_aliases.py`` reads the boundary ``led`` --
under both GHDL and NVC.

* mono + mono: Amaranth iCEBreaker, ``led_r``/``led_g`` = ``led`` 0/1;
* mono names on an RGB LED: LiteX OrangeCrab, ``user_led`` 0-2 = r, g, b;
* three names on one RGB LED: LiteX iCE40UP5K EVN, ``user_ledr_n``/``_g_``/``_b_``.
"""

from __future__ import annotations

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
DESIGNS = PROJECT / "tests" / "fixtures" / "led_aliases"

#: (toplevel, board JSON, boundary led MSB first).
_CASES = [
    ("alias_icebreaker", "amaranth-boards/icebreaker.json", "01"),
    ("alias_orangecrab", "litex-boards/gsd_orangecrab.json", "110"),
    ("alias_ice40up5k", "litex-boards/lattice_ice40up5k_evn.json", "001"),
]


def _run(toplevel: str, board_rel: str, expect: str, sim: Simulator) -> None:
    backend_cls = _backend(sim)
    design = DESIGNS / f"{toplevel}.vhd"
    bd = BoardDef.from_json((PROJECT / "boards" / board_rel).read_text(encoding="utf-8"))
    res = check_vhdl_contract(design, board_def=bd)
    assert res.ok and res.match is not None, f"{toplevel} did not match: {res.message}"
    assert len(expect) == bd.num_led_channels

    work_dir = tempfile.mkdtemp(prefix=f"alias_{sim}_")
    ok, detail = analyze_vhdl(
        design, work_dir=work_dir, toplevel=toplevel, simulator=sim, board_def=bd, match=res.match
    )
    assert ok, f"{sim.upper()} analyze failed: {detail}"

    generics = {
        "NUM_SWITCHES": str(max(1, len(bd.switches))),
        "NUM_BUTTONS": str(max(1, len(bd.buttons))),
        "NUM_LEDS": str(bd.num_led_channels),
        "CLK_HALF_NS_INIT": "5",
    }
    env, plugin_lib = _build_sim_env(simulator=sim)
    if sim == "nvc":  # NVC bakes generics in at elaboration; GHDL applies them at -r
        subprocess.run(
            backend_cls.elaborate_cmd("sim_wrapper", generics, work_dir),
            env=env,
            check=True,
            cwd=work_dir,
        )
    run_cmd = backend_cls.run_cmd("sim_wrapper", generics, plugin_lib, work_dir)
    run_cmd.append("--stop-time=1000ns")
    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_led_aliases"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["ALIAS_EXPECT_LED"] = expect
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")
    result = subprocess.run(
        run_cmd,
        env=run_env,
        cwd=work_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and "PASS=1" in output, (
        f"{toplevel} under {sim.upper()}:\n" + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
@pytest.mark.parametrize(("toplevel", "board_rel", "expect"), _CASES)
def test_alias_design_ghdl(ghdl, toplevel, board_rel, expect):
    _run(toplevel, board_rel, expect, "ghdl")


@pytest.mark.slow
@pytest.mark.parametrize(("toplevel", "board_rel", "expect"), _CASES)
def test_alias_design_nvc(nvc, toplevel, board_rel, expect):
    _run(toplevel, board_rel, expect, "nvc")
