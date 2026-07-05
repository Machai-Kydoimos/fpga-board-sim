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
from fpga_sim.session_config import save_session
from fpga_sim.sim_bridge import (
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

_HDL_DIR = Path(__file__).parent.parent.parent / "hdl"


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

    # ── Loop ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Drive the screen flow until the user quits, then shut pygame down."""
        nxt = NextScreen.SELECTOR
        while nxt is not NextScreen.QUIT:
            nxt = self._run_selector() if nxt is NextScreen.SELECTOR else self._run_preview()
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
        """Enter the preview for *board*.

        Deliberately does **not** touch the persisted ``board_class`` /
        ``board_source`` preselection — those update only when a simulation
        actually launches (matching the pre-D6b behavior).
        """
        self.board = board
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
        self.state.simulator = preview.simulator  # pick up any toggle change

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
            intent: DialogResult = DialogResult.RETRY
            ok, detail = check_vhdl_encoding(picked)
            if not ok:
                intent = ErrorDialog(self.screen, "VHDL Error", detail).run(self.clock)
            else:
                ok, detail = check_vhdl_contract(picked, board_def=self.board)
                if not ok:
                    intent = ErrorDialog(self.screen, "VHDL Error", detail).run(self.clock)
                else:
                    ok, detail = self._analyze_with_spinner(picked)
                    if not ok:
                        intent = ErrorDialog(
                            self.screen, f"{s.simulator.upper()} Error", detail
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
        later simulator toggle triggers re-analysis at launch.  (U5 will add
        its save-on-pick session write here.)
        """
        s = self.state
        s.vhdl_path = vhdl_path
        s.last_vhdl_path = vhdl_path
        s.work_dir = work_dir
        s.work_dir_simulator = s.simulator
        return NextScreen.PREVIEW

    # ── Step 5: launch simulation ─────────────────────────────────────────

    def _analyze_with_spinner(self, vhdl_path: str) -> tuple[bool, str]:
        """Run simulator analysis + elaboration behind a busy spinner.

        Analysis is slow (5-10 s), so the spinner keeps the window from
        looking frozen.  Returns ``(ok, work_dir_or_error_message)``.
        """
        assert self.board is not None
        return run_with_spinner(
            self.screen,
            self.clock,
            f"Analyzing {Path(vhdl_path).name}…",
            partial(
                analyze_vhdl,
                vhdl_path,
                toplevel=Path(vhdl_path).stem,
                simulator=self.state.simulator,
                board_def=self.board,
            ),
            detail=f"Running {self.state.simulator.upper()} analysis & elaboration…",
        )

    def on_simulate(self) -> NextScreen:
        """Launch the simulation subprocess, then return to the launcher.

        pygame is quit before the launch (the cocotb subprocess opens its own
        window at the same size) and re-initialized afterwards; ``screen``
        and ``clock`` are re-created, and the VHDL/work-dir state persists so
        the user can restart immediately.
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
            ok, msg = check_vhdl_contract(Path(s.vhdl_path), board_def=board)
            if not ok:
                ErrorDialog(self.screen, "VHDL Error", msg).run(self.clock)
                s.clear_vhdl()
                return NextScreen.PREVIEW
            ok, detail = self._analyze_with_spinner(s.vhdl_path)
            if not ok:
                ErrorDialog(self.screen, f"{s.simulator.upper()} Error", detail).run(self.clock)
                return NextScreen.PREVIEW
            s.work_dir = detail
            s.work_dir_simulator = s.simulator

        save_session(
            board.class_name,
            s.vhdl_path,
            s.simulator,
            board.source,
            s.board_sort,
            s.component_filters,
            s.vendor_filters,
        )
        s.board_class = board.class_name
        s.board_source = board.source
        s.last_vhdl_path = s.vhdl_path

        # Capture the final window size before quitting pygame so the
        # simulation subprocess and the post-sim restart both use it.
        width, height = self.screen.get_size()
        get_font.cache_clear()
        pygame.quit()  # the cocotb subprocess starts its own pygame

        sim_error: str | None = None
        try:
            launch_simulation(
                board.to_json(),
                s.vhdl_path,
                Path(s.vhdl_path).stem,
                build_generics(board),
                sim_width=width,
                sim_height=height,
                work_dir=s.work_dir,
                simulator=s.simulator,
                board_def=board,
            )
        except Exception as e:
            sim_error = str(e)

        # After the simulation ends, bring the launcher window back.
        pygame.init()
        self.screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("FPGA Simulator")
        self.clock = pygame.time.Clock()

        if sim_error:
            intent = ErrorDialog(self.screen, "Simulation Error", sim_error).run(self.clock)
            if intent is DialogResult.BACK:
                return self.on_back()
            # DialogResult.RETRY → fall through to re-enter the board preview
        return NextScreen.PREVIEW
