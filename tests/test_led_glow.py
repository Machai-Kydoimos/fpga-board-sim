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

from fpga_sim.ui.components import LED, RGBLED, _draw_glow, _perceptual, glow_radius
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


# ── The radius policy (glow_radius) ───────────────────────────────────────────
#
# The halo's size is the one thing about it that carries brightness information
# beyond alpha, and the policy is load-bearing for how a dim board reads.  These
# pin the policy itself; the invariants above pin that no policy can move an LED.


@pytest.mark.parametrize("led_radius", [4, 11, 21, 40])
def test_halo_is_unchanged_at_full_brightness(headless_pygame, led_radius):
    """The compatibility pin: k=1 must reproduce the fixed radius this replaced.

    Every board screenshot and every visual review of a fully-lit LED predates
    the dynamic radius; if this drifts, all of them silently become wrong.
    """
    assert glow_radius(led_radius, 1.0) == 2 * led_radius


@pytest.mark.parametrize("led_radius", [4, 11, 21, 40])
def test_halo_shrinks_monotonically_as_the_led_dims(headless_pygame, led_radius):
    radii = [glow_radius(led_radius, _perceptual(d)) for d in (1.0, 0.5, 0.3, 0.1, 0.01)]
    assert radii == sorted(radii, reverse=True), f"halo must shrink as duty falls: {radii}"
    assert radii[0] > radii[-1]


def test_halo_radius_tracks_perceptual_brightness_linearly(headless_pygame):
    """Radius is linear in k -- which is what makes alpha x area linear in duty.

    Both halves scale with k, so the painted light goes as ``k * r^2 == k^3``,
    and k is ``d ** (1/3)``: the halo's total ink is exactly proportional to the
    LED's real duty cycle.  Asserting the ratio rather than the ink keeps the
    check exact (integer rounding aside) instead of chasing a tolerance.
    """
    for d in (1.0, 0.75, 0.5, 0.3, 0.1):
        k = _perceptual(d)
        assert glow_radius(200, k) / 400 == pytest.approx(k, abs=0.005)


def test_halo_is_not_floored_at_the_led_body(headless_pygame):
    """A floor at the body radius is the tempting mistake -- it must stay out.

    It reads as protecting the halo's visibility, but below k=0.5 there is
    nothing to protect: the halo is behind the opaque body either way.  What a
    floor actually does is hold the halo at full size while it is invisible,
    which keeps a dim board's PCB washed -- the defect this policy exists to
    fix (see ``test_dim_leds_leave_the_board_between_them_unwashed``).
    """
    for d in (0.1, 0.03, 0.01):
        assert glow_radius(21, _perceptual(d)) < 21


@pytest.mark.parametrize("led_radius", [1, 4, 40])
@pytest.mark.parametrize("k", [0.001, 0.05, 0.2])
def test_a_lit_led_always_paints_a_halo(headless_pygame, led_radius, k):
    """The 1px floor: never a zero radius, which would mean a 0x0 scratch surface.

    ``_draw_glow`` promises a lit LED paints *something*; a small LED at a low
    level is where that promise and the shrinking radius meet.
    """
    assert glow_radius(led_radius, k) >= 1


def test_dim_leds_leave_the_board_between_them_unwashed(headless_pygame):
    """The defect this policy fixes, measured on a real board.

    A DE10-Lite's LEDs sit on a 60px pitch with a 21px body, so the midpoint
    between two neighbors is 30px from each.  The old fixed 42px halo covered it
    from both sides at *any* brightness, so a whole row at 30% duty turned the
    PCB green from (34,139,34) into (88,120,38) -- a board-wide wash the design
    never asked for.  A radius that tracks brightness clears the midpoint the
    moment the LEDs are meaningfully dim, while full brightness still glows.
    """
    from fpga_sim.board_loader import discover_boards, get_default_boards_path
    from fpga_sim.generate_board_images import render_board_raster
    from fpga_sim.ui import FPGABoard

    bd = next(
        b for b in discover_boards(get_default_boards_path()) if b.class_name == "DE10LitePlatform"
    )

    def midpoints(duty: float) -> list[tuple[int, ...]]:
        board = FPGABoard(board_def=bd, width=1024, height=700)
        for i in range(len(board.leds)):
            board.set_led_level(i, duty)
        surface = render_board_raster(board)
        centers = [led.rect.center for led in board.leds]
        return [
            surface.get_at(((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))[:3]
            for a, b in zip(centers, centers[1:], strict=False)  # pairwise: one short
        ]

    pcb = tuple(THEME.pcb_bg)
    for duty in (0.3, 0.1):
        assert all(px == pcb for px in midpoints(duty)), (
            f"LEDs at {duty:.0%} duty washed the board between them: {midpoints(duty)[:3]}"
        )
    # ...and the halo has not simply been deleted: at full drive it still meets.
    assert all(px != pcb for px in midpoints(1.0))
