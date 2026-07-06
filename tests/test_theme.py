"""Tests for the consolidated color theme (D15) and the theme system (U6).

These guard the value-preserving refactor and the theme registry: every
semantic role must be a valid color in every selectable theme, the
cross-process PCB-blue gradient must stay shared, a few known pcb-green
shades are pinned so an accidental edit to a default is caught, and
``set_theme()`` must swap the shared THEME instance's contents in place —
restoring the defaults exactly on round-trip.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType

import pytest

from fpga_sim.ui.theme import (
    THEME,
    THEME_LABELS,
    THEME_NAMES,
    Theme,
    current_theme_name,
    set_theme,
)
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


@pytest.mark.parametrize("name", THEME_NAMES)
def test_every_role_is_rgb_or_buttonstyle(name: str, restore_theme: None) -> None:
    set_theme(name)
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
            assert _is_rgb(value), f"{name}.{f.name} is not a valid RGB: {value!r}"


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


# ── U6 theme system: registry + in-place swapping ─────────────────────────────


def test_theme_names_and_labels_consistent() -> None:
    assert THEME_NAMES[0] == "pcb-green"  # first entry is the default look
    assert set(THEME_LABELS) == set(THEME_NAMES)
    assert all(THEME_LABELS[n] for n in THEME_NAMES)


@pytest.mark.parametrize("name", THEME_NAMES)
def test_set_theme_applies_every_name(name: str, restore_theme: None) -> None:
    set_theme(name)
    assert current_theme_name() == name


def test_set_theme_swaps_in_place(restore_theme: None) -> None:
    ref = THEME  # simulate a call site's import-time binding
    set_theme("dark")
    assert ref is THEME  # same object, so every importer sees the change
    assert ref.pcb_bg == (30, 32, 36)


def test_themes_are_visually_distinct(restore_theme: None) -> None:
    # The board surface and sim-panel fill are the loudest roles: no two
    # themes may share the pair.
    seen: list[tuple[tuple[int, int, int], tuple[int, int, int]]] = []
    for name in THEME_NAMES:
        set_theme(name)
        seen.append((THEME.pcb_bg, THEME.accent_bar))
    assert len(set(seen)) == len(THEME_NAMES)


def test_round_trip_restores_defaults_exactly(restore_theme: None) -> None:
    set_theme("high-contrast")
    set_theme("pcb-green")
    assert THEME == Theme()
    assert current_theme_name() == "pcb-green"


def test_unknown_name_raises_and_leaves_theme_untouched(restore_theme: None) -> None:
    set_theme("dark")
    with pytest.raises(ValueError, match="unknown theme"):
        set_theme("no-such-theme")
    assert THEME.pcb_bg == (30, 32, 36)
    assert current_theme_name() == "dark"


def test_default_theme_starts_active() -> None:
    # Every theme-switching test restores via the restore_theme fixture, so
    # outside a switch the module default must be the pristine pcb-green.
    assert current_theme_name() == "pcb-green"
    assert THEME == Theme()
