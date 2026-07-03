r"""Capture a short GIF (or PNG still) of a running simulation for the README/guide.

Builds a board + VHDL design through the real ``sim_bridge`` pipeline, runs the
headless ``sim/capture_frames`` cocotb test to dump per-frame PNGs, then
assembles them into an optimized animated GIF with Pillow (or, with ``--png``,
keeps just the last frame as a still).

This is a maintainer / documentation tool (a sibling to
``src/fpga_sim/generate_board_images.py``); it is not part of the installed
package, and Pillow lives in the ``dev`` dependency group rather than in the
runtime dependencies.

Four scenarios (``--scenario``): the default ``snake`` captures a scripted,
interactive demo on the DE10-Lite (``btn0`` reverse, ``btn1`` all-segments,
``SW0`` speed-up, then both restored); ``cpu_walk`` is the same storyboard
shape for an embedded-CPU design; ``dice`` scripts four button-triggered die
rolls; ``plain`` is a fixed-length, non-interactive capture.

Examples
--------
Regenerate the README hero GIF::

    uv run python scripts/capture_demo.py

Capture a plain (non-interactive) clip of another board / design::

    uv run python scripts/capture_demo.py --scenario plain \
        --board arty_a7-35 --vhdl hdl/blinky.vhd --sim ghdl --step-ns 2000 \
        --counter-bits 24 --out docs/assets/blinky.gif

"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

from capture_common import assemble_gif

from fpga_sim.board_loader import BoardDef
from fpga_sim.sim_bridge import (
    Simulator,
    _backend,
    _build_sim_env,
    _generate_wrapper,
    _has_seg_port,
)

_ROOT = Path(__file__).resolve().parent.parent

# Per-scenario tuning defaults, used whenever the matching --flag is omitted.
_SCENARIO_DEFAULTS: dict[str, dict[str, int]] = {
    "snake": {"step_ns": 12000, "counter_bits": 12, "fps": 24},
    "plain": {"step_ns": 2000, "counter_bits": 24, "fps": 25},
    "cpu_walk": {"step_ns": 336000, "counter_bits": 24, "fps": 25},
    "dice": {"step_ns": 336000, "counter_bits": 24, "fps": 25},
}


def _parse_args() -> argparse.Namespace:
    """Parse command-line options for the capture run."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--scenario",
        default="snake",
        choices=["snake", "plain", "cpu_walk", "dice"],
        help="capture scenario",
    )
    p.add_argument("--board", default="de10_lite", help="board JSON path or name stem")
    p.add_argument(
        "--vhdl", type=Path, default=_ROOT / "hdl" / "snake_7seg.vhd", help="VHDL design file"
    )
    p.add_argument(
        "--sim", default="nvc", choices=["ghdl", "nvc"], help="simulator backend (default: nvc)"
    )
    p.add_argument(
        "--out", type=Path, default=_ROOT / "docs" / "assets" / "demo.gif", help="output GIF path"
    )
    p.add_argument(
        "--step-ns", type=int, default=None, help="ns per Timer step (default: scenario-tuned)"
    )
    p.add_argument(
        "--counter-bits", type=int, default=None, help="COUNTER_BITS (default: scenario-tuned)"
    )
    p.add_argument(
        "--fps", type=int, default=None, help="GIF playback fps (default: scenario-tuned)"
    )
    p.add_argument(
        "--end-cycles", type=int, default=8, help="snake: stop after this many snake cycles"
    )
    p.add_argument(
        "--hold-frames",
        type=int,
        default=20,
        help="storyboard scenarios: frames a button/switch stays pressed",
    )
    p.add_argument(
        "--tail-frames", type=int, default=30, help="snake: extra frames after the speed-up"
    )
    p.add_argument("--frames", type=int, default=80, help="plain: number of frames to capture")
    p.add_argument("--every", type=int, default=1, help="plain: Timer steps between saved frames")
    p.add_argument(
        "--switches", type=int, default=0, help="plain: number of low switches to hold high"
    )
    p.add_argument(
        "--prescaler-bits",
        type=int,
        default=10,
        help=(
            "cpu_walk: informs the storyboard's step accounting (CAPTURE_PRESCALER_BITS) -- "
            "must match the capture variant .vhd's own PRESCALER_BITS generic"
        ),
    )
    p.add_argument(
        "--vhdl-label",
        default=None,
        help="override the VHDL path shown in the info strip (e.g. for a temp-generated variant)",
    )
    p.add_argument("--width", type=int, default=900, help="board surface width in px")
    p.add_argument("--height", type=int, default=640, help="board surface height in px")
    p.add_argument(
        "--colors", type=int, default=128, help="GIF palette size (fewer = smaller file)"
    )
    p.add_argument("--keep-frames", action="store_true", help="keep the intermediate PNG frames")
    p.add_argument(
        "--png",
        action="store_true",
        help="save the last captured frame as a still PNG to --out, instead of a GIF",
    )
    return p.parse_args()


def _resolve_board(spec: str) -> Path:
    """Resolve a board spec (a JSON path or a bare name stem) to a board JSON file."""
    direct = Path(spec)
    if direct.is_file():
        return direct
    matches = sorted(_ROOT.glob(f"boards/**/{spec}.json"))
    if not matches:
        raise SystemExit(f"No board JSON found for {spec!r} (looked for boards/**/{spec}.json)")
    return matches[0]


def _run_step(cmd: list[str], env: dict[str, str], cwd: str, what: str) -> None:
    """Run a build subprocess, raising with captured output on failure."""
    result = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{what} failed (rc={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )


def main() -> None:
    """Build the design, capture frames, and assemble the demo GIF (or PNG still)."""
    args = _parse_args()
    if args.png and args.out.suffix.lower() != ".png":
        raise SystemExit(f"--png requires --out to end in .png (got {args.out})")

    simulator = cast(Simulator, args.sim)
    defaults = _SCENARIO_DEFAULTS[args.scenario]
    step_ns = args.step_ns if args.step_ns is not None else defaults["step_ns"]
    counter_bits = args.counter_bits if args.counter_bits is not None else defaults["counter_bits"]
    fps = args.fps if args.fps is not None else defaults["fps"]

    board_json_path = _resolve_board(args.board)
    board_def = BoardDef.from_json(board_json_path.read_text())
    vhdl_path = args.vhdl.resolve()
    toplevel = vhdl_path.stem
    try:
        vhdl_rel = str(vhdl_path.relative_to(_ROOT))
    except ValueError:
        vhdl_rel = vhdl_path.name
    if args.vhdl_label is not None:
        vhdl_rel = args.vhdl_label
    design_has_seg = _has_seg_port(vhdl_path.read_text())

    generics: dict[str, str] = {
        "NUM_SWITCHES": str(len(board_def.switches)),
        "NUM_BUTTONS": str(len(board_def.buttons)),
        "NUM_LEDS": str(len(board_def.leds)),
        "COUNTER_BITS": str(counter_bits),
    }
    if board_def.seven_seg is not None and design_has_seg:
        generics["NUM_SEGS"] = str(board_def.seven_seg.num_digits)

    backend = _backend(simulator)
    env, plugin_lib = _build_sim_env(simulator=simulator)
    work_dir = tempfile.mkdtemp(prefix="capture_demo_")
    frames_dir = tempfile.mkdtemp(prefix="capture_frames_")

    try:
        # Build: analyze user VHDL, generate + analyze the wrapper, elaborate.
        _run_step(backend.analyze_cmd(vhdl_path, work_dir), env, work_dir, "analyze design")
        wrapper = _generate_wrapper(
            toplevel, work_dir, board_def=board_def, design_has_seg=design_has_seg
        )
        _run_step(backend.analyze_cmd(wrapper, work_dir), env, work_dir, "analyze wrapper")
        # NVC bakes generics in at elaboration; GHDL elaborates structurally (empty generics).
        elab_generics = generics if simulator == "nvc" else {}
        _run_step(
            backend.elaborate_cmd("sim_wrapper", elab_generics, work_dir),
            env,
            work_dir,
            "elaborate",
        )

        # Run the headless capture testbench.
        run_env = dict(env)
        run_env.update(
            {
                "COCOTB_TEST_MODULES": "capture_frames",
                "TOPLEVEL": "sim_wrapper",
                "TOPLEVEL_LANG": "vhdl",
                "FPGA_SIM_BOARD_JSON": board_json_path.read_text(),
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
                "CAPTURE_OUTDIR": frames_dir,
                "CAPTURE_SCENARIO": args.scenario,
                "CAPTURE_STEP_NS": str(step_ns),
                "CAPTURE_COUNTER_BITS": str(counter_bits),
                "CAPTURE_END_CYCLES": str(args.end_cycles),
                "CAPTURE_HOLD_FRAMES": str(args.hold_frames),
                "CAPTURE_TAIL_FRAMES": str(args.tail_frames),
                "CAPTURE_SOURCE": board_json_path.parent.name,
                "CAPTURE_VHDL_NAME": vhdl_rel,
                "CAPTURE_FRAMES": str(args.frames),
                "CAPTURE_EVERY": str(args.every),
                "CAPTURE_SW": str((1 << args.switches) - 1 if args.switches > 0 else 0),
                "CAPTURE_W": str(args.width),
                "CAPTURE_H": str(args.height),
                "CAPTURE_PRESCALER_BITS": str(args.prescaler_bits),
                "PYTHONPATH": os.pathsep.join(
                    [
                        str(_ROOT / "src"),
                        str(_ROOT / "sim"),
                        str(_ROOT / "scripts"),
                        run_env.get("PYTHONPATH", ""),
                    ]
                ),
            }
        )
        print(f"Capturing {toplevel} on {board_json_path.name} [{simulator}, {args.scenario}]...")
        _run_step(
            backend.run_cmd("sim_wrapper", generics, plugin_lib, work_dir),
            run_env,
            work_dir,
            "simulate",
        )

        frame_paths = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
        if not frame_paths:
            raise SystemExit("No frames were captured.")

        if args.png:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(frame_paths[-1], args.out)
            size_kib = args.out.stat().st_size // 1024
            print(f"Wrote {args.out} (last of {len(frame_paths)} frames, {size_kib} KiB)")
        else:
            assemble_gif(
                frame_paths, args.out, durations=max(20, round(1000 / fps)), colors=args.colors
            )
            size_kib = args.out.stat().st_size // 1024
            print(f"Wrote {args.out} ({len(frame_paths)} frames, {size_kib} KiB)")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
        if args.keep_frames:
            print(f"Frames kept in {frames_dir}")
        else:
            shutil.rmtree(frames_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
