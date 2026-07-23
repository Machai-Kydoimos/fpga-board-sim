"""Launcher screen-flow controller (roadmap D6b).

Extracted from ``fpga_sim.__main__``, whose ``main()`` was a 264-line
``while``-loop juggling four screens through implicit flag variables
(``_return_to_board``, ``current_vhdl_path``, ``_work_dir_simulator``, …).
The flow is now an explicit state machine:

* :class:`SessionState` — the cross-screen data: the current VHDL /
  work-dir / simulator tuple plus the selector preferences that mirror the
  persisted session file.
* :class:`ScreenController` — owns the pygame ``screen`` / ``clock`` and the
  loop.  Each launcher screen has a private ``_run_*`` method; the public
  ``on_*`` transition methods mutate :class:`SessionState` and return the
  next screen (:class:`NextScreen`), so every edge of the state machine is a
  plain, unit-testable call.

The simulation runs in the launcher's own window (single-window, U34): a
headless GHDL/NVC + cocotb child streams signal state to a
:class:`~fpga_sim.ui.SimulationScreen` rendered right here, so no window is
ever created or destroyed between launcher start and app exit (see
:meth:`ScreenController.on_simulate`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Any

import pygame

from fpga_sim.board_loader import BoardDef
from fpga_sim.session_config import load_session, push_recent, save_session
from fpga_sim.sim_bridge import (
    ConventionMatch,
    SimulatorInfo,
    _probe_simulator,
    analyze_vhdl,
    check_vhdl_contract,
    check_vhdl_encoding,
    finish_waveform,
    resolve_simulator_arg,
    start_simulation,
)
from fpga_sim.ui import (
    BoardSelector,
    DialogResult,
    ErrorDialog,
    FPGABoard,
    ScreenResult,
    SimExit,
    SimulationScreen,
    VHDLFilePicker,
    run_with_spinner,
)
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.sim_panel import SPEED_DEFAULT

_HDL_DIR = Path(__file__).parent.parent.parent / "hdl"


def example_vhdl_for(board: BoardDef | None) -> Path:
    """Return the bundled example design that satisfies the contract for *board*.

    Offered by validation ErrorDialogs as [View Example]: ``counter_7seg.vhd``
    for boards with a 7-segment display, ``blinky.vhd`` otherwise.
    """
    has_7seg = board is not None and board.seven_seg is not None
    return _HDL_DIR / ("counter_7seg.vhd" if has_7seg else "blinky.vhd")


# COUNTER_BITS floor for plain-LED generic designs, per simulator engine.  The
# visible LED rate is (simulator throughput) / 2**COUNTER_BITS, so a faster
# backend blinks a plain ``blinky`` faster at the same width.  Post-U34, NVC's
# ~8x throughput lands blinky at a blurry ~42 Hz on the default 17-bit floor
# (issue #256), so NVC gets +3 bits (~divide by 8) to reach GHDL's watchable
# ~5 Hz.  Keyed on the engine, not the backend: every GHDL code generator keeps
# 17.  Many-digit 7-seg displays widen past either floor via 4*num_segs.
_COUNTER_BITS_FLOOR_DEFAULT = 17
_COUNTER_BITS_FLOOR: dict[str, int] = {"nvc": 20}


def build_generics(board: BoardDef, *, simulator: str | None = None) -> dict[str, str]:
    """Build the generic map for sim_wrapper from a board definition.

    NUM_SEGS is absent here: it is conditionally injected by start_simulation()
    only when both the board has a 7-seg display and the design declares a
    ``seg`` output port (which also selects the 7-seg wrapper template).
    Passing NUM_SEGS to the standard wrapper (which lacks that generic) would
    cause NVC to error during elaboration.  NUM_RGB_LEDS follows the same
    pattern (U37), injected only when the design declares the generic — but
    gated on the *design* alone, since boards without RGB LEDs simply pass 0.

    NUM_LEDS counts boundary *channels*, not components: each 3-pin RGB LED
    contributes three ``led`` bits (mono LEDs first, then r/g/b per site).

    ``simulator`` is the engine (``"ghdl"`` / ``"nvc"``) whose throughput sets
    the COUNTER_BITS floor (issue #256); ``None`` keeps the conservative 17-bit
    default used by analysis and tests, which never run a blink to watch.
    """
    clk_half_ns = max(1, round(5e8 / board.default_clock_hz))
    num_segs = board.seven_seg.num_digits if board.seven_seg else 0
    counter_floor = _COUNTER_BITS_FLOOR.get(simulator or "", _COUNTER_BITS_FLOOR_DEFAULT)
    return {
        "NUM_SWITCHES": str(max(1, len(board.switches))),
        "NUM_BUTTONS": str(max(1, len(board.buttons))),
        "NUM_LEDS": str(max(1, board.num_led_channels)),
        # Deliberately below the VHDL default (24/32): at the simulator's
        # sub-real-time throughput a 24-bit counter's MSB toggles too slowly to
        # see, so floor COUNTER_BITS (17, or 20 on NVC — see above; MSB ~every
        # 1.3 ms of simulated time at 100 MHz on GHDL) and widen it only for
        # many-digit 7-seg displays. Real hardware would use the full 24/32.
        "COUNTER_BITS": str(max(counter_floor, 4 * num_segs)),
        "CLK_HALF_NS_INIT": str(clk_half_ns),
    }


class NextScreen(Enum):
    """Which launcher screen the controller shows after a transition."""

    SELECTOR = auto()  # board selector (Step 1)
    PREVIEW = auto()  # board preview for the current board (Step 2)
    QUIT = auto()  # leave the launcher loop


@dataclass
class SessionState:
    """Cross-screen launcher state (the D6b VHDL / work-dir / simulator tuple).

    ``vhdl_path`` / ``work_dir`` survive across preview re-entries and
    simulation runs so the user can restart immediately.
    ``work_dir_sim`` records which simulator install produced ``work_dir``, so
    switching simulators — including between two GHDL code generators, whose
    compiled artifacts differ (U35) — or restoring a stale session forces
    re-analysis before the next launch.  ``last_vhdl_path`` is stickier than
    ``vhdl_path``: it survives invalidation (e.g. a restored file that fails
    the new board's contract) so the picker can still start in the user's
    directory.  The ``board_*`` / ``*_filters`` fields mirror the persisted
    session file: they seed the selector's preselection and the next
    ``save_session()``.
    """

    sim: SimulatorInfo
    vhdl_path: str | None = None
    work_dir: str | None = None
    work_dir_sim: SimulatorInfo | None = None
    # U21 B3: set when the loaded VHDL is board-native (its port names match the
    # selected board's convention); drives native wrapper generation + the badge.
    convention: ConventionMatch | None = None
    last_vhdl_path: str = ""
    board_class: str = ""
    board_source: str = ""
    board_sort: str = ""
    component_filters: list[str] = field(default_factory=list)
    vendor_filters: list[str] = field(default_factory=list)

    def needs_reanalysis(self) -> bool:
        """Report whether ``work_dir`` is stale for the current simulator install.

        Keys on both engine and resolved path: switching between two GHDL code
        generators (same engine, different binary) must re-analyze because a
        compiled backend's ``work_dir`` executable is backend-specific.
        """
        w = self.work_dir_sim
        return w is None or (w.engine, w.path) != (self.sim.engine, self.sim.path)

    def clear_analysis(self) -> None:
        """Drop the analysis products so the next launch re-analyzes."""
        self.work_dir = None
        self.work_dir_sim = None

    def clear_vhdl(self) -> None:
        """Drop the loaded VHDL file and its analysis products."""
        self.vhdl_path = None
        self.convention = None
        self.clear_analysis()


class ScreenController:
    """Drive the launcher flow: selector → preview → (picker | simulate) → repeat.

    Owns the pygame ``screen`` / ``clock`` (both are re-created after every
    simulation run) and the :class:`SessionState`.  :meth:`run` is the loop;
    the ``on_*`` methods are the state-machine edges.
    """

    def __init__(
        self,
        boards: list[BoardDef],
        screen: pygame.Surface,
        clock: pygame.time.Clock,
        available_sims: list[SimulatorInfo],
        *,
        session: dict[str, Any],
        cli_simulator: str | None = None,
    ) -> None:
        """Seed the controller from the saved *session* dict and CLI override.

        *session* is the (possibly empty) dict from ``load_session()``;
        *cli_simulator* is the raw ``--sim`` argument, which overrides the
        session's saved simulator when it names an available one.
        *available_sims* is the discovered install list (non-empty; the caller
        supplies a fallback entry when nothing is installed).
        """
        self.boards = boards
        self.screen = screen
        self.clock = clock
        self.available_sims = available_sims
        self.board: BoardDef | None = None  # set by on_board_selected()

        last_vhdl: str = session.get("vhdl_path", "")
        self.state = SessionState(
            sim=self._resolve_sim(cli_simulator, session, available_sims),
            # Pre-populate from the session so the last-used file is ready on
            # launch; analysis runs on-demand at the first [Start Simulation].
            vhdl_path=last_vhdl if last_vhdl and Path(last_vhdl).exists() else None,
            last_vhdl_path=last_vhdl,
            board_class=session.get("board_class", ""),
            board_source=session.get("board_source", ""),
            board_sort=session.get("board_sort", ""),
            component_filters=session.get("component_filters", []),
            vendor_filters=session.get("vendor_filters", []),
        )

    @staticmethod
    def _resolve_sim(
        cli_simulator: str | None,
        session: dict[str, Any],
        available_sims: list[SimulatorInfo],
    ) -> SimulatorInfo:
        """Pick the simulator install: CLI overrides session; session overrides default.

        Restore-with-fallback (U35): a saved ``simulator_path`` no longer
        present (binary moved/removed) falls back to the PATH default with a
        one-line console note — never crashing, never blocking the launcher.  A
        legacy session with only the engine slug re-selects that engine's first
        install silently (an unknown slug falls through to the default).
        """
        default = available_sims[0]
        if cli_simulator:
            info = resolve_simulator_arg(cli_simulator, available_sims)
            if info is not None:
                return info
            print(f"[warn] Simulator '{cli_simulator}' not found; falling back to {default.label}")
            return default
        saved_path = str(session.get("simulator_path", "") or "")
        if saved_path:
            target = os.path.realpath(saved_path)
            for info in available_sims:
                if os.path.realpath(info.path) == target:
                    return info
            probed = _probe_simulator(saved_path)  # not discovered; re-probe directly
            if probed is not None:
                return probed
            print(f"[warn] Saved simulator '{saved_path}' unavailable; using {default.label}")
            return default
        # Legacy session (pre-U35: engine slug only) or no saved path.
        saved_engine = str(session.get("simulator", "") or "")
        if saved_engine:
            return next((i for i in available_sims if i.engine == saved_engine), default)
        return default

    # ── Session persistence ───────────────────────────────────────────────

    def _save_session(self, *, window_size: tuple[int, int] | None = None) -> None:
        """Persist the launcher state (a merge — see ``session_config``).

        Called on every board / simulator / VHDL change, at quit, and at
        simulation launch — not only at launch as pre-U5 — so preferences
        survive a browse-only session.  *window_size* is included when the
        caller has a live window to measure.
        """
        s = self.state
        save_session(
            s.board_class,
            s.vhdl_path or s.last_vhdl_path,
            s.sim.engine,
            s.board_source,
            s.board_sort,
            s.component_filters,
            s.vendor_filters,
            simulator_path=s.sim.path,
            window_size=window_size,
        )

    # ── Loop ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Drive the screen flow until the user quits, then shut pygame down."""
        nxt = NextScreen.SELECTOR
        while nxt is not NextScreen.QUIT:
            nxt = self._run_selector() if nxt is NextScreen.SELECTOR else self._run_preview()
        # Quit-time save: keep the final window size and any sort/filter/
        # simulator changes from a browse-only session.
        self._save_session(window_size=self.screen.get_size())
        get_font.cache_clear()
        pygame.quit()

    # ── Step 1: pick a board ──────────────────────────────────────────────

    def _run_selector(self) -> NextScreen:
        """Run the board selector; capture sort/filter preferences even on quit."""
        s = self.state
        selector = BoardSelector(
            self.boards,
            self.screen,
            preselect_class=s.board_class,
            preselect_source=s.board_source,
            initial_sort=s.board_sort,
            initial_component_filters=s.component_filters,
            initial_vendor_filters=s.vendor_filters,
        )
        chosen = selector.run(self.clock)
        s.board_sort = selector.sort_key
        s.component_filters = selector.component_filters
        s.vendor_filters = selector.vendor_filters
        if chosen is None:
            return NextScreen.QUIT
        return self.on_board_selected(chosen)

    def on_board_selected(self, board: BoardDef) -> NextScreen:
        """Enter the preview for *board* and persist it as the new preselection.

        Pre-U5 the preselection updated only when a simulation launched; now
        the last *browsed* board is restored too, so a pick-then-quit session
        resumes where the user left off.
        """
        self.board = board
        s = self.state
        if (s.board_class, s.board_source) != (board.class_name, board.source):
            s.board_class = board.class_name
            s.board_source = board.source
            self._save_session()
        return NextScreen.PREVIEW

    # ── Step 2: board preview ─────────────────────────────────────────────

    def _run_preview(self) -> NextScreen:
        """Show the board preview and dispatch on its :class:`ScreenResult`.

        Three footer buttons: [Select Board] [Load VHDL File]
        [Start Simulation].  The window title is set by
        ``FPGABoard.__init__`` (it includes the VHDL filename when loaded).
        """
        assert self.board is not None  # PREVIEW is only reachable after on_board_selected()
        preview = FPGABoard(
            board_def=self.board,
            screen=self.screen,
            sim=self.state.sim,
            available_sims=self.available_sims,
            vhdl_path=self.state.vhdl_path,
        )
        result = preview.run()
        if preview.sim is not None and preview.sim != self.state.sim:  # pick up any toggle change
            self.state.sim = preview.sim
            self._save_session()

        match result:
            case ScreenResult.QUIT:
                return NextScreen.QUIT
            case ScreenResult.BACK:
                return self.on_back()
            case ScreenResult.LOAD_VHDL:
                return self._run_vhdl_picker()
            case ScreenResult.SIMULATE:
                return self.on_simulate()

    def on_back(self) -> NextScreen:
        """Return to the selector, dropping the analysis products.

        The loaded VHDL path is kept (it may be reused on the next board),
        but clearing ``work_dir_sim`` guarantees the contract check and
        analysis re-run before the next launch — a different board may have
        incompatible resources.
        """
        self.state.clear_analysis()
        return NextScreen.SELECTOR

    # ── Steps 3-4: pick + validate VHDL ───────────────────────────────────

    def _run_vhdl_picker(self) -> NextScreen:
        """Pick a VHDL file and validate it (encoding → contract → analysis).

        Loops on [Try Another File]; a validation dialog's [Back to Boards]
        bails out to the selector; cancelling the picker returns to the
        preview with the previously-loaded VHDL untouched.
        """
        assert self.board is not None
        s = self.state

        # Start dir: current VHDL, then last session path, then hdl/
        ref: Path | None = None
        if s.vhdl_path:
            ref = Path(s.vhdl_path)
        elif s.last_vhdl_path:
            ref = Path(s.last_vhdl_path)
        start_dir = ref.parent if (ref is not None and ref.exists()) else _HDL_DIR
        preselect = ref.name if (ref is not None and ref.exists()) else ""
        first_pick = True

        while True:
            pygame.display.set_caption("FPGA Simulator \u2013 Select VHDL")
            if first_pick:
                picker = VHDLFilePicker(self.screen, start_dir=start_dir, preselect_name=preselect)
            else:
                picker = VHDLFilePicker(self.screen, start_dir=_HDL_DIR)
            first_pick = False
            picked = picker.run(self.clock)

            if picked is None:
                # Cancelled → back to the preview, keeping the existing VHDL.
                return NextScreen.PREVIEW

            # Stage 1+2: encoding and contract checks; stage 3: analysis.
            example = example_vhdl_for(self.board)
            intent: DialogResult = DialogResult.RETRY
            ok, detail = check_vhdl_encoding(picked)
            if not ok:
                intent = ErrorDialog(self.screen, "VHDL Error", detail, example_path=example).run(
                    self.clock
                )
            else:
                res = check_vhdl_contract(picked, board_def=self.board)
                ok, detail = res.ok, res.message
                s.convention = res.match  # board-native (U21 B3) when set, else None
                if not ok:
                    intent = ErrorDialog(
                        self.screen, "VHDL Error", detail, example_path=example
                    ).run(self.clock)
                else:
                    ok, detail = self._analyze_with_spinner(picked)
                    if not ok:
                        intent = ErrorDialog(
                            self.screen,
                            f"{s.sim.label} Error",
                            detail,
                            example_path=example,
                        ).run(self.clock)

            if ok:
                # After all three stages pass, ``detail`` is the work dir.
                return self.on_vhdl_loaded(picked, detail)
            if intent is DialogResult.BACK:
                pygame.display.set_caption("FPGA Simulator")
                return self.on_back()
            # DialogResult.RETRY → pick again (starting back at hdl/)

    def on_vhdl_loaded(self, vhdl_path: str, work_dir: str) -> NextScreen:
        """Record a validated + analyzed VHDL file, then re-enter the preview.

        ``work_dir_sim`` records which simulator did the analysis so a
        later simulator toggle triggers re-analysis at launch.  The session is
        saved here — on *pick*, not only at launch — so a browsed-but-unrun
        file, its directory, and its ``recent[]`` entry survive a restart.
        """
        s = self.state
        s.vhdl_path = vhdl_path
        s.last_vhdl_path = vhdl_path
        s.work_dir = work_dir
        s.work_dir_sim = s.sim
        self._save_session()
        if self.board is not None:
            push_recent(self.board.class_name, self.board.source, vhdl_path)
        return NextScreen.PREVIEW

    # ── Step 5: launch simulation ─────────────────────────────────────────

    def _analyze_with_spinner(
        self, vhdl_path: str, work_dir: str | None = None
    ) -> tuple[bool, str]:
        """Run simulator analysis + elaboration behind a busy spinner.

        Analysis is slow (5-10 s), so the spinner keeps the window from
        looking frozen.  *work_dir* (when given) re-analyzes into an existing
        work dir instead of a fresh temp dir — the [Reload VHDL] path, where a
        new dir per reload would pile up in $TMP.  Returns
        ``(ok, work_dir_or_error_message)``.
        """
        assert self.board is not None
        _conv = self.state.convention
        _title = (
            f"Analyzing board-native {Path(vhdl_path).name}…"
            if _conv is not None
            else f"Analyzing {Path(vhdl_path).name}…"
        )
        _detail = f"Running {self.state.sim.label} analysis & elaboration…"
        if _conv is not None:
            _detail = (
                f"Board-native ({_conv.maker}) – {self.state.sim.label} analysis & elaboration…"
            )
        return run_with_spinner(
            self.screen,
            self.clock,
            _title,
            partial(
                analyze_vhdl,
                vhdl_path,
                work_dir=work_dir,
                toplevel=Path(vhdl_path).stem,
                simulator=self.state.sim.engine,
                sim_path=self.state.sim.path,
                board_def=self.board,
                match=_conv,
            ),
            detail=_detail,
        )

    def on_simulate(self) -> NextScreen:
        """Run the simulation in the launcher's window (single-window, U34).

        Re-analyzes when the work dir is missing or came from a different
        simulator (with a mandatory contract re-check, so a stale session
        cannot bypass it), saves the session, then loops: start the headless
        GHDL/NVC child, render a :class:`SimulationScreen` in place, and route
        its :class:`SimExit` — RELOAD_VHDL revalidates + relaunches without
        showing the preview, BACK_TO_BOARDS returns to the selector, CHANGE_VHDL
        opens the picker, QUIT (window X) exits the app, and STOPPED re-enters
        the preview.  No window is ever created or destroyed.
        """
        board = self.board
        s = self.state
        assert board is not None
        assert s.vhdl_path is not None  # Start button only fires when VHDL is set

        # Re-analyze if the work dir is missing / from a different simulator —
        # the same guard (and mandatory contract re-check) as on_simulate.
        if s.needs_reanalysis():
            example = example_vhdl_for(board)
            res = check_vhdl_contract(Path(s.vhdl_path), board_def=board)
            s.convention = res.match
            if not res.ok:
                ErrorDialog(self.screen, "VHDL Error", res.message, example_path=example).run(
                    self.clock
                )
                s.clear_vhdl()
                return NextScreen.PREVIEW
            ok, detail = self._analyze_with_spinner(s.vhdl_path)
            if not ok:
                ErrorDialog(self.screen, f"{s.sim.label} Error", detail, example_path=example).run(
                    self.clock
                )
                return NextScreen.PREVIEW
            s.work_dir = detail
            s.work_dir_sim = s.sim

        s.board_class = board.class_name
        s.board_source = board.source
        s.last_vhdl_path = s.vhdl_path
        self._save_session(window_size=self.screen.get_size())
        push_recent(board.class_name, board.source, s.vhdl_path)

        sim_error: str | None = None
        sim_exit = SimExit.STOPPED
        while True:
            # Re-read the session each (re)launch so the slider resumes where the
            # user left it (SimulationScreen writes it back at exit); the waveform
            # settings ride along too.
            sess = load_session()
            try:
                speed = float(sess.get("speed_factor", SPEED_DEFAULT))
            except (TypeError, ValueError):
                speed = SPEED_DEFAULT
            try:
                child = start_simulation(
                    board.to_json(),
                    s.vhdl_path,
                    Path(s.vhdl_path).stem,
                    build_generics(board, simulator=s.sim.engine),
                    work_dir=s.work_dir,
                    simulator=s.sim.engine,
                    sim_path=s.sim.path,
                    board_def=board,
                    speed_factor=speed,
                    waveform=sess.get("waveform"),
                    waveform_open=sess.get("waveform_open"),
                    waveform_memories=sess.get("waveform_memories"),
                    match=s.convention,
                )
            except Exception as e:  # noqa: BLE001 - surface any launch failure in a dialog
                sim_error = str(e)
                break

            sim_exit = SimulationScreen(
                self.screen,
                self.clock,
                board,
                child,
                speed_factor=speed,
                match=s.convention,
                vhdl_path=s.vhdl_path,
                sim=s.sim,
            ).run()
            finish_waveform(child)

            if sim_exit is not SimExit.RELOAD_VHDL:
                break
            # [Reload VHDL]: revalidate in place (the window stays up), then loop
            # straight into the next launch — never showing the preview.
            bail = self._revalidate_for_reload()
            if bail is not None:
                return bail

        if sim_error:
            intent = ErrorDialog(self.screen, "Simulation Error", sim_error).run(self.clock)
            if intent is DialogResult.BACK:
                return self.on_back()
            return NextScreen.PREVIEW
        if sim_exit is SimExit.QUIT:
            return NextScreen.QUIT  # SimulationScreen already saved the slider speed
        if sim_exit is SimExit.BACK_TO_BOARDS:
            return self.on_back()
        if sim_exit is SimExit.CHANGE_VHDL:
            return self._run_vhdl_picker()
        return NextScreen.PREVIEW

    def _revalidate_for_reload(self) -> NextScreen | None:
        """Re-run the validation pipeline on the current VHDL for [Reload VHDL].

        The file on disk may have changed arbitrarily since it was analyzed —
        that is the point of the button — so all three stages run again:
        encoding → contract → analysis/elaboration, the analysis reusing the
        existing work dir.

        Returns ``None`` when the file is good to relaunch.  On failure the
        analysis products are dropped (they may describe the old file, and the
        reused work dir now holds a partial build) and the validation
        ErrorDialog decides the next screen — [Try Another File] re-enters the
        preview, [Back to Boards] the selector.
        """
        board = self.board
        s = self.state
        assert board is not None
        assert s.vhdl_path is not None
        example = example_vhdl_for(board)

        ok, detail = check_vhdl_encoding(s.vhdl_path)
        if ok:
            res = check_vhdl_contract(Path(s.vhdl_path), board_def=board)
            ok, detail = res.ok, res.message
            s.convention = res.match  # board-native (U21 B3) when set, else None
        title = "VHDL Error"
        if ok:
            title = f"{s.sim.label} Error"
            ok, detail = self._analyze_with_spinner(s.vhdl_path, work_dir=s.work_dir)
        if ok:
            s.work_dir = detail
            s.work_dir_sim = s.sim
            return None

        s.clear_analysis()
        intent = ErrorDialog(self.screen, title, detail, example_path=example).run(self.clock)
        return self.on_back() if intent is DialogResult.BACK else NextScreen.PREVIEW
