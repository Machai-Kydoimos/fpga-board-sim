r"""Capture a short GIF of a running simulation for the README.

Builds a board + VHDL design through the real ``sim_bridge`` pipeline, runs the
headless ``sim/capture_frames`` cocotb test to dump per-frame PNGs, then
assembles them into an optimised animated GIF with Pillow.

This is a maintainer / documentation tool (a sibling to
``src/fpga_sim/generate_board_images.py``); it is not part of the installed
package, and Pillow lives in the ``dev`` dependency group rather than in the
runtime dependencies.

Examples
--------
Regenerate the README hero GIF (snake animation on the DE10-Lite)::

    uv run python scripts/capture_demo.py

Capture a different board / design::

    uv run python scripts/capture_demo.py \
        --board arty_a7-35 --vhdl hdl/blinky.vhd --sim ghdl \
        --out docs/assets/blinky.gif

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

from fpga_sim.board_loader import BoardDef
from fpga_sim.sim_bridge import (
    Simulator,
    _backend,
    _build_sim_env,
    _generate_wrapper,
    _has_seg_port,
)

_ROOT = Path(__file__).resolve().parent.parent


def _parse_args() -> argparse.Namespace:
    """Parse command-line options for the capture run."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--board", default="de10_lite", help="board JSON path or name stem (default: de10_lite)"
    )
    p.add_argument(
        "--vhdl", type=Path, default=_ROOT / "hdl" / "snake_7seg.vhd", help="VHDL design file"
    )
    p.add_argument(
        "--sim", default="nvc", choices=["ghdl", "nvc"], help="simulator backend (default: nvc)"
    )
    p.add_argument(
        "--out", type=Path, default=_ROOT / "docs" / "assets" / "demo.gif", help="output GIF path"
    )
    p.add_argument("--frames", type=int, default=90, help="number of frames to capture")
    p.add_argument("--every", type=int, default=1, help="Timer steps advanced between saved frames")
    p.add_argument("--step-ns", type=int, default=2000, help="nanoseconds per Timer step")
    p.add_argument(
        "--switches", type=int, default=4, help="number of low switches to hold high (snake speed)"
    )
    p.add_argument("--counter-bits", type=int, default=24, help="COUNTER_BITS generic")
    p.add_argument("--width", type=int, default=900, help="board surface width in px")
    p.add_argument("--height", type=int, default=640, help="board surface height in px")
    p.add_argument("--fps", type=int, default=25, help="GIF playback frames per second")
    p.add_argument(
        "--colors", type=int, default=128, help="GIF palette size (fewer = smaller file)"
    )
    p.add_argument("--keep-frames", action="store_true", help="keep the intermediate PNG frames")
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


def _assemble_gif(frame_paths: list[str], out: Path, *, fps: int, colors: int) -> None:
    """Quantise the PNG frames and write an optimised looping GIF to *out*."""
    from PIL import Image

    out.parent.mkdir(parents=True, exist_ok=True)
    frames = [
        Image.open(p).convert("RGB").quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
        for p in frame_paths
    ]
    duration_ms = max(20, round(1000 / fps))
    frames[0].save(
        out,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    """Build the design, capture frames, and assemble the demo GIF."""
    args = _parse_args()
    simulator = cast(Simulator, args.sim)

    board_json_path = _resolve_board(args.board)
    board_def = BoardDef.from_json(board_json_path.read_text())
    vhdl_path = args.vhdl.resolve()
    toplevel = vhdl_path.stem
    design_has_seg = _has_seg_port(vhdl_path.read_text())

    generics: dict[str, str] = {
        "NUM_SWITCHES": str(len(board_def.switches)),
        "NUM_BUTTONS": str(len(board_def.buttons)),
        "NUM_LEDS": str(len(board_def.leds)),
        "COUNTER_BITS": str(args.counter_bits),
    }
    if board_def.seven_seg is not None and design_has_seg:
        generics["NUM_SEGS"] = str(board_def.seven_seg.num_digits)

    backend = _backend(simulator)
    env, plugin_lib = _build_sim_env(simulator=simulator)
    work_dir = tempfile.mkdtemp(prefix="capture_demo_")
    frames_dir = tempfile.mkdtemp(prefix="capture_frames_")

    try:
        # Build: analyse user VHDL, generate + analyse the wrapper, elaborate.
        _run_step(backend.analyze_cmd(vhdl_path, work_dir), env, work_dir, "analyse design")
        wrapper = _generate_wrapper(
            toplevel, work_dir, board_def=board_def, design_has_seg=design_has_seg
        )
        _run_step(backend.analyze_cmd(wrapper, work_dir), env, work_dir, "analyse wrapper")
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
                "CAPTURE_FRAMES": str(args.frames),
                "CAPTURE_EVERY": str(args.every),
                "CAPTURE_STEP_NS": str(args.step_ns),
                "CAPTURE_SW": str((1 << args.switches) - 1 if args.switches > 0 else 0),
                "CAPTURE_W": str(args.width),
                "CAPTURE_H": str(args.height),
                "PYTHONPATH": os.pathsep.join(
                    [str(_ROOT / "src"), str(_ROOT / "sim"), run_env.get("PYTHONPATH", "")]
                ),
            }
        )
        print(f"Capturing {toplevel} on {board_json_path.name} [{simulator}] x{args.frames}")
        _run_step(
            backend.run_cmd("sim_wrapper", generics, plugin_lib, work_dir),
            run_env,
            work_dir,
            "simulate",
        )

        frame_paths = sorted(glob.glob(os.path.join(frames_dir, "frame_*.png")))
        if not frame_paths:
            raise SystemExit("No frames were captured.")

        _assemble_gif(frame_paths, args.out, fps=args.fps, colors=args.colors)
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
