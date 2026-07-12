"""FPGA Board Simulator - entry point.

This module is the thin entry point: argument parsing, pygame/window setup,
and the headless benchmark.  The launcher screen flow (selector → preview →
picker → simulate) is orchestrated by fpga_sim/controller.py
(ScreenController), and all UI logic lives in the fpga_sim.ui package:
  fpga_sim/ui/constants.py      colors and _ui_scale
  fpga_sim/ui/components.py     FPGAChip, LED, Switch, Button
  fpga_sim/ui/board_selector.py BoardSelector screen
  fpga_sim/ui/board_display.py  FPGABoard screen
  fpga_sim/ui/vhdl_picker.py    VHDLFilePicker screen
  fpga_sim/ui/error_dialog.py   ErrorDialog overlay

Usage:
  uv run python -m fpga_sim [--sim ghdl|nvc]
  uv run python -m fpga_sim --benchmark 10 [--board ICEStick] [--vhdl hdl/blinky.vhd]
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import pygame

from fpga_sim.board_loader import discover_boards, get_default_boards_path
from fpga_sim.controller import ScreenController, build_generics
from fpga_sim.session_config import load_session
from fpga_sim.sim_bridge import Simulator, detect_simulators
from fpga_sim.ui import FPGABoard
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.theme import THEME_NAMES, set_theme


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


def _run_benchmark(args: argparse.Namespace, available_sims: list[Simulator]) -> int:
    """Run a headless benchmark and return an exit code.

    Discovers the board, analyzes the VHDL, then launches the simulation
    with ``SDL_VIDEODRIVER=dummy`` and ``FPGA_SIM_BENCHMARK=<N>``.
    The simulation runs for *args.benchmark* wall-clock seconds and then
    prints a performance report via the session log.

    Returns 0 on success, 1 on error.
    """
    from fpga_sim.sim_bridge import analyze_vhdl, check_vhdl_contract, check_vhdl_encoding

    simulator: Simulator = (
        args.sim if args.sim and args.sim in available_sims else available_sims[0]
    )
    boards_path = get_default_boards_path()
    boards = discover_boards(boards_path)

    if not boards:
        print(
            "[benchmark] No boards found. Run: uv run python scripts/sync_amaranth_boards.py",
            file=sys.stderr,
        )
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
    hdl_dir = Path(__file__).parent.parent.parent / "hdl"
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
    res = check_vhdl_contract(vhdl_path, board_def=chosen)
    ok, msg = res.ok, res.message
    if not ok:
        print(f"[benchmark] VHDL contract error: {msg}", file=sys.stderr)
        return 1

    print(f"[benchmark] Board:    {chosen.name}")
    print(f"[benchmark] VHDL:     {vhdl_path.name}")
    print(f"[benchmark] Sim:      {simulator}")
    print(f"[benchmark] Duration: {args.benchmark}s  (headless)")

    # Analyze VHDL
    generics = build_generics(chosen)
    ok, work_dir = analyze_vhdl(
        vhdl_path, toplevel=toplevel_name, simulator=simulator, board_def=chosen
    )
    if not ok:
        print(f"[benchmark] VHDL analysis failed: {work_dir}", file=sys.stderr)
        return 1

    # Launch headless simulation
    from fpga_sim.sim_bridge import launch_simulation

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
            board_def=chosen,
        )
    finally:
        os.environ.pop("FPGA_SIM_BENCHMARK", None)
        os.environ.pop("SDL_VIDEODRIVER", None)
    return 0


# Floor for a restored window size: saved values below this are treated as junk.
_MIN_RESTORE_W, _MIN_RESTORE_H = 640, 480


def _restore_session_theme(session: dict[str, Any]) -> None:
    """Apply the persisted theme before anything draws.

    An unknown, junk, or missing name silently keeps the default — the
    session schema's readers-fall-back-to-defaults rule.
    """
    saved = session.get("theme", "")
    if saved in THEME_NAMES:
        set_theme(saved)


def _initial_window_size(session: dict[str, Any], desktop: tuple[int, int]) -> tuple[int, int]:
    """Pick the launcher window size: the saved one, else ~80% of the desktop.

    A saved ``window_w`` / ``window_h`` pair (written at quit and at every
    simulation launch) is clamped to the desktop; missing, junk, or
    implausibly small values fall through to the default calculation.
    """
    sw, sh = desktop
    try:
        w, h = int(session.get("window_w", 0)), int(session.get("window_h", 0))
    except (TypeError, ValueError):
        w, h = 0, 0
    if w >= _MIN_RESTORE_W and h >= _MIN_RESTORE_H:
        return min(w, sw), min(h, sh)
    return (
        max(1024, min(round(sw * 0.80), 1600)),
        max(700, min(round(sh * 0.80), 1000)),
    )


def main() -> None:
    """Run the FPGA Board Simulator: set up pygame, then hand off to ScreenController."""
    args = _parse_args()
    available_sims = detect_simulators()

    if args.benchmark is not None:
        sys.exit(_run_benchmark(args, available_sims))

    session = load_session()
    _restore_session_theme(session)
    pygame.init()
    # get_desktop_sizes() is reliable in pygame 2.x before any set_mode() call
    sizes = pygame.display.get_desktop_sizes()
    width, height = _initial_window_size(session, sizes[0] if sizes else (1920, 1080))

    boards = discover_boards(get_default_boards_path())

    if not boards:
        print("No board definitions found; using generic board.")
        print("Run  uv run python scripts/sync_amaranth_boards.py  to generate board files.")
        FPGABoard(width=width, height=height).run()
        get_font.cache_clear()
        pygame.quit()
        return

    screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
    pygame.display.set_caption("FPGA Simulator")
    clock = pygame.time.Clock()

    ScreenController(
        boards,
        screen,
        clock,
        available_sims,
        session=session,
        cli_simulator=args.sim,
    ).run()


if __name__ == "__main__":
    main()
