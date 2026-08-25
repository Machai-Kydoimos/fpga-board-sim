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
