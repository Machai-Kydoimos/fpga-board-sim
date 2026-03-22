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
"""

import argparse
from pathlib import Path

import pygame

from board_loader import discover_boards, get_default_boards_path
from session_config import load_session, save_session
from sim_bridge import detect_simulators
from ui import BoardSelector, ErrorDialog, FPGABoard, VHDLFilePicker


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="FPGA Board Simulator")
    p.add_argument(
        "--sim", metavar="NAME", default=None,
        help="Simulator to use: 'ghdl' or 'nvc' (overrides saved session)",
    )
    return p.parse_args()


def main():
    args = _parse_args()
    available_sims = detect_simulators()

    pygame.init()
    # get_desktop_sizes() is reliable in pygame 2.x before any set_mode() call
    sizes = pygame.display.get_desktop_sizes()
    sw, sh = sizes[0] if sizes else (1920, 1080)
    width  = max(1024, min(round(sw * 0.80), 1600))
    height = max(700,  min(round(sh * 0.80), 1000))

    boards = discover_boards(get_default_boards_path())

    if not boards:
        print("No amaranth-boards found; using generic board.")
        print("Run  git submodule update --init  to load board definitions.")
        FPGABoard(width=width, height=height).run()
        pygame.quit()
        return

    screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
    pygame.display.set_caption("FPGA Simulator")
    clock = pygame.time.Clock()

    session = load_session()
    last_board_class = session.get("board_class", "")
    last_vhdl_path   = session.get("vhdl_path", "")

    # CLI flag overrides session; session overrides default; default is first available
    if args.sim and args.sim in available_sims:
        simulator = args.sim
    elif args.sim:
        print(f"[warn] Simulator '{args.sim}' not found; falling back to {available_sims[0]}")
        simulator = available_sims[0]
    else:
        saved = session.get("simulator", "")
        simulator = saved if saved in available_sims else available_sims[0]

    while True:
        # ── Step 1: pick a board ─────────────────────────────────
        chosen = BoardSelector(boards, screen,
                               preselect_class=last_board_class).run(clock)
        if chosen is None:
            break

        # ── Step 2: preview board ────────────────────────────────
        # ESC → back to selector, Enter → pick VHDL, close → quit
        # Pass the existing screen — no set_mode(), preserves window state.
        preview = FPGABoard(board_def=chosen, screen=screen,
                            simulator=simulator,
                            available_simulators=available_sims)
        result = preview.run()
        simulator = preview.simulator   # pick up any toggle change
        if result == "quit":
            break
        if result == "back":
            continue

        # result == "simulate" → proceed to VHDL file picker
        # ── Steps 3-4: pick + validate VHDL (inner loop for retry) ───
        from sim_bridge import analyze_vhdl, check_vhdl_contract, check_vhdl_encoding
        hdl_dir = Path(__file__).parent / "hdl"
        vhdl_path = None
        _back_to_boards = False
        analyzed_work_dir = None

        # Derive file-picker start dir and pre-selection from session (first pick only)
        _last_p = Path(last_vhdl_path) if last_vhdl_path else None
        _fp_dir  = _last_p.parent if (_last_p and _last_p.exists()) else hdl_dir
        _fp_pre  = _last_p.name   if (_last_p and _last_p.exists()) else ""
        _first_pick = True

        while True:
            pygame.display.set_caption("FPGA Simulator – Select VHDL")
            if _first_pick:
                vhdl_path = VHDLFilePicker(
                    screen, start_dir=_fp_dir, preselect_name=_fp_pre).run(clock)
                _first_pick = False
            else:
                vhdl_path = VHDLFilePicker(screen, start_dir=hdl_dir).run(clock)
            if vhdl_path is None:
                # ESC in file picker → back to board selector
                _back_to_boards = True
                break

            # Stage 1 + 2: encoding and contract checks
            toplevel_name = Path(vhdl_path).stem
            intent = "retry"
            for check_fn in [check_vhdl_encoding, check_vhdl_contract]:
                ok, detail = check_fn(vhdl_path)
                if not ok:
                    intent = ErrorDialog(screen, "VHDL Error", detail).run(clock)
                    break
            else:
                # Stage 3: simulator analysis + elaboration
                ok, detail = analyze_vhdl(vhdl_path, toplevel=toplevel_name,
                                          simulator=simulator)
                if ok:
                    analyzed_work_dir = detail  # reuse in launch_simulation
                else:
                    intent = ErrorDialog(
                        screen, f"{simulator.upper()} Error", detail).run(clock)

            if ok:
                break  # valid file — proceed to simulation
            if intent == "back":
                _back_to_boards = True
                break
            # intent == "retry" → loop back to file picker

        if _back_to_boards:
            pygame.display.set_caption("FPGA Simulator")
            continue  # back to BoardSelector

        # ── Step 5: launch simulation ────────────────────────────
        save_session(chosen.class_name, vhdl_path, simulator)
        last_board_class = chosen.class_name  # update in-memory session for this run
        last_vhdl_path   = vhdl_path

        # Capture final window size before quitting pygame so the
        # simulation subprocess and the post-sim restart both use it.
        width, height = screen.get_size()
        pygame.quit()  # cocotb subprocess will start its own pygame

        from sim_bridge import launch_simulation

        board_json = chosen.to_json()
        toplevel = toplevel_name

        # Size generics to match board
        generics = {
            "NUM_SWITCHES": str(max(1, len(chosen.switches))),
            "NUM_BUTTONS": str(max(1, len(chosen.buttons))),
            "NUM_LEDS": str(max(1, len(chosen.leds))),
            "COUNTER_BITS": "10",  # short for fast visible blinking
        }

        try:
            launch_simulation(board_json, vhdl_path, toplevel, generics,
                              sim_width=width, sim_height=height,
                              work_dir=analyzed_work_dir,
                              simulator=simulator)
        except Exception as e:
            print(f"Simulation error: {e}")

        # After simulation ends, re-init pygame and loop back at the same size.
        pygame.init()
        screen = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        pygame.display.set_caption("FPGA Simulator")
        clock = pygame.time.Clock()
        continue

    pygame.quit()


if __name__ == "__main__":
    main()
