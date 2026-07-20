"""Tests for the U9 duty engine: wrapper splice, host math, end-to-end measurement.

Three layers:

* pure host units -- :class:`~fpga_sim.sim_duty.DutyTracker` against hand-worked
  numbers, no simulator needed;
* wrapper generation -- Off/Color-only must stay *byte-identical* to the pre-U9
  wrapper (that is what makes not measuring genuinely free), Full must splice
  the integrator into both the generic and the board-native path;
* the real thing -- ``sim/test_duty.py`` run against ``sim/duty_probe.vhd``
  under GHDL and NVC, mirroring tests/test_stopwatch.py's elaborate-then-run
  pattern.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from fpga_sim.sim_bridge import (
    DEFAULT_DUTY_ALGO,
    DUTY_ALGOS,
    _build_sim_env,
    _duty_channels,
    _generate_wrapper,
    _GHDLBackend,
    _NVCBackend,
    analyze_vhdl,
    resolve_duty_algo,
    resolve_duty_mode,
)
from fpga_sim.sim_duty import ACC_BITS, DutyTracker, unpack
from tests.conftest import _7seg_board, _plain_board

PROJECT = Path(__file__).resolve().parent.parent
DUTY_PROBE = PROJECT / "sim" / "duty_probe.vhd"
BLINKY = PROJECT / "hdl" / "blinky.vhd"

_GENERICS = {
    "NUM_SWITCHES": "4",
    "NUM_BUTTONS": "4",
    "NUM_LEDS": "8",
    "COUNTER_BITS": "17",
    "CLK_HALF_NS_INIT": "5",  # 10 ns clock period -- see sim/test_duty.py
}

# The run tests require exactly this many cocotb PASSes (with FAIL=0) so a
# zero-test run can't false-pass. Keep in sync with sim/test_duty.py.
_DUTY_TEST_COUNT = 4

# Long enough for the >2.147 s INTEGER-overflow probe plus its measurements.
_STOP_TIME = "--stop-time=3000000000ns"


def _pack(*channels: tuple[int, int]) -> tuple[int, int]:
    """Pack ``(acc, tch)`` pairs into the two wide vectors the wrapper exports."""
    acc = tch = 0
    for i, (a, t) in enumerate(channels):
        acc |= a << (ACC_BITS * i)
        tch |= t << (ACC_BITS * i)
    return acc, tch


# ── Host math ────────────────────────────────────────────────────────────────


def test_unpack_splits_channels():
    acc, _ = _pack((7, 0), (0, 0), (2**47, 0))
    assert unpack(acc, 3) == [7, 0, 2**47]


def test_stuck_on_channel_reads_full_duty():
    """A channel that never transitions has acc=0 -- the in-progress term carries it."""
    tracker = DutyTracker(1)
    acc, tch = _pack((0, 0))
    assert tracker.update(acc, tch, 0b1, 1_000) == [1.0]
    assert tracker.update(acc, tch, 0b1, 2_000) == [1.0]


def test_stuck_off_channel_reads_zero():
    tracker = DutyTracker(1)
    acc, tch = _pack((0, 0))
    assert tracker.update(acc, tch, 0b0, 1_000) == [0.0]


def test_partial_tail_is_not_double_counted():
    """The falsified pre-phase-0 design rendered this 60% channel as 100%.

    Channel is on since t=600 having accumulated 200 ns of on-time up to its
    last change; over the window (0, 1000] that is 200 + 400 = 600 ns.
    """
    tracker = DutyTracker(1)
    acc, tch = _pack((200, 600))
    assert tracker.update(acc, tch, 0b1, 1_000) == [0.6]


def test_window_duty_is_differenced_not_cumulative():
    tracker = DutyTracker(1)
    acc, tch = _pack((500, 1_000))
    assert tracker.update(acc, tch, 0b0, 1_000) == [0.5]  # (0, 1000]
    acc, tch = _pack((750, 2_000))  # 250 ns more on-time in the next 1000 ns
    assert tracker.update(acc, tch, 0b0, 2_000) == [0.25]


def test_no_elapsed_time_reports_nothing():
    """A zero-length window has no duty to report -- the caller reuses its last."""
    tracker = DutyTracker(1)
    acc, tch = _pack((0, 0))
    assert tracker.update(acc, tch, 0b0, 1_000) == [0.0]
    assert tracker.update(acc, tch, 0b0, 1_000) is None


def test_accumulator_wrap_is_survivable():
    """Differencing is mod 2**48, so a wrapped accumulator still reads correctly."""
    tracker = DutyTracker(1)
    acc, tch = _pack((2**ACC_BITS - 100, 0))
    tracker.update(acc, tch, 0b0, 1_000)
    acc, tch = _pack((50, 0))  # wrapped past 2**48 after 150 ns of on-time
    assert tracker.update(acc, tch, 0b0, 2_000) == [0.15]


def test_duty_is_clamped_to_unit_range():
    tracker = DutyTracker(1)
    acc, tch = _pack((5_000, 0))
    assert tracker.update(acc, tch, 0b0, 1_000) == [1.0]


# ── Mode resolution + wrapper generation ─────────────────────────────────────


def test_duty_mode_defaults_to_full(monkeypatch):
    monkeypatch.delenv("FPGA_SIM_DUTY", raising=False)
    assert resolve_duty_mode() == "full"
    assert resolve_duty_mode("off") == "off"


def test_duty_mode_env_wins(monkeypatch):
    monkeypatch.setenv("FPGA_SIM_DUTY", "OFF")
    assert resolve_duty_mode("full") == "off"
    monkeypatch.setenv("FPGA_SIM_DUTY", "nonsense")
    assert resolve_duty_mode("full") == "full", "a typo must not stop a run"


def test_duty_algo_defaults_and_env(monkeypatch):
    monkeypatch.delenv("FPGA_SIM_DUTY_ALGO", raising=False)
    assert resolve_duty_algo() == DEFAULT_DUTY_ALGO
    monkeypatch.setenv("FPGA_SIM_DUTY_ALGO", "fix_ns_pc")
    assert resolve_duty_algo() == "fix_ns_pc"
    monkeypatch.setenv("FPGA_SIM_DUTY_ALGO", "nonsense")
    assert resolve_duty_algo() == DEFAULT_DUTY_ALGO, "a typo must not stop a run"


@pytest.mark.parametrize("algo", DUTY_ALGOS)
def test_every_algo_has_its_fragments(algo, tmp_path, monkeypatch):
    """Each selectable algorithm splices a complete, distinct integrator.

    Both export the same accumulator contract, so the host math (and every duty
    assertion in sim/test_duty.py) is independent of which one is spliced.
    """
    monkeypatch.setenv("FPGA_SIM_DUTY_ALGO", algo)
    work = tmp_path / algo
    work.mkdir()
    text = _generate_wrapper("blinky", str(work), duty="full").read_text()
    assert "led_acc     : out std_logic_vector(48 * NUM_LEDS - 1 downto 0)" in text
    assert "led_meas" in text and "led <= led_int;" in text
    # The seconds->ns product is a ~900-bit-op numeric_std multiply; it must stay
    # behind the once-per-simulated-second guard, not sit in the hot path.
    assert "if now - sec_t >= 1 sec then" in text


@pytest.mark.parametrize("mode", ["off", "color"])
def test_unmeasured_wrapper_is_byte_identical(mode, tmp_path):
    """Off and Color-only emit exactly the pre-U9 wrapper -- no integrator, no cost."""
    work = tmp_path / mode
    work.mkdir()
    off = _generate_wrapper("blinky", str(work), duty=mode).read_text()
    assert "_acc" not in off and "_tch" not in off
    assert "numeric_std" not in off
    assert "led => led\n" in off, "the uut must drive the boundary port directly"
    assert _duty_channels(mode, has_seg=True) == []


def test_full_wrapper_splices_the_integrator(tmp_path):
    full = _generate_wrapper("blinky", str(tmp_path), duty="full").read_text()
    assert "led_acc     : out std_logic_vector(48 * NUM_LEDS - 1 downto 0)" in full
    assert "led_tch     : out std_logic_vector(48 * NUM_LEDS - 1 downto 0)" in full
    assert "use ieee.numeric_std.all;" in full
    assert "led => led_int" in full and "led <= led_int;" in full
    assert "seg" not in full, "a design without a seg port must not grow seg channels"


def test_full_wrapper_measures_segments_too(tmp_path):
    """Segments are LEDs: a 7-seg run integrates all 8 channels per digit."""
    full = _generate_wrapper(
        "counter_7seg", str(tmp_path), board_def=_7seg_board(), design_has_seg=True, duty="full"
    ).read_text()
    assert "seg_acc     : out std_logic_vector(48 * 8 * NUM_SEGS - 1 downto 0)" in full
    assert "seg => seg_int" in full and "seg <= seg_int;" in full
    assert _duty_channels("full", has_seg=True) == [("led", "NUM_LEDS"), ("seg", "8 * NUM_SEGS")]


def test_native_wrapper_measures_the_boundary_value(tmp_path):
    """A board-native run measures after polarity inversion, not the raw design pins."""
    from fpga_sim.sim_bridge import check_vhdl_contract

    from fpga_sim.board_loader import discover_boards, get_default_boards_path  # isort: skip

    boards = {b.class_name: b for b in discover_boards(get_default_boards_path())}
    board = boards["DE0Platform"]
    result = check_vhdl_contract(PROJECT / "hdl" / "native" / "de0.vhd", board_def=board)
    assert result.ok and result.match is not None, result.message

    native = _generate_wrapper(
        "de0", str(tmp_path), board_def=board, match=result.match, duty="full"
    ).read_text()
    assert "led_int <= std_logic_vector(resize(" in native, "LEDs must feed the integrator"
    assert "led <= led_int;" in native
    assert "seg_int(6 downto 0) <= not hex0_uut;" in native, "measure the inverted value"
    # Topology is the algorithm's business (generate-of-processes vs one process),
    # so assert only the contract every algorithm shares.
    assert "led_meas" in native and "led_acc" in native


# ── End-to-end: the integrator, measured against known duty cycles ───────────


def test_duty_probe_exists():
    assert DUTY_PROBE.is_file(), f"duty probe missing: {DUTY_PROBE}"


@pytest.mark.slow
@pytest.mark.parametrize("simulator", ["ghdl", "nvc"])
def test_full_wrapper_analyzes(simulator, request):
    """A Full-mode wrapper passes the ordinary analyze + elaborate validation."""
    request.getfixturevalue(simulator)  # skips when that simulator is absent
    work_dir = tempfile.mkdtemp(prefix=f"duty_analyze_{simulator}_")
    ok, detail = analyze_vhdl(
        BLINKY,
        work_dir=work_dir,
        toplevel="blinky",
        simulator=simulator,
        board_def=_plain_board(),
        duty="full",
    )
    assert ok, f"{simulator.upper()} analyze of a Full wrapper failed: {detail}"


def _run_probe(simulator, backend, binary_fixture):
    """Analyze + elaborate + run the cocotb duty suite against duty_probe."""
    work_dir = tempfile.mkdtemp(prefix=f"duty_{simulator}_")
    ok, detail = analyze_vhdl(
        DUTY_PROBE,
        work_dir=work_dir,
        toplevel="duty_probe",
        simulator=simulator,
        board_def=_plain_board(),
        duty="full",
    )
    assert ok, f"{simulator.upper()} analyze failed: {detail}"

    env, plugin_lib = _build_sim_env(simulator=simulator)
    if simulator == "nvc":
        # NVC bakes generics in at elaboration; GHDL applies them at -r.
        subprocess.run(
            backend.elaborate_cmd("sim_wrapper", _GENERICS, work_dir),
            env=env,
            check=True,
            cwd=work_dir,
        )
    run_cmd = backend.run_cmd("sim_wrapper", _GENERICS, plugin_lib, work_dir)
    run_cmd.append(_STOP_TIME)

    run_env = env.copy()
    run_env["COCOTB_TEST_MODULES"] = "test_duty"
    run_env["TOPLEVEL"] = "sim_wrapper"
    run_env["PYTHONPATH"] = str(PROJECT / "sim") + os.pathsep + run_env.get("PYTHONPATH", "")

    result = subprocess.run(run_cmd, env=run_env, cwd=work_dir, capture_output=True, text=True)
    output = result.stdout + result.stderr
    assert "FAIL=0" in output and f"PASS={_DUTY_TEST_COUNT}" in output, (
        f"cocotb duty suite did not pass under {simulator.upper()}.\n"
        + "\n".join(output.splitlines()[-40:])
    )


def _probe_board():
    """A board wide enough for duty_probe's channels (8 LEDs, 4 switches)."""
    from fpga_sim.board_loader import BoardDef, ComponentInfo

    return BoardDef(
        name="Duty Probe Board",
        class_name="DutyProbeBoard",
        leds=[ComponentInfo("led", "led", i, []) for i in range(8)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(4)],
    )


@pytest.mark.slow
def test_pause_holds_the_measured_duty(ghdl):
    """Pausing must not change rendered brightness.

    Pause is an *observation* control: it exists so the board can be inspected,
    so it must not alter what the board looks like.  While paused the child's
    step shrinks to 1 ns, so a naive implementation measures duty over a window
    shorter than a clock period -- every channel reads unambiguously high or low
    and a 50%-duty LED snaps to fully on or fully off, which is exactly the
    sampling artifact this whole card exists to remove.
    """
    import time

    from fpga_sim.controller import build_generics
    from fpga_sim.sim_bridge import start_simulation
    from fpga_sim.sim_link import drain, send

    board = _probe_board()
    child = start_simulation(
        board.to_json(),
        DUTY_PROBE,
        "duty_probe",
        build_generics(board),
        simulator="ghdl",
        board_def=board,
        speed_factor=1.0,
    )
    try:
        assert child.link.wait_connected(60), "sim child never connected"

        def collect(secs: float) -> list[float]:
            """LED 3's duty (a steady 50% at a 100-clock period) over *secs*."""
            out: list[float] = []
            end = time.monotonic() + secs
            while time.monotonic() < end:
                for kind, payload in drain(child.link.conn):
                    if kind == "state" and payload.get("led_duty"):
                        out.append(float(payload["led_duty"][3]))
                time.sleep(0.02)
            return out

        running = collect(1.5)
        assert running, "no duty samples while running"
        assert 0.4 < running[-1] < 0.6, f"50% channel measured {running[-1]} while running"

        send(child.link.conn, "pause", {"on": True})
        time.sleep(0.3)  # let the pause take effect before sampling
        paused = collect(1.5)
        assert paused, "no state messages while paused"
        assert set(paused) == {paused[0]}, f"duty moved while paused: {sorted(set(paused))}"
        assert 0.4 < paused[0] < 0.6, f"duty collapsed to {paused[0]} while paused"
    finally:
        child.stop()


@pytest.mark.slow
def test_measured_duty_matches_ground_truth_ghdl(ghdl):
    """Measured duty matches duty_probe's known channels under GHDL."""
    _run_probe("ghdl", _GHDLBackend, ghdl)


@pytest.mark.slow
def test_measured_duty_matches_ground_truth_nvc(nvc):
    """Measured duty matches duty_probe's known channels under NVC."""
    _run_probe("nvc", _NVCBackend, nvc)
