"""Tests for the U34 single-window SimulationScreen.

Unit tests drive the screen's sub-methods against a real ``SimLinkHost`` with an
in-process client standing in for the headless child (no subprocess), so the
message plumbing, state application, and exit classification run for real.  The
``slow`` e2e tests run the whole thing against real GHDL/NVC via
``start_simulation(benchmark_secs=...)``: the child free-runs and self-stops, so
the screen exits deterministically with no event injection required.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pytest

from fpga_sim import sim_link
from fpga_sim.board_loader import BoardDef, ComponentInfo, SevenSegDef
from fpga_sim.sim_bridge import SimChild, SimulatorInfo
from fpga_sim.sim_link import drain, send
from fpga_sim.ui.results import SimExit
from fpga_sim.ui.simulation_screen import SimulationScreen

if TYPE_CHECKING:
    from multiprocessing.connection import Connection
    from types import ModuleType


def _sim(engine: str = "ghdl") -> SimulatorInfo:
    """A SimulatorInfo for the screen under test (display/log only; the run uses PATH)."""
    label = "NVC" if engine == "nvc" else "GHDL"
    backend = "nvc" if engine == "nvc" else "mcode"
    return SimulatorInfo(engine, f"/usr/bin/{engine}", backend, label, f"{engine} 1.0")  # type: ignore[arg-type]


# ── Fakes / fixtures ──────────────────────────────────────────────────────────
# ``fake_child`` (and its ``_FakeProc``) live in conftest, shared with the
# brightness tests, which drive this same screen.


def _sample_board(*, seg: bool = False) -> BoardDef:
    return BoardDef(
        name="Test Board",
        class_name="TestBoard",
        vendor="TestVendor",
        device="TestDevice",
        package="QFP100",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(3)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(4)],
        seven_seg=SevenSegDef(2, True, False, True, False) if seg else None,
    )


@pytest.fixture(autouse=True)
def _isolate_session(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect session writes away from ~/.fpga_simulator for every test."""
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", tmp_path / "session.json")
    monkeypatch.setattr("fpga_sim.sim_session_log._SESSION_DIR", tmp_path / "sessions")


def _make_screen(
    pygame: ModuleType,
    child: SimChild,
    *,
    seg: bool = False,
    show_toolbar: bool = True,
) -> SimulationScreen:
    surface = pygame.display.set_mode((1024, 700))
    return SimulationScreen(
        surface,
        pygame.time.Clock(),
        _sample_board(seg=seg),
        child,
        speed_factor=0.1,
        match=None,
        vhdl_path="blinky.vhd",
        sim=_sim("ghdl"),
        show_toolbar=show_toolbar,
    )


def _collect(conn: Connection, count: int, timeout: float = 2.0) -> list[sim_link.Message]:
    out: list[sim_link.Message] = []
    deadline = time.monotonic() + timeout
    while len(out) < count and time.monotonic() < deadline:
        out += drain(conn)
        if len(out) < count:
            time.sleep(0.005)
    return out


def _pump_state(screen: SimulationScreen, timeout: float = 2.0) -> None:
    """Drain the link until a state message has been applied (loopback lag)."""
    deadline = time.monotonic() + timeout
    while not screen._last_state and time.monotonic() < deadline:
        screen._pump_link()
        time.sleep(0.005)


# ── Unit tests (no subprocess) ────────────────────────────────────────────────


def test_construct_does_not_raise(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    assert screen.board is not None and screen.panel is not None


def test_render_frame_when_connected(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()  # draws board + overlays + flip; must not raise


def test_render_frame_while_waiting(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._render_frame()  # not connected: draws the "Starting..." banner


def test_state_message_applies_leds(headless_pygame, fake_child):
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    send(client, "state", {"led": 0b0101, "seg": None, "sim_ns": 1000, "at_max": False})
    _pump_state(screen)
    assert screen.board.leds[0].state
    assert not screen.board.leds[1].state
    assert screen.board.leds[2].state
    assert not screen.board.leds[3].state


def test_state_message_applies_seg(headless_pygame, fake_child):
    child, client = fake_child
    screen = _make_screen(headless_pygame, child, seg=True)
    screen._connected = True
    # digit 0 = 0x3F, digit 1 = 0x06 → seg = 0x063F
    send(client, "state", {"led": 0, "seg": 0x063F, "sim_ns": 10, "at_max": False})
    _pump_state(screen)
    assert screen.board._seven_segs[0].bits == 0x3F
    assert screen.board._seven_segs[1].bits == 0x06


def test_quit_event_returns_quit(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    headless_pygame.event.post(headless_pygame.event.Event(headless_pygame.QUIT))
    assert screen._pump_events() is SimExit.QUIT


def test_escape_event_returns_stopped(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    ev = headless_pygame.event.Event(headless_pygame.KEYDOWN, {"key": headless_pygame.K_ESCAPE})
    headless_pygame.event.post(ev)
    assert screen._pump_events() is SimExit.STOPPED


def test_d_key_toggles_debug_view_and_persists(
    headless_pygame, fake_child, tmp_path, monkeypatch, restore_debug_view
):
    """U38: the in-sim D hotkey flips the duty-bar view live and saves it."""
    from fpga_sim.session_config import load_session
    from fpga_sim.ui.components import debug_view_enabled

    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", tmp_path / "session.json")
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    key_d = headless_pygame.event.Event(headless_pygame.KEYDOWN, {"key": headless_pygame.K_d})
    headless_pygame.event.post(key_d)
    assert screen._pump_events() is None  # not a navigation key
    assert debug_view_enabled() is True
    assert load_session()["debug_view"] is True

    headless_pygame.event.post(key_d)
    screen._pump_events()
    assert debug_view_enabled() is False
    assert load_session()["debug_view"] is False


def test_bye_message_returns_stopped(headless_pygame, fake_child):
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    send(client, "bye", {"sim_ns": 5, "steps": 3, "wall_s": 0.1})
    result = None
    for _ in range(200):
        result = screen._pump_link()
        if result is not None:
            break
        time.sleep(0.005)
    assert result is SimExit.STOPPED
    assert screen._bye is not None


def test_switch_callback_sends_input(headless_pygame, fake_child):
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen.board.switches[0].state = True
    screen._on_switch(0, True, None)
    msgs = _collect(client, 1)
    assert msgs[0][0] == "input"
    assert msgs[0][1]["sw"] == 0b0001
    assert msgs[0][1]["seq"] == 1


def test_help_modal_pauses_and_resumes(headless_pygame, fake_child, monkeypatch):
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    class _NoopHelp:
        def __init__(self, _screen: Any) -> None:
            pass

        def run(self, _clock: Any) -> None:
            pass

    monkeypatch.setattr("fpga_sim.ui.simulation_screen.HelpDialog", _NoopHelp)
    screen._run_help_modal()
    msgs = _collect(client, 2)
    assert ("pause", {"on": True}) in msgs
    assert ("pause", {"on": False}) in msgs


def test_stop_button_returns_stopped(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()  # populate _stop_btn_rect
    assert screen._stop_btn_rect is not None
    ev = headless_pygame.event.Event(
        headless_pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": screen._stop_btn_rect.center}
    )
    headless_pygame.event.post(ev)
    assert screen._pump_events() is SimExit.STOPPED


def test_toolbar_click_routes_intent(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()  # populate the toolbar hit rects
    assert screen._toolbar is not None and screen._toolbar._hit
    rect, intent = screen._toolbar._hit[0]  # [Back to Boards]
    ev = headless_pygame.event.Event(
        headless_pygame.MOUSEBUTTONDOWN, {"button": 1, "pos": rect.center}
    )
    headless_pygame.event.post(ev)
    assert screen._pump_events() is intent


def test_sync_controls_sends_clk_speed_pause(headless_pygame, fake_child):
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    # First sync sends the initial clk (last_clk_half starts None).
    screen._sync_controls()
    # Change speed + pause, resync.
    screen.panel.speed_factor = 0.5
    screen.panel.paused = True
    screen._sync_controls()
    kinds = [k for k, _ in _collect(client, 3)]
    assert "clk" in kinds
    assert "speed" in kinds
    assert "pause" in kinds


def test_connect_skips_clk_deposit_when_wrapper_default_matches(headless_pygame, fake_child):
    """No redundant clk write at connect — it costs ~4x on GHDL's llvm backend."""
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    half = max(1, int(screen.panel.clk_state["period_ns"] / 2))
    child.generics = {"CLK_HALF_NS_INIT": str(half)}
    assert screen._pump_connect(time.monotonic()) is None
    screen._sync_controls()
    assert not client.poll(0.2)  # panel matches the wrapper default: nothing sent
    assert screen._last_clk_half == half
    # A real user change still syncs.
    screen.panel.clk_state["period_ns"] *= 2
    expected = max(1, int(screen.panel.clk_state["period_ns"] / 2))
    screen._sync_controls()
    kind, payload = _collect(client, 1)[0]
    assert kind == "clk"
    assert payload["half_ns"] == expected


def test_connect_syncs_clk_when_wrapper_default_differs(headless_pygame, fake_child):
    """A panel/wrapper mismatch (e.g. preset snap) is synced on the first frame."""
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    half = max(1, int(screen.panel.clk_state["period_ns"] / 2))
    child.generics = {"CLK_HALF_NS_INIT": str(half * 4)}
    assert screen._pump_connect(time.monotonic()) is None
    screen._sync_controls()
    kind, payload = _collect(client, 1)[0]
    assert kind == "clk"
    assert payload["half_ns"] == half


def test_no_toolbar_when_disabled(headless_pygame, fake_child):
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child, show_toolbar=False)
    assert screen._toolbar is None
    screen._connected = True
    screen._render_frame()  # must not raise with the toolbar absent


# ── e2e against a real simulator (slow) ───────────────────────────────────────


def _arty_board() -> BoardDef | None:
    from fpga_sim.board_loader import discover_boards, get_default_boards_path

    boards = discover_boards(get_default_boards_path())
    return next((b for b in boards if "ArtyA7_35Platform" in (b.class_name, b.name)), None)


def _run_screen_e2e(pygame: ModuleType, simulator: str) -> None:
    """Drive a real headless child through the manual loop, asserting LED + input."""
    from fpga_sim.controller import build_generics
    from fpga_sim.sim_bridge import finish_waveform, start_simulation

    board = _arty_board()
    assert board is not None, "Arty A7-35 board not found"
    project = Path(__file__).resolve().parent.parent
    child = start_simulation(
        board.to_json(),
        project / "hdl" / "blinky.vhd",
        "blinky",
        build_generics(board),
        simulator=cast(Any, simulator),
        board_def=board,
        benchmark_secs=4.0,
    )
    surface = pygame.display.set_mode((1024, 700))
    screen = SimulationScreen(
        surface,
        pygame.time.Clock(),
        board,
        child,
        speed_factor=0.1,
        match=None,
        vhdl_path="blinky.vhd",
        sim=_sim(simulator),
    )
    leds_seen: set[int] = set()
    injected = False
    exit_intent: SimExit | None = None
    session_start = time.monotonic()
    try:
        while exit_intent is None and time.monotonic() - session_start < 40:
            if not screen._connected:
                exit_intent = screen._pump_connect(session_start)
                continue
            exit_intent = screen._pump_link()
            if exit_intent is not None:
                break
            if screen._last_state:
                leds_seen.add(int(screen._last_state.get("led", 0) or 0))
                if not injected:
                    screen.board.switches[0].state = True
                    screen._on_switch(0, True, None)  # input seq 1 -> child echoes it
                    injected = True
            time.sleep(0.01)
        assert exit_intent is SimExit.STOPPED, f"expected STOPPED, got {exit_intent}"
        assert len(leds_seen) > 1, f"LED never changed: {leds_seen}"
        assert int(screen._last_state.get("input_seq", 0)) >= 1, "input did not round-trip"
    finally:
        child.stop()
        finish_waveform(child)


@pytest.mark.slow
def test_e2e_screen_blinky_ghdl(headless_pygame, ghdl):
    _run_screen_e2e(headless_pygame, "ghdl")


@pytest.mark.slow
def test_e2e_screen_blinky_nvc(headless_pygame, nvc):
    _run_screen_e2e(headless_pygame, "nvc")


@pytest.mark.slow
def test_e2e_run_loop_exits_stopped(headless_pygame, ghdl):
    """The real run() loop returns STOPPED when the free-running child sends bye."""
    from fpga_sim.controller import build_generics
    from fpga_sim.sim_bridge import finish_waveform, start_simulation

    board = _arty_board()
    assert board is not None
    project = Path(__file__).resolve().parent.parent
    child = start_simulation(
        board.to_json(),
        project / "hdl" / "blinky.vhd",
        "blinky",
        build_generics(board),
        simulator="ghdl",
        board_def=board,
        benchmark_secs=3.0,
    )
    surface = headless_pygame.display.set_mode((1024, 700))
    screen = SimulationScreen(
        surface,
        headless_pygame.time.Clock(),
        board,
        child,
        speed_factor=0.1,
        match=None,
        vhdl_path="blinky.vhd",
        sim=_sim("ghdl"),
    )
    result = screen.run()
    finish_waveform(child)
    assert result is SimExit.STOPPED
    assert screen.run_stats.frames > 0
    assert screen.run_stats.sim_ns > 0
