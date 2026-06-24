"""Headless cocotb test that captures PNG frames of a running design.

Sibling to :mod:`sim_testbench` but non-interactive: it steps the simulation,
mirrors ``dut.led`` / ``dut.seg`` onto an :class:`~fpga_sim.ui.FPGABoard`, and
writes one ``frame_NNNN.png`` per frame into ``CAPTURE_OUTDIR``.  The orchestrator
``scripts/capture_demo.py`` builds the design, runs this module inside the
simulator, then assembles the frames into an optimised GIF for the README.

Like ``sim_testbench``, it runs inside the simulator subprocess and cannot be
imported or executed in the normal pytest environment.  Behaviour is driven by
environment variables set by the orchestrator:

``FPGA_SIM_BOARD_JSON``
    Serialised :class:`~fpga_sim.board_loader.BoardDef` (same var sim_testbench uses).
``CAPTURE_OUTDIR``
    Directory to receive ``frame_NNNN.png`` files (created if absent).
``CAPTURE_SCENARIO``
    ``plain`` (default) — fixed-length capture; or ``snake`` — a scripted
    interactive storyboard for ``snake_7seg`` (button taps + a switch toggle).
``CAPTURE_STEP_NS``
    Nanoseconds per ``await Timer`` step (default ``2000``).
``CAPTURE_W`` / ``CAPTURE_H``
    Board surface size in pixels (default ``900`` x ``640``).

Plain scenario only: ``CAPTURE_FRAMES`` (default 80), ``CAPTURE_EVERY`` (default 1),
``CAPTURE_SW`` (default 0).  Snake scenario only: ``CAPTURE_COUNTER_BITS``,
``CAPTURE_END_CYCLES`` (default 5), ``CAPTURE_HOLD_FRAMES`` (default 6),
``CAPTURE_MAX_FRAMES`` (safety cap, default 400).
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


def _mirror_outputs(dut: object, board: FPGABoard, num_leds: int, num_segs: int) -> int:
    """Copy ``dut.led`` / ``dut.seg`` onto the board widgets; return the LED bits."""
    led_val = int(dut.led.value)  # type: ignore[attr-defined]
    for i in range(num_leds):
        board.set_led(i, bool(led_val & (1 << i)))
    if num_segs:
        seg_val = int(dut.seg.value)  # type: ignore[attr-defined]
        for digit in range(num_segs):
            board.set_seg(digit, (seg_val >> (8 * digit)) & 0xFF)
    return led_val


def _save_frame(board: FPGABoard, outdir: str, frame: int) -> None:
    """Render the board and write ``frame_NNNN.png``."""
    board._draw(flip=False)
    pygame.image.save(board.screen, os.path.join(outdir, f"frame_{frame:04d}.png"))


async def _run_plain(
    dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int
) -> None:
    """Fixed-length capture: step, mirror outputs, save, repeat."""
    frames = _env_int("CAPTURE_FRAMES", 80)
    every = max(1, _env_int("CAPTURE_EVERY", 1))
    step_ns = _env_int("CAPTURE_STEP_NS", 2000)
    sw_value = _env_int("CAPTURE_SW", 0)
    num_switches = len(board.switches)
    if num_switches:
        dut.sw.value = sw_value & ((1 << num_switches) - 1)  # type: ignore[attr-defined]

    for frame in range(frames):
        for _ in range(every):
            await Timer(step_ns, unit="ns")
        _mirror_outputs(dut, board, num_leds, num_segs)
        _save_frame(board, outdir, frame)


async def _run_snake(
    dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int
) -> None:
    """Interactive storyboard for ``snake_7seg``: button taps + a switch speed-up.

    Timeline (deterministic snake-cycle tracking, with the button taps gated on a
    central LED being lit so the interaction reads clearly):

    * cycle 1 done -> tap ``btn0`` (reverses the snake) while a central LED is lit
    * cycle 2 done -> tap ``btn1`` (lights every segment) while a central LED is lit
    * cycle 3 done -> toggle ``SW0`` (each switch doubles the step rate -> faster)
    * run to ``CAPTURE_END_CYCLES`` so the speed-up is visible, then stop
    """
    step_ns = _env_int("CAPTURE_STEP_NS", 14000)
    counter_bits = _env_int("CAPTURE_COUNTER_BITS", 12)
    end_cycles = _env_int("CAPTURE_END_CYCLES", 5)
    hold = _env_int("CAPTURE_HOLD_FRAMES", 6)
    max_frames = _env_int("CAPTURE_MAX_FRAMES", 400)

    steps_per_cycle = 4 * num_segs + 4 if num_segs else 16
    base_idx = min(counter_bits - 1, 16)
    clocks_per_frame = step_ns / (2 * _CLK_HALF_NS)
    center = num_leds // 2
    central_mask = ((1 << center) | (1 << max(0, center - 1))) if num_leds else 0
    n_buttons = len(board.buttons)

    dut.sw.value = 0  # type: ignore[attr-defined]
    dut.btn.value = 0  # type: ignore[attr-defined]

    sw_value = 0
    steps_done = 0.0
    done = {"btn0": False, "btn1": False, "sw0": False}
    pulse_idx = -1
    pulse_left = 0

    frame = 0
    while True:
        await Timer(step_ns, unit="ns")
        led_val = _mirror_outputs(dut, board, num_leds, num_segs)

        # Accrue snake steps so we know when each full cycle completes.  The step
        # period is 2**step_idx clocks; each active switch lowers step_idx by 2.
        step_idx = max(1, base_idx - 2 * sw_value.bit_count())
        steps_done += clocks_per_frame / float(1 << step_idx)
        cycles_done = int(steps_done // steps_per_cycle)
        central = bool(led_val & central_mask)

        if pulse_left > 0:
            pulse_left -= 1
            if pulse_left == 0:
                board.buttons[pulse_idx].pressed = False
                dut.btn.value = 0  # type: ignore[attr-defined]
                done["btn0" if pulse_idx == 0 else "btn1"] = True
                pulse_idx = -1
        elif not done["btn0"] and cycles_done >= 1 and central and n_buttons > 0:
            pulse_idx, pulse_left = 0, hold
            board.buttons[0].pressed = True
            dut.btn.value = 1  # type: ignore[attr-defined]
        elif not done["btn1"] and cycles_done >= 2 and central and n_buttons > 1:
            pulse_idx, pulse_left = 1, hold
            board.buttons[1].pressed = True
            dut.btn.value = 2  # type: ignore[attr-defined]
        elif not done["sw0"] and cycles_done >= 3 and len(board.switches) > 0:
            sw_value |= 1
            board.switches[0].state = True
            dut.sw.value = sw_value  # type: ignore[attr-defined]
            done["sw0"] = True

        _save_frame(board, outdir, frame)
        frame += 1
        if cycles_done >= end_cycles or frame >= max_frames:
            break


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
    scenario = os.environ.get("CAPTURE_SCENARIO", "plain")

    pygame.init()
    board = FPGABoard(board_def=board_def, width=width, height=height, show_footer=False)
    num_leds = len(board_def.leds)
    num_segs = (
        board_def.seven_seg.num_digits if (board_def.seven_seg and hasattr(dut, "seg")) else 0
    )

    dut.clk_half_ns.value = _CLK_HALF_NS  # type: ignore[attr-defined]

    if scenario == "snake":
        await _run_snake(dut, board, outdir, num_leds, num_segs)
    else:
        await _run_plain(dut, board, outdir, num_leds, num_segs)

    pygame.quit()
    cocotb.log.info("capture_frames: scenario=%s done in %s", scenario, outdir)
