"""Inspect mode (U55): the overlay, and the round trip it exists to close.

The feature's whole claim is that a person can read a name off the screen, paste
it into a question, and have the reader land on the right line of code.  So the
centrepiece here is not a unit test of any one part -- it is
``test_end_to_end_*``, which drives the real screen, presses F4, reads the
**system clipboard**, and resolves what it finds through ``docs/ui_map.md`` to a
line of source that it then opens and checks.  Every link in that chain is the
product's own; nothing is recomputed in the test and compared against itself.

The rest are the seams, which is where a feature like this actually breaks:
U23's redraw gate, the ``--screenshots`` guard, the coverage rule that forces
icon-only buttons to be named, and the uniqueness rule that already caught five
Settings rows sharing one address.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

from fpga_sim.ui import inspect
from fpga_sim.ui.clipboard import copy_to_clipboard, read_clipboard
from fpga_sim.ui.constants import _ui_scale
from fpga_sim.ui.results import SimExit
from tests.test_simulation_screen import _make_screen, _pump_state

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from fpga_sim.sim_bridge import SimChild

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
MAP_PATH = REPO_ROOT / "docs" / "ui_map.md"

#: A map row: ``| `path` | kind | `file:line` |``
_MAP_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(\w+)\s*\|\s*`([^`]*)`\s*\|$", re.M)

#: What a line of source that registers a region has to look like.  Broad on
#: purpose -- the test is checking that the map points at *registration* code,
#: not policing how it is spelled.
_REGISTRATION = (
    "inspect.item(",
    "inspect.zone(",
    "inspect.widget(",
    "draw_button(",
    "region=",
)


def _key(pygame: ModuleType, key: int) -> Any:
    """A KEYDOWN event with no ``unicode``/``scancode``, as this suite's others are."""
    return pygame.event.Event(pygame.KEYDOWN, key=key)


def _ui_map() -> dict[str, tuple[str, str]]:
    """Parse ``docs/ui_map.md`` into ``path -> (kind, origin)``."""
    text = MAP_PATH.read_text(encoding="utf-8")
    return {m[1]: (m[2], m[3]) for m in _MAP_ROW.finditer(text)}


@pytest.fixture
def clipboard(headless_pygame: ModuleType) -> None:
    """Skip unless this machine's SDL build really round-trips clipboard text.

    Probed **inside** a test rather than in a ``skipif``, because a
    collection-time probe runs before any display mode is set and so fails on
    every machine -- which would have quietly skipped the two tests that matter
    most here while the suite still reported green.

    Under the dummy video driver SDL keeps its own clipboard, so this neither
    reads nor clobbers the developer's real one (verified on Wayland).
    """
    headless_pygame.display.set_mode((320, 240))
    token = "fpga-sim-clipboard-probe"
    if not (copy_to_clipboard(token) and read_clipboard() == token):
        pytest.skip("no usable clipboard on this machine")


# ── the overlay is off, and free, until asked for ─────────────────────────────


def test_off_by_default() -> None:
    """A fresh process paints no overlay and registers nothing."""
    assert inspect.inspect_enabled() is False
    assert inspect.trace_origins_enabled() is False


def test_registration_is_a_no_op_while_off(headless_pygame: ModuleType) -> None:
    """Registering while off must cost nothing and record nothing.

    This is the property that lets the calls sit on the hot path unguarded.
    """
    inspect.begin_frame("select")
    inspect.zone("list", headless_pygame.Rect(0, 0, 10, 10))
    inspect.item("row", headless_pygame.Rect(0, 0, 5, 5))
    assert inspect.regions() == ()


def test_f3_toggles_from_the_event_stream(headless_pygame: ModuleType) -> None:
    """F3 flips the flag and is consumed, so nothing downstream sees it."""
    ev = _key(headless_pygame, inspect.TOGGLE_KEY)
    assert inspect.handle_key(ev) is True
    assert inspect.inspect_enabled() is True
    assert inspect.handle_key(_key(headless_pygame, inspect.TOGGLE_KEY)) is True
    assert inspect.inspect_enabled() is False


def test_an_unrelated_key_is_not_consumed(headless_pygame: ModuleType) -> None:
    """Every other key falls straight through -- the overlay changes no behavior."""
    assert inspect.handle_key(_key(headless_pygame, headless_pygame.K_s)) is False
    assert inspect.handle_key(_key(headless_pygame, headless_pygame.K_d)) is False
    assert inspect.handle_key(_key(headless_pygame, headless_pygame.K_a)) is False


def test_one_f3_through_the_sim_screens_real_loop_turns_it_on(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection]
) -> None:
    """One press, one toggle -- driven through ``_pump_events``, not ``handle_key``.

    This is the regression for the bug that shipped in the first cut and was
    found by running the app: the simulation screen composes two handlers over
    **one** event list -- the embedded board's ``_handle_events`` and its own
    key chain -- so F3 was consumed twice and the overlay turned on and straight
    back off inside a single frame. Every other screen handles it once, which is
    exactly why the selector, preview and picker all worked and only the screen
    somebody actually reaches by running a design did not.

    The existing tests all called ``handle_key`` directly or set the flag, so
    none of them composed anything. Press the key through the loop.
    """
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    headless_pygame.event.post(_key(headless_pygame, inspect.TOGGLE_KEY))
    screen._pump_events()
    assert inspect.inspect_enabled() is True, "one F3 did not turn the overlay on"

    headless_pygame.event.post(_key(headless_pygame, inspect.TOGGLE_KEY))
    screen._pump_events()
    assert inspect.inspect_enabled() is False, "a second F3 did not turn it off"


def test_one_f3_through_every_other_screens_real_loop(headless_pygame: ModuleType) -> None:
    """The same single-toggle rule on the selector, the picker and the preview.

    Each dispatches KEYDOWN its own way, so "it works on one" says nothing about
    the others -- the sim-screen bug is the proof.
    """
    from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
    from fpga_sim.ui.board_display import FPGABoard
    from fpga_sim.ui.board_selector import BoardSelector
    from fpga_sim.ui.vhdl_picker import VHDLFilePicker

    surface = headless_pygame.display.set_mode((1024, 700))
    boards = discover_boards(get_default_boards_path())
    board_def = find_board(boards, "DE10-Standard")

    selector = BoardSelector(boards, surface)
    picker = VHDLFilePicker(surface, str(REPO_ROOT / "hdl"))
    preview = FPGABoard(board_def=board_def, screen=surface, width=1024, height=700)

    presses: list[tuple[str, object]] = [
        ("select", lambda ev: selector._handle_keydown(ev)),
        ("pick", lambda ev: picker._handle_keydown(ev)),
        ("preview", lambda ev: preview._handle_events([ev])),
    ]
    for name, press in presses:
        inspect.set_inspect(False)
        press(_key(headless_pygame, inspect.TOGGLE_KEY))  # type: ignore[operator]
        assert inspect.inspect_enabled() is True, f"one F3 did nothing on {name}"
        press(_key(headless_pygame, inspect.TOGGLE_KEY))  # type: ignore[operator]
        assert inspect.inspect_enabled() is False, f"a second F3 did nothing on {name}"


def test_one_f4_through_a_real_loop_copies_exactly_once(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection], monkeypatch: Any
) -> None:
    """F4 was double-handled by the same defect as F3 -- count the copies, do not infer them.

    The F3 symptom was loud (on-then-off, so nothing happened). F4's was silent:
    two copies of identical text land on the clipboard looking exactly like one,
    and only the duplicated stdout line gave it away. A boolean "did it copy?"
    assertion passes either way, so this counts.
    """
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    copies: list[str] = []

    def _spy(text: str) -> bool:
        copies.append(text)
        return True

    monkeypatch.setattr(inspect, "copy_to_clipboard", _spy)

    inspect.set_inspect(True)
    screen._events_this_frame = True
    screen._render_frame()
    target = next(r for r in inspect.regions() if r.path == "sim.overlay.stop")
    headless_pygame.mouse.set_pos(target.rect.center)
    headless_pygame.event.pump()

    headless_pygame.event.post(_key(headless_pygame, inspect.COPY_KEY))
    screen._pump_events()
    assert len(copies) == 1, f"one F4 produced {len(copies)} copies"
    assert copies[0].startswith("sim.overlay.stop · ")


def test_one_f4_on_the_preview_copies_exactly_once(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """The preview routes keys through ``FPGABoard._handle_events`` instead."""
    from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
    from fpga_sim.ui.board_display import FPGABoard

    surface = headless_pygame.display.set_mode((1024, 700))
    board_def = find_board(discover_boards(get_default_boards_path()), "DE10-Standard")
    board = FPGABoard(board_def=board_def, screen=surface, width=1024, height=700)

    copies: list[str] = []

    def _spy(text: str) -> bool:
        copies.append(text)
        return True

    monkeypatch.setattr(inspect, "copy_to_clipboard", _spy)

    inspect.set_inspect(True)
    board._draw(flip=False)
    target = next(r for r in inspect.regions() if r.path.endswith("board.led[0]"))
    headless_pygame.mouse.set_pos(target.rect.center)
    headless_pygame.event.pump()

    board._handle_events([_key(headless_pygame, inspect.COPY_KEY)])
    assert len(copies) == 1, f"one F4 produced {len(copies)} copies"
    assert copies[0].startswith("preview.board.led[0] · ")


# ── addressing ────────────────────────────────────────────────────────────────


def test_hover_resolves_the_smallest_containing_region(headless_pygame: ModuleType) -> None:
    """A widget always beats the zone it sits inside, whatever the order."""
    inspect.set_inspect(True)
    inspect.begin_frame("sim")
    inspect.zone("panel", headless_pygame.Rect(0, 0, 100, 100))
    inspect.item("panel.speed.slider", headless_pygame.Rect(40, 40, 10, 10))
    inside = inspect.hovered((45, 45))
    assert inside is not None and inside.path == "sim.panel.speed.slider"
    outside = inspect.hovered((5, 5))
    assert outside is not None and outside.path == "sim.panel"
    assert inspect.hovered((500, 500)) is None


def test_a_label_that_reduces_to_nothing_is_loud(headless_pygame: ModuleType) -> None:
    """An icon-only button must not register a path with a trailing dot."""
    assert inspect.slug("?") == inspect.UNNAMED
    assert inspect.slug("") == inspect.UNNAMED
    assert inspect.slug("Back to Boards") == "back-to-boards"


def test_context_stamp_names_the_build_and_the_state(headless_pygame: ModuleType) -> None:
    """The stamp carries what a report needs and cannot be guessed from a path."""
    inspect.begin_frame("sim")
    inspect.set_context(
        board={"name": "DE10-Standard"},
        design={"file": "blinky.vhd", "mode": "generic"},
        simulator={"label": "GHDL-LLVM"},
    )
    stamp = inspect.context_stamp()
    assert "fpga-sim " in stamp
    for fact in ("sim", "DE10-Standard", "blinky.vhd", "GHDL-LLVM"):
        assert fact in stamp, f"{fact!r} missing from {stamp!r}"


def test_context_fields_can_be_cleared(headless_pygame: ModuleType) -> None:
    """``None`` is how "no design loaded" gets said."""
    inspect.set_context(design={"file": "blinky.vhd", "mode": "generic"})
    assert "blinky.vhd" in inspect.context_stamp()
    inspect.set_context(design=None)
    assert "blinky.vhd" not in inspect.context_stamp()


def test_type_scales_with_the_window_like_every_other_widget(
    headless_pygame: ModuleType,
) -> None:
    """Fixed point sizes were the first cut's mistake, found by running the app.

    The board, its captions and its buttons all size themselves off
    ``_ui_scale``, so an overlay drawn at a constant size shrinks *relative to
    everything around it* as the window grows -- unreadable at full screen while
    every test passed. Assert the relationship, not a pixel count.
    """
    small = inspect._px(inspect._PATH_PT, _ui_scale(1024, 700), inspect._MIN_PATH_PT)
    large = inspect._px(inspect._PATH_PT, _ui_scale(1920, 1080), inspect._MIN_PATH_PT)
    huge = inspect._px(inspect._PATH_PT, _ui_scale(3840, 2160), inspect._MIN_PATH_PT)
    assert small < large < huge, f"type did not grow with the window: {small}, {large}, {huge}"
    # The address is the string somebody reads off the screen and retypes, so it
    # is deliberately the largest thing the overlay draws.
    assert inspect._PATH_PT > inspect._STAMP_PT >= inspect._LABEL_PT


def test_a_tiny_window_falls_back_to_the_floor(headless_pygame: ModuleType) -> None:
    """Small is acceptable; illegible is not."""
    tiny = inspect._px(inspect._PATH_PT, _ui_scale(320, 240), inspect._MIN_PATH_PT)
    assert tiny == inspect._MIN_PATH_PT


def test_the_scale_override_is_read_clamped_and_survives_junk(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """The env knob exists because legibility cannot be settled from in here."""
    monkeypatch.delenv(inspect._SCALE_ENV, raising=False)
    assert inspect._env_scale() == 1.0
    monkeypatch.setenv(inspect._SCALE_ENV, "1.5")
    assert inspect._env_scale() == 1.5
    # Clamped: a zero would draw nothing, a huge one would fill the window.
    monkeypatch.setenv(inspect._SCALE_ENV, "0")
    assert inspect._env_scale() == 0.5
    monkeypatch.setenv(inspect._SCALE_ENV, "99")
    assert inspect._env_scale() == 4.0
    # Junk degrades to the default rather than taking down the frame.
    for junk in ("", "   ", "big", "1.2.3"):
        monkeypatch.setenv(inspect._SCALE_ENV, junk)
        assert inspect._env_scale() == 1.0, f"{junk!r} did not fall back"


def _shift_f3(pygame_mod: ModuleType) -> Any:
    """A shift-F3 chord, as SDL delivers it."""
    return pygame_mod.event.Event(
        pygame_mod.KEYDOWN, key=inspect.TOGGLE_KEY, mod=pygame_mod.KMOD_LSHIFT
    )


def test_shift_f3_cycles_the_size_and_plain_f3_still_toggles(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """The chord must not fall through to the toggle, or resizing would also hide it."""
    # ``_isolate_session_file`` (conftest, autouse) already points the session
    # file at a tmp dir, so the persisting write here touches nothing real.
    monkeypatch.delenv(inspect._SCALE_ENV, raising=False)

    assert inspect.handle_key(_key(headless_pygame, inspect.TOGGLE_KEY)) is True
    assert inspect.inspect_enabled() is True

    seen = []
    for _ in range(len(inspect.SCALE_STEPS) + 1):
        assert inspect.handle_key(_shift_f3(headless_pygame)) is True
        assert inspect.inspect_enabled() is True, "shift-F3 also toggled the overlay off"
        seen.append(inspect.user_scale())

    assert set(seen) == set(inspect.SCALE_STEPS), f"did not visit every step: {seen}"
    # One press past a full lap lands back where the first press did.
    assert seen[len(inspect.SCALE_STEPS)] == seen[0], f"the cycle did not wrap: {seen}"
    # And the plain key is untouched by any of it.
    assert inspect.handle_key(_key(headless_pygame, inspect.TOGGLE_KEY)) is True
    assert inspect.inspect_enabled() is False


def test_shift_f3_is_left_alone_while_the_overlay_is_off(headless_pygame: ModuleType) -> None:
    """There is nothing on screen to resize, so the chord is not consumed."""
    assert inspect.inspect_enabled() is False
    assert inspect.handle_key(_shift_f3(headless_pygame)) is False
    assert inspect.user_scale() is None


def test_a_chosen_size_beats_the_environment_default(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """Not env-wins, unlike the waveform settings -- and deliberately so.

    There the variable exists so CI can force a choice. Here it supplies a
    starting point for somebody about to adjust it by eye, and a control that
    visibly did nothing would be worse than a variable being superseded by the
    very reader it was set for. A restart brings the variable back.
    """
    monkeypatch.setenv(inspect._SCALE_ENV, "2.0")
    surface = headless_pygame.display.set_mode((1024, 700))

    inspect.set_user_scale(None)
    assert inspect._scale(surface) == pytest.approx(_ui_scale(1024, 700) * 2.0)

    inspect.set_user_scale(1.25)
    assert inspect._scale(surface) == pytest.approx(_ui_scale(1024, 700) * 1.25)

    inspect.set_user_scale(None)
    assert inspect._scale(surface) == pytest.approx(_ui_scale(1024, 700) * 2.0)


def test_a_chosen_size_is_persisted_and_restored(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """The size describes the display, so it outlives the run -- unlike on/off."""
    from fpga_sim.__main__ import _restore_session_inspect_scale

    written: dict[str, object] = {}
    monkeypatch.setattr("fpga_sim.session_config.update_session", lambda **kw: written.update(kw))
    monkeypatch.delenv(inspect._SCALE_ENV, raising=False)
    inspect.set_inspect(True)
    inspect.handle_key(_shift_f3(headless_pygame))

    assert written == {inspect.SCALE_SESSION_KEY: inspect.user_scale()}

    # A fresh process restores it; the on/off state is not restored at all.
    inspect.set_user_scale(None)
    _restore_session_inspect_scale({inspect.SCALE_SESSION_KEY: 1.6})
    assert inspect.user_scale() == 1.6
    # Junk and a stray bool leave it unset rather than resizing to nothing.
    for junk in ({"inspect_scale": "big"}, {"inspect_scale": True}, {}):
        inspect.set_user_scale(None)
        _restore_session_inspect_scale(junk)
        assert inspect.user_scale() is None, f"{junk} was accepted"


def test_the_readout_wraps_instead_of_spanning_the_window(headless_pygame: ModuleType) -> None:
    """A stamp naming seven facts must not set the box's width to the screen's."""
    font = headless_pygame.font.SysFont("consolas", 14)
    stamp = (
        "fpga-sim 0.22.0+gabc1234 · sim · DE10-Standard · blinky.vhd · GHDL-LLVM · dark · 1920x1080"
    )
    max_w = 400
    lines = inspect._wrap(stamp, font, max_w)
    assert len(lines) > 1, "a long stamp did not wrap"
    assert all(font.size(line)[0] <= max_w for line in lines[:-1])
    # Wrapped on the separator, so no fact is split across two lines.
    assert " · ".join(lines) == stamp
    assert "DE10-Standard" in " ".join(lines)


def _shift_f4(pygame_mod: ModuleType) -> Any:
    """A shift-F4 chord, as SDL delivers it."""
    return pygame_mod.event.Event(
        pygame_mod.KEYDOWN, key=inspect.COPY_KEY, mod=pygame_mod.KMOD_LSHIFT
    )


def test_shift_f4_copies_valid_json_carrying_what_a_reader_cannot_see(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """The record must parse, and must carry the facts that are invisible on screen.

    Asserted against the JSON the product actually produced and re-parsed, not
    against a dict rebuilt here -- a record that cannot survive ``json.loads`` is
    no use to whoever receives it.
    """
    from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
    from fpga_sim.ui.board_display import FPGABoard

    surface = headless_pygame.display.set_mode((1280, 800))
    board_def = find_board(discover_boards(get_default_boards_path()), "DE10-Standard")
    board = FPGABoard(board_def=board_def, screen=surface, width=1280, height=800)
    board.inspect_scope = "sim"

    copies: list[str] = []

    def _spy(text: str) -> bool:
        copies.append(text)
        return True

    monkeypatch.setattr(inspect, "copy_to_clipboard", _spy)
    inspect.set_inspect(True)
    inspect.set_context(
        board={"name": "DE10-Standard", "source": "custom"},
        design={"file": "blinky.vhd", "mode": "board-native", "generics": {"COUNTER_BITS": "17"}},
        simulator={"label": "GHDL-LLVM", "version": "GHDL 5.0.0"},
        run={"sim_ns": 12400000, "paused": False, "speed": 1.0, "clock_hz": 50000000.0},
    )
    # Deliberately unequal: a fixture where measurement and display agree could
    # not catch the record reading the wrong one of them.
    board.leds[3].duty = 0.37
    board.leds[3].level = 0.42
    board._draw(flip=False)

    target = next(r for r in inspect.regions() if r.path == "sim.board.led[3]")
    headless_pygame.mouse.set_pos(target.rect.center)
    headless_pygame.event.pump()
    assert inspect.handle_key(_shift_f4(headless_pygame)) is True
    assert len(copies) == 1

    doc = json.loads(copies[0])
    assert doc["at"] == "sim.board.led[3]"
    assert doc["screen"] == "sim"
    # The three things a reader can neither see on screen nor guess.
    assert doc["design"]["mode"] == "board-native"
    assert doc["design"]["generics"] == {"COUNTER_BITS": "17"}
    assert doc["run"]["sim_ns"] == 12400000
    # And the one they can see but cannot quote precisely.
    assert doc["value"] == {"duty_pct": 37.0, "displayed_pct": 42.0}
    # Host and toolchain are deliberately absent; the record says where to get them.
    assert "host" not in doc and "python" not in doc
    assert "--doctor" in doc["more"]


def test_plain_f4_stays_a_single_line(headless_pygame: ModuleType, monkeypatch: Any) -> None:
    """The two formats exist because the two readers want opposite things.

    A review pastes a dozen of these inline; a fifteen-line blob each time would
    make that unusable. Guard the property, not the exact wording.
    """
    copies: list[str] = []

    def _spy(text: str) -> bool:
        copies.append(text)
        return True

    monkeypatch.setattr(inspect, "copy_to_clipboard", _spy)
    inspect.set_inspect(True)
    inspect.begin_frame("sim")
    inspect.set_context(design={"file": "blinky.vhd", "mode": "generic"})
    assert inspect.handle_key(_key(headless_pygame, inspect.COPY_KEY)) is True

    assert "\n" not in copies[0], "the short copy is not one line"
    assert not copies[0].lstrip().startswith("{"), "the short copy is JSON"
    # The design mode rides along, since it changes how every LED complaint reads.
    assert "blinky.vhd (generic)" in copies[0]


def test_an_led_reports_its_duty_even_when_fully_on_or_off(
    headless_pygame: ModuleType,
) -> None:
    """The hover tooltip elides 0% and 100%; a report must not.

    In a tooltip an exact 0 or 100 is uninformative noise. In a report the
    number *is* the answer to "this LED looks wrong", and a missing field reads
    as missing data rather than as a clean zero.
    """
    from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
    from fpga_sim.ui.board_display import FPGABoard

    surface = headless_pygame.display.set_mode((1280, 800))
    board_def = find_board(discover_boards(get_default_boards_path()), "DE10-Standard")
    board = FPGABoard(board_def=board_def, screen=surface, width=1280, height=800)
    inspect.set_inspect(True)

    for duty in (0.0, 1.0, 0.375):
        board.leds[0].duty = duty
        board.leds[0].level = duty
        board._draw(flip=False)
        region = next(r for r in inspect.regions() if r.path.endswith("board.led[0]"))
        assert dict(region.value) == {
            "duty_pct": round(duty * 100, 1),
            "displayed_pct": round(duty * 100, 1),
        }
    # The tooltip's own rule is unchanged: it still hides the binary cases.
    board.leds[0].level = 1.0
    assert board.leds[0].tooltip_extra == []


def test_measured_duty_survives_the_led_pwm_display_toggle(
    headless_pygame: ModuleType,
    fake_child: tuple[SimChild, Connection],
    restore_pwm_display: None,
) -> None:
    """Reporting the *displayed* level as a duty would be a lie in both modes.

    With the LED PWM display off (U47) the renderer is handed the raw bit, so an
    LED the design drives at 42% displays 100%. With it on, the displayed value
    is a persistence-of-vision EMA of the measurement, so it is *still* not the
    measurement. The record therefore carries both, and the ``display`` block
    says which mode produced the second -- otherwise the gap between them reads
    as a bug.

    Driven through the real link and the real ``_apply_state``, because the
    whole defect lives in that routing rather than in anything the record does.
    """
    from fpga_sim.sim_link import send
    from fpga_sim.ui.components import set_pwm_display

    child, conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    inspect.set_inspect(True)

    send(conn, "state", {"led": 0b1, "led_duty": [0.42, 0.0, 0.0, 0.0], "sim_ns": 1000})
    _pump_state(screen)

    seen = {}
    for pwm in (True, False):
        set_pwm_display(pwm)
        screen._apply_state()
        screen._events_this_frame = True
        screen._render_frame()
        region = next(r for r in inspect.regions() if r.path.endswith("board.led[0]"))
        seen[pwm] = dict(region.value)
        assert inspect.report(region)["display"]["led_pwm"] is pwm

    # The measurement is the same in both modes, because it is the same design.
    assert seen[True]["duty_pct"] == pytest.approx(42.0)
    assert seen[False]["duty_pct"] == pytest.approx(42.0)
    # The displayed value is not, and with PWM off it is the raw bit.
    assert seen[False]["displayed_pct"] == pytest.approx(100.0)
    assert seen[True]["displayed_pct"] != pytest.approx(42.0), (
        "the displayed level happened to equal the duty — pick a case where they differ"
    )


def test_the_run_block_does_not_outlive_the_run(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection]
) -> None:
    """A report filed from the preview must not quote a run that has ended."""
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    inspect.set_inspect(True)
    screen._events_this_frame = True
    screen._render_frame()
    assert "run" in inspect.report(None), "the sim screen never published its run state"

    screen._teardown(SimExit.STOPPED, time.monotonic())
    assert "run" not in inspect.report(None), "the run block survived the run"


def test_the_led_index_is_a_widget_index_not_a_channel_index(
    headless_pygame: ModuleType,
) -> None:
    """The address indexes widgets; the screenshot manifest indexes channels.

    They coincide only while a board is all-mono, and the docs used to claim
    they always did -- caught by working a real report against the 8-mono +
    4-RGB Myminieye Runber, where ``board.led[7]`` is the fourth RGB site and
    the manifest's channel 7 is the eighth mono LED. A reader who mixed them up
    would file a report against the wrong LED.
    """
    from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
    from fpga_sim.manifest import led_legend
    from fpga_sim.ui.board_display import FPGABoard
    from fpga_sim.ui.components import RGBLED

    surface = headless_pygame.display.set_mode((1280, 800))
    board_def = find_board(discover_boards(get_default_boards_path()), "Myminieye Runber")
    assert board_def is not None and board_def.num_rgb_leds > 0, "pick a board with RGB LEDs"

    board = FPGABoard(board_def=board_def, screen=surface, width=1280, height=800)
    inspect.set_inspect(True)
    board._draw(flip=False)

    region = next(r for r in inspect.regions() if r.path.endswith("board.led[7]"))
    # Widget 7 is an RGB site, so the value carries three channels.
    assert isinstance(board.leds[7], RGBLED)
    assert {k for k, _ in region.value} == {
        "r_duty_pct",
        "r_displayed_pct",
        "g_duty_pct",
        "g_displayed_pct",
        "b_duty_pct",
        "b_displayed_pct",
    }
    # Channel 7 in the manifest's numbering is a different LED entirely.
    assert led_legend(board_def)[7]["role"] == "mono"
    assert len(board.leds) != board_def.num_led_channels, (
        "this board cannot distinguish the two numberings"
    )


def test_the_surfaces_a_confused_reader_reaches_are_addressable() -> None:
    """Coverage is the feature. A screen with no address cannot be reported on.

    These four were the gaps a per-screen audit found: the stall advisory (the
    control that appears exactly when somebody is confused), the two scrolling
    lists, the analysis spinner, and the help dialog's prose sections — which
    had two addresses for a screen that is almost entirely text.
    """
    addresses = set(_ui_map())
    required = {
        "sim.stall.offer",
        "sim.stall.panel",
        "sim.stall.close",
        "select.list.row[i]",
        "pick.list.row[i]",
        "spinner.panel",
        "dlg.help.workflow",
        "dlg.help.keyboard-shortcuts",
        "dlg.help.vhdl-design-contract",
    }
    assert required <= addresses, f"no longer addressable: {sorted(required - addresses)}"


def test_a_list_row_reports_which_entry_it_is(headless_pygame: ModuleType) -> None:
    """A row index alone is worthless once the filter changes; carry the name."""
    from fpga_sim.board_loader import discover_boards, get_default_boards_path
    from fpga_sim.ui.board_selector import BoardSelector

    surface = headless_pygame.display.set_mode((1280, 800))
    boards = discover_boards(get_default_boards_path())
    selector = BoardSelector(boards, surface)
    inspect.set_inspect(True)
    selector._draw()

    rows = [r for r in inspect.regions() if ".list.row[" in r.path]
    assert rows, "the selector registered no list rows"
    named = dict(rows[0].value)
    assert named.get("board"), f"a row carried no board name: {rows[0].value}"
    # The name must be the board actually drawn on that row.
    assert named["board"] == selector._filtered()[0].name


def test_the_record_carries_geometry(headless_pygame: ModuleType) -> None:
    """A layout complaint is a statement about a rect, so the record must hold one."""
    inspect.set_inspect(True)
    inspect.begin_frame("sim")
    inspect.item("overlay.stop", headless_pygame.Rect(11, 22, 33, 44))
    target = inspect.hovered((12, 23))
    assert target is not None
    assert inspect.report(target)["rect"] == [11, 22, 33, 44]


# ── the seams ─────────────────────────────────────────────────────────────────


def test_toggling_changes_the_u23_frame_signature(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection]
) -> None:
    """Without this, F3 on a static board would draw nothing (U23).

    Asserted against the signature the screen actually builds, by reading
    ``_last_frame_sig`` after a render -- not against a tuple rebuilt here.
    """
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._render_frame()
    before = screen._last_frame_sig

    inspect.set_inspect(True)
    screen._render_frame()
    assert screen._last_frame_sig != before, "toggling the overlay left the frame unchanged"


def test_cursor_movement_changes_the_signature_only_while_on(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection]
) -> None:
    """The cursor is in the signature, but only when something reads it."""
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True

    headless_pygame.mouse.set_pos((10, 10))
    screen._render_frame()
    off_a = screen._last_frame_sig
    headless_pygame.mouse.set_pos((300, 300))
    screen._render_frame()
    assert screen._last_frame_sig == off_a, "the cursor moved the signature while off"

    inspect.set_inspect(True)
    headless_pygame.mouse.set_pos((10, 10))
    screen._render_frame()
    on_a = screen._last_frame_sig
    headless_pygame.mouse.set_pos((300, 300))
    screen._render_frame()
    assert screen._last_frame_sig != on_a, "the cursor did not move the signature while on"


def test_the_preview_paints_the_overlay_itself(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """The preview owns its flip, so it must paint the overlay on the way there.

    The two screens reach the overlay by different routes -- the preview draws
    it inside ``FPGABoard._draw``, the simulation screen draws it later, after
    its screenshot capture -- so covering one says nothing about the other.
    """
    from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
    from fpga_sim.ui.board_display import FPGABoard

    surface = headless_pygame.display.set_mode((1024, 700))
    board_def = find_board(discover_boards(get_default_boards_path()), "DE10-Standard")
    board = FPGABoard(board_def=board_def, screen=surface, width=1024, height=700)
    inspect.set_inspect(True)

    painted: list[int] = []
    monkeypatch.setattr(inspect, "draw_overlay", lambda surf: painted.append(1))

    board._draw(flip=False)
    assert painted == [], "the composited path painted its own overlay twice"
    board._draw(flip=True)
    assert painted == [1], "the preview did not paint the overlay before its flip"


def test_board_parts_are_registered_but_never_badged(headless_pygame: ModuleType) -> None:
    """57 badges would be less readable than none; the readout names them instead."""
    from fpga_sim.board_loader import discover_boards, find_board, get_default_boards_path
    from fpga_sim.ui.board_display import FPGABoard

    surface = headless_pygame.display.set_mode((1280, 800))
    board_def = find_board(discover_boards(get_default_boards_path()), "DE2-115")
    board = FPGABoard(board_def=board_def, screen=surface, width=1280, height=800)
    inspect.set_inspect(True)
    board._draw(flip=False)

    parts = [r for r in inspect.regions() if ".board." in r.path and r.kind != "zone"]
    assert len(parts) > 40, f"only {len(parts)} board parts registered"
    badged = [r.path for r in parts if r.kind != "widget"]
    assert not badged, f"board parts registered as badged chrome: {badged[:5]}"
    # Still addressable, which is the point of registering them at all.
    led = next(r for r in parts if r.path == "sim.board.led[3]" or r.path.endswith("led[3]"))
    assert inspect.hovered(led.rect.center) is not None


def test_a_benchmark_frame_never_paints_the_overlay(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection], monkeypatch: Any
) -> None:
    """``interactive=False`` is what keeps this out of every generated still."""
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    screen._interactive = False
    inspect.set_inspect(True)

    painted: list[int] = []
    monkeypatch.setattr(inspect, "draw_overlay", lambda surface: painted.append(1))
    screen._render_frame()
    assert painted == [], "a non-interactive frame painted the inspect overlay"

    screen._interactive = True
    screen._events_this_frame = True
    screen._render_frame()
    assert painted == [1], "an interactive frame did not paint the inspect overlay"


# ── coverage and uniqueness, over every screen the map knows ───────────────────


def test_there_are_addresses_to_check() -> None:
    """A gate that scans nothing passes vacuously."""
    rows = _ui_map()
    assert len(rows) > 40, f"only {len(rows)} addresses parsed from {MAP_PATH.name}"


def test_no_screen_registers_an_unnamed_region() -> None:
    """Every button gets a real name -- including the two drawn as icons.

    ``slug`` turns a label of "?" or "" into ``UNNAMED``, so this is the rule
    that forces those two call sites to pass an explicit ``region``.
    """
    offenders = [path for path in _ui_map() if path.endswith(f".{inspect.UNNAMED}")]
    assert not offenders, f"unnamed regions: {offenders}"


def test_every_address_is_unique() -> None:
    """Two places must never answer to one name.

    This rule found a real defect on its first run: five Settings rows are
    labeled "Toggle", so deriving their addresses from the button text gave all
    five of them ``dlg.settings.toggle``.
    """
    text = MAP_PATH.read_text(encoding="utf-8")
    paths = [m[1] for m in _MAP_ROW.finditer(text)]
    duplicates = {p for p in paths if paths.count(p) > 1}
    assert not duplicates, f"duplicate addresses: {sorted(duplicates)}"


def test_the_uniqueness_rule_would_actually_fail(headless_pygame: ModuleType) -> None:
    """A gate that has only ever agreed with itself proves nothing.

    Register the same address twice and confirm the collision is visible in what
    a frame produced -- otherwise the test above could be passing because the
    check is inert rather than because the product is clean.
    """
    inspect.set_inspect(True)
    inspect.begin_frame("dlg.settings")
    inspect.item("toggle", headless_pygame.Rect(0, 0, 10, 10))
    inspect.item("toggle", headless_pygame.Rect(20, 0, 10, 10))
    paths = [r.path for r in inspect.regions()]
    assert paths.count("dlg.settings.toggle") == 2
    duplicates = {p for p in paths if paths.count(p) > 1}
    assert duplicates, "a duplicate address did not register as a duplicate"


def test_the_map_is_up_to_date() -> None:
    """``docs/ui_map.md`` must agree with what the product registers today."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import gen_ui_map

    assert gen_ui_map.main(["--check"]) == 0, (
        "docs/ui_map.md is stale — run `uv run python scripts/gen_ui_map.py`"
    )


def test_every_mapped_address_points_at_registration_code() -> None:
    """Each row's ``file:line`` must be a line that really registers a region.

    The map is only worth having if the second column can be followed.
    """
    bad: list[str] = []
    for path, (_kind, origin) in sorted(_ui_map().items()):
        file_part, _, line_part = origin.rpartition(":")
        source = SRC / file_part
        if not source.exists():
            bad.append(f"{path}: no such file {origin}")
            continue
        lines = source.read_text(encoding="utf-8").splitlines()
        n = int(line_part)
        if not 1 <= n <= len(lines):
            bad.append(f"{path}: {origin} is past the end of the file")
            continue
        # A multi-line call reports the line the call *starts* on, so look at a
        # small window rather than demanding the marker sit on one exact line.
        window = "\n".join(lines[n - 1 : n + 12])
        if not any(marker in window for marker in _REGISTRATION):
            bad.append(f"{path}: {origin} does not look like a registration")
    assert not bad, "map rows that do not resolve:\n  " + "\n  ".join(bad)


# ── the round trip: screen -> clipboard -> map -> source ──────────────────────


def test_end_to_end_f4_copies_an_address_that_resolves_to_code(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection], clipboard: None
) -> None:
    """Drive the real screen, press F4, read the clipboard, and find the code.

    This is the feature, end to end, with nothing stubbed:

    1. render a real ``SimulationScreen`` frame with the overlay on;
    2. put the cursor over a widget the product laid out itself;
    3. hand ``handle_key`` a real F4 event;
    4. read the text back off the **system clipboard**;
    5. split it into the address and the context stamp;
    6. look the address up in ``docs/ui_map.md``;
    7. open that file at that line and confirm it is the code that registers it.
    """
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    _pump_state(screen)

    inspect.set_inspect(True)
    inspect.set_trace_origins(True)
    inspect.set_context(
        board={"name": "DE10-Standard"},
        design={"file": "blinky.vhd", "mode": "generic"},
        simulator={"label": "GHDL-LLVM"},
    )

    # (1) a real frame, so the registry holds what the product actually drew.
    screen._events_this_frame = True
    screen._render_frame()
    target = next(r for r in inspect.regions() if r.path == "sim.toolbar.reload")

    # (2) the cursor onto it, then redraw so the frame agrees with the cursor.
    headless_pygame.mouse.set_pos(target.rect.center)
    headless_pygame.event.pump()
    screen._events_this_frame = True
    screen._render_frame()

    # (3) the keypress, through the same entry point every screen calls.
    assert inspect.handle_key(_key(headless_pygame, inspect.COPY_KEY)) is True
    assert inspect.last_copy_ok() is True

    # (4) what actually landed on the clipboard.
    pasted = read_clipboard()
    assert pasted is not None, "nothing on the clipboard after F4"

    # (5) the two halves.
    address, _, stamp = pasted.partition(" · ")
    assert address == "sim.toolbar.reload", f"copied {address!r}"
    assert "DE10-Standard" in stamp and "blinky.vhd" in stamp and "GHDL-LLVM" in stamp
    assert "fpga-sim " in stamp

    # (6) the address, looked up the way a reader would look it up.
    rows = _ui_map()
    assert address in rows, f"{address} is not in {MAP_PATH.name}"
    _kind, origin = rows[address]

    # The map and the running product must name the same line.
    assert origin == target.origin, f"map says {origin}, the frame said {target.origin}"

    # (7) the code itself.
    file_part, _, line_part = origin.rpartition(":")
    source = SRC / file_part
    line = source.read_text(encoding="utf-8").splitlines()[int(line_part) - 1]
    assert "draw_button(" in line, f"{origin} is {line.strip()!r}"

    # And the thing that line draws really is the Reload button: its region name
    # is declared in the toolbar's own table.
    from fpga_sim.ui.sim_toolbar import _BUTTONS

    assert any(region == "toolbar.reload" for *_rest, region in _BUTTONS)


def test_f4_over_empty_space_still_copies_the_stamp(
    headless_pygame: ModuleType, fake_child: tuple[SimChild, Connection], clipboard: None
) -> None:
    """Off every region, the copy is still useful -- it names the screen and build."""
    child, _conn = fake_child
    screen = _make_screen(headless_pygame, child)
    screen._connected = True
    inspect.set_inspect(True)
    screen._events_this_frame = True
    screen._render_frame()

    empty = (screen.screen.get_width() - 1, 0)
    assert inspect.hovered(empty) is None, "picked a point that is not empty"
    headless_pygame.mouse.set_pos(empty)
    headless_pygame.event.pump()
    assert inspect.handle_key(_key(headless_pygame, inspect.COPY_KEY)) is True

    pasted = read_clipboard()
    assert pasted is not None
    assert pasted.startswith("(no region)")
    assert "sim" in pasted


def test_copy_reports_failure_rather_than_raising(
    headless_pygame: ModuleType, monkeypatch: Any
) -> None:
    """A machine with no clipboard must lose the copy, not the frame."""
    monkeypatch.setattr(inspect, "copy_to_clipboard", lambda text: False)
    inspect.set_inspect(True)
    inspect.begin_frame("sim")
    assert inspect.handle_key(_key(headless_pygame, inspect.COPY_KEY)) is True
    assert inspect.last_copy_ok() is False
