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


# ── Pause: held-off/on channels follow live input (U9 decision C) ────────────


def test_pause_lets_held_off_on_leds_follow_switch_input(headless_pygame, fake_child):
    """A held-off/on LED follows the live binary bit under pause (a combinational
    switch -> LED still responds), while a mid-PWM channel keeps its exact duty."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    scr.panel.paused = True
    # Duty held from before the pause; `led` reflects a switch flip that
    # combinationally turned ch2 on and ch1 off.
    scr._last_state = {"led": 0b0100, "seg": None, "led_duty": [0.3, 1.0, 0.0, 0.6]}
    scr._apply_state()
    levels = [scr.board.leds[i].level for i in range(4)]
    assert levels[0] == pytest.approx(0.3)  # mid-PWM: held, ignores binary
    assert levels[1] == pytest.approx(0.0)  # held 1.0, bit now 0 -> follows off
    assert levels[2] == pytest.approx(1.0)  # held 0.0, bit now 1 -> follows on
    assert levels[3] == pytest.approx(0.6)  # mid-PWM: held


def test_running_uses_duty_even_for_off_on_leds(headless_pygame, fake_child):
    """Not paused: duty always wins; the follow-binary hybrid is pause-only."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child)
    scr.panel.paused = False
    scr._last_state = {"led": 0b1111, "seg": None, "led_duty": [0.0, 1.0, 0.0, 1.0]}
    scr._apply_state()
    levels = [scr.board.leds[i].level for i in range(4)]
    assert levels == pytest.approx([0.0, 1.0, 0.0, 1.0])  # all-on binary ignored


def test_pause_follow_binary_applies_to_segments(headless_pygame, fake_child):
    """Segments are LEDs: the same pause rule holds a mid-PWM segment but lets a
    held-off/on segment follow the live bits."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child, seg=True)
    scr.panel.paused = True
    n = 8 * scr._seg_digits
    duty = [0.0] * n
    duty[0], duty[1] = 0.4, 1.0  # segment a mid-PWM (held), segment b held-on
    scr._last_state = {"led": 0, "seg": 0b01, "led_duty": None, "seg_duty": duty}
    scr._apply_state()
    d0 = scr.board._seven_segs[0].levels
    assert d0[0] == pytest.approx(0.4)  # mid-PWM held, ignores bit0=1
    assert d0[1] == pytest.approx(0.0)  # held-on, bit1=0 -> follows off


# ── LED emission color (U36) ─────────────────────────────────────────────────


def test_resolve_led_color_named_hex_and_unknown():
    from fpga_sim.ui.components import resolve_led_color

    assert resolve_led_color("red") == (255, 60, 55)
    assert resolve_led_color("#00ff88") == (0, 255, 136)
    assert resolve_led_color("") is None
    assert resolve_led_color("mauve") is None
    assert resolve_led_color("#12zz00") is None  # malformed hex


def test_led_widget_resolves_its_info_color(headless_pygame):
    from fpga_sim.board_loader import ComponentInfo
    from fpga_sim.ui.components import LED

    assert LED(0, info=ComponentInfo("led", "led_r", 0, [], color="red"))._on_color == (255, 60, 55)
    assert LED(1, info=ComponentInfo("led", "led", 1, []))._on_color is None  # uncolored
    assert LED(2)._on_color is None  # no info at all


def test_fading_digit_is_not_swallowed_by_the_change_gate(headless_pygame, fake_child):
    """set_seg's bit-pattern gate must not hide a brightness-only change."""
    child, _client = fake_child
    scr = _screen(headless_pygame, child, seg=True)
    scr.board.set_seg_levels(0, [1.0] + [0.0] * 7)
    scr.board.set_seg_levels(0, [0.3] + [0.0] * 7)  # same bits, different brightness
    assert scr.board._seven_segs[0].levels[0] == pytest.approx(0.3)


# ── RGB channel fold (U37 interim, pre-RGBLED-puck) ──────────────────────────


def _rgb_screen(pygame_mod, child):
    """A screen on a 2-mono + 1-rgb_led board: 5 boundary channels, 3 widgets."""
    from fpga_sim.board_loader import BoardDef, ComponentInfo
    from fpga_sim.ui.simulation_screen import SimulationScreen
    from tests.test_simulation_screen import _sim

    board_def = BoardDef(
        name="RGBish",
        class_name="RGBish",
        leds=[
            ComponentInfo("led", "led", 0, ["A1"]),
            ComponentInfo("led", "led", 1, ["A2"]),
            ComponentInfo("led", "rgb_led", 0, ["a", "b", "c"]),
        ],
    )
    surface = pygame_mod.display.set_mode((1024, 700))
    scr = SimulationScreen(
        surface,
        pygame_mod.time.Clock(),
        board_def,
        child,
        speed_factor=0.1,
        match=None,
        vhdl_path="x.vhd",
        sim=_sim("ghdl"),
    )
    scr._connected = True
    return scr


def test_rgb_duty_channels_fold_to_the_component_widget(headless_pygame, fake_child):
    """Channel duties [m0, m1, r, g, b]: monos map 1:1; the RGB widget shows
    its brightest channel until the RGBLED puck (U37 PR-2) mixes a color."""
    child, _client = fake_child
    scr = _rgb_screen(headless_pygame, child)
    scr._last_state = {"led": 0, "seg": None, "led_duty": [0.25, 0.0, 0.1, 0.6, 0.2]}
    scr._apply_state()
    assert scr.board.leds[0].level == pytest.approx(0.25)
    assert scr.board.leds[1].level == pytest.approx(0.0)
    assert scr.board.leds[2].level == pytest.approx(0.6)  # brightest-channel view
    assert scr.board.leds[2].levels == pytest.approx([0.1, 0.6, 0.2])  # the real mix


def test_rgb_binary_bits_fold_to_the_component_widget(headless_pygame, fake_child):
    """Binary fallback: the RGB widget lights when any of its channels is set."""
    child, _client = fake_child
    scr = _rgb_screen(headless_pygame, child)
    scr._last_state = {"led": 0b01000, "seg": None}  # only the g channel (bit 3)
    scr._apply_state()
    assert scr.board.leds[0].level == 0.0
    assert scr.board.leds[1].level == 0.0
    assert scr.board.leds[2].level == 1.0
    assert scr.board.leds[2].levels == [0.0, 1.0, 0.0]  # only the g channel


# ── RGBLED widget (U37 PR-2) ─────────────────────────────────────────────────


def test_rgbled_level_is_a_view_and_setter_drives_all_channels():
    from fpga_sim.ui.components import RGBLED

    puck = RGBLED(0)
    assert puck.levels == [0.0, 0.0, 0.0]
    puck.set_channel("g", 0.4)
    assert puck.level == pytest.approx(0.4)
    assert puck.state is True  # LED's binary view still works
    puck.level = 1.0  # binary "on" = white mix
    assert puck.levels == [1.0, 1.0, 1.0]


def test_rgbled_tooltip_always_lists_the_three_channels():
    from fpga_sim.ui.components import RGBLED

    puck = RGBLED(0)
    puck.set_channel("r", 0.73)
    puck.set_channel("b", 1.0)
    assert puck.tooltip_extra == [("R", "73%"), ("G", "0%"), ("B", "100%")]


def test_rgbled_draws_the_gamma_encoded_mix(headless_pygame):
    """Full-red puck: red pixel at center; all-off puck: theme neutral."""
    from fpga_sim.ui.components import RGBLED

    surface = headless_pygame.Surface((60, 60))
    surface.fill((0, 0, 0))
    font = headless_pygame.font.Font(None, 10)
    puck = RGBLED(0)
    puck.rect = headless_pygame.Rect(10, 10, 30, 30)
    puck.set_channel("r", 1.0)
    puck.draw(surface, font)
    r, g, b, _ = surface.get_at(puck.rect.center)
    assert r == 255
    assert g < 80 and b < 80  # dark-lens floor only

    surface.fill((0, 0, 0))
    puck.level = 0.0
    puck.draw(surface, font)
    off = surface.get_at(puck.rect.center)[:3]
    assert off == THEME.led_off  # dark neutral, no color cast


def test_debug_view_rgbled_draws_linear_length_bars(headless_pygame, restore_debug_view):
    """U38 debug view: three stacked R/G/B bars whose fill length is the
    *linear* duty — a 50% channel fills exactly half the track (perceptual
    encoding would fill ~73%), which is the whole point of the mode."""
    from fpga_sim.ui.components import _LED_COLOR_RGB, RGBLED, _bar_track_color, set_debug_view

    surface = headless_pygame.Surface((90, 60))
    surface.fill((0, 0, 0))
    # A font taller than the 8px bars: the % text never renders, so every
    # probed pixel is pure bar geometry (font metrics vary per platform).
    font = headless_pygame.font.Font(None, 40)
    puck = RGBLED(0)
    puck.rect = headless_pygame.Rect(10, 10, 60, 30)  # gap=2 -> three 8px bars
    puck.set_channel("r", 1.0)
    puck.set_channel("g", 0.5)
    puck.set_channel("b", 0.0)
    set_debug_view(True)
    puck.draw(surface, font)

    # Red bar (y 10..17): full-length fill.
    assert surface.get_at((60, 14))[:3] == _LED_COLOR_RGB["red"]
    # Green bar (y 20..27): linear 50% -> fill ends at x=40 exactly.
    assert surface.get_at((25, 24))[:3] == _LED_COLOR_RGB["green"]
    assert surface.get_at((50, 24))[:3] == _bar_track_color()  # perceptual would still be filled
    # Blue bar (y 30..37): zero fill, bare track (near-black: off time reads as empty).
    assert surface.get_at((40, 34))[:3] == _bar_track_color()


def test_debug_view_bar_percent_text_appears_when_it_fits(headless_pygame, restore_debug_view):
    """A bar tall enough for the label font gets its % readout (white glyphs)."""
    from fpga_sim.ui.components import RGBLED, set_debug_view

    surface = headless_pygame.Surface((160, 120))
    surface.fill((0, 0, 0))
    font = headless_pygame.font.Font(None, 14)
    puck = RGBLED(0)
    puck.rect = headless_pygame.Rect(10, 10, 120, 90)  # three ~28px bars
    puck.set_channel("r", 1.0)
    set_debug_view(True)
    puck.draw(surface, font)

    # "100%" is right-aligned inside the red bar: some near-white glyph pixels
    # must exist in its right half (loose: font rendering varies per platform).
    red_bar_rows = range(12, 36)
    hits = sum(
        1
        for y in red_bar_rows
        for x in range(70, 128)
        if surface.get_at((x, y))[1] > 200 and surface.get_at((x, y))[2] > 200
    )
    assert hits > 0


def test_debug_view_mono_led_gains_a_duty_bar_and_percent(headless_pygame, restore_debug_view):
    """U38 debug view: a mono LED keeps its circle, adds a thin linear bar, and
    shows the exact % centered in the circle (the bar is too short to host it)."""
    from fpga_sim.ui.components import LED, _bar_track_color, set_debug_view

    surface = headless_pygame.Surface((60, 70))
    surface.fill((0, 0, 0))
    font = headless_pygame.font.Font(None, 10)
    led = LED(0)
    led.rect = headless_pygame.Rect(10, 10, 40, 40)  # bar_h = 5 -> track y 45..49
    led.level = 0.5
    set_debug_view(True)
    led.draw(surface, font)

    assert surface.get_at((15, 47))[:3] == THEME.led_on  # inside the 20px fill
    assert surface.get_at((45, 47))[:3] == _bar_track_color()  # past it: bare track
    assert surface.get_at((30, 20))[:3] != (0, 0, 0)  # the circle is still there (r=13 @ 30,30)
    # "50%" glyph pixels (near-white) exist around the circle center.
    hits = sum(
        1
        for y in range(24, 37)
        for x in range(18, 43)
        if all(c > 200 for c in surface.get_at((x, y))[:3])
    )
    assert hits > 0


def test_set_led_channel_on_a_plain_led_collapses_to_level(headless_pygame):
    """Safety: routing an RGB channel at a mono widget just sets its level."""
    from fpga_sim.board_loader import BoardDef, ComponentInfo
    from fpga_sim.ui.board_display import FPGABoard

    bd = BoardDef(name="B", class_name="B", leds=[ComponentInfo("led", "led", 0, ["A1"])])
    board = FPGABoard(board_def=bd, width=400, height=300)
    board.set_led_channel(0, "g", 0.5)
    assert board.leds[0].level == 0.5
