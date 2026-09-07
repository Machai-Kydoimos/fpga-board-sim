"""The lab-shaped reference designs (U52): they build everywhere, and they work.

Two different claims, tested two different ways.

*They build everywhere.* Each generic-contract design is analyzed and
elaborated against boards chosen to break assumptions -- a board with no
switches, one with no buttons, one with a single 7-segment digit -- because a
design that indexes `sw(3)` is only wrong on the board that has one switch, and
that board is never the one you happen to try.

*They work.* The decoder and the FSM get real cocotb runs on both engines. The
FSM's tests are deliberately not all happy-path: a lock that opens on the right
sequence *and* on a wrong one passes a happy-path test and is still broken.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.board_loader import BoardDef, SevenSegDef
from fpga_sim.sim_bridge import _build_sim_env, _GHDLBackend, _NVCBackend, analyze_vhdl
from fpga_sim.vhdl_contract import check_vhdl_contract

PROJECT = Path(__file__).resolve().parent.parent
HDL = PROJECT / "hdl"

#: The five new generic-contract designs, and whether each drives a display.
LAB_DESIGNS = [
    ("gates_mux", False),
    ("running_light", False),
    ("code_lock_fsm", False),
    ("hex_decoder_7seg", True),
    ("countdown_7seg", True),
]

_GENERICS = {
    "NUM_SWITCHES": "8",  # the decoder reads a whole byte
    "NUM_BUTTONS": "4",
    "NUM_LEDS": "8",
    "NUM_SEGS": "4",
    "COUNTER_BITS": "17",
}

# Keep in sync with the cocotb modules: a run that silently executes zero tests
# still prints FAIL=0, so the count is what makes the assertion mean anything.
_HEX_DECODER_TESTS = 2
_CODE_LOCK_TESTS = 3
_GATES_MUX_TESTS = 2
_COUNTDOWN_TESTS = 2
_RUNNING_LIGHT_TESTS = 1


def _board(*, digits: int = 4, switches: int = 8, buttons: int = 4, leds: int = 8) -> BoardDef:
    """A synthetic board with the resource counts a test wants to stress."""
    seven = SevenSegDef(digits, True, False, True, False) if digits else None
    board = BoardDef("Bench", "BenchPlatform", seven_seg=seven)
    board.switches = [object()] * switches  # type: ignore[list-item]
    board.buttons = [object()] * buttons  # type: ignore[list-item]
    return board


@pytest.mark.parametrize(("stem", "_has_seg"), LAB_DESIGNS)
def test_the_design_file_exists(stem, _has_seg):
    assert (HDL / f"{stem}.vhd").is_file()


@pytest.mark.parametrize(("stem", "has_seg"), LAB_DESIGNS)
def test_it_satisfies_the_generic_contract(stem, has_seg):
    """Every one of these runs on every board, which is the point of them."""
    res = check_vhdl_contract(HDL / f"{stem}.vhd", board_def=_board())
    assert res.ok, res.message
    assert res.match is None, f"{stem} matched a board convention; it is a generic design"


@pytest.mark.slow
@pytest.mark.parametrize(("stem", "has_seg"), LAB_DESIGNS)
@pytest.mark.parametrize("digits", [1, 8])
def test_it_elaborates_on_one_digit_and_on_eight(stem, has_seg, digits, ghdl):
    """A display-driving design must not assume how many digits it has."""
    work_dir = tempfile.mkdtemp(prefix=f"lab_{stem}_")
    ok, detail = analyze_vhdl(
        HDL / f"{stem}.vhd",
        work_dir=work_dir,
        toplevel=stem,
        simulator="ghdl",
        board_def=_board(digits=digits),
    )
    assert ok, f"{stem} failed on a {digits}-digit board: {detail}"


@pytest.mark.slow
@pytest.mark.parametrize(("stem", "has_seg"), LAB_DESIGNS)
def test_it_elaborates_with_no_switches_and_no_buttons(stem, has_seg, ghdl):
    """The floor case: the wrapper hands a one-bit dummy bank to each input."""
    work_dir = tempfile.mkdtemp(prefix=f"lab_{stem}_bare_")
    ok, detail = analyze_vhdl(
        HDL / f"{stem}.vhd",
        work_dir=work_dir,
        toplevel=stem,
        simulator="ghdl",
        board_def=_board(switches=0, buttons=0, leds=1, digits=0),
    )
    assert ok, f"{stem} failed on a board with no inputs: {detail}"


def _run_cocotb(
    design: str,
    module: str,
    engine: str,
    expected: int,
    stop_ns: int,
    *,
    has_seg: bool,
    generics: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
) -> None:
    """Analyze, elaborate and run *module* against *design*; require every test to pass.

    *has_seg* drops ``NUM_SEGS`` for a design without a display: the generated
    wrapper only declares that generic when the design has a ``seg`` port, and
    GHDL rejects an unknown ``-g`` outright (``no generic "num_segs" for -g``)
    where NVC merely warns -- so passing it unconditionally would have made the
    two engines disagree about whether the test even ran.
    """
    generics = dict(generics or _GENERICS)
    if not has_seg:
        generics.pop("NUM_SEGS", None)
    work_dir = tempfile.mkdtemp(prefix=f"{design}_{engine}_")
    ok, detail = analyze_vhdl(
        HDL / f"{design}.vhd",
        work_dir=work_dir,
        toplevel=design,
        simulator=engine,  # type: ignore[arg-type]
        board_def=_board(),
        # A generic of the design's own is not a `-g` at run time: the wrapper
        # bakes it in as a literal (U48), so it has to be set here.
        generic_overrides=overrides,
    )
    assert ok, f"{engine} analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator=engine)  # type: ignore[arg-type]
    if engine == "nvc":
        subprocess.run(
            _NVCBackend.elaborate_cmd("sim_wrapper", generics, work_dir),
            env=env,
            check=True,
            cwd=work_dir,
        )
        run_cmd = _NVCBackend.run_cmd("sim_wrapper", generics, plugin_lib, work_dir)
    else:
        run_cmd = _GHDLBackend.run_cmd("sim_wrapper", generics, plugin_lib, work_dir)
    run_cmd.append(f"--stop-time={stop_ns}ns")

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = module
    run_env["TOPLEVEL"] = "sim_wrapper"
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
    assert "FAIL=0" in output and f"PASS={expected}" in output, (
        f"{module} did not pass under {engine.upper()}.\n" + "\n".join(output.splitlines()[-30:])
    )


@pytest.mark.slow
def test_hex_decoder_behaves_under_ghdl(ghdl):
    _run_cocotb(
        "hex_decoder_7seg", "test_hex_decoder", "ghdl", _HEX_DECODER_TESTS, 200_000, has_seg=True
    )


@pytest.mark.slow
def test_hex_decoder_behaves_under_nvc(nvc):
    _run_cocotb(
        "hex_decoder_7seg", "test_hex_decoder", "nvc", _HEX_DECODER_TESTS, 200_000, has_seg=True
    )


@pytest.mark.slow
def test_code_lock_behaves_under_ghdl(ghdl):
    _run_cocotb("code_lock_fsm", "test_code_lock", "ghdl", _CODE_LOCK_TESTS, 200_000, has_seg=False)


@pytest.mark.slow
def test_code_lock_behaves_under_nvc(nvc):
    _run_cocotb("code_lock_fsm", "test_code_lock", "nvc", _CODE_LOCK_TESTS, 200_000, has_seg=False)


@pytest.mark.slow
def test_gates_mux_behaves_under_ghdl(ghdl):
    _run_cocotb("gates_mux", "test_gates_mux", "ghdl", _GATES_MUX_TESTS, 200_000, has_seg=False)


@pytest.mark.slow
def test_gates_mux_behaves_under_nvc(nvc):
    _run_cocotb("gates_mux", "test_gates_mux", "nvc", _GATES_MUX_TESTS, 200_000, has_seg=False)


#: A prescaler small enough to watch a dozen ticks inside a short simulation.
#: `countdown_7seg` caps its own divider at `minimum(COUNTER_BITS, 18)`, so
#: lowering COUNTER_BITS here lowers the tick rate with it.
_FAST_COUNTDOWN = {**_GENERICS, "COUNTER_BITS": "10"}


@pytest.mark.slow
@pytest.mark.parametrize("engine", ["ghdl", "nvc"])
def test_countdown_sequences_one_at_a_time(engine, request):
    """A still shows a number; only this shows that it got there by counting."""
    request.getfixturevalue(engine)
    _run_cocotb(
        "countdown_7seg",
        "test_countdown",
        engine,
        _COUNTDOWN_TESTS,
        4_000_000,
        has_seg=True,
        generics=_FAST_COUNTDOWN,
    )


@pytest.mark.slow
@pytest.mark.parametrize("engine", ["ghdl", "nvc"])
def test_running_light_walks_one_step_at_a_time(engine, request):
    """One LED lit, advancing by exactly one, wrapping at the end."""
    request.getfixturevalue(engine)
    _run_cocotb(
        "running_light",
        "test_running_light",
        engine,
        _RUNNING_LIGHT_TESTS,
        4_000_000,
        has_seg=False,
        overrides={"DIVIDER_BITS": "8"},
    )
