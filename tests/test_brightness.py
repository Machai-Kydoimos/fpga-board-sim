"""Tests for U9b brightness rendering: duty -> level -> pixel.

The duty cycles themselves are exact (tests/test_duty.py proves that against a
real simulator); these cover what the host does with them — the perceptual
ramp, the persistence-of-vision filter, and the compatibility of the binary
APIs that predate it.
"""

from __future__ import annotations

import math
import time

import pytest

from fpga_sim.ui.components import GAMMA, LED, SevenSeg, _perceptual
from fpga_sim.ui.constants import lerp_rgb
from fpga_sim.ui.simulation_screen import _POV_TAU_S
from fpga_sim.ui.theme import THEME
from fpga_sim.ui.tooltip import tooltip_rows

# ``fake_child`` (a real SimLinkHost with an in-process client standing in for
# the headless simulator) comes from conftest, shared with the screen tests.

# ── Perceptual ramp ──────────────────────────────────────────────────────────


def test_perceptual_ramp_endpoints_are_exact():
    """Full off and full on must land exactly, or a binary run would shift."""
    assert _perceptual(0.0) == 0.0
    assert _perceptual(1.0) == 1.0


def test_perceptual_ramp_lifts_dim_levels():
    """A 10%-duty LED reads as clearly lit, as it does on real hardware."""
    assert _perceptual(0.1) == pytest.approx(0.1 ** (1 / GAMMA), abs=1e-9)
    assert _perceptual(0.1) > 0.3


def test_perceptual_ramp_is_monotonic_and_clamped():
    levels = [_perceptual(v / 20) for v in range(21)]
    assert levels == sorted(levels)
    assert _perceptual(-1.0) == 0.0
    assert _perceptual(5.0) == 1.0


# ── LED level / state compatibility ──────────────────────────────────────────


def test_led_starts_dark():
    assert LED(0).level == 0.0
    assert LED(0).state is False


def test_led_state_setter_is_a_view_over_level():
    """Binary callers (and every pre-U9 test) must keep working unchanged."""
    led = LED(0)
    led.state = True
    assert led.level == 1.0
    led.state = False
    assert led.level == 0.0


def test_led_state_reads_true_for_any_brightness():
    led = LED(0)
    led.level = 0.02
    assert led.state is True


def test_led_full_brightness_is_the_theme_color():
    """level=1.0 must render exactly THEME.led_on, not a rounded approximation."""
    assert lerp_rgb(THEME.led_off, THEME.led_on, _perceptual(1.0)) == THEME.led_on
    assert lerp_rgb(THEME.led_off, THEME.led_on, _perceptual(0.0)) == THEME.led_off


def test_led_draws_at_every_level(headless_pygame):
    """Every brightness renders without error, including the glow path."""
    import pygame

    from fpga_sim.ui.constants import get_font

    surface = pygame.Surface((80, 80))
    font = get_font(12)
    led = LED(0)
    led.rect = pygame.Rect(10, 10, 24, 24)
    for level in (0.0, 0.001, 0.25, 0.5, 0.999, 1.0):
        led.level = level
        led.draw(surface, font)


# ── LED tooltip ──────────────────────────────────────────────────────────────


def test_led_tooltip_shows_fractional_duty():
    led = LED(3)
    led.level = 0.732
    assert led.tooltip_extra == [("Duty", "73.2%")]
    assert ("Duty", "73.2%") in tooltip_rows(led.label, led.info, led.tooltip_extra)


@pytest.mark.parametrize("level", [0.0, 1.0])
def test_led_tooltip_omits_duty_when_binary(level):
    """A plain on/off LED has nothing to add — no row, no noise."""
    led = LED(3)
    led.level = level
    assert led.tooltip_extra == []


# ── SevenSeg per-segment levels ──────────────────────────────────────────────


def test_set_bits_populates_full_levels():
    digit = SevenSeg(0)
    digit.set_bits(0b0000_0101)  # segments a and c
    assert digit.levels[:4] == [1.0, 0.0, 1.0, 0.0]
    assert digit.bits == 0b0000_0101


def test_set_levels_keeps_bits_as_the_binary_view():
    digit = SevenSeg(0)
    digit.set_levels([0.4, 0.0, 0.9, 0.0, 0.0, 0.0, 0.0, 0.0])
    assert digit.bits == 0b0000_0101, "any lit segment must read as on"
    assert digit.levels[0] == 0.4
    assert digit._seg("a") and not digit._seg("b")


def test_set_levels_pads_and_clamps():
    digit = SevenSeg(0)
    digit.set_levels([2.0, -1.0])
    assert digit.levels == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]


def test_seven_seg_draws_at_fractional_levels(headless_pygame):
    import pygame

    digit = SevenSeg(0)
    digit.set_levels([0.5] * 8)
    digit.draw(pygame.Surface((64, 96)))


# ── Duty routing + persistence of vision (SimulationScreen) ──────────────────


def _screen(pygame_mod, child, *, seg=False):
    from tests.test_simulation_screen import _make_screen

    scr = _make_screen(pygame_mod, child, seg=seg)
    scr._connected = True
    return scr


def test_duty_payload_sets_fractional_levels(headless_pygame, fake_child):
    """led_duty drives brightness; the first sample snaps rather than fading up."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    scr._last_state = {"led": 0b0011, "seg": None, "led_duty": [0.25, 1.0, 0.0, 0.0]}
    scr._apply_state()
    assert scr.board.leds[0].level == pytest.approx(0.25)
    assert scr.board.leds[1].level == pytest.approx(1.0)


def test_missing_duty_falls_back_to_binary_bits(headless_pygame, fake_child):
    """An Off / Color-only run has no duty and must render exactly as before."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    scr._last_state = {"led": 0b0101, "seg": None}
    scr._apply_state()
    assert [led.level for led in scr.board.leds[:4]] == [1.0, 0.0, 1.0, 0.0]


def test_persistence_of_vision_eases_toward_the_target(headless_pygame, fake_child):
    """After the first snap, a step change is approached, not jumped to."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    scr._last_state = {"led": 0, "seg": None, "led_duty": [0.0, 0.0, 0.0, 0.0]}
    scr._apply_state()  # snaps to 0.0
    # Pin the elapsed wall time rather than relying on how long two back-to-back
    # calls happen to take, which would make the assertion a race.
    scr._ema_t = time.monotonic() - 0.05
    scr._last_state = {"led": 0, "seg": None, "led_duty": [1.0, 0.0, 0.0, 0.0]}
    scr._apply_state()
    level = scr.board.leds[0].level
    assert 0.0 < level < 1.0, f"expected an eased value, got {level}"
    # ~0.05 s at TAU=0.1 s is ~(1 - e^-0.5) of the way there; the exact constant
    # is asserted against _smooth below, where dt is not read from the clock.
    assert level == pytest.approx(1.0 - math.exp(-0.5), abs=1e-3)


def test_smoothing_follows_the_declared_time_constant(headless_pygame, fake_child):
    """One time constant of wall time closes 1 - 1/e of the gap, exactly."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    scr._ema = {"led": [0.0]}
    assert scr._smooth("led", [1.0], _POV_TAU_S)[0] == pytest.approx(1.0 - math.exp(-1.0))


def test_smoothing_is_wall_clock_not_per_frame(headless_pygame, fake_child):
    """A longer gap must move further, so the fade looks the same at any frame rate."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    scr._ema = {"led": [0.0, 0.0]}
    short = scr._smooth("led", [1.0, 1.0], 0.01)[0]
    scr._ema = {"led": [0.0, 0.0]}
    long = scr._smooth("led", [1.0, 1.0], 0.10)[0]
    assert long > short


def test_first_sample_snaps(headless_pygame, fake_child):
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    assert scr._smooth("led", [0.7, 0.2], 0.016) == [0.7, 0.2]


def test_seg_duty_drives_per_segment_levels(headless_pygame, fake_child):
    """Segments are LEDs: a 7-seg run gets per-segment brightness too."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child, seg=True)
    n = 8 * scr._seg_digits
    duty = [0.0] * n
    duty[0], duty[1] = 0.5, 0.25  # digit 0, segments a and b
    scr._last_state = {"led": 0, "seg": 0b11, "led_duty": None, "seg_duty": duty}
    scr._apply_state()
    digit0 = scr.board._seven_segs[0]
    assert digit0.levels[0] == pytest.approx(0.5)
    assert digit0.levels[1] == pytest.approx(0.25)


def test_seg_without_duty_still_uses_bits(headless_pygame, fake_child):
    child, _client = fake_child
    scr = _screen(headless_pygame, child, seg=True)
    scr._last_state = {"led": 0, "seg": 0b0000_0101}
    scr._apply_state()
    assert scr.board._seven_segs[0].bits == 0b0000_0101


def test_fading_digit_is_not_swallowed_by_the_change_gate(headless_pygame, fake_child):
    """set_seg's bit-pattern gate must not hide a brightness-only change."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child, seg=True)
    scr.board.set_seg_levels(0, [1.0] + [0.0] * 7)
    scr.board.set_seg_levels(0, [0.3] + [0.0] * 7)  # same bits, different brightness
    assert scr.board._seven_segs[0].levels[0] == pytest.approx(0.3)
