"""Tests for FPGABoard hover-tooltip tracking (U3)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from fpga_sim.board_loader import BoardDef, ComponentInfo
from fpga_sim.ui.board_display import HOVER_TOOLTIP_MS

if TYPE_CHECKING:
    from types import ModuleType

    from fpga_sim.ui import FPGABoard


def _sample_board() -> BoardDef:
    return BoardDef(
        name="Test Board",
        class_name="TestBoard",
        leds=[ComponentInfo("led", "led", i, [f"P{i}"], direction="o") for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, [], direction="i") for i in range(2)],
        switches=[ComponentInfo("switch", "switch", i, [], direction="i") for i in range(4)],
    )


def _make_board(headless_pygame: ModuleType) -> FPGABoard:
    from fpga_sim.ui import FPGABoard

    headless_pygame.display.set_mode((1024, 700))
    return FPGABoard(board_def=_sample_board(), width=1024, height=700)


# ── unified component list + hit-testing ─────────────────────────────────────


def test_components_list_is_leds_then_switches_then_buttons(headless_pygame):
    board = _make_board(headless_pygame)
    assert board.components == [*board.leds, *board.switches, *board.buttons]
    assert len(board.components) == 4 + 4 + 2


def test_component_at_hits_the_switch_under_the_cursor(headless_pygame):
    board = _make_board(headless_pygame)
    sw = board.switches[1]
    assert board._component_at(sw.rect.center) is sw


def test_component_at_returns_none_off_all_components(headless_pygame):
    board = _make_board(headless_pygame)
    assert board._component_at((-50, -50)) is None


# ── dwell timer ──────────────────────────────────────────────────────────────


def test_update_hover_requires_the_dwell_interval(headless_pygame):
    board = _make_board(headless_pygame)
    sw = board.switches[0]
    pos = sw.rect.center
    assert board._update_hover(pos, 1000) is None  # dwell starts
    assert board._update_hover(pos, 1000 + HOVER_TOOLTIP_MS - 1) is None
    assert board._update_hover(pos, 1000 + HOVER_TOOLTIP_MS) is sw  # threshold met


def test_update_hover_resets_when_moving_to_a_new_component(headless_pygame):
    board = _make_board(headless_pygame)
    sw = board.switches[0]
    led = board.leds[0]
    assert board._update_hover(sw.rect.center, 0) is None
    assert board._update_hover(sw.rect.center, HOVER_TOOLTIP_MS) is sw
    # Moving to a different component restarts the timer.
    assert board._update_hover(led.rect.center, HOVER_TOOLTIP_MS + 1) is None
    assert board._update_hover(led.rect.center, 2 * HOVER_TOOLTIP_MS + 1) is led


def test_update_hover_clears_when_cursor_leaves_all_components(headless_pygame):
    board = _make_board(headless_pygame)
    sw = board.switches[0]
    assert board._update_hover(sw.rect.center, 0) is None
    assert board._update_hover(sw.rect.center, HOVER_TOOLTIP_MS) is sw
    assert board._update_hover((-99, -99), HOVER_TOOLTIP_MS + 10) is None


# ── _draw wiring ─────────────────────────────────────────────────────────────


def test_draw_renders_tooltip_only_after_dwell(headless_pygame, monkeypatch):
    board = _make_board(headless_pygame)
    sw = board.switches[0]
    calls: list[tuple[tuple[int, int], str, ComponentInfo | None]] = []

    def _spy(surface, pos, label, info):
        calls.append((pos, label, info))
        return pygame.Rect(0, 0, 1, 1)

    monkeypatch.setattr(board._tooltip, "draw", _spy)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: sw.rect.center)

    monkeypatch.setattr(pygame.time, "get_ticks", lambda: 5000)
    board._draw()  # dwell starts this frame → no tooltip yet
    assert calls == []

    monkeypatch.setattr(pygame.time, "get_ticks", lambda: 5000 + HOVER_TOOLTIP_MS)
    board._draw()  # dwell met → tooltip drawn once, for the hovered switch
    assert len(calls) == 1
    assert calls[0][1] == sw.label


def test_draw_renders_tooltip_in_sim_mode_without_footer(headless_pygame, monkeypatch):
    """The sim subprocess draws with show_footer=False; tooltips must still fire."""
    board = _make_board(headless_pygame)
    board._show_footer = False
    led = board.leds[0]
    calls: list[str] = []

    def _spy(surface, pos, label, info):
        calls.append(label)
        return pygame.Rect(0, 0, 1, 1)

    monkeypatch.setattr(board._tooltip, "draw", _spy)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: led.rect.center)
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: 0)
    board._draw(flip=False)
    monkeypatch.setattr(pygame.time, "get_ticks", lambda: HOVER_TOOLTIP_MS)
    board._draw(flip=False)
    assert calls == [led.label]
