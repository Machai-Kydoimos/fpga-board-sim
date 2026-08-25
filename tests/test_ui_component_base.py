"""Tests for the UIComponent abstract base shared by LED / Switch / Button (D3)."""

from __future__ import annotations

import pygame
import pytest

from fpga_sim.board_loader import ComponentInfo
from fpga_sim.ui.components import LED, Button, Switch, UIComponent

# ── Inheritance & abstractness ───────────────────────────────────────────────


def test_led_switch_button_are_uicomponents():
    """LED, Switch, and Button must all inherit the shared base."""
    for cls in (LED, Switch, Button):
        assert issubclass(cls, UIComponent)


def test_uicomponent_is_abstract():
    """The base declares an abstract draw(), so it cannot be instantiated bare."""
    with pytest.raises(TypeError):
        UIComponent(0)  # type: ignore[abstract]


# ── Shared attributes from the base __init__ ─────────────────────────────────


@pytest.mark.parametrize("cls", [LED, Switch, Button])
def test_shared_attributes_present(cls):
    """Every subclass exposes index / info / rect from the base __init__."""
    c = cls(2)
    assert c.index == 2
    assert c.info is None
    assert isinstance(c.rect, pygame.Rect)
    assert c.rect == pygame.Rect(0, 0, 0, 0)


@pytest.mark.parametrize("cls", [LED, Switch, Button])
def test_info_is_stored(cls):
    """A ComponentInfo passed positionally or by keyword is retained."""
    info = ComponentInfo("led", "led", 0)
    assert cls(0, info).info is info
    assert cls(0, info=info).info is info


# ── Subclass-specific interactive state is preserved ─────────────────────────


def test_led_default_state():
    led = LED(0)
    assert led.state is False
    assert not hasattr(led, "callback")  # LEDs are read-only


def test_switch_defaults():
    sw = Switch(0)
    assert sw.state is False
    assert sw.callback is None


def test_button_defaults():
    btn = Button(0)
    assert btn.pressed is False
    assert btn.callback is None


# ── Unified label derivation (prefix fallback vs ComponentInfo) ──────────────


@pytest.mark.parametrize(
    ("cls", "prefix"),
    [(LED, "LED"), (Switch, "SW"), (Button, "BTN")],
)
def test_label_fallback_prefix(cls, prefix):
    """With no ComponentInfo the label is the class prefix plus the index."""
    assert cls(0).label == f"{prefix}0"
    assert cls(7).label == f"{prefix}7"


def test_label_prefers_component_info_display_name():
    """When info is present, label follows info.display_name, not the prefix."""
    # "button_up" → display_name "UP3"; proves the BTN prefix is not used.
    btn = Button(3, ComponentInfo("button", "button_up", 3))
    assert btn.info is not None and btn.info.display_name == "UP3"
    assert btn.label == "UP3"


# ── The heterogeneous list[UIComponent] that U3 hover hit-testing relies on ──


def test_uniform_access_across_a_mixed_component_list():
    """A single list[UIComponent] exposes label / info / rect uniformly."""
    comps: list[UIComponent] = [LED(0), Switch(1), Button(2)]
    assert [c.label for c in comps] == ["LED0", "SW1", "BTN2"]
    assert all(c.info is None for c in comps)
    assert all(isinstance(c.rect, pygame.Rect) for c in comps)


# ── Button hold sources (U44) ────────────────────────────────────────────────


def test_button_pressed_setter_is_state_only():
    """Assigning .pressed must change state and fire nothing (invariant 1)."""
    btn = Button(0)
    fired: list[tuple[int, bool]] = []
    btn.callback = lambda idx, state, _info: fired.append((idx, state))

    btn.pressed = True
    assert btn.pressed is True
    btn.pressed = False
    assert btn.pressed is False
    assert fired == []


def test_button_pressed_setter_clears_every_source():
    """`.pressed = False` is a full reset, not just the direct source."""
    btn = Button(0)
    btn.hold("mouse:1")
    btn.hold("key:30")
    btn.pressed = False
    assert btn.holds == frozenset()


def test_button_multiple_hold_sources():
    """The button stays down until the *last* source lets go, in any order."""
    btn = Button(0)
    btn.hold("mouse:1")
    btn.hold("key:30")
    assert btn.pressed is True

    btn.handle_release("mouse:1")
    assert btn.pressed is True  # the key still holds it
    btn.handle_release("key:30")
    assert btn.pressed is False


def test_button_callback_fires_once_per_edge():
    """Adding/removing sources mid-hold must not fire; only edges do (invariant 2)."""
    btn = Button(0)
    fired: list[tuple[int, bool]] = []
    btn.callback = lambda idx, state, _info: fired.append((idx, state))

    btn.hold("mouse:1")
    btn.hold("key:30")
    btn.hold("latch")
    assert fired == [(0, True)]

    btn.handle_release("key:30")
    assert fired == [(0, True)]

    btn.handle_release()  # clears the two remaining sources at once
    assert fired == [(0, True), (0, False)]


def test_button_release_unknown_source_is_noop():
    """Releasing a source that never held the button changes nothing."""
    btn = Button(0)
    fired: list[tuple[int, bool]] = []
    btn.callback = lambda idx, state, _info: fired.append((idx, state))

    btn.handle_release("key:99")
    assert fired == []

    btn.hold("mouse:1")
    btn.handle_release("key:99")
    assert btn.pressed is True
    assert fired == [(0, True)]


def test_button_release_transient_keeps_the_latch():
    """Focus loss drops live holds; a latch is deliberate state and survives."""
    btn = Button(0)
    fired: list[tuple[int, bool]] = []
    btn.callback = lambda idx, state, _info: fired.append((idx, state))

    btn.hold("mouse:1")
    btn.hold(Button.LATCH_SOURCE)
    btn.release_transient()
    assert btn.pressed is True
    assert btn.holds == frozenset({Button.LATCH_SOURCE})
    assert fired == [(0, True)]  # no release edge — it never went up


def test_button_release_transient_fires_once_when_it_goes_up():
    """With no latch held, release_transient() reports exactly one release."""
    btn = Button(0)
    fired: list[tuple[int, bool]] = []
    btn.callback = lambda idx, state, _info: fired.append((idx, state))

    btn.hold("mouse:1")
    btn.hold("key:30")
    btn.release_transient()
    assert btn.pressed is False
    assert fired == [(0, True), (0, False)]


def test_button_handle_press_records_its_source():
    """A hit press registers the caller's source token; a miss changes nothing."""
    btn = Button(0)
    btn.rect = pygame.Rect(10, 10, 20, 20)

    assert btn.handle_press((15, 15), "mouse:1") is True
    assert btn.holds == frozenset({"mouse:1"})
    assert btn.handle_press((100, 100), "mouse:3") is False
    assert btn.holds == frozenset({"mouse:1"})


# ── Latching (U44 phase 3) ───────────────────────────────────────────────────


def test_button_toggle_latch_round_trip():
    """Right-click semantics: latch, then unlatch, with one callback each way."""
    btn = Button(0)
    fired: list[tuple[int, bool]] = []
    btn.callback = lambda idx, state, _info: fired.append((idx, state))

    btn.toggle_latch()
    assert btn.pressed is True
    assert btn.latched is True
    btn.toggle_latch()
    assert btn.pressed is False
    assert btn.latched is False
    assert fired == [(0, True), (0, False)]


def test_latch_and_live_hold_are_independent():
    """A latch outlives the mouse; releasing the latch leaves a key hold alone."""
    btn = Button(0)
    btn.hold("mouse:1")
    btn.toggle_latch()
    btn.handle_release("mouse:1")
    assert btn.pressed is True  # the latch keeps it down
    assert btn.latched is True

    btn.hold("key:30")
    btn.toggle_latch()  # unlatch
    assert btn.latched is False
    assert btn.pressed is True  # the key still holds it


def test_pressed_setter_does_not_forge_a_latch():
    """`.pressed = True` is a plain hold, not a latch (capture_frames uses it)."""
    btn = Button(0)
    btn.pressed = True
    assert btn.pressed is True
    assert btn.latched is False


def test_button_tooltip_names_the_vector_bit_and_gesture():
    """The bit disambiguates duplicate labels; the gesture row teaches latching."""
    btn = Button(3)
    rows = dict(btn.tooltip_extra)
    assert rows["Bit"] == "btn(3)"
    assert "Right-click" in rows
    assert "Latched" not in rows  # only shown once it actually is

    btn.toggle_latch()
    assert dict(btn.tooltip_extra)["Latched"] == "yes"


def test_switch_tooltip_names_the_vector_bit():
    assert dict(Switch(11).tooltip_extra)["Bit"] == "sw(11)"


# ── Latch marker: padlock, with the ring as fallback (U44) ───────────────────


def _draw_button(headless_pygame, btn, size=(120, 62)):
    """Render *btn* onto a blank surface and return it."""
    from fpga_sim.ui.constants import get_font

    surf = headless_pygame.Surface(size)
    surf.fill((0, 0, 0))
    btn.rect = headless_pygame.Rect(0, 0, *size)
    btn.draw(surf, get_font(12))
    return surf


def _pixels(surf):
    return {
        surf.get_at((x, y))[:3] for x in range(surf.get_width()) for y in range(surf.get_height())
    }


def _has_near(pixels, color, tol=6):
    """True if any pixel is within *tol* per channel of *color*.

    Smoothscale plus the 8-bit multiply blend land the ink a few levels off its
    nominal value, so an exact-match assertion would be testing the blend's
    rounding rather than whether the padlock was drawn.
    """
    return any(all(abs(p[i] - color[i]) <= tol for i in range(3)) for p in pixels)


def test_latched_button_draws_the_padlock(headless_pygame):
    """The latched button must paint the icon's ink, which held never does."""
    from fpga_sim.ui.theme import THEME

    held = Button(0)
    held.hold("mouse:1")
    latched = Button(0)
    latched.toggle_latch()

    assert _has_near(_pixels(_draw_button(headless_pygame, latched)), THEME.latch_icon_ink)
    assert not _has_near(_pixels(_draw_button(headless_pygame, held)), THEME.latch_icon_ink)


def test_latched_button_falls_back_to_the_ring_without_the_asset(
    headless_pygame, tmp_path, monkeypatch
):
    """A missing asset must still leave the latch visually distinct.

    This is why `icons.latch_icon` returns None instead of raising: the button
    quietly reverts to the inset ring rather than losing the state cue.
    """
    from fpga_sim.ui import icons

    monkeypatch.setattr(icons, "_ASSET_DIR", tmp_path)
    icons.clear_cache()

    latched = Button(0)
    latched.toggle_latch()
    px = _pixels(_draw_button(headless_pygame, latched))
    icons.clear_cache()

    held = Button(0)
    held.hold("mouse:1")
    assert px != _pixels(_draw_button(headless_pygame, held))


def test_tiny_latched_button_falls_back_to_the_ring(headless_pygame):
    """Below the glyph floor the icon declines, so the ring takes over."""
    from fpga_sim.ui import icons
    from fpga_sim.ui.theme import THEME

    icons.clear_cache()
    latched = Button(0)
    latched.toggle_latch()
    # 0.34 * 14 = 5 px, under MIN_ICON_PX.
    px = _pixels(_draw_button(headless_pygame, latched, size=(20, 14)))
    assert not _has_near(px, THEME.latch_icon_ink)


# ── Badge placement (U44 phase 4 review fixes) ───────────────────────────────


def _ink_box(surf, color, tol=40):
    """Bounding box of pixels close to *color*, or None."""
    import pygame as _pg

    xs, ys = [], []
    for x in range(surf.get_width()):
        for y in range(surf.get_height()):
            p = surf.get_at((x, y))
            if all(abs(p[i] - color[i]) <= tol for i in range(3)):
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return _pg.Rect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


@pytest.mark.parametrize("size", [(171, 81), (120, 62), (62, 56)])
def test_badge_ink_is_vertically_centered(headless_pygame, size):
    """`render` reserves descender room digits never use.

    Centering the *surface* therefore floats the visible mark above the middle
    — by 3 px at the sizes a large button uses, which reads as a misalignment.
    The glyph's ink box is what must be centered.
    """
    from fpga_sim.ui.theme import THEME

    btn = Button(3)
    surf = _draw_button(headless_pygame, btn, size=size)
    box = _ink_box(surf, THEME.badge_ink)
    assert box is not None, "no badge was drawn"
    assert abs(box.centery - btn.rect.centery) <= 2
    assert abs(box.centerx - btn.rect.centerx) <= 2


@pytest.mark.parametrize("size", [(171, 81), (73, 48), (62, 56), (40, 30), (24, 24)])
def test_badge_never_overlaps_the_latch_corner(headless_pygame, size):
    """A centered badge and the corner padlock must not collide.

    They did on near-square buttons: the 62x56 ULX3S overlapped by 7 px, while
    wide buttons stayed clear — which is why it survived the first screenshots.
    """
    btn = Button(3)
    btn.rect = headless_pygame.Rect(0, 0, *size)
    budget = btn._badge_budget()
    if budget == 0:
        pytest.skip("no badge fits at this size")

    badge = headless_pygame.Rect(0, 0, budget, budget)
    badge.center = btn.rect.center
    icon = round(min(size) * Button._LATCH_ICON_SCALE)
    pad = Button._LATCH_ICON_PAD
    lock = headless_pygame.Rect(btn.rect.right - pad - icon, btn.rect.top + pad, icon, icon)
    assert not badge.colliderect(lock)


def test_badge_size_does_not_change_when_latched(headless_pygame):
    """The corner is reserved always — a badge that resized on right-click
    would read as a glitch rather than as feedback."""
    btn = Button(3)
    btn.rect = headless_pygame.Rect(0, 0, 62, 56)
    before = btn._badge_budget()
    btn.toggle_latch()
    assert btn._badge_budget() == before
