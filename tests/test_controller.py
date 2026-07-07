"""Tests for the D6b ScreenController / SessionState state machine.

Follows the repo convention of constructing objects directly and driving
methods (never ``.run()`` on real screens): the screen classes and sim_bridge
functions the controller collaborates with are replaced by fakes, monkeypatched
on the ``fpga_sim.controller`` module namespace.

The ``on_simulate`` tests exercise the real pygame quit → init → set_mode
cycle the method performs; that is safe under the session-scoped
``headless_pygame`` fixture because ``on_simulate`` clears the ``get_font``
cache *before* quitting (the invariant conftest.py documents) and leaves
pygame re-initialized afterwards.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

import fpga_sim.controller as controller_mod
from fpga_sim.board_loader import BoardDef, ComponentInfo, SevenSegDef
from fpga_sim.controller import (
    NextScreen,
    ScreenController,
    SessionState,
    build_generics,
    example_vhdl_for,
)
from fpga_sim.sim_bridge import SimExit
from fpga_sim.ui import DialogResult, ScreenResult
from fpga_sim.ui.sim_panel import SPEED_DEFAULT
from fpga_sim.ui.theme import set_theme

if TYPE_CHECKING:
    from pathlib import Path
    from types import ModuleType

    from fpga_sim.sim_bridge import Simulator


@pytest.fixture(autouse=True)
def _isolated_session_file(tmp_path, monkeypatch):
    """Redirect SESSION_FILE so controller saves never touch the real user file."""
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", tmp_path / "session.json")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _board(**kwargs: Any) -> BoardDef:
    return BoardDef("Arty A7-35", "ArtyA7_35Platform", source="amaranth-boards", **kwargs)


def _make_controller(
    headless_pygame: ModuleType,
    *,
    session: dict[str, Any] | None = None,
    cli_simulator: str | None = None,
    available: list[Simulator] | None = None,
) -> ScreenController:
    screen = headless_pygame.display.set_mode((1024, 700))
    clock = headless_pygame.time.Clock()
    sims: list[Simulator] = available if available is not None else ["ghdl", "nvc"]
    return ScreenController(
        [_board()],
        screen,
        clock,
        sims,
        session=session or {},
        cli_simulator=cli_simulator,
    )


def _passthrough_spinner(
    screen: Any, clock: Any, message: str, work: Any, *, detail: str = ""
) -> Any:
    """Stand-in for run_with_spinner: call the work function synchronously."""
    return work()


class _FakeDialog:
    """ErrorDialog stand-in: records (title, message), replays scripted intents."""

    shown: list[tuple[str, str]] = []
    example_paths: list[Path | None] = []
    intents: list[DialogResult] = []

    def __init__(
        self, screen: Any, title: str, message: str, example_path: Path | None = None
    ) -> None:
        type(self).shown.append((title, message))
        type(self).example_paths.append(example_path)

    def run(self, clock: Any) -> DialogResult:
        return type(self).intents.pop(0)


def _install_dialog(
    monkeypatch: pytest.MonkeyPatch, intents: list[DialogResult]
) -> type[_FakeDialog]:
    _FakeDialog.shown = []
    _FakeDialog.example_paths = []
    _FakeDialog.intents = list(intents)
    monkeypatch.setattr(controller_mod, "ErrorDialog", _FakeDialog)
    return _FakeDialog


def _fail_if_called(name: str) -> Any:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError(f"{name} should not have been called")

    return _boom


# ── build_generics ───────────────────────────────────────────────────────────


def test_build_generics_floors_counts_and_counter_bits():
    board = _board(default_clock_hz=100e6)  # no components at all
    g = build_generics(board)
    assert g["NUM_SWITCHES"] == "1"
    assert g["NUM_BUTTONS"] == "1"
    assert g["NUM_LEDS"] == "1"
    assert g["COUNTER_BITS"] == "17"
    assert g["CLK_HALF_NS_INIT"] == "5"  # 5e8 / 100 MHz


def test_build_generics_counts_components_and_widens_for_7seg():
    board = _board(
        default_clock_hz=50e6,
        leds=[ComponentInfo("led", "led", i) for i in range(3)],
        buttons=[ComponentInfo("button", "button", i) for i in range(2)],
        switches=[ComponentInfo("switch", "switch", i) for i in range(4)],
        seven_seg=SevenSegDef(6, True, False, True, False),
    )
    g = build_generics(board)
    assert g["NUM_LEDS"] == "3"
    assert g["NUM_BUTTONS"] == "2"
    assert g["NUM_SWITCHES"] == "4"
    assert g["COUNTER_BITS"] == "24"  # max(17, 4 * 6 digits)
    assert g["CLK_HALF_NS_INIT"] == "10"  # 5e8 / 50 MHz


# ── SessionState ─────────────────────────────────────────────────────────────


def test_clear_analysis_keeps_vhdl_path():
    s = SessionState(simulator="ghdl", vhdl_path="a.vhd", work_dir="wd", work_dir_simulator="ghdl")
    s.clear_analysis()
    assert s.vhdl_path == "a.vhd"
    assert s.work_dir is None
    assert s.work_dir_simulator is None


def test_clear_vhdl_drops_everything():
    s = SessionState(
        simulator="ghdl",
        vhdl_path="a.vhd",
        work_dir="wd",
        work_dir_simulator="ghdl",
        last_vhdl_path="a.vhd",
    )
    s.clear_vhdl()
    assert s.vhdl_path is None
    assert s.work_dir is None
    assert s.work_dir_simulator is None
    assert s.last_vhdl_path == "a.vhd"  # sticky: still seeds the picker start dir


# ── _resolve_simulator ───────────────────────────────────────────────────────


def test_resolve_simulator_cli_wins():
    got = ScreenController._resolve_simulator("nvc", {"simulator": "ghdl"}, ["ghdl", "nvc"])
    assert got == "nvc"


def test_resolve_simulator_bad_cli_warns_and_falls_back(capsys):
    got = ScreenController._resolve_simulator("iverilog", {}, ["ghdl", "nvc"])
    assert got == "ghdl"
    assert "[warn]" in capsys.readouterr().out


def test_resolve_simulator_session_used_when_no_cli():
    got = ScreenController._resolve_simulator(None, {"simulator": "nvc"}, ["ghdl", "nvc"])
    assert got == "nvc"


def test_resolve_simulator_bad_session_falls_back_silently(capsys):
    got = ScreenController._resolve_simulator(None, {"simulator": "xsim"}, ["ghdl", "nvc"])
    assert got == "ghdl"
    assert capsys.readouterr().out == ""


# ── Constructor: session restore ─────────────────────────────────────────────


def test_ctor_restores_existing_vhdl_and_prefs(headless_pygame, tmp_path):
    vhdl = tmp_path / "blinky.vhd"
    vhdl.write_text("-- design")
    ctrl = _make_controller(
        headless_pygame,
        session={
            "vhdl_path": str(vhdl),
            "board_class": "DE10Lite",
            "board_source": "custom",
            "board_sort": "vendor",
            "component_filters": ["7seg"],
            "vendor_filters": ["Terasic"],
        },
    )
    s = ctrl.state
    assert s.vhdl_path == str(vhdl)
    assert s.last_vhdl_path == str(vhdl)
    assert s.work_dir is None  # analysis is on-demand at first Start
    assert s.work_dir_simulator is None
    assert (s.board_class, s.board_source, s.board_sort) == ("DE10Lite", "custom", "vendor")
    assert s.component_filters == ["7seg"]
    assert s.vendor_filters == ["Terasic"]
    assert ctrl.board is None


def test_ctor_drops_missing_vhdl_but_keeps_it_as_last(headless_pygame):
    ctrl = _make_controller(headless_pygame, session={"vhdl_path": "/nope/gone.vhd"})
    assert ctrl.state.vhdl_path is None
    assert ctrl.state.last_vhdl_path == "/nope/gone.vhd"


# ── Transition methods ───────────────────────────────────────────────────────


def test_on_board_selected_updates_preselect_and_saves(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame, session={"board_class": "Old", "board_source": "src"})
    saves: list[Any] = []
    monkeypatch.setattr(controller_mod, "save_session", lambda *a, **k: saves.append((a, k)))
    board = _board()
    assert ctrl.on_board_selected(board) is NextScreen.PREVIEW
    assert ctrl.board is board
    # U5: browsing persists the preselection immediately (not only at launch)
    assert ctrl.state.board_class == board.class_name
    assert ctrl.state.board_source == board.source
    assert len(saves) == 1


def test_on_board_selected_same_board_skips_save(headless_pygame, monkeypatch):
    ctrl = _make_controller(
        headless_pygame,
        session={"board_class": "ArtyA7_35Platform", "board_source": "amaranth-boards"},
    )
    saves: list[Any] = []
    monkeypatch.setattr(controller_mod, "save_session", lambda *a, **k: saves.append((a, k)))
    ctrl.on_board_selected(_board())  # same class/source as the session
    assert saves == []


def test_on_back_clears_analysis_keeps_vhdl(headless_pygame):
    ctrl = _make_controller(headless_pygame)
    ctrl.state.vhdl_path = "a.vhd"
    ctrl.state.work_dir = "wd"
    ctrl.state.work_dir_simulator = "ghdl"
    assert ctrl.on_back() is NextScreen.SELECTOR
    assert ctrl.state.vhdl_path == "a.vhd"
    assert ctrl.state.work_dir is None
    assert ctrl.state.work_dir_simulator is None


def test_on_vhdl_loaded_records_file_workdir_and_simulator(headless_pygame):
    ctrl = _make_controller(headless_pygame)
    ctrl.state.simulator = "nvc"
    assert ctrl.on_vhdl_loaded("/tmp/x.vhd", "/tmp/work") is NextScreen.PREVIEW
    s = ctrl.state
    assert s.vhdl_path == "/tmp/x.vhd"
    assert s.last_vhdl_path == "/tmp/x.vhd"
    assert s.work_dir == "/tmp/work"
    assert s.work_dir_simulator == "nvc"


def test_on_vhdl_loaded_saves_session_and_pushes_recent(headless_pygame, monkeypatch):
    """U5 save-on-pick: a picked file must persist without a simulation run."""
    ctrl = _make_controller(headless_pygame)
    board = _board()
    ctrl.on_board_selected(board)
    saves: list[Any] = []
    recents: list[tuple[Any, ...]] = []
    monkeypatch.setattr(controller_mod, "save_session", lambda *a, **k: saves.append((a, k)))
    monkeypatch.setattr(controller_mod, "push_recent", lambda *a: recents.append(a))
    ctrl.on_vhdl_loaded("/tmp/x.vhd", "/tmp/work")
    (args, _kwargs) = saves[-1]
    assert args[1] == "/tmp/x.vhd"  # the newly picked file is in the save
    assert recents == [(board.class_name, board.source, "/tmp/x.vhd")]


def test_on_vhdl_loaded_without_board_skips_recent(headless_pygame, monkeypatch):
    """No board (direct call) → session still saved, recent[] untouched."""
    ctrl = _make_controller(headless_pygame)
    recents: list[tuple[Any, ...]] = []
    monkeypatch.setattr(controller_mod, "push_recent", lambda *a: recents.append(a))
    ctrl.on_vhdl_loaded("/tmp/x.vhd", "/tmp/work")
    assert recents == []


# ── run() loop ───────────────────────────────────────────────────────────────


def test_run_alternates_screens_until_quit(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    seq: list[str] = []

    def fake_selector() -> NextScreen:
        seq.append("selector")
        return NextScreen.PREVIEW

    def fake_preview() -> NextScreen:
        seq.append("preview")
        return NextScreen.SELECTOR if len(seq) < 3 else NextScreen.QUIT

    monkeypatch.setattr(ctrl, "_run_selector", fake_selector)
    monkeypatch.setattr(ctrl, "_run_preview", fake_preview)
    # keep the session-scoped pygame alive for the rest of the suite
    monkeypatch.setattr(headless_pygame, "quit", lambda: None)
    ctrl.run()
    assert seq == ["selector", "preview", "selector", "preview"]


def test_run_quit_saves_prefs_and_window_size(headless_pygame, monkeypatch):
    """U5: quitting must persist the final window size and selector prefs."""
    ctrl = _make_controller(headless_pygame)
    saves: list[Any] = []
    monkeypatch.setattr(controller_mod, "save_session", lambda *a, **k: saves.append((a, k)))
    monkeypatch.setattr(ctrl, "_run_selector", lambda: NextScreen.QUIT)
    monkeypatch.setattr(headless_pygame, "quit", lambda: None)
    ctrl.run()
    ((_args, kwargs),) = saves
    assert kwargs == {"window_size": (1024, 700)}


# ── _run_selector ────────────────────────────────────────────────────────────


class _FakeSelector:
    """BoardSelector stand-in: records ctor kwargs, returns a scripted board."""

    result: BoardDef | None = None
    last_kwargs: dict[str, Any] = {}

    def __init__(self, boards: Any, screen: Any, **kwargs: Any) -> None:
        type(self).last_kwargs = kwargs
        self.sort_key = "vendor"
        self.component_filters = ["led"]
        self.vendor_filters = ["Digilent"]

    def run(self, clock: Any) -> BoardDef | None:
        return type(self).result


def test_run_selector_quit_still_harvests_prefs(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame, session={"board_class": "DE0", "board_sort": "name"})
    _FakeSelector.result = None
    monkeypatch.setattr(controller_mod, "BoardSelector", _FakeSelector)
    assert ctrl._run_selector() is NextScreen.QUIT
    # ctor got the session-seeded preselection…
    assert _FakeSelector.last_kwargs["preselect_class"] == "DE0"
    assert _FakeSelector.last_kwargs["initial_sort"] == "name"
    # …and the selector's final sort/filter prefs were captured even on quit
    assert ctrl.state.board_sort == "vendor"
    assert ctrl.state.component_filters == ["led"]
    assert ctrl.state.vendor_filters == ["Digilent"]


def test_run_selector_choice_enters_preview(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    board = _board()
    _FakeSelector.result = board
    monkeypatch.setattr(controller_mod, "BoardSelector", _FakeSelector)
    assert ctrl._run_selector() is NextScreen.PREVIEW
    assert ctrl.board is board


# ── _run_preview dispatch ────────────────────────────────────────────────────


class _FakePreview:
    """FPGABoard stand-in: records ctor kwargs, returns a scripted result."""

    result: ScreenResult = ScreenResult.QUIT
    sim: Simulator = "ghdl"
    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        type(self).last_kwargs = kwargs
        self.simulator: Simulator = type(self).sim

    def run(self) -> ScreenResult:
        return type(self).result


def _install_preview(
    monkeypatch: pytest.MonkeyPatch, result: ScreenResult, simulator: Simulator = "ghdl"
) -> type[_FakePreview]:
    _FakePreview.result = result
    _FakePreview.sim = simulator
    _FakePreview.last_kwargs = {}
    monkeypatch.setattr(controller_mod, "FPGABoard", _FakePreview)
    return _FakePreview


def test_preview_quit(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    _install_preview(monkeypatch, ScreenResult.QUIT)
    assert ctrl._run_preview() is NextScreen.QUIT


def test_preview_back_routes_through_on_back(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    ctrl.state.work_dir = "wd"
    ctrl.state.work_dir_simulator = "ghdl"
    _install_preview(monkeypatch, ScreenResult.BACK)
    assert ctrl._run_preview() is NextScreen.SELECTOR
    assert ctrl.state.work_dir is None


def test_preview_load_vhdl_routes_to_picker(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    _install_preview(monkeypatch, ScreenResult.LOAD_VHDL)
    monkeypatch.setattr(ctrl, "_run_vhdl_picker", lambda: NextScreen.PREVIEW)
    assert ctrl._run_preview() is NextScreen.PREVIEW


def test_preview_simulate_routes_to_on_simulate(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    _install_preview(monkeypatch, ScreenResult.SIMULATE)
    monkeypatch.setattr(ctrl, "on_simulate", lambda: NextScreen.PREVIEW)
    assert ctrl._run_preview() is NextScreen.PREVIEW


def test_preview_picks_up_simulator_toggle_and_passes_state(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    board = _board()
    ctrl.on_board_selected(board)
    ctrl.state.vhdl_path = "x.vhd"
    fake = _install_preview(monkeypatch, ScreenResult.QUIT, simulator="nvc")
    ctrl._run_preview()
    assert ctrl.state.simulator == "nvc"  # toggle change picked up
    assert fake.last_kwargs["board_def"] is board
    assert fake.last_kwargs["vhdl_path"] == "x.vhd"
    assert fake.last_kwargs["available_simulators"] == ["ghdl", "nvc"]


def test_preview_simulator_toggle_saves_session(headless_pygame, monkeypatch):
    """U5: a simulator toggle persists immediately, not only at launch."""
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    saves: list[Any] = []
    monkeypatch.setattr(controller_mod, "save_session", lambda *a, **k: saves.append((a, k)))
    _install_preview(monkeypatch, ScreenResult.QUIT, simulator="nvc")
    ctrl._run_preview()
    ((args, _kwargs),) = saves
    assert args[2] == "nvc"  # the new simulator is in the save


def test_preview_unchanged_simulator_skips_save(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    saves: list[Any] = []
    monkeypatch.setattr(controller_mod, "save_session", lambda *a, **k: saves.append((a, k)))
    _install_preview(monkeypatch, ScreenResult.QUIT, simulator="ghdl")  # no change
    ctrl._run_preview()
    assert saves == []


# ── _run_vhdl_picker ─────────────────────────────────────────────────────────


class _FakePicker:
    """VHDLFilePicker stand-in: records ctor kwargs, replays scripted picks."""

    picks: list[str | None] = []
    ctor_kwargs: list[dict[str, Any]] = []

    def __init__(self, screen: Any, **kwargs: Any) -> None:
        type(self).ctor_kwargs.append(kwargs)

    def run(self, clock: Any) -> str | None:
        return type(self).picks.pop(0)


def _install_picker(monkeypatch: pytest.MonkeyPatch, picks: list[str | None]) -> type[_FakePicker]:
    _FakePicker.picks = list(picks)
    _FakePicker.ctor_kwargs = []
    monkeypatch.setattr(controller_mod, "VHDLFilePicker", _FakePicker)
    return _FakePicker


def test_picker_cancel_keeps_existing_vhdl(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    ctrl.state.vhdl_path = "keep.vhd"
    _install_picker(monkeypatch, [None])
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", _fail_if_called("encoding check"))
    assert ctrl._run_vhdl_picker() is NextScreen.PREVIEW
    assert ctrl.state.vhdl_path == "keep.vhd"


def test_picker_first_pick_starts_at_current_vhdl(headless_pygame, monkeypatch, tmp_path):
    vhdl = tmp_path / "mine.vhd"
    vhdl.write_text("-- design")
    ctrl = _make_controller(headless_pygame, session={"vhdl_path": str(vhdl)})
    ctrl.on_board_selected(_board())
    _install_picker(monkeypatch, [None])
    ctrl._run_vhdl_picker()
    assert _FakePicker.ctor_kwargs[0] == {"start_dir": tmp_path, "preselect_name": "mine.vhd"}


def test_picker_success_records_state(headless_pygame, monkeypatch, tmp_path):
    vhdl = tmp_path / "good.vhd"
    vhdl.write_text("-- design")
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    _install_picker(monkeypatch, [str(vhdl)])
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (True, ""))
    monkeypatch.setattr(controller_mod, "check_vhdl_contract", lambda p, board_def: (True, ""))
    monkeypatch.setattr(controller_mod, "run_with_spinner", _passthrough_spinner)
    monkeypatch.setattr(controller_mod, "analyze_vhdl", lambda *a, **k: (True, "/work/dir"))
    assert ctrl._run_vhdl_picker() is NextScreen.PREVIEW
    s = ctrl.state
    assert s.vhdl_path == str(vhdl)
    assert s.last_vhdl_path == str(vhdl)
    assert s.work_dir == "/work/dir"
    assert s.work_dir_simulator == s.simulator


def test_picker_validation_error_back_bails_to_selector(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    ctrl.state.work_dir = "stale"
    ctrl.state.work_dir_simulator = "ghdl"
    _install_picker(monkeypatch, ["bad.vhd"])
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (False, "not ASCII"))
    dialog = _install_dialog(monkeypatch, [DialogResult.BACK])
    assert ctrl._run_vhdl_picker() is NextScreen.SELECTOR
    assert dialog.shown == [("VHDL Error", "not ASCII")]
    assert ctrl.state.work_dir is None  # on_back cleared the analysis
    assert ctrl.state.vhdl_path is None  # nothing was loaded


def test_picker_retry_reopens_at_hdl_dir(headless_pygame, monkeypatch, tmp_path):
    vhdl = tmp_path / "mine.vhd"
    vhdl.write_text("-- design")
    ctrl = _make_controller(headless_pygame, session={"vhdl_path": str(vhdl)})
    ctrl.on_board_selected(_board())
    _install_picker(monkeypatch, [str(vhdl), None])  # fail once, then cancel
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (False, "bad"))
    _install_dialog(monkeypatch, [DialogResult.RETRY])
    assert ctrl._run_vhdl_picker() is NextScreen.PREVIEW
    first, second = _FakePicker.ctor_kwargs
    assert first == {"start_dir": tmp_path, "preselect_name": "mine.vhd"}
    assert second == {"start_dir": controller_mod._HDL_DIR}  # retry: no preselect


def test_picker_analysis_failure_shows_simulator_error(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    _install_picker(monkeypatch, ["a.vhd", None])
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (True, ""))
    monkeypatch.setattr(controller_mod, "check_vhdl_contract", lambda p, board_def: (True, ""))
    monkeypatch.setattr(controller_mod, "run_with_spinner", _passthrough_spinner)
    monkeypatch.setattr(controller_mod, "analyze_vhdl", lambda *a, **k: (False, "elab failed"))
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])
    assert ctrl._run_vhdl_picker() is NextScreen.PREVIEW
    assert dialog.shown == [("GHDL Error", "elab failed")]
    assert ctrl.state.vhdl_path is None


# ── on_simulate ──────────────────────────────────────────────────────────────


def _sim_harness(
    headless_pygame: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    analyzed: bool = True,
    sim_exits: list[SimExit] | None = None,
) -> tuple[ScreenController, list[dict[str, Any]], list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    """Build a controller ready to simulate, with launch/save/recent recorders.

    With ``analyzed=True`` the state looks freshly analyzed by the current
    simulator (no re-analysis path); the contract check is fenced off so any
    unexpected call fails the test.  *sim_exits* scripts what each successive
    fake launch reports (exhausted → ``SimExit.STOPPED``), driving the U7
    intent handling.
    """
    vhdl = tmp_path / "blinky.vhd"
    vhdl.write_text("-- design")
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    ctrl.state.vhdl_path = str(vhdl)
    if analyzed:
        ctrl.state.work_dir = "wd"
        ctrl.state.work_dir_simulator = ctrl.state.simulator
        monkeypatch.setattr(
            controller_mod, "check_vhdl_contract", _fail_if_called("contract check")
        )

    launches: list[dict[str, Any]] = []
    exits = list(sim_exits or [])

    def fake_launch(
        board_json: Any, vhdl_path: Any, toplevel: Any, generics: Any, **kwargs: Any
    ) -> SimExit:
        launches.append(
            {
                "board_json": board_json,
                "vhdl_path": vhdl_path,
                "toplevel": toplevel,
                "generics": generics,
                **kwargs,
            }
        )
        return exits.pop(0) if exits else SimExit.STOPPED

    saves: list[tuple[Any, ...]] = []
    recents: list[tuple[Any, ...]] = []
    monkeypatch.setattr(controller_mod, "launch_simulation", fake_launch)
    monkeypatch.setattr(controller_mod, "save_session", lambda *a, **k: saves.append((a, k)))
    monkeypatch.setattr(controller_mod, "push_recent", lambda *a: recents.append(a))
    return ctrl, launches, saves, recents


def test_simulate_launches_and_reinits_pygame(headless_pygame, monkeypatch, tmp_path):
    ctrl, launches, saves, recents = _sim_harness(headless_pygame, monkeypatch, tmp_path)
    board = ctrl.board
    assert board is not None
    old_screen = ctrl.screen

    assert ctrl.on_simulate() is NextScreen.PREVIEW

    (launch,) = launches
    assert launch["vhdl_path"] == ctrl.state.vhdl_path
    assert launch["toplevel"] == "blinky"
    assert launch["generics"] == build_generics(board)
    assert launch["work_dir"] == "wd"
    assert launch["simulator"] == "ghdl"
    assert launch["board_def"] is board
    assert (launch["sim_width"], launch["sim_height"]) == (1024, 700)
    assert launch["speed_factor"] == SPEED_DEFAULT  # nothing saved yet → default
    assert launch["theme"] == "pcb-green"  # default theme forwarded (U6)

    assert saves == [
        (
            (board.class_name, ctrl.state.vhdl_path, "ghdl", board.source, "", [], []),
            {"window_size": (1024, 700)},
        )
    ]
    assert recents == [(board.class_name, board.source, ctrl.state.vhdl_path)]
    assert ctrl.state.board_class == board.class_name  # preselect updated on launch
    assert ctrl.state.board_source == board.source
    assert ctrl.screen is not old_screen  # pygame was quit and re-initialized


def test_simulate_passes_saved_speed_to_launch(headless_pygame, monkeypatch, tmp_path):
    """U5: the sim-written speed_factor is re-read at every launch."""
    ctrl, launches, _saves, _recents = _sim_harness(headless_pygame, monkeypatch, tmp_path)
    monkeypatch.setattr(controller_mod, "load_session", lambda: {"speed_factor": 2.5})
    ctrl.on_simulate()
    assert launches[0]["speed_factor"] == 2.5


def test_simulate_passes_active_theme_to_launch(
    headless_pygame, monkeypatch, tmp_path, restore_theme
):
    """U6: the launcher's live theme name rides into the subprocess launch."""
    ctrl, launches, _saves, _recents = _sim_harness(headless_pygame, monkeypatch, tmp_path)
    set_theme("dark")
    ctrl.on_simulate()
    assert launches[0]["theme"] == "dark"


def test_simulate_junk_saved_speed_falls_back_to_default(headless_pygame, monkeypatch, tmp_path):
    ctrl, launches, _saves, _recents = _sim_harness(headless_pygame, monkeypatch, tmp_path)
    monkeypatch.setattr(controller_mod, "load_session", lambda: {"speed_factor": "fast"})
    ctrl.on_simulate()
    assert launches[0]["speed_factor"] == SPEED_DEFAULT


def test_simulate_stale_session_contract_failure_drops_vhdl(headless_pygame, monkeypatch, tmp_path):
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, analyzed=False
    )
    monkeypatch.setattr(
        controller_mod, "check_vhdl_contract", lambda p, board_def: (False, "port mismatch")
    )
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])  # intent is ignored here
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert dialog.shown == [("VHDL Error", "port mismatch")]
    assert ctrl.state.vhdl_path is None  # cleared: stale session may not bypass the check
    assert launches == []


def test_simulate_reanalyzes_when_simulator_changed(headless_pygame, monkeypatch, tmp_path):
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, analyzed=False
    )
    ctrl.state.work_dir = "old-wd"
    ctrl.state.work_dir_simulator = "nvc"  # produced by the other simulator
    monkeypatch.setattr(controller_mod, "check_vhdl_contract", lambda p, board_def: (True, ""))
    monkeypatch.setattr(controller_mod, "run_with_spinner", _passthrough_spinner)
    monkeypatch.setattr(controller_mod, "analyze_vhdl", lambda *a, **k: (True, "new-wd"))
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert ctrl.state.work_dir == "new-wd"
    refreshed: Simulator | None = ctrl.state.work_dir_simulator  # defeat stale mypy narrowing
    assert refreshed == "ghdl"
    (launch,) = launches
    assert launch["work_dir"] == "new-wd"


def test_simulate_reanalysis_failure_keeps_state_and_skips_launch(
    headless_pygame, monkeypatch, tmp_path
):
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, analyzed=False
    )
    ctrl.state.work_dir = "old-wd"
    ctrl.state.work_dir_simulator = "nvc"
    monkeypatch.setattr(controller_mod, "check_vhdl_contract", lambda p, board_def: (True, ""))
    monkeypatch.setattr(controller_mod, "run_with_spinner", _passthrough_spinner)
    monkeypatch.setattr(controller_mod, "analyze_vhdl", lambda *a, **k: (False, "no such entity"))
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert dialog.shown == [("GHDL Error", "no such entity")]
    assert ctrl.state.vhdl_path is not None  # kept — user can retry or switch back
    assert ctrl.state.work_dir == "old-wd"
    assert launches == []


def test_simulate_error_retry_reenters_preview(headless_pygame, monkeypatch, tmp_path):
    ctrl, _launches, _saves, _recents = _sim_harness(headless_pygame, monkeypatch, tmp_path)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("cocotb exploded")

    monkeypatch.setattr(controller_mod, "launch_simulation", boom)
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert dialog.shown == [("Simulation Error", "cocotb exploded")]
    assert ctrl.state.work_dir == "wd"  # retry keeps the analysis


def test_simulate_error_back_returns_to_selector(headless_pygame, monkeypatch, tmp_path):
    ctrl, _launches, _saves, _recents = _sim_harness(headless_pygame, monkeypatch, tmp_path)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(controller_mod, "launch_simulation", boom)
    _install_dialog(monkeypatch, [DialogResult.BACK])
    assert ctrl.on_simulate() is NextScreen.SELECTOR
    assert ctrl.state.work_dir is None  # back drops the analysis
    assert ctrl.state.vhdl_path is not None  # …but keeps the file


# ── on_simulate: U7 toolbar exit intents ─────────────────────────────────────


def test_simulate_back_to_boards_intent_goes_to_selector(headless_pygame, monkeypatch, tmp_path):
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, sim_exits=[SimExit.BACK_TO_BOARDS]
    )
    assert ctrl.on_simulate() is NextScreen.SELECTOR
    assert len(launches) == 1
    assert ctrl.state.work_dir is None  # routed through on_back → analysis dropped
    assert ctrl.state.vhdl_path is not None  # …but the file is kept for the next board


def test_simulate_change_vhdl_intent_opens_picker(headless_pygame, monkeypatch, tmp_path):
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, sim_exits=[SimExit.CHANGE_VHDL]
    )
    picker_calls: list[int] = []

    def fake_picker() -> NextScreen:
        picker_calls.append(1)
        return NextScreen.PREVIEW

    monkeypatch.setattr(ctrl, "_run_vhdl_picker", fake_picker)
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert picker_calls == [1]
    assert len(launches) == 1


def test_simulate_reload_intent_revalidates_and_relaunches(headless_pygame, monkeypatch, tmp_path):
    """[Reload VHDL] re-runs the full pipeline and relaunches without a preview."""
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame,
        monkeypatch,
        tmp_path,
        sim_exits=[SimExit.RELOAD_VHDL, SimExit.STOPPED],
    )
    # The harness fences the contract check for the *pre-launch* path; the
    # reload path must run it again, so re-allow it here.
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (True, ""))
    monkeypatch.setattr(controller_mod, "check_vhdl_contract", lambda p, board_def: (True, ""))
    monkeypatch.setattr(controller_mod, "run_with_spinner", _passthrough_spinner)
    analyze_calls: list[dict[str, Any]] = []

    def fake_analyze(vhdl_path: Any, **kwargs: Any) -> tuple[bool, str]:
        analyze_calls.append({"vhdl_path": vhdl_path, **kwargs})
        return True, "wd"

    monkeypatch.setattr(controller_mod, "analyze_vhdl", fake_analyze)
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert len(launches) == 2  # reload relaunched immediately
    (call,) = analyze_calls
    assert call["vhdl_path"] == ctrl.state.vhdl_path  # same file, re-analyzed
    assert call["work_dir"] == "wd"  # existing work dir reused, not a fresh temp dir
    assert launches[1]["work_dir"] == "wd"
    refreshed: Any = ctrl.state.work_dir_simulator
    assert refreshed == "ghdl"


def test_simulate_reload_rereads_speed_each_launch(headless_pygame, monkeypatch, tmp_path):
    """The sim writes its final slider value at exit; a reload must pick it up."""
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame,
        monkeypatch,
        tmp_path,
        sim_exits=[SimExit.RELOAD_VHDL, SimExit.STOPPED],
    )
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (True, ""))
    monkeypatch.setattr(controller_mod, "check_vhdl_contract", lambda p, board_def: (True, ""))
    monkeypatch.setattr(controller_mod, "run_with_spinner", _passthrough_spinner)
    monkeypatch.setattr(controller_mod, "analyze_vhdl", lambda *a, **k: (True, "wd"))
    speeds = iter([1.5, 3.0])
    monkeypatch.setattr(controller_mod, "load_session", lambda: {"speed_factor": next(speeds)})
    ctrl.on_simulate()
    assert [launch["speed_factor"] for launch in launches] == [1.5, 3.0]


def test_simulate_reload_encoding_failure_shows_dialog(headless_pygame, monkeypatch, tmp_path):
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, sim_exits=[SimExit.RELOAD_VHDL]
    )
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (False, "not ASCII"))
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert len(launches) == 1  # no relaunch with a bad file
    assert dialog.shown == [("VHDL Error", "not ASCII")]
    assert dialog.example_paths == [controller_mod._HDL_DIR / "blinky.vhd"]
    assert ctrl.state.vhdl_path is not None  # kept: the user is mid-edit
    assert ctrl.state.work_dir is None  # old artifacts may not match the edited file


def test_simulate_reload_analysis_failure_uses_simulator_title(
    headless_pygame, monkeypatch, tmp_path
):
    ctrl, launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, sim_exits=[SimExit.RELOAD_VHDL]
    )
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (True, ""))
    monkeypatch.setattr(controller_mod, "check_vhdl_contract", lambda p, board_def: (True, ""))
    monkeypatch.setattr(controller_mod, "run_with_spinner", _passthrough_spinner)
    monkeypatch.setattr(controller_mod, "analyze_vhdl", lambda *a, **k: (False, "elab failed"))
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])
    assert ctrl.on_simulate() is NextScreen.PREVIEW
    assert len(launches) == 1
    assert dialog.shown == [("GHDL Error", "elab failed")]
    assert ctrl.state.work_dir is None  # the reused dir now holds a partial build


def test_simulate_reload_failure_back_goes_to_selector(headless_pygame, monkeypatch, tmp_path):
    ctrl, _launches, _saves, _recents = _sim_harness(
        headless_pygame, monkeypatch, tmp_path, sim_exits=[SimExit.RELOAD_VHDL]
    )
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (False, "bad"))
    _install_dialog(monkeypatch, [DialogResult.BACK])
    assert ctrl.on_simulate() is NextScreen.SELECTOR


# ── example_vhdl_for / View-Example wiring (U4) ──────────────────────────────


def test_example_vhdl_for_plain_board():
    assert example_vhdl_for(_board()).name == "blinky.vhd"


def test_example_vhdl_for_none():
    assert example_vhdl_for(None).name == "blinky.vhd"


def test_example_vhdl_for_7seg_board():
    board = _board(seven_seg=SevenSegDef(4, True, False, True, False))
    assert example_vhdl_for(board).name == "counter_7seg.vhd"


def test_picker_error_dialog_gets_example_path(headless_pygame, monkeypatch):
    """Validation dialogs offer the board-appropriate example design."""
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board())
    _install_picker(monkeypatch, ["bad.vhd", None])
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (False, "bad"))
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])
    ctrl._run_vhdl_picker()
    assert dialog.example_paths == [controller_mod._HDL_DIR / "blinky.vhd"]


def test_picker_error_dialog_gets_7seg_example(headless_pygame, monkeypatch):
    ctrl = _make_controller(headless_pygame)
    ctrl.on_board_selected(_board(seven_seg=SevenSegDef(4, True, False, True, False)))
    _install_picker(monkeypatch, ["bad.vhd", None])
    monkeypatch.setattr(controller_mod, "check_vhdl_encoding", lambda p: (False, "bad"))
    dialog = _install_dialog(monkeypatch, [DialogResult.RETRY])
    ctrl._run_vhdl_picker()
    assert dialog.example_paths == [controller_mod._HDL_DIR / "counter_7seg.vhd"]
