"""FPGA Board Simulator - entry point.

All UI logic lives in the ui/ package:
  ui/constants.py      colours and _ui_scale
  ui/components.py     FPGAChip, LED, Switch, Button
  ui/board_selector.py BoardSelector screen
  ui/fpga_board.py     FPGABoard screen
  ui/vhdl_picker.py    VHDLFilePicker screen
  ui/error_dialog.py   ErrorDialog overlay

Usage:
  uv run python fpga_board.py [--sim ghdl|nvc]
  uv run python fpga_board.py --benchmark 10 [--board ICEStick] [--vhdl hdl/blinky.vhd]
"""

import argparse
import os
import sys
from pathlib import Path

import pygame

from board_loader import BoardDef, discover_boards, get_default_boards_path
from session_config import load_session, save_session
from sim_bridge import detect_simulators
from ui import BoardSelector, ErrorDialog, FPGABoard, VHDLFilePicker
from ui.constants import get_font


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FPGA Board Simulator")
    p.add_argument(
        "--sim",
        metavar="NAME",
        default=None,
        help="Simulator to use: 'ghdl' or 'nvc' (overrides saved session)",
    )
    p.add_argument(
        "--benchmark",
        metavar="SECONDS",
        type=int,
        default=None,
        help="Run headless benchmark for N seconds and print a performance report",
    )
    p.add_argument(
        "--board",
        metavar="CLASSNAME",
        default=None,
        help="Board class name to use in benchmark mode (default: first available)",
    )
    p.add_argument(
        "--vhdl",
        metavar="PATH",
        default=None,
        help="VHDL file to simulate in benchmark mode (default: hdl/blinky.vhd)",
    )
    return p.parse_args()


def _run_benchmark(args: argparse.Namespace, available_sims: list[str]) -> int:
    """Run a headless benchmark and return an exit code.

    Discovers the board, analyzes the VHDL, then launches the simulation
    with ``SDL_VIDEODRIVER=dummy`` and ``FPGA_SIM_BENCHMARK=<N>``.
    The simulation runs for *args.benchmark* wall-clock seconds and then
    prints a performance report via the session log.

    Returns 0 on success, 1 on error.
    """
    from sim_bridge import analyze_vhdl, check_vhdl_contract, check_vhdl_encoding

    simulator = args.sim if args.sim and args.sim in available_sims else available_sims[0]
    boards_path = get_default_boards_path()
    boards = discover_boards(boards_path)

    if not boards:
        print("[benchmark] No boards found. Run: git submodule update --init", file=sys.stderr)
        return 1

    # Board selection
    if args.board:
        chosen = next(
            (b for b in boards if b.class_name == args.board or b.name == args.board),
            None,
        )
        if chosen is None:
            names = ", ".join(b.class_name for b in boards[:6])
            print(
                f"[benchmark] Board '{args.board}' not found. Examples: {names}...", file=sys.stderr
            )
            return 1
    else:
        chosen = boards[0]

    # VHDL file selection
    hdl_dir = Path(__file__).parent / "hdl"
    vhdl_path = Path(args.vhdl) if args.vhdl else hdl_dir / "blinky.vhd"
    if not vhdl_path.exists():
        print(f"[benchmark] VHDL file not found: {vhdl_path}", file=sys.stderr)
        return 1

    # Quick validation
    ok, msg = check_vhdl_encoding(vhdl_path)
    if not ok:
        print(f"[benchmark] VHDL encoding error: {msg}", file=sys.stderr)
        return 1
    toplevel_name = vhdl_path.stem
    ok, msg = check_vhdl_contract(vhdl_path)
    if not ok:
        print(f"[benchmark] VHDL contract error: {msg}", file=sys.stderr)
        return 1

    print(f"[benchmark] Board:    {chosen.name}")
    print(f"[benchmark] VHDL:     {vhdl_path.name}")
    print(f"[benchmark] Sim:      {simulator}")
    print(f"[benchmark] Duration: {args.benchmark}s  (headless)")

    # Analyze VHDL
    clk_half_ns = max(1, round(5e8 / chosen.default_clock_hz))
    generics = {
        "NUM_SWITCHES": str(max(1, len(chosen.switches))),
        "NUM_BUTTONS": str(max(1, len(chosen.buttons))),
        "NUM_LEDS": str(max(1, len(chosen.leds))),
        "COUNTER_BITS": "17",
        "CLK_HALF_NS_INIT": str(clk_half_ns),
    }
    ok, work_dir = analyze_vhdl(vhdl_path, toplevel=toplevel_name, simulator=simulator)
    if not ok:
        print(f"[benchmark] VHDL analysis failed: {work_dir}", file=sys.stderr)
        return 1

    # Launch headless simulation
    from sim_bridge import launch_simulation

    board_json = chosen.to_json()
    os.environ["FPGA_SIM_BENCHMARK"] = str(args.benchmark)
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    try:
        launch_simulation(
            board_json,
            vhdl_path,
            toplevel_name,
            generics,
            sim_width=1024,
            sim_height=700,
            work_dir=work_dir,
            simulator=simulator,
        )
    finally:
        os.environ.pop("FPGA_SIM_BENCHMARK", None)
        os.environ.pop("SDL_VIDEODRIVER", None)
    return 0


def main() -> None:
    """Run the FPGA Board Simulator: board selection, VHDL picking, and simulation loop."""
    args = _parse_args()
    available_sims = detect_simulators()

    if args.benchmark is not None:
        sys.exit(_run_benchmark(args, available_sims))

    pygame.init()
    # get_desktop_sizes() is reliable in pygame 2.x before any set_mode() call
    sizes = pygame.display.get_desktop_sizes()
    sw, sh = sizes[0] if sizes else (1920, 1080)
    width = max(1024, min(round(sw * 0.80), 1600))
    height = max(700, min(round(sh * 0.80), 1000))

    boards = discover_boards(get_default_boards_path())

    if not boards:
        print("No amaranth-boards found; using generic board.")
        print("Run  git submodule update --init  to load board definitions.")
        FPGABoard(width=width, height=height).run()
        get_font.cache_clear()
        pygame.quit()
        return

    screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
    pygame.display.set_caption("FPGA Simulator")
    clock = pygame.time.Clock()

    session = load_session()
    last_board_class = session.get("board_class", "")
    last_vhdl_path = session.get("vhdl_path", "")

    # CLI flag overrides session; session overrides default; default is first available
    if args.sim and args.sim in available_sims:
        simulator = args.sim
    elif args.sim:
        print(f"[warn] Simulator '{args.sim}' not found; falling back to {available_sims[0]}")
        simulator = available_sims[0]
    else:
        saved = session.get("simulator", "")
        simulator = saved if saved in available_sims else available_sims[0]

    # Persistent VHDL state — survives across FPGABoard re-entries and simulation runs.
    # Reset to None when the user switches to a different board.
    # Pre-populate from the session so the last-used file is ready on launch;
    # analysis runs on-demand when the user first clicks [Start Simulation].
    current_vhdl_path: str | None = (
        last_vhdl_path if last_vhdl_path and Path(last_vhdl_path).exists() else None
    )
    current_work_dir: str | None = None
    # Track which simulator produced current_work_dir so we can re-analyse
    # automatically when the user switches simulators before hitting Start.
    _work_dir_simulator: str | None = None

    # When set, skip BoardSelector and re-enter FPGABoard with this board.
    # Set after [Load VHDL], after simulation ends, etc.
    _return_to_board: BoardDef | None = None

    from sim_bridge import analyze_vhdl, check_vhdl_contract, check_vhdl_encoding

    while True:
        # ── Step 1: pick a board ─────────────────────────────────
        chosen: BoardDef | None
        if _return_to_board is not None:
            chosen = _return_to_board
            _return_to_board = None
        else:
            chosen = BoardSelector(boards, screen, preselect_class=last_board_class).run(clock)
            if chosen is None:
                break
        assert chosen is not None  # both branches above guarantee non-None here

        # ── Step 2: FPGABoard preview ─────────────────────────────
        # Three footer buttons: [Select Board] [Load VHDL File] [Start Simulation]
        # run() returns: 'back', 'load_vhdl', 'simulate', or 'quit'
        # Title is set by FPGABoard.__init__ (includes VHDL filename when loaded).
        preview = FPGABoard(
            board_def=chosen,
            screen=screen,
            simulator=simulator,
            available_simulators=available_sims,
            vhdl_path=current_vhdl_path,
        )
        result = preview.run()
        simulator = preview.simulator  # pick up any toggle change

        if result == "quit":
            break

        if result == "back":
            # User chose a new board — clear VHDL state so stale path isn't shown
            current_vhdl_path = None
            current_work_dir = None
            _work_dir_simulator = None
            continue

        if result == "load_vhdl":
            # ── Steps 3-4: pick + validate VHDL ──────────────────────────────
            hdl_dir = Path(__file__).parent / "hdl"

            # Start dir: current VHDL, then last session path, then hdl/
            _ref_p = (
                Path(current_vhdl_path)
                if current_vhdl_path
                else (Path(last_vhdl_path) if last_vhdl_path else None)
            )
            _fp_dir = _ref_p.parent if (_ref_p and _ref_p.exists()) else hdl_dir
            _fp_pre = _ref_p.name if (_ref_p and _ref_p.exists()) else ""
            _first_pick = True
            _new_path: str | None = None
            _new_work_dir: str | None = None
            _back_to_boards = False

            while True:
                pygame.display.set_caption("FPGA Simulator \u2013 Select VHDL")
                if _first_pick:
                    picked = VHDLFilePicker(screen, start_dir=_fp_dir, preselect_name=_fp_pre).run(
                        clock
                    )
                    _first_pick = False
                else:
                    picked = VHDLFilePicker(screen, start_dir=hdl_dir).run(clock)

                if picked is None:
                    break  # cancelled → return to FPGABoard keeping existing VHDL

                # Stage 1+2: encoding and contract checks
                _toplevel = Path(picked).stem
                _intent = "retry"
                _ok = False
                _detail = ""
                for _check_fn in [check_vhdl_encoding, check_vhdl_contract]:
                    _ok, _detail = _check_fn(picked)
                    if not _ok:
                        _intent = ErrorDialog(screen, "VHDL Error", _detail).run(clock)
                        break
                else:
                    # Stage 3: simulator analysis + elaboration
                    _ok, _detail = analyze_vhdl(picked, toplevel=_toplevel, simulator=simulator)
                    if _ok:
                        _new_work_dir = _detail
                    else:
                        _intent = ErrorDialog(screen, f"{simulator.upper()} Error", _detail).run(
                            clock
                        )

                if _ok:
                    _new_path = picked
                    break
                if _intent == "back":
                    _back_to_boards = True
                    break
                # "retry" → loop

            if _back_to_boards:
                # "Back to Boards" in error dialog → go to board selector
                current_vhdl_path = None
                current_work_dir = None
                pygame.display.set_caption("FPGA Simulator")
                continue
            if _new_path is not None:
                current_vhdl_path = _new_path
                current_work_dir = _new_work_dir
                last_vhdl_path = _new_path
                _work_dir_simulator = simulator  # record which sim was used
            _return_to_board = chosen  # return to FPGABoard with updated state
            continue

        # result == "simulate" ────────────────────────────────────
        # ── Step 5: launch simulation ─────────────────────────────
        assert current_vhdl_path is not None  # Start button only fires when VHDL is set

        # Re-analyse if the user switched simulator since the last analysis.
        # Each simulator writes its own work directory, so a work_dir produced
        # by NVC cannot be reused by GHDL and vice-versa.
        if _work_dir_simulator != simulator:
            _ra_top = Path(current_vhdl_path).stem
            _ra_ok, _ra_dir = analyze_vhdl(current_vhdl_path, toplevel=_ra_top, simulator=simulator)
            if _ra_ok:
                current_work_dir = _ra_dir
                _work_dir_simulator = simulator
            else:
                ErrorDialog(screen, f"{simulator.upper()} Error", _ra_dir).run(clock)
                _return_to_board = chosen
                continue

        save_session(chosen.class_name, current_vhdl_path, simulator)
        last_board_class = chosen.class_name
        last_vhdl_path = current_vhdl_path

        # Capture final window size before quitting pygame so the
        # simulation subprocess and the post-sim restart both use it.
        width, height = screen.get_size()
        get_font.cache_clear()
        pygame.quit()  # cocotb subprocess will start its own pygame

        from sim_bridge import launch_simulation

        board_json = chosen.to_json()
        toplevel_sim = Path(current_vhdl_path).stem

        # Size generics to match the selected board.
        # CLK_HALF_NS seeds the VHDL wrapper's clock process (sim_wrapper)
        # and is the initial value written to dut.clk_half_ns by sim_testbench.
        clk_half_ns = max(1, round(5e8 / chosen.default_clock_hz))
        generics = {
            "NUM_SWITCHES": str(max(1, len(chosen.switches))),
            "NUM_BUTTONS": str(max(1, len(chosen.buttons))),
            "NUM_LEDS": str(max(1, len(chosen.leds))),
            "COUNTER_BITS": "17",
            "CLK_HALF_NS_INIT": str(clk_half_ns),
        }

        try:
            launch_simulation(
                board_json,
                current_vhdl_path,
                toplevel_sim,
                generics,
                sim_width=width,
                sim_height=height,
                work_dir=current_work_dir,
                simulator=simulator,
            )
        except Exception as e:
            print(f"Simulation error: {e}")

        # After simulation ends, re-init pygame and return to board preview.
        # current_vhdl_path / current_work_dir persist so user can restart immediately.
        pygame.init()
        screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("FPGA Simulator")
        clock = pygame.time.Clock()
        _return_to_board = chosen  # skip board selector; re-enter preview
        continue

    get_font.cache_clear()
    pygame.quit()


if __name__ == "__main__":
    main()
