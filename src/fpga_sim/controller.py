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

The simulation itself still runs in a separate GHDL/NVC + cocotb subprocess
(:func:`fpga_sim.sim_bridge.launch_simulation`); pygame is torn down before
launch and re-initialized after, because the subprocess opens its own pygame
window (see :meth:`ScreenController.on_simulate`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from functools import partial
from pathlib import Path
from typing import Any, cast

import pygame

from fpga_sim.board_loader import BoardDef
from fpga_sim.session_config import load_session, push_recent, save_session
from fpga_sim.sim_bridge import (
    SimExit,
    Simulator,
    analyze_vhdl,
    check_vhdl_contract,
    check_vhdl_encoding,
    launch_simulation,
)
from fpga_sim.ui import (
    BoardSelector,
    DialogResult,
    ErrorDialog,
    FPGABoard,
    ScreenResult,
    VHDLFilePicker,
    run_with_spinner,
)
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.sim_panel import SPEED_DEFAULT
from fpga_sim.ui.theme import current_theme_name

_HDL_DIR = Path(__file__).parent.parent.parent / "hdl"


def example_vhdl_for(board: BoardDef | None) -> Path:
    """Return the bundled example design that satisfies the contract for *board*.

    Offered by validation ErrorDialogs as [View Example]: ``counter_7seg.vhd``
    for boards with a 7-segment display, ``blinky.vhd`` otherwise.
    """
    has_7seg = board is not None and board.seven_seg is not None
    return _HDL_DIR / ("counter_7seg.vhd" if has_7seg else "blinky.vhd")


def build_generics(board: BoardDef) -> dict[str, str]:
    """Build the generic map for sim_wrapper from a board definition.

    NUM_SEGS is absent here: it is conditionally injected by launch_simulation()
    only when both the board has a 7-seg display and the design declares a
    ``seg`` output port (which also selects the 7-seg wrapper template).
    Passing NUM_SEGS to the standard wrapper (which lacks that generic) would
    cause NVC to error during elaboration.
    """
    clk_half_ns = max(1, round(5e8 / board.default_clock_hz))
    num_segs = board.seven_seg.num_digits if board.seven_seg else 0
    return {
        "NUM_SWITCHES": str(max(1, len(board.switches))),
        "NUM_BUTTONS": str(max(1, len(board.buttons))),
        "NUM_LEDS": str(max(1, len(board.leds))),
        # Deliberately below the VHDL default (24/32): at the simulator's
        # sub-real-time throughput a 24-bit counter's MSB toggles too slowly to
        # see, so floor COUNTER_BITS at 17 (MSB ~every 1.3 ms of simulated time
        # at 100 MHz) and widen it only for many-digit 7-seg displays. Real
        # hardware would use the full 24/32.
        "COUNTER_BITS": str(max(17, 4 * num_segs)),
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
    ``work_dir_simulator`` records which simulator produced ``work_dir``, so
    switching simulators (or restoring a stale session) forces re-analysis
    before the next launch.  ``last_vhdl_path`` is stickier than
    ``vhdl_path``: it survives invalidation (e.g. a restored file that fails
    the new board's contract) so the picker can still start in the user's
    directory.  The ``board_*`` / ``*_filters`` fields mirror the persisted
    session file: they seed the selector's preselection and the next
    ``save_session()``.
    """

    simulator: Simulator
    vhdl_path: str | None = None
    work_dir: str | None = None
    work_dir_simulator: Simulator | None = None
    last_vhdl_path: str = ""
    board_class: str = ""
    board_source: str = ""
    board_sort: str = ""
    component_filters: list[str] = field(default_factory=list)
    vendor_filters: list[str] = field(default_factory=list)

    def clear_analysis(self) -> None:
        """Drop the analysis products so the next launch re-analyzes."""
        self.work_dir = None
        self.work_dir_simulator = None

    def clear_vhdl(self) -> None:
        """Drop the loaded VHDL file and its analysis products."""
        self.vhdl_path = None
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
        available_sims: list[Simulator],
        *,
        session: dict[str, Any],
        cli_simulator: str | None = None,
    ) -> None:
        """Seed the controller from the saved *session* dict and CLI override.

        *session* is the (possibly empty) dict from ``load_session()``;
        *cli_simulator* is the raw ``--sim`` argument, which overrides the
        session's saved simulator when it names an available one.
        """
        self.boards = boards
        self.screen = screen
        self.clock = clock
        self.available_sims = available_sims
        self.board: BoardDef | None = None  # set by on_board_selected()

        last_vhdl: str = session.get("vhdl_path", "")
        self.state = SessionState(
            simulator=self._resolve_simulator(cli_simulator, session, available_sims),
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
    def _resolve_simulator(
        cli_simulator: str | None,
        session: dict[str, Any],
        available_sims: list[Simulator],
    ) -> Simulator:
        """Pick the simulator: CLI flag overrides session; session overrides default."""
        if cli_simulator:
            if cli_simulator in available_sims:
                return cli_simulator  # mypy narrows str to Simulator via the `in` check
            print(
                f"[warn] Simulator '{cli_simulator}' not found; falling back to {available_sims[0]}"
            )
            return available_sims[0]
        saved = session.get("simulator", "")
        return cast("Simulator", saved) if saved in available_sims else available_sims[0]

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
            s.simulator,
            s.board_source,
            s.board_sort,
            s.component_filters,
            s.vendor_filters,
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
            simulator=self.state.simulator,
            available_simulators=self.available_sims,
            vhdl_path=self.state.vhdl_path,
        )
        result = preview.run()
        if preview.simulator != self.state.simulator:  # pick up any toggle change
            self.state.simulator = preview.simulator
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
        but clearing ``work_dir_simulator`` guarantees the contract check and
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
                ok, detail = check_vhdl_contract(picked, board_def=self.board)
                if not ok:
                    intent = ErrorDialog(
                        self.screen, "VHDL Error", detail, example_path=example
                    ).run(self.clock)
                else:
                    ok, detail = self._analyze_with_spinner(picked)
                    if not ok:
                        intent = ErrorDialog(
                            self.screen,
                            f"{s.simulator.upper()} Error",
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

        ``work_dir_simulator`` records which simulator did the analysis so a
        later simulator toggle triggers re-analysis at launch.  The session is
        saved here — on *pick*, not only at launch — so a browsed-but-unrun
        file, its directory, and its ``recent[]`` entry survive a restart.
        """
        s = self.state
        s.vhdl_path = vhdl_path
        s.last_vhdl_path = vhdl_path
        s.work_dir = work_dir
        s.work_dir_simulator = s.simulator
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
        return run_with_spinner(
            self.screen,
            self.clock,
            f"Analyzing {Path(vhdl_path).name}…",
            partial(
                analyze_vhdl,
                vhdl_path,
                work_dir=work_dir,
                toplevel=Path(vhdl_path).stem,
                simulator=self.state.simulator,
                board_def=self.board,
            ),
            detail=f"Running {self.state.simulator.upper()} analysis & elaboration…",
        )

    def on_simulate(self) -> NextScreen:
        """Launch the simulation subprocess, then act on its exit intent (U7).

        pygame is quit before the launch (the cocotb subprocess opens its own
        window at the same size) and re-initialized afterwards; ``screen``
        and ``clock`` are re-created, and the VHDL/work-dir state persists so
        the user can restart immediately.

        The in-simulation toolbar routes through the :class:`SimExit` the
        subprocess reports: RELOAD_VHDL revalidates + re-analyzes the same
        file and relaunches right here (never showing the preview),
        BACK_TO_BOARDS returns to the selector, CHANGE_VHDL opens the picker,
        and STOPPED re-enters the preview as before.
        """
        board = self.board
        s = self.state
        assert board is not None
        assert s.vhdl_path is not None  # Start button only fires when VHDL is set

        # Re-analyze if the work directory is missing or was produced by a
        # different simulator.  This also covers the session-restore case
        # (work_dir_simulator is None on first launch) where the saved
        # board+VHDL pair may be mismatched (e.g. a 7-seg board with a
        # standard design or vice-versa).  Always re-run the contract check
        # here so a stale session cannot bypass it.
        if s.work_dir_simulator != s.simulator:
            example = example_vhdl_for(board)
            ok, msg = check_vhdl_contract(Path(s.vhdl_path), board_def=board)
            if not ok:
                ErrorDialog(self.screen, "VHDL Error", msg, example_path=example).run(self.clock)
                s.clear_vhdl()
                return NextScreen.PREVIEW
            ok, detail = self._analyze_with_spinner(s.vhdl_path)
            if not ok:
                ErrorDialog(
                    self.screen, f"{s.simulator.upper()} Error", detail, example_path=example
                ).run(self.clock)
                return NextScreen.PREVIEW
            s.work_dir = detail
            s.work_dir_simulator = s.simulator

        s.board_class = board.class_name
        s.board_source = board.source
        s.last_vhdl_path = s.vhdl_path

        # Capture the final window size before quitting pygame so the
        # simulation subprocess, the post-sim restart, and the next app
        # launch (via the session file) all use it.
        width, height = self.screen.get_size()
        self._save_session(window_size=(width, height))
        push_recent(board.class_name, board.source, s.vhdl_path)

        get_font.cache_clear()
        pygame.quit()  # the cocotb subprocess starts its own pygame

        sim_error: str | None = None
        sim_exit = SimExit.STOPPED
        while True:
            # The sim writes the slider's final value back to the session file at
            # exit, so re-read the session each (re)launch: the slider resumes
            # where the user left it — across runs, reloads, and restarts.  The
            # waveform mode + memories + auto-open (launcher-owned; U10/U29/U30)
            # ride along too.
            sess = load_session()
            try:
                speed = float(sess.get("speed_factor", SPEED_DEFAULT))
            except (TypeError, ValueError):
                speed = SPEED_DEFAULT
            waveform = sess.get("waveform")
            waveform_open = sess.get("waveform_open")
            waveform_memories = sess.get("waveform_memories")

            try:
                sim_exit = launch_simulation(
                    board.to_json(),
                    s.vhdl_path,
                    Path(s.vhdl_path).stem,
                    build_generics(board),
                    sim_width=width,
                    sim_height=height,
                    work_dir=s.work_dir,
                    simulator=s.simulator,
                    board_def=board,
                    speed_factor=speed,
                    theme=current_theme_name(),
                    waveform=waveform,
                    waveform_open=waveform_open,
                    waveform_memories=waveform_memories,
                )
            except Exception as e:
                sim_error = str(e)
                break
            if sim_exit is not SimExit.RELOAD_VHDL:
                break

            # [Reload VHDL]: the file on disk may have been edited, so run the
            # full validation pipeline again behind a spinner window, then
            # loop straight into the next launch — never showing the preview.
            self._restore_window(width, height)
            bail = self._revalidate_for_reload()
            if bail is not None:
                return bail
            get_font.cache_clear()
            pygame.quit()

        # After the simulation ends, bring the launcher window back.
        self._restore_window(width, height)

        if sim_error:
            intent = ErrorDialog(self.screen, "Simulation Error", sim_error).run(self.clock)
            if intent is DialogResult.BACK:
                return self.on_back()
            # DialogResult.RETRY → re-enter the board preview
            return NextScreen.PREVIEW
        if sim_exit is SimExit.BACK_TO_BOARDS:
            return self.on_back()
        if sim_exit is SimExit.CHANGE_VHDL:
            return self._run_vhdl_picker()
        return NextScreen.PREVIEW

    def _restore_window(self, width: int, height: int) -> None:
        """Bring the launcher window back after the sim subprocess owned the display."""
        pygame.init()
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("FPGA Simulator")
        self.clock = pygame.time.Clock()

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
            ok, detail = check_vhdl_contract(Path(s.vhdl_path), board_def=board)
        title = "VHDL Error"
        if ok:
            title = f"{s.simulator.upper()} Error"
            ok, detail = self._analyze_with_spinner(s.vhdl_path, work_dir=s.work_dir)
        if ok:
            s.work_dir = detail
            s.work_dir_simulator = s.simulator
            return None

        s.clear_analysis()
        intent = ErrorDialog(self.screen, title, detail, example_path=example).run(self.clock)
        return self.on_back() if intent is DialogResult.BACK else NextScreen.PREVIEW
