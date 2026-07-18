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

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame

from fpga_sim.board_loader import discover_boards, get_default_boards_path
from fpga_sim.controller import ScreenController, build_generics
from fpga_sim.session_config import load_session, update_session
from fpga_sim.sim_bridge import (
    Simulator,
    _probe_simulator,
    detect_simulators,
    discover_simulators,
)
from fpga_sim.ui import FPGABoard
from fpga_sim.ui.constants import get_font
from fpga_sim.ui.theme import THEME_NAMES, set_theme

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef
    from fpga_sim.sim_bridge import ConventionMatch, SimulatorInfo


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
    p.add_argument(
        "--no-ui",
        action="store_true",
        help="Benchmark the simulator only (headless child, no pygame UI); "
        "requires --benchmark. Isolates simulator throughput from UI rendering.",
    )
    p.add_argument(
        "--list-sims",
        action="store_true",
        help="List all discovered/registered simulators (label, backend, version, path) and exit",
    )
    p.add_argument(
        "--add-sim",
        metavar="PATH",
        default=None,
        help="Register a simulator binary at PATH (probe it, save it to the session) and exit",
    )
    return p.parse_args()


def _run_benchmark(args: argparse.Namespace, available_sims: list[Simulator]) -> int:
    """Run a headless benchmark and return an exit code.

    Discovers the board and analyzes the VHDL, then dispatches to one of two
    measurement modes: the default full-system benchmark (the real
    ``SimulationScreen`` rendering headless — :func:`_benchmark_full_system`)
    or, with ``--no-ui``, the simulator alone (:func:`_benchmark_no_ui`).  The
    child free-runs for *args.benchmark* wall-clock seconds; each mode prints a
    performance report and writes a session-log entry.

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

    mode = "simulator only" if args.no_ui else "full system"
    print(f"[benchmark] Board:    {chosen.name}")
    print(f"[benchmark] VHDL:     {vhdl_path.name}")
    print(f"[benchmark] Sim:      {simulator}")
    print(f"[benchmark] Duration: {args.benchmark}s  (headless, {mode})")

    # Analyze VHDL
    generics = build_generics(chosen)
    ok, work_dir = analyze_vhdl(
        vhdl_path,
        toplevel=toplevel_name,
        simulator=simulator,
        board_def=chosen,
        match=res.match,
    )
    if not ok:
        print(f"[benchmark] VHDL analysis failed: {work_dir}", file=sys.stderr)
        return 1

    # Launch the headless child and measure.  Default = the whole app rendering
    # at 60 fps (SimulationScreen under a dummy video driver); --no-ui runs the
    # child alone with no pygame, isolating simulator throughput from UI cost.
    if args.no_ui:
        return _benchmark_no_ui(
            chosen,
            vhdl_path,
            toplevel_name,
            generics,
            simulator,
            work_dir,
            res.match,
            args.benchmark,
        )
    return _benchmark_full_system(
        chosen, vhdl_path, toplevel_name, generics, simulator, work_dir, res.match, args.benchmark
    )


def _benchmark_full_system(
    board: BoardDef,
    vhdl_path: Path,
    toplevel: str,
    generics: dict[str, str],
    simulator: Simulator,
    work_dir: str,
    match: ConventionMatch | None,
    secs: int,
) -> int:
    """Benchmark the whole app headless: the real SimulationScreen + a free-running child.

    Uses ``SDL_VIDEODRIVER=dummy`` and drives the production render loop at
    60 fps (toolbar hidden, matching the pre-U34 benchmark overlay rules), so
    the numbers cover pygame rendering + the IPC link, not just the simulator.
    The child free-runs via *secs* and self-stops, so the screen exits on its
    own with no event injection.  Reads the screen's public ``run_stats``.
    """
    from fpga_sim.sim_bridge import finish_waveform, start_simulation
    from fpga_sim.ui import SimulationScreen
    from fpga_sim.ui.sim_panel import SPEED_DEFAULT

    os.environ["SDL_VIDEODRIVER"] = "dummy"
    try:
        pygame.init()
        screen = pygame.display.set_mode((1024, 700))
        clock = pygame.time.Clock()
        session = load_session()
        try:
            speed = float(session.get("speed_factor", SPEED_DEFAULT))
        except (TypeError, ValueError):
            speed = SPEED_DEFAULT
        child = start_simulation(
            board.to_json(),
            vhdl_path,
            toplevel,
            generics,
            work_dir=work_dir,
            simulator=simulator,
            board_def=board,
            speed_factor=speed,
            match=match,
            benchmark_secs=secs,
        )
        sim_screen = SimulationScreen(
            screen,
            clock,
            board,
            child,
            speed_factor=speed,
            match=match,
            vhdl_path=vhdl_path,
            simulator=simulator,
            show_toolbar=False,
        )
        sim_screen.run()
        finish_waveform(child)
        stats = sim_screen.run_stats
        _print_benchmark_report(
            board,
            simulator,
            ui=True,
            duration_s=stats.duration_s,
            sim_ns=stats.sim_ns,
            steps=stats.steps,
            sim_pct=stats.avg_sim_pct,
            frames=stats.frames,
            avg_fps=stats.avg_fps,
            draw_pct=stats.avg_draw_pct,
            idle_pct=stats.avg_idle_pct,
        )
    finally:
        get_font.cache_clear()
        pygame.quit()
        os.environ.pop("SDL_VIDEODRIVER", None)
    return 0


def _benchmark_no_ui(
    board: BoardDef,
    vhdl_path: Path,
    toplevel: str,
    generics: dict[str, str],
    simulator: Simulator,
    work_dir: str,
    match: ConventionMatch | None,
    secs: int,
) -> int:
    """Benchmark the simulator alone: a free-running headless child, no pygame.

    Drains the link until the child reports ``bye``, then prints its steps /
    sim rate / timer%.  Isolates simulator throughput from UI cost — a gap vs
    the full-system sim rate points to host/child CPU contention.  Writes a
    session-log entry with the UI (fps/draw/idle) fields zeroed.
    """
    from fpga_sim.sim_bridge import finish_waveform, start_simulation
    from fpga_sim.sim_link import drain
    from fpga_sim.sim_session_log import save_session_stats

    child = start_simulation(
        board.to_json(),
        vhdl_path,
        toplevel,
        generics,
        work_dir=work_dir,
        simulator=simulator,
        board_def=board,
        match=match,
        benchmark_secs=secs,
    )
    try:
        connected = child.link.wait_connected(90.0)
    except RuntimeError as e:
        print(f"[benchmark] simulator link failed: {e}", file=sys.stderr)
        child.stop()
        return 1
    if not connected:
        print("[benchmark] simulator never connected", file=sys.stderr)
        child.stop()
        return 1

    bye: dict[str, Any] | None = None
    timer_pct = 0.0
    deadline = time.monotonic() + secs + 120.0  # startup + run + drain headroom
    while bye is None and time.monotonic() < deadline:
        eof = False
        for kind, payload in drain(child.link.conn):
            if kind == "state":
                timer_pct = float(payload.get("timer_pct", timer_pct))
            elif kind == "bye":
                bye = payload
                break
            elif kind == "eof":
                eof = True
        if bye is None and eof:
            break
        if bye is None:
            time.sleep(0.02)

    child.stop()
    finish_waveform(child)
    if bye is None:
        print("[benchmark] child exited without reporting stats", file=sys.stderr)
        return 1

    _print_benchmark_report(
        board,
        simulator,
        ui=False,
        duration_s=float(bye.get("wall_s", 0.0)),
        sim_ns=int(bye.get("sim_ns", 0)),
        steps=int(bye.get("steps", 0)),
        sim_pct=timer_pct,
    )
    save_session_stats(
        board_name=board.name,
        simulator=simulator,
        duration_s=float(bye.get("wall_s", 0.0)),
        avg_fps=0.0,
        sim_time_ns=int(bye.get("sim_ns", 0)),
        avg_ghdl_pct=timer_pct,
        avg_draw_pct=0.0,
        avg_idle_pct=0.0,
        clock_hz=board.default_clock_hz,
        mode="native" if match else "generic",
        convention=match.maker if match else None,
    )
    return 0


def _print_benchmark_report(
    board: BoardDef,
    simulator: Simulator,
    *,
    ui: bool,
    duration_s: float,
    sim_ns: int,
    steps: int,
    sim_pct: float,
    frames: int = 0,
    avg_fps: float = 0.0,
    draw_pct: float = 0.0,
    idle_pct: float = 0.0,
) -> None:
    """Print a benchmark report block (full-system when *ui*, else simulator-only)."""
    scope = "full system" if ui else "simulator only, --no-ui"
    sim_rate = (sim_ns / 1e9) / max(duration_s, 1e-9)
    bar = "=" * 55
    print(f"\n{bar}")
    print(f"  Benchmark Report  ({duration_s:.1f}s wall-clock, {scope})")
    print(bar)
    print(f"  Board     : {board.name}")
    print(f"  Simulator : {simulator.upper()}")
    print(f"  Clock     : {board.default_clock_hz / 1e6:.4g} MHz")
    if ui:
        print(f"  Frames    : {frames}")
        print(f"  Avg FPS   : {avg_fps:.1f}")
    print(f"  Sim steps : {steps}")
    print(f"  Sim time  : {sim_ns / 1e9:.4g} s simulated")
    print(f"  Sim rate  : {sim_rate:.4g}x real-time")
    print(f"  Sim step  : {sim_pct:.1f}%   (child loop share)")
    if ui:
        print(f"  Draw      : {draw_pct:.1f}%   (host frame share)")
        print(f"  Idle      : {idle_pct:.1f}%   (host frame share)")
    print(f"{bar}\n")


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


# ── Simulator registry CLI (U35) ──────────────────────────────────────────────


def _session_extra_sims() -> list[str]:
    """Return the registered simulator paths from the session ``extra_simulators`` list."""
    raw = load_session().get("extra_simulators", [])
    return [str(p) for p in raw] if isinstance(raw, list) else []


def _print_sims_table(infos: list[SimulatorInfo]) -> None:
    """Print discovered simulators as a label / backend / version + path block."""
    if not infos:
        print("No simulators found. Install GHDL or NVC, or register one with --add-sim PATH.")
        return
    label_w = max(len(i.label) for i in infos)
    backend_w = max(len(i.backend) for i in infos)
    print(f"Discovered {len(infos)} simulator(s):")
    for i in infos:
        print(f"  {i.label:<{label_w}}  {i.backend:<{backend_w}}  {i.version}")
        print(f"  {'':<{label_w}}  {'':<{backend_w}}  {i.path}")


def _list_sims() -> int:
    """``--list-sims``: print the discovered/registered simulators, then exit 0."""
    _print_sims_table(discover_simulators(_session_extra_sims()))
    return 0


def _probe_diagnostic(path: str) -> str:
    """Best-effort ``--version`` text of a rejected --add-sim path, for the error."""
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=5)
    except Exception:  # noqa: BLE001 - the diagnostic is best-effort
        return ""
    return (result.stdout or result.stderr).strip()


def _add_sim(path: str) -> int:
    """``--add-sim PATH``: probe, persist to ``extra_simulators``, print the table.

    Returns 0 on success.  A path that is not a recognized GHDL/NVC simulator
    exits nonzero, echoing the binary's own ``--version`` output so the user can
    see why it was rejected.
    """
    info = _probe_simulator(path)
    if info is None:
        print(f"[add-sim] Not a recognized GHDL or NVC simulator: {path}", file=sys.stderr)
        detail = _probe_diagnostic(path)
        if detail:
            print(detail, file=sys.stderr)
        return 1
    extras = _session_extra_sims()
    target = os.path.realpath(info.path)
    if not any(os.path.realpath(p) == target for p in extras):
        update_session(extra_simulators=[*extras, info.path])
    print(f"[add-sim] Registered {info.label} ({info.backend}): {info.path}")
    _print_sims_table(discover_simulators(_session_extra_sims()))
    return 0


def main() -> None:
    """Run the FPGA Board Simulator: set up pygame, then hand off to ScreenController."""
    args = _parse_args()

    # Headless registry utilities: probe/report installed simulators, then exit.
    if args.list_sims:
        sys.exit(_list_sims())
    if args.add_sim is not None:
        sys.exit(_add_sim(args.add_sim))

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
