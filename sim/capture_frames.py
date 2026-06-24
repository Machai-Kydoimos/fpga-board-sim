"""Headless cocotb test that captures PNG frames of a running design.

Sibling to :mod:`sim_testbench` but non-interactive: it steps the simulation,
mirrors ``dut.led`` / ``dut.seg`` onto an :class:`~fpga_sim.ui.FPGABoard`, and
writes one ``frame_NNNN.png`` per frame into ``CAPTURE_OUTDIR``.  The orchestrator
``scripts/capture_demo.py`` builds the design, runs this module inside the
simulator, then assembles the frames into an optimised GIF for the README.

Like ``sim_testbench``, it runs inside the simulator subprocess and cannot be
imported or executed in the normal pytest environment.  All behaviour is driven
by environment variables set by the orchestrator:

``FPGA_SIM_BOARD_JSON``
    Serialised :class:`~fpga_sim.board_loader.BoardDef` (same var sim_testbench uses).
``CAPTURE_OUTDIR``
    Directory to receive ``frame_NNNN.png`` files (created if absent).
``CAPTURE_FRAMES``
    Number of frames to capture (default ``80``).
``CAPTURE_EVERY``
    ``await Timer`` steps advanced between saved frames (default ``1``).
``CAPTURE_STEP_NS``
    Nanoseconds per ``await Timer`` step (default ``2000``).
``CAPTURE_SW``
    Integer written once to ``dut.sw`` at start (default ``0``); lets the
    orchestrator speed up designs whose rate is switch-controlled (snake_7seg).
``CAPTURE_W`` / ``CAPTURE_H``
    Board surface size in pixels (default ``900`` x ``640``).
"""

import os

import cocotb
import pygame
from cocotb.triggers import Timer

from fpga_sim.board_loader import BoardDef
from fpga_sim.ui import FPGABoard

# Fixed wrapper clock half-period (ns).  The absolute clock rate is irrelevant
# for capture; pinning it makes "clocks advanced per frame" = CAPTURE_STEP_NS / 10,
# i.e. animation pace is board-independent and tunable purely via CAPTURE_STEP_NS.
_CLK_HALF_NS = 5


def _env_int(name: str, default: int) -> int:
    """Return integer environment variable *name*, or *default* when unset/empty."""
    raw = os.environ.get(name, "")
    return int(raw) if raw else default


@cocotb.test()
async def capture(dut: object) -> None:
    """Step the design and write one PNG per frame to ``CAPTURE_OUTDIR``."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    outdir = os.environ["CAPTURE_OUTDIR"]
    os.makedirs(outdir, exist_ok=True)

    board_def = BoardDef.from_json(os.environ["FPGA_SIM_BOARD_JSON"])
    width = _env_int("CAPTURE_W", 900)
    height = _env_int("CAPTURE_H", 640)
    frames = _env_int("CAPTURE_FRAMES", 80)
    every = max(1, _env_int("CAPTURE_EVERY", 1))
    step_ns = _env_int("CAPTURE_STEP_NS", 2000)
    sw_value = _env_int("CAPTURE_SW", 0)

    pygame.init()
    board = FPGABoard(board_def=board_def, width=width, height=height, show_footer=False)

    num_leds = len(board_def.leds)
    num_switches = len(board_def.switches)
    has_seg = hasattr(dut, "seg") and board_def.seven_seg is not None
    num_segs = board_def.seven_seg.num_digits if board_def.seven_seg else 0

    # Drive the wrapper's internal clock so the design advances, and apply the
    # requested static switch pattern (used to set animation speed on snake_7seg).
    dut.clk_half_ns.value = _CLK_HALF_NS  # type: ignore[attr-defined]
    if num_switches:
        dut.sw.value = sw_value & ((1 << num_switches) - 1)  # type: ignore[attr-defined]

    for frame in range(frames):
        for _ in range(every):
            await Timer(step_ns, unit="ns")

        led_val = int(dut.led.value)  # type: ignore[attr-defined]
        for i in range(num_leds):
            board.set_led(i, bool(led_val & (1 << i)))

        if has_seg and num_segs:
            seg_val = int(dut.seg.value)  # type: ignore[attr-defined]
            for digit in range(num_segs):
                board.set_seg(digit, (seg_val >> (8 * digit)) & 0xFF)

        board._draw(flip=False)
        pygame.image.save(board.screen, os.path.join(outdir, f"frame_{frame:04d}.png"))

    pygame.quit()
    cocotb.log.info("capture_frames: wrote %d frames to %s", frames, outdir)
