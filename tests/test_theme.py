"""Tests for the consolidated color theme (D15).

These guard the value-preserving refactor: every semantic role must be a valid
color, the cross-process PCB-blue gradient must stay shared, and a few known
shades are pinned so an accidental edit to a role default is caught.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from fpga_sim.ui.theme import THEME, Theme
from fpga_sim.ui.widgets.button import ButtonStyle


def _is_rgb(value: object) -> bool:
    return (
        isinstance(value, tuple)
        and len(value) == 3
        and all(isinstance(c, int) and 0 <= c <= 255 for c in value)
    )


def test_theme_is_frozen_dataclass() -> None:
    assert dataclasses.is_dataclass(THEME)
    assert isinstance(THEME, Theme)
    attr = "led_on"  # indirect so ruff B010 doesn't rewrite to an attribute assignment
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(THEME, attr, (0, 0, 0))


def test_every_role_is_rgb_or_buttonstyle() -> None:
    for f in dataclasses.fields(THEME):
        value = getattr(THEME, f.name)
        if isinstance(value, ButtonStyle):
            assert _is_rgb(value.bg) and _is_rgb(value.bg_hover)
            assert _is_rgb(value.fg) and _is_rgb(value.border)
            for opt in (value.bg_disabled, value.fg_disabled, value.border_disabled):
                assert opt is None or _is_rgb(opt)
        elif isinstance(value, Mapping):
            assert value and all(_is_rgb(v) for v in value.values())
        else:
            assert _is_rgb(value), f"{f.name} is not a valid RGB: {value!r}"


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("pcb_bg", (34, 139, 34)),
        ("led_on", (255, 30, 30)),
        ("led_off", (80, 0, 0)),
        ("switch_on", (80, 140, 255)),
        ("seg_on", (255, 140, 0)),
        ("sel_bg", (30, 30, 40)),
        ("panel_bg", (30, 30, 40)),
        ("info_green", (180, 220, 180)),
    ],
)
def test_known_role_values_preserved(role: str, expected: tuple[int, int, int]) -> None:
    assert getattr(THEME, role) == expected


def test_pcb_blue_gradient_shared() -> None:
    # The cross-process PCB-blue pair must stay identical across all three buttons.
    pair = ((20, 60, 110), (30, 80, 140))
    for btn in (THEME.btn_load_vhdl, THEME.btn_sim_toggle_ghdl, THEME.btn_sim_pause):
        assert (btn.bg, btn.bg_hover) == pair


def test_vendor_colors_present_and_immutable() -> None:
    assert set(THEME.vendor_colors) == {"Xilinx", "Intel", "Lattice", "QuickLogic", "Gowin"}
    assert isinstance(THEME.vendor_colors, MappingProxyType)
