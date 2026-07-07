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
