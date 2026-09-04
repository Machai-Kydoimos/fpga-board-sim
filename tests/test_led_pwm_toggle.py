"""U47 — the LED PWM display toggle, across all three of its effects.

The setting is one switch with two consequences, and the tests are grouped that
way:

1. **Display** — ``SimulationScreen._apply_state`` renders plain on/off, taken
   at the *source* and returned unsmoothed. Thresholding the persistence-of-vision
   EMA instead would latch an LED on forever, since an exponential never reaches
   zero; the test that pins this asserts an LED actually reaches 0.0.
2. **Cost** — ``resolve_duty_mode`` returns ``"off"``, which drops the U9
   integrator from the generated wrapper. That is where the measured ~4.8x
   throughput on a 6-digit 7-segment board comes from.
3. **Re-analysis** — because (2) changes the wrapper, the launch path must
   notice. That is #386's artifact comparison, and without it this row would be
   silently inert; the test here is the end-to-end version of that claim.

Every test here reads or writes the session, which conftest's autouse
``_isolate_session_file`` redirects to a per-test temp path -- the same fixture
this card's ``resolve_duty_mode`` change made necessary suite-wide.
"""

from __future__ import annotations

import math
import time

import pytest

from fpga_sim.session_config import update_session
from fpga_sim.sim_bridge import _duty_channels, _generate_wrapper, resolve_duty_mode
from fpga_sim.ui.components import pwm_display_enabled, set_pwm_display


def _screen(pygame_mod, child, *, seg=False):
    from tests.test_simulation_screen import _make_screen

    scr = _make_screen(pygame_mod, child, seg=seg)
    scr._connected = True
    return scr


# ── 1. Display ───────────────────────────────────────────────────────────────


def test_pwm_on_is_the_default():
    assert pwm_display_enabled() is True, "PWM is what the simulator has always done"


def test_pwm_off_renders_binary_from_measured_duty(
    headless_pygame, fake_child, restore_pwm_display
):
    """A measured 0.25 duty reads as fully off, 1.0 as fully on -- no in-between."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    set_pwm_display(False)
    scr._last_state = {"led": 0b0010, "seg": None, "led_duty": [0.25, 1.0, 0.9, 0.0]}
    scr._apply_state()
    # The *bits* decide, not the duty: only led1 is set.
    assert [led.level for led in scr.board.leds[:4]] == [0.0, 1.0, 0.0, 0.0]


def test_pwm_off_is_unsmoothed_so_an_led_can_reach_zero(
    headless_pygame, fake_child, restore_pwm_display
):
    """The load-bearing one: cutting at the source, not thresholding the EMA.

    An exponential never reaches zero, so had the flag been applied to the
    smoothed output an LED that turned off would stay faintly -- then forever --
    lit. Drive it on, then off, with real elapsed time in between.
    """
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    set_pwm_display(False)
    scr._last_state = {"led": 0b0001, "seg": None, "led_duty": [1.0, 0.0, 0.0, 0.0]}
    scr._apply_state()
    assert scr.board.leds[0].level == 1.0

    scr._ema_t = time.monotonic() - 0.05  # a real gap, as the POV tests do
    scr._last_state = {"led": 0b0000, "seg": None, "led_duty": [1.0, 0.0, 0.0, 0.0]}
    scr._apply_state()
    assert scr.board.leds[0].level == 0.0, "must be exactly off, not an EMA tail"


def test_pwm_on_still_eases(headless_pygame, fake_child, restore_pwm_display):
    """The inverse: with PWM on, the same sequence is smoothed as before."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    set_pwm_display(True)
    scr._last_state = {"led": 0, "seg": None, "led_duty": [0.0, 0.0, 0.0, 0.0]}
    scr._apply_state()
    scr._ema_t = time.monotonic() - 0.05
    scr._last_state = {"led": 0, "seg": None, "led_duty": [1.0, 0.0, 0.0, 0.0]}
    scr._apply_state()
    assert scr.board.leds[0].level == pytest.approx(1.0 - math.exp(-0.5), abs=1e-3)


def test_pwm_off_renders_segments_binary(headless_pygame, fake_child, restore_pwm_display):
    """Segments are LEDs: the 7-seg path takes the same source cut."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child, seg=True)
    set_pwm_display(False)
    scr._last_state = {"led": 0, "seg": 0b0000_0011, "seg_duty": [0.5] * 32}
    scr._apply_state()
    digit0 = scr.board._seven_segs[0]
    assert digit0.levels[:3] == [1.0, 1.0, 0.0], "bits, not the 0.5 duty"


# ── 2. Cost: the duty mode the wrapper is built with ─────────────────────────


def test_session_preference_drives_the_duty_mode():
    assert resolve_duty_mode() == "full"
    update_session(led_pwm=False)
    assert resolve_duty_mode() == "off"
    update_session(led_pwm=True)
    assert resolve_duty_mode() == "full"


def test_explicit_mode_beats_the_preference():
    """A caller that means "full" gets it -- the preference is only a default."""
    update_session(led_pwm=False)
    assert resolve_duty_mode("full") == "full"


def test_env_beats_the_preference(monkeypatch):
    """FPGA_SIM_DUTY still pins a benchmark or CI run without touching the session."""
    update_session(led_pwm=False)
    monkeypatch.setenv("FPGA_SIM_DUTY", "full")
    assert resolve_duty_mode() == "full"


def test_pwm_off_drops_the_integrator_from_the_wrapper(tmp_path):
    """Where the ~4.8x on a 6-digit 7-seg board comes from: no integrator at all."""
    update_session(led_pwm=False)
    assert _duty_channels(resolve_duty_mode(), has_seg=True) == []
    text = _generate_wrapper("blinky", str(tmp_path)).read_text(encoding="utf-8")
    assert "_acc" not in text and "numeric_std" not in text
    assert "led => led\n" in text, "the uut must drive the boundary port directly"


def test_pwm_on_keeps_the_integrator(tmp_path):
    update_session(led_pwm=True)
    text = _generate_wrapper("blinky", str(tmp_path)).read_text(encoding="utf-8")
    assert "led_acc" in text and "use ieee.numeric_std.all;" in text


# ── 3. Re-analysis: the row is not silently inert (#386) ─────────────────────


def test_toggling_the_preference_forces_reanalysis(tmp_path):
    """The end-to-end version of #386's claim, which is why it had to land first."""
    from fpga_sim.board_loader import BoardDef
    from fpga_sim.controller import SessionState
    from fpga_sim.sim_bridge import SimulatorInfo

    board = BoardDef("Arty", "ArtyPlatform")
    vhdl = tmp_path / "blinky.vhd"
    vhdl.write_text("-- design", encoding="utf-8")
    work = tmp_path / "wd"
    work.mkdir()

    update_session(led_pwm=True)
    _generate_wrapper("blinky", str(work), board_def=board)
    sim = SimulatorInfo("ghdl", "/usr/bin/ghdl", "mcode", "GHDL", "ghdl 1.0")
    state = SessionState(sim=sim, vhdl_path=str(vhdl), work_dir=str(work), work_dir_sim=sim)
    assert not state.needs_reanalysis(board)

    update_session(led_pwm=False)
    assert state.needs_reanalysis(board), "changing the row must re-analyze"


# ── The benchmark path must restore it too ───────────────────────────────────


def test_benchmark_path_restores_the_pwm_preference(monkeypatch, restore_pwm_display):
    """``--screenshots`` must not render PWM for a run whose wrapper measured none.

    ``main()`` exits into ``_run_benchmark`` *before* the theme / debug-view
    restores, so the benchmark used to keep PWM display on while
    ``resolve_duty_mode`` had already dropped the integrator from its wrapper --
    the same preference honored in one half only, and the capture showed
    something the product never displays. Caught by pixel-sampling the captured
    frames, so it is pinned here.
    """
    import sys

    from fpga_sim import __main__ as main_mod
    from fpga_sim.ui.components import set_pwm_display

    update_session(led_pwm=False)
    set_pwm_display(True)  # as a fresh process starts

    seen: list[bool] = []

    def fake_benchmark(args, discovered):
        seen.append(pwm_display_enabled())
        return 0

    monkeypatch.setattr(main_mod, "_run_benchmark", fake_benchmark)
    monkeypatch.setattr(sys, "argv", ["fpga-sim", "--benchmark", "1"])
    with pytest.raises(SystemExit):
        main_mod.main()

    assert seen == [False], "the benchmark must see the saved preference"
