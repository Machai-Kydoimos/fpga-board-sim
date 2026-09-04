"""End-to-end: the label cache survives a real simulation, with and without input.

``tests/test_render_text_cache.py`` covers the cache's contract in isolation.
What it cannot cover is the thing that would actually bite: a *long, live* run
where the board is redrawn thousands of times while a real simulator drives the
LEDs and a user throws switches, holds and latches buttons, and taps keys. Those
are the paths that could plausibly mutate a shared surface -- pressed states,
latch markers, key badges, hover overlays -- and a corrupted cache would show as
a garbled or stale label rather than a crash.

The check is deliberately not "the dict still has the right keys". It is
**pixel equality against a cold cache**: draw the board with the warm cache,
clear the cache, draw again, and require the two frames to be identical. If any
draw had mutated a cached surface, the warm frame carries the damage and the
cold one does not.

Runs on **NVC** (`--sim nvc`), so the simulator half is a real elaboration and
run rather than a fake child.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

import pygame
import pytest

from fpga_sim.sim_link import drain
from fpga_sim.ui.constants import render_text

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef
    from fpga_sim.sim_bridge import SimChild

from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
DESIGN = PROJECT / "hdl" / "counter_7seg.vhd"


def _board() -> BoardDef:
    """DE10-Lite: 10 LEDs, 10 switches, 2 buttons and a 6-digit display.

    Chosen because it exercises every widget kind that renders a label, which is
    every kind that can touch the cache -- 28 cached strings per frame.
    """
    from fpga_sim.board_loader import discover_boards, get_default_boards_path

    boards = discover_boards(get_default_boards_path())
    board = next((b for b in boards if b.class_name == "DE10LitePlatform"), None)
    assert board is not None, "DE10-Lite board not found"
    return board


def _wait_connected(child: SimChild, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if child.link.wait_connected(0.1):
            return
    raise AssertionError("the simulation child never connected")


def _pump(screen: Any, seconds: float) -> int:
    """Feed the screen whatever the child has sent, redrawing each time."""
    frames = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for kind, payload in drain(screen.child.link.conn):
            if kind == "state":
                screen._last_state = payload
        screen._apply_state()
        screen._render_frame()
        frames += 1
        time.sleep(0.002)
    return frames


def _pixels(surface: pygame.Surface) -> bytes:
    return pygame.image.tobytes(surface, "RGBA")


def _frame(screen: Any) -> bytes:
    # Force the U23 dirty gate open: a redraw that the gate skips would compare
    # two untouched buffers and pass no matter what the cache held.
    screen._last_frame_sig = None
    screen._render_frame()
    return pygame.image.tobytes(screen.screen, "RGB")


def _click(pos: tuple[int, int], button: int = 1) -> None:
    for kind in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        pygame.event.post(pygame.event.Event(kind, {"pos": pos, "button": button}))


def _run(screen: Any, board: Any, *, interact: bool) -> int:
    """Drive the screen for a while; optionally throw every switch and button."""
    frames = _pump(screen, 1.5)
    if not interact:
        return frames + _pump(screen, 1.5)

    # Switches: press, drag-paint across the bank, release (U44 phase 5).
    first, last = board.switches[0].rect.center, board.switches[-1].rect.center
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": first, "button": 1}))
    pygame.event.post(
        pygame.event.Event(
            pygame.MOUSEMOTION,
            {"pos": last, "rel": (last[0] - first[0], 0), "buttons": (1, 0, 0)},
        )
    )
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": last, "button": 1}))
    screen._pump_events()
    frames += _pump(screen, 0.5)

    # Buttons: a plain hold, then a right-click latch (U44 phase 3).
    btn = board.buttons[0].rect.center
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": btn, "button": 1}))
    screen._pump_events()
    frames += _pump(screen, 0.3)
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, {"pos": btn, "button": 1}))
    _click(board.buttons[-1].rect.center, button=3)  # latch
    screen._pump_events()
    frames += _pump(screen, 0.5)

    # A keyboard hold, which draws the on-face key badge (U44 phase 4).
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {"key": pygame.K_0, "scancode": 39}))
    screen._pump_events()
    frames += _pump(screen, 0.3)
    pygame.event.post(pygame.event.Event(pygame.KEYUP, {"key": pygame.K_0, "scancode": 39}))
    screen._pump_events()

    # Hover, which draws the tooltip overlay over the board (U3).
    pygame.event.post(
        pygame.event.Event(
            pygame.MOUSEMOTION,
            {"pos": board.leds[0].rect.center, "rel": (1, 1), "buttons": (0, 0, 0)},
        )
    )
    screen._pump_events()
    return frames + _pump(screen, 0.5)


def _keys_used(screen: Any, monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Record the ``(font, text, color)`` keys one real frame actually asks for.

    Discovered rather than predicted: an earlier version of the sibling unit
    test guessed the label font size, guessed wrong (the board draws at 13, not
    12), and so inspected an entry no draw had ever touched -- a deliberate
    corruption walked straight past it.
    """
    seen: list[Any] = []

    def spy(font: Any, text: str, color: Any) -> Any:
        seen.append((font, text, color))
        return render_text(font, text, color)

    # Patched by dotted path: components imports the name, so the module object
    # has no declared attribute for it.
    monkeypatch.setattr("fpga_sim.ui.components.render_text", spy)
    screen._last_frame_sig = None
    screen._render_frame()
    monkeypatch.undo()
    return list(dict.fromkeys(seen))


def _assert_cache_intact(screen: Any, frames: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two independent checks after the run: the frame, and the surfaces."""
    assert frames > 50, f"only {frames} frames drawn -- the run was too short to prove much"
    assert render_text.cache_info().hits > 0, "labels were never served from the cache"

    # 1. A warm-cache frame must equal a cold-cache one. Catches a stale or
    #    wrongly-keyed entry: the kind of damage that survives across frames.
    warm = _frame(screen)
    render_text.cache_clear()
    cold = _frame(screen)
    assert warm == cold, (
        "a warm-cache frame differs from a cold-cache one: the run left a stale "
        "or wrongly-keyed entry behind"
    )

    # 2. Every surface the frame uses must still be pristine after more drawing.
    #    Catches a widget mutating what it was handed -- which check 1 cannot,
    #    because a mutation reapplied identically on the cold pass cancels out.
    keys = _keys_used(screen, monkeypatch)
    assert len(keys) >= 28, f"expected every widget label, saw {len(keys)}"
    render_text.cache_clear()
    pristine = []
    for key in keys:
        surf = render_text(*key)
        pristine.append((key, surf, _pixels(surf), (surf.get_alpha(), surf.get_colorkey())))
    for _ in range(5):
        screen._last_frame_sig = None
        screen._render_frame()
    for key, surf, pixels, flags in pristine:
        assert _pixels(surf) == pixels, f"a draw mutated the shared surface for {key[1]!r}"
        assert (surf.get_alpha(), surf.get_colorkey()) == flags, (
            f"a draw set an alpha or colorkey on the shared surface for {key[1]!r}"
        )


@pytest.mark.slow
@pytest.mark.parametrize("interact", [False, True], ids=["idle", "with-input"])
def test_label_cache_survives_a_real_nvc_run(nvc, headless_pygame, monkeypatch, interact):
    from fpga_sim.controller import build_generics
    from fpga_sim.sim_bridge import SimulatorInfo, finish_waveform, start_simulation
    from fpga_sim.ui import SimulationScreen

    board_def = _board()
    child = start_simulation(
        board_def.to_json(),
        DESIGN,
        DESIGN.stem,
        build_generics(board_def, simulator="nvc"),
        simulator=cast(Any, "nvc"),
        board_def=board_def,
        speed_factor=0.1,
    )
    try:
        _wait_connected(child)
        surface = headless_pygame.display.set_mode((1024, 700))
        screen = SimulationScreen(
            surface,
            headless_pygame.time.Clock(),
            board_def,
            child,
            speed_factor=0.1,
            match=None,
            vhdl_path=DESIGN,
            sim=SimulatorInfo("nvc", nvc, "nvc", "NVC", "nvc"),
        )
        screen._connected = True
        render_text.cache_clear()
        frames = _run(screen, screen.board, interact=interact)
        _assert_cache_intact(screen, frames, monkeypatch)
    finally:
        pygame.event.clear()
        child.stop()
        finish_waveform(child)
