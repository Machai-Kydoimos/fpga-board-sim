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
    from collections.abc import Callable
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
    """A widget callback marks input dirty; the frame flush is what sends (U44)."""
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen.board.switches[0].state = True
    screen._on_switch(0, True, None)
    screen._flush_input()
    msgs = _collect(client, 1)
    assert msgs[0][0] == "input"
    assert msgs[0][1]["sw"] == 0b0001
    assert msgs[0][1]["seq"] == 1


# ── Input atomicity: one message per frame (U44) ──────────────────────────────


def _wide_board() -> BoardDef:
    """An 18-switch board -- the fleet maximum (DE2-115, VEEK-MT2)."""
    return BoardDef(
        name="Wide Board",
        class_name="WideBoard",
        vendor="TestVendor",
        device="TestDevice",
        package="QFP100",
        leds=[ComponentInfo("led", "led", i, []) for i in range(4)],
        buttons=[ComponentInfo("button", "button", i, []) for i in range(3)],
        switches=[ComponentInfo("switch", "switch", i, []) for i in range(18)],
    )


def _wide_screen(pygame: ModuleType, child: SimChild) -> SimulationScreen:
    surface = pygame.display.set_mode((1024, 700))
    return SimulationScreen(
        surface,
        pygame.time.Clock(),
        _wide_board(),
        child,
        speed_factor=0.1,
        match=None,
        vhdl_path="blinky.vhd",
        sim=_sim("ghdl"),
    )


def test_reset_on_a_wide_board_sends_exactly_one_message(headless_pygame, fake_child):
    """R changed 18 widgets and sent 18 full-state messages; now it sends one.

    Each send is a complete snapshot, so the extra 17 were pure duplication --
    and if two of them straddled a child drain, the DUT held a half-reset switch
    vector for a whole sim step (up to ~9.6k clock cycles).
    """
    child, client = fake_child
    screen = _wide_screen(headless_pygame, child)
    screen._connected = True
    for sw in screen.board.switches:
        sw.state = True
    screen.board.buttons[0].hold("mouse:1")

    reset = headless_pygame.event.Event(headless_pygame.KEYDOWN, {"key": headless_pygame.K_r})
    screen.board._handle_events([reset])
    screen._flush_input()

    msgs = _collect(client, 1)
    assert len(msgs) == 1
    assert msgs[0][0] == "input"
    assert msgs[0][1] == {"sw": 0, "btn": 0, "seq": 1}


def test_many_changes_in_one_frame_coalesce_to_one_message(headless_pygame, fake_child):
    """Simultaneous switch and button changes reach the DUT atomically."""
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    screen.board.switches[0].state = True
    screen._on_switch(0, True, None)
    screen.board.switches[2].state = True
    screen._on_switch(2, True, None)
    screen.board.buttons[1].hold("key:31")
    screen._on_button(1, True, None)
    screen._flush_input()

    msgs = _collect(client, 1)
    assert len(msgs) == 1
    assert msgs[0][1]["sw"] == 0b0101
    assert msgs[0][1]["btn"] == 0b010
    assert msgs[0][1]["seq"] == 1


def test_flush_without_changes_sends_nothing(headless_pygame, fake_child):
    """A quiet frame must not put a redundant message on the wire."""
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._flush_input()
    screen._flush_input()
    assert _collect(client, 1, timeout=0.1) == []
    assert screen._input_seq == 0


def test_flush_is_idempotent_after_sending(headless_pygame, fake_child):
    """The dirty flag clears on flush, so re-flushing the same frame is a no-op."""
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen.board.switches[0].state = True
    screen._on_switch(0, True, None)
    screen._flush_input()
    screen._flush_input()
    assert len(_collect(client, 2, timeout=0.2)) == 1


def test_input_before_connect_is_delivered_once_connected(headless_pygame, fake_child):
    """Input taken during the connect spinner must not be silently discarded.

    The board widget already showed the switch on, so dropping the message left
    the display claiming a state the DUT had never been told about.
    """
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = False

    screen.board.switches[1].state = True
    screen._on_switch(1, True, None)
    screen._flush_input()
    assert _collect(client, 1, timeout=0.1) == []
    assert screen._input_dirty is True  # still owed

    screen._connected = True
    screen._flush_input()
    msgs = _collect(client, 1)
    assert len(msgs) == 1
    assert msgs[0][1]["sw"] == 0b0010


def test_run_flushes_input_once_per_frame(headless_pygame, fake_child, monkeypatch):
    """run() must call the flush after events are handled, not per callback."""
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    order: list[str] = []

    def _note(name: str) -> Callable[[], None]:
        def _record() -> None:
            order.append(name)

        return _record

    monkeypatch.setattr(screen, "_pump_link", _note("link"))
    monkeypatch.setattr(screen, "_pump_events", _note("events"))
    monkeypatch.setattr(screen, "_flush_input", _note("flush"))
    monkeypatch.setattr(screen, "_render_frame", lambda: None)
    monkeypatch.setattr(screen, "_teardown", lambda *_a: None)

    def _stop_after_two_frames() -> None:
        if order.count("flush") >= 2:
            screen.panel.stop_requested = True

    monkeypatch.setattr(screen, "_sync_controls", _stop_after_two_frames)
    screen.run()

    assert order[:3] == ["link", "events", "flush"]
    assert order.count("flush") == 2


# ── Latching: redraw + chrome z-order (U44 phase 3) ───────────────────────────


def test_render_redraws_on_latch_while_held(headless_pygame, fake_child, monkeypatch):
    """Latching a button the mouse already holds must repaint it.

    `pressed` stays True across the transition, so only the latch entering
    `visual_signature()` breaks the U23 redraw-skip. Fails without that.
    """
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen.board.buttons[0].hold("mouse:1")
    screen._render_frame()
    screen._render_frame()
    drawn = screen.run_stats.frames_drawn

    screen.board.buttons[0].toggle_latch()
    screen._render_frame()
    assert screen.run_stats.frames_drawn == drawn + 1
    assert screen.board.buttons[0].pressed is True


def test_chrome_press_does_not_reach_the_board(headless_pygame, fake_child):
    """A right-click on [Stop] must not latch a button hidden underneath it."""
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()  # populates the chrome rects
    assert screen._stop_btn_rect is not None

    # Park a button exactly under the [Stop] chrome.
    screen.board.buttons[0].rect = screen._stop_btn_rect.copy()
    pos = screen._stop_btn_rect.center
    headless_pygame.event.post(
        headless_pygame.event.Event(headless_pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": 3})
    )
    screen._pump_events()
    assert screen.board.buttons[0].latched is False


def test_chrome_release_still_reaches_the_board(headless_pygame, fake_child):
    """Filtering must not eat a release, or the hold under it is stranded.

    Press a button, drag onto [Stop], let go there: the button has to come up.
    """
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()
    assert screen._stop_btn_rect is not None

    btn = screen.board.buttons[0]
    screen.board._handle_events(
        [
            headless_pygame.event.Event(
                headless_pygame.MOUSEBUTTONDOWN, {"pos": btn.rect.center, "button": 1}
            )
        ]
    )
    assert btn.pressed is True

    headless_pygame.event.post(
        headless_pygame.event.Event(
            headless_pygame.MOUSEBUTTONUP,
            {"pos": screen._stop_btn_rect.center, "button": 1},
        )
    )
    screen._pump_events()
    assert btn.pressed is False


# ── Keyboard holds reach the DUT atomically (U44 phase 4) ────────────────────


def test_two_keys_in_one_frame_send_one_message_with_both_bits(headless_pygame, fake_child):
    """The keyboard is the only device that can express true simultaneity.

    Both KEYDOWNs land in one event batch, so the frame flush must deliver them
    as a single input message — not two, which would let the DUT observe an
    intermediate state that never existed.
    """
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    for key in (headless_pygame.K_1, headless_pygame.K_2):
        headless_pygame.event.post(
            headless_pygame.event.Event(headless_pygame.KEYDOWN, {"key": key, "mod": 0})
        )
    screen._pump_events()
    screen._flush_input()

    msgs = _collect(client, 1)
    assert len(msgs) == 1
    assert msgs[0][1]["btn"] == 0b011
    assert msgs[0][1]["seq"] == 1


def test_help_modal_mid_hold_leaves_nothing_pressed(headless_pygame, fake_child, monkeypatch):
    """F1 while holding a key must not strand the button down.

    HelpDialog runs its own event.get() loop handling only QUIT/RESIZE/KEYDOWN/
    MOUSEBUTTONDOWN, so the KEYUP is discarded — and _run_help_modal then
    *unpauses* the child, leaving the design running with a phantom button.
    """

    class _NoopHelp:
        def __init__(self, _screen: Any) -> None:
            pass

        def run(self, _clock: Any) -> None:
            pass

    monkeypatch.setattr("fpga_sim.ui.simulation_screen.HelpDialog", _NoopHelp)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    screen.board._handle_events(
        [
            headless_pygame.event.Event(
                headless_pygame.KEYDOWN, {"key": headless_pygame.K_1, "mod": 0}
            )
        ]
    )
    assert screen.board.buttons[0].pressed is True

    screen._run_help_modal()
    assert all(not b.pressed for b in screen.board.buttons)
    assert screen.board._key_holds == {}


def test_help_modal_keeps_latches(headless_pygame, fake_child, monkeypatch):
    """Latches are deliberate state; only live holds are transient."""

    class _NoopHelp:
        def __init__(self, _screen: Any) -> None:
            pass

        def run(self, _clock: Any) -> None:
            pass

    monkeypatch.setattr("fpga_sim.ui.simulation_screen.HelpDialog", _NoopHelp)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen.board.buttons[1].toggle_latch()

    screen._run_help_modal()
    assert screen.board.buttons[1].latched is True
    assert screen.board.buttons[1].pressed is True


def test_help_modal_tells_the_child_about_the_release_before_resuming(
    headless_pygame, fake_child, monkeypatch
):
    """The release must reach the child before the modal unpauses it.

    Otherwise the design resumes for a frame still seeing a button that the
    user physically let go of while the overlay was up.
    """

    class _NoopHelp:
        def __init__(self, _screen: Any) -> None:
            pass

        def run(self, _clock: Any) -> None:
            pass

    monkeypatch.setattr("fpga_sim.ui.simulation_screen.HelpDialog", _NoopHelp)
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen.board._handle_events(
        [
            headless_pygame.event.Event(
                headless_pygame.KEYDOWN, {"key": headless_pygame.K_1, "mod": 0}
            )
        ]
    )
    screen._flush_input()
    _collect(client, 1)  # drain the press

    screen._run_help_modal()
    seq = [(kind, payload) for kind, payload in _collect(client, 3)]
    kinds = [k for k, _ in seq]

    assert "input" in kinds, "the release was never sent"
    release_at = kinds.index("input")
    unpause_at = next(i for i, (k, p) in enumerate(seq) if k == "pause" and p.get("on") is False)
    assert release_at < unpause_at
    assert seq[release_at][1]["btn"] == 0


def test_drag_paint_sends_one_message_per_motion_frame(headless_pygame, fake_child):
    """A sweep crossing several switches is still one atomic update per frame.

    Without frame coalescing this would emit one full-state message per switch
    crossed, and two of them straddling a child drain would leave the DUT
    holding a half-painted switch vector for a whole simulation step.
    """
    child, client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()  # lay out the switch rects

    first = screen.board.switches[0].rect.center
    last = screen.board.switches[3].rect.center
    screen.board._handle_events(
        [
            headless_pygame.event.Event(
                headless_pygame.MOUSEBUTTONDOWN, {"pos": first, "button": 1}
            ),
            headless_pygame.event.Event(
                headless_pygame.MOUSEMOTION,
                {
                    "pos": last,
                    "rel": (last[0] - first[0], last[1] - first[1]),
                    "buttons": (1, 0, 0),
                },
            ),
        ]
    )
    screen._flush_input()

    msgs = _collect(client, 1)
    assert len(msgs) == 1
    assert msgs[0][1]["sw"] == 0b1111
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


# ── redraw gating (U23) ───────────────────────────────────────────────────────


def _park_cursor_off_board(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the cursor off every component so hover never forces a redraw (U23)."""
    monkeypatch.setattr("pygame.mouse.get_pos", lambda: (-50, -50))


def test_render_skips_when_nothing_changed(headless_pygame, fake_child, monkeypatch):
    """A second identical frame is skipped: no draw, no flip, no frames_drawn bump."""
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    screen._render_frame()  # first frame always draws (nothing drawn yet)
    assert screen.run_stats.frames_drawn == 1
    screen._render_frame()  # identical → skipped
    screen._render_frame()  # still identical → skipped
    assert screen.run_stats.frames_drawn == 1


def test_render_redraws_on_led_change(headless_pygame, fake_child, monkeypatch):
    """A changed LED level re-dirties the signature, forcing exactly one redraw."""
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    screen._render_frame()
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 1  # settled → skipping

    screen.board.set_led_level(0, 1.0)  # visible state change
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 2
    screen._render_frame()  # settled again
    assert screen.run_stats.frames_drawn == 2


def test_render_redraws_on_switch_and_button_change(headless_pygame, fake_child, monkeypatch):
    """Switch and button state each re-dirty the signature (input still shows)."""
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 1

    screen.board.switches[0].state = True
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 2
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 2

    screen.board.buttons[0].pressed = True
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 3


def test_render_redraws_on_pause_toggle(headless_pygame, fake_child, monkeypatch):
    """Pausing swaps the overlay [PAUSE]/[RESUME] label, so it must redraw."""
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 1

    screen.panel.paused = True
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 2


def test_render_redraws_on_event(headless_pygame, fake_child, monkeypatch):
    """Any pygame event this frame forces a redraw (hover/overlay highlights)."""
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 1

    # _pump_events sets the flag from whatever it drained; a posted event trips it.
    headless_pygame.event.post(
        headless_pygame.event.Event(headless_pygame.MOUSEMOTION, {"pos": (5, 5), "rel": (1, 1)})
    )
    screen._pump_events()
    assert screen._events_this_frame is True
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 2

    # No new events → flag cleared by the next _pump_events → skip resumes.
    screen._pump_events()
    assert screen._events_this_frame is False
    screen._render_frame()
    assert screen.run_stats.frames_drawn == 2


def test_render_redraws_while_hovering_component(headless_pygame, fake_child, monkeypatch):
    """A cursor resting on a component keeps redrawing so its tooltip can appear."""
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    monkeypatch.setattr("pygame.mouse.get_pos", lambda: screen.board.leds[0].rect.center)

    screen._render_frame()
    screen._render_frame()
    screen._render_frame()
    # Every frame redraws while the cursor sits on the LED (no skipping).
    assert screen.run_stats.frames_drawn == 3


def test_render_redraws_on_connect_transition(headless_pygame, fake_child, monkeypatch):
    """The disconnected 'Starting…' banner and the connected view differ (U23)."""
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)

    screen._render_frame()  # waiting banner
    screen._render_frame()  # identical waiting → skipped
    assert screen.run_stats.frames_drawn == 1

    screen._connected = True  # connection established
    screen._render_frame()  # must swap to the connected overlays
    assert screen.run_stats.frames_drawn == 2


def test_skipped_frame_leaves_surface_byte_identical(headless_pygame, fake_child, monkeypatch):
    """A skip is a true no-op on the surface: the pixels equal the last drawn frame.

    This is the correctness guarantee behind U23 — we only skip *redundant*
    redraws, so what stays on screen is exactly what the previous draw produced.
    """
    _park_cursor_off_board(monkeypatch)
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    screen._render_frame()  # draws
    drawn = headless_pygame.image.tobytes(screen.screen, "RGB")
    screen._render_frame()  # skips (nothing changed)
    assert screen.run_stats.frames_drawn == 1  # confirm it really skipped
    skipped = headless_pygame.image.tobytes(screen.screen, "RGB")
    assert skipped == drawn


def test_visual_signature_tracks_state(headless_pygame, fake_child):
    """The board signature changes with LED/seg/switch/button state and size."""
    child, _client = fake_child
    screen = _make_screen(headless_pygame, child, seg=True)
    board = screen.board

    base = board.visual_signature()
    board.set_led_level(0, 0.5)
    assert board.visual_signature() != base

    sig_led = board.visual_signature()
    board.set_seg_levels(0, [1.0, 0, 0, 0, 0, 0, 0, 0])
    assert board.visual_signature() != sig_led

    sig_seg = board.visual_signature()
    board.switches[0].state = True
    assert board.visual_signature() != sig_seg


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
                    screen._flush_input()
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
