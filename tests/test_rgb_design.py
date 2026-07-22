"""Runs the headless cocotb suite for hdl/rgb_rainbow.vhd (U37).

Uses the product path — ``analyze_vhdl`` generates and analyzes the real
``sim_wrapper`` around the design, and the cocotb suite runs with
TOPLEVEL=sim_wrapper — because GHDL-mcode applies ``-r``-time generic
overrides to a bare toplevel's ports but not to its generic-dependent
*generate* structure (a direct ``-r rgb_rainbow -gNUM_RGB_LEDS=2`` run leaves
every ``led`` driver unelaborated, all-U). Instantiating through the wrapper
elaborates the generics ordinarily on every backend, exactly as a real run
does — which also makes this an end-to-end test of the U37 wrapper splice.
"""

import os
import subprocess
import tempfile
from pathlib import Path

from fpga_sim.board_loader import BoardDef, ComponentInfo
from fpga_sim.sim_bridge import (
    Simulator,
    _backend,
    _build_sim_env,
    _SimBackend,
    analyze_vhdl,
    check_vhdl_contract,
)

PROJECT = Path(__file__).resolve().parent.parent
DESIGN = PROJECT / "hdl" / "rgb_rainbow.vhd"

#: MONO=1 + 2 RGB sites: matches sim/test_rgb.py's channel constants.
_GENERICS = {
    "NUM_SWITCHES": "10",
    "NUM_BUTTONS": "2",
    "NUM_LEDS": "7",
    "NUM_RGB_LEDS": "2",
    "COUNTER_BITS": "10",
    "CLK_HALF_NS_INIT": "5",
}
_COCOTB_TESTS = 6
_STOP_TIME = "--stop-time=1000000ns"


def _rgb_test_board() -> BoardDef:
    """A 1-mono + 2-RGB board (7 channels), matching the test generics."""
    return BoardDef(
        name="RGB Test Board",
        class_name="RGBTestBoard",
        leds=[ComponentInfo("led", "led", 0, ["A1"])]
        + [ComponentInfo("led", "rgb_led", i, ["a", "b", "c"]) for i in range(2)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(10)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(2)],
    )


def _run_rgb_suite(simulator: Simulator, backend_cls: type[_SimBackend]) -> None:
    """Analyze + wrap + run sim/test_rgb.py against sim_wrapper."""
    work_dir = tempfile.mkdtemp(prefix=f"rgb_{simulator}_")
    ok, detail = analyze_vhdl(
        DESIGN,
        work_dir=work_dir,
        toplevel="rgb_rainbow",
        simulator=simulator,
        board_def=_rgb_test_board(),
        duty="off",  # plain pass-through wrapper; duty machinery is test_duty's job
    )
    assert ok, f"{simulator.upper()} analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator=simulator)
    if simulator == "nvc":
        # NVC bakes generics in at elaboration; GHDL applies them at -r.
        subprocess.run(
            backend_cls.elaborate_cmd("sim_wrapper", _GENERICS, work_dir),
            env=env,
            check=True,
            cwd=work_dir,
        )
    run_cmd = backend_cls.run_cmd("sim_wrapper", _GENERICS, plugin_lib, work_dir)
    run_cmd.append(_STOP_TIME)

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_rgb"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_COCOTB_TESTS}" in output, (
        f"rgb cocotb suite did not pass under {simulator.upper()}.\n"
        + "\n".join(output.splitlines()[-40:])
    )


def test_rgb_cocotb_suite_ghdl(ghdl):
    _run_rgb_suite("ghdl", _backend("ghdl"))


def test_rgb_cocotb_suite_nvc(nvc):
    _run_rgb_suite("nvc", _backend("nvc"))


def test_rgb_rainbow_elaborates_without_rgb_leds(ghdl):
    """NUM_RGB_LEDS=0: the generate loops vanish; a plain 4-LED run is clean."""
    env, _ = _build_sim_env()
    d = tempfile.mkdtemp(prefix="rgb_plain_")
    subprocess.run(
        [ghdl, "-a", "--std=08", f"--workdir={d}", str(DESIGN)],
        check=True,
        env=env,
        cwd=d,
        capture_output=True,
    )
    result = subprocess.run(
        [
            ghdl,
            "-r",
            "--std=08",
            f"--workdir={d}",
            "rgb_rainbow",
            "--stop-time=1000ns",  # default generics: NUM_RGB_LEDS=0, MONO=4
        ],
        env=env,
        cwd=d,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_rgb_rainbow_passes_the_contract_checker():
    """check_vhdl_contract accepts the design on an Arty-shape RGB board."""
    mono = [ComponentInfo("led", "led", i) for i in range(4)]
    rgb = [ComponentInfo("led", "rgb_led", i, pins=["a", "b", "c"]) for i in range(4)]
    board = BoardDef("Arty-ish", "ArtyIsh", leds=mono + rgb)
    res = check_vhdl_contract(DESIGN, board_def=board)
    assert res.ok, res.message
