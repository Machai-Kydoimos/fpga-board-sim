"""The shared LED halo: it must never move the LED it surrounds.

The halo is the only part of an LED whose geometry depends on brightness, so it
is the only thing that *could* make a board's LEDs shift or jitter as a design
drives them. That would be far worse than any halo it replaced: the board is a
model of fixed hardware, and a component that wanders is a lie about the
hardware, not a rendering nicety.

These tests pin the invariant end to end rather than by inspection, so the
policy that picks the halo radius stays free to change -- including the
brightness-scaled radius that motivated factoring this helper out -- while the
LED body, its ring and its label stay exactly where the layout put them.
"""

from __future__ import annotations

import pygame
import pytest

from fpga_sim.ui.components import LED, RGBLED, _draw_glow
from fpga_sim.ui.constants import WHITE
from fpga_sim.ui.theme import THEME

LEVELS = (0.0, 0.01, 0.1, 0.25, 0.5, 0.75, 0.99, 1.0)


def _rendered(widget: LED) -> pygame.Surface:
    """Draw an already-levelled *widget* onto a fresh board-colored surface."""
    surface = pygame.Surface((240, 240))
    surface.fill(THEME.pcb_bg)
    widget.rect = pygame.Rect(90, 80, 44, 44)
    widget.draw(surface, pygame.font.Font(None, 14))
    return surface


def _mono(level: float) -> LED:
    led = LED(0)
    led.level = level
    return led


def _puck(mix: list[float]) -> RGBLED:
    puck = RGBLED(0)
    puck.levels = mix
    return puck


def _white_bbox(surface: pygame.Surface) -> tuple[int, int, int, int] | None:
    """Bounding box of pure-white pixels: the LED's ring plus its label.

    White is the right probe because it is drawn *last* and is opaque, so the
    halo -- translucent, and never white for a mono LED -- cannot contribute to
    it however large it grows.
    """
    xs: list[int] = []
    ys: list[int] = []
    for x in range(surface.get_width()):
        for y in range(surface.get_height()):
            if surface.get_at((x, y))[:3] == WHITE:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def test_led_geometry_is_brightness_invariant(headless_pygame):
    """A mono LED's ring and label sit in exactly one place, at every level."""
    boxes = {lv: _white_bbox(_rendered(_mono(lv))) for lv in LEVELS}
    assert None not in boxes.values()
    assert len(set(boxes.values())) == 1, f"the LED moved with brightness: {boxes}"


def test_rgb_puck_geometry_is_brightness_invariant(headless_pygame):
    """Same for a tri-color puck, across mixes rather than a single ramp."""
    mixes = [
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [0.0, 0.5, 0.0],
        [0.2, 0.9, 0.4],
        [1.0, 1.0, 0.0],
    ]
    boxes = {tuple(m): _white_bbox(_rendered(_puck(m))) for m in mixes}
    assert None not in boxes.values()
    assert len(set(boxes.values())) == 1, f"the puck moved with brightness: {boxes}"


@pytest.mark.parametrize("led_radius", [4, 11, 21, 40])
@pytest.mark.parametrize("k", [0.05, 0.5, 1.0])
def test_glow_is_symmetric_about_the_led_center(headless_pygame, led_radius, k):
    """The structural guarantee: whatever the radius, the halo stays concentric.

    Asserted on the painted pixels rather than on the blit arithmetic, so it
    still holds if the radius policy changes.
    """
    surface = pygame.Surface((400, 400))
    surface.fill(THEME.pcb_bg)
    center = (200, 200)
    _draw_glow(surface, center, led_radius, (255, 30, 30), k)

    lit = [
        (x, y) for x in range(400) for y in range(400) if surface.get_at((x, y))[:3] != THEME.pcb_bg
    ]
    assert lit, "a lit LED must produce a halo"
    xs = [x for x, _ in lit]
    ys = [y for _, y in lit]
    # The painted region's midpoint is the LED's own center, to within the one
    # pixel a even/odd diameter can cost.
    assert abs((min(xs) + max(xs)) / 2 - center[0]) <= 1
    assert abs((min(ys) + max(ys)) / 2 - center[1]) <= 1
    # ...and it is as wide as it is tall: a circle, not an offset ellipse.
    assert abs((max(xs) - min(xs)) - (max(ys) - min(ys))) <= 1


def test_glow_alpha_tracks_brightness(headless_pygame):
    """A dimmer LED washes the board less -- the halo's one brightness cue."""

    def wash(k: float) -> int:
        surface = pygame.Surface((400, 400))
        surface.fill(THEME.pcb_bg)
        _draw_glow(surface, (200, 200), 21, (255, 30, 30), k)
        return surface.get_at((200, 200))[0]  # red channel at the center

    washes = [wash(k) for k in (0.1, 0.4, 0.7, 1.0)]
    assert washes == sorted(washes), f"halo must brighten monotonically: {washes}"
    assert washes[0] < washes[-1]


def test_both_led_kinds_share_one_glow_implementation():
    """The duplication that motivated this helper must not creep back."""
    import inspect

    from fpga_sim.ui import components

    source = inspect.getsource(components)
    assert source.count("pygame.SRCALPHA") == 1, (
        "a second translucent-surface blit appeared: fold it into _draw_glow "
        "rather than copying it, or the two halos will drift apart"
    )
    for method in (LED.draw, RGBLED.draw):
        assert "_draw_glow" in inspect.getsource(method)
