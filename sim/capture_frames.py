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
    interactive storyboard for ``snake_7seg`` (a faux cursor taps the buttons
    and a switch, with captions).
``CAPTURE_STEP_NS``
    Nanoseconds per ``await Timer`` step (default ``2000``).
``CAPTURE_W`` / ``CAPTURE_H``
    Board surface size in pixels (default ``900`` x ``640``).

Plain scenario only: ``CAPTURE_FRAMES`` (default 80), ``CAPTURE_EVERY`` (default 1),
``CAPTURE_SW`` (default 0).  Snake scenario only: ``CAPTURE_COUNTER_BITS``,
``CAPTURE_END_CYCLES`` (default 6), ``CAPTURE_HOLD_FRAMES`` (default 11, frames a
press is held), ``CAPTURE_TAIL_FRAMES`` (default 12, extra time after the speed-up).
"""

import os

import cocotb
import pygame
from capture_common import draw_caption, draw_cursor
from cocotb.triggers import Timer

from fpga_sim.board_loader import BoardDef
from fpga_sim.ui import FPGABoard
from fpga_sim.ui.constants import get_font

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


class _SnakeDemo:
    """Drives the interactive ``snake_7seg`` storyboard: eased cursor, captions, taps.

    Each ``_tick`` advances the sim one frame, eases the faux cursor toward its
    target, draws the board + cursor + caption, and saves a PNG.  The snake step
    count is tracked deterministically (step period = ``2**step_idx`` clocks; each
    active switch lowers ``step_idx`` by 2) so we know when each full cycle ends.
    """

    def __init__(
        self, dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int
    ) -> None:
        """Capture references + tuning, park the cursor, and zero the inputs."""
        self.dut = dut
        self.board = board
        self.outdir = outdir
        self.num_leds = num_leds
        self.num_segs = num_segs
        self.step_ns = _env_int("CAPTURE_STEP_NS", 12000)
        self.hold = _env_int("CAPTURE_HOLD_FRAMES", 11)
        self.base_idx = min(_env_int("CAPTURE_COUNTER_BITS", 12) - 1, 16)
        self.clocks_per_frame = self.step_ns / (2 * _CLK_HALF_NS)
        self.steps_per_cycle = 4 * num_segs + 4 if num_segs else 16
        center = num_leds // 2
        self.central_mask = ((1 << center) | (1 << max(0, center - 1))) if num_leds else 0
        self.font = get_font(20, bold=True)

        w, h = board.screen.get_size()
        self.park = (w * 0.5, h * 0.44)
        self.cx, self.cy = self.park
        self.tx, self.ty = self.park
        self.pressed = False
        self.caption = ""
        self.sw_value = 0
        self.steps_done = 0.0
        self.frame = 0
        self.dut.sw.value = 0  # type: ignore[attr-defined]
        self.dut.btn.value = 0  # type: ignore[attr-defined]

    @property
    def cycle(self) -> int:
        """Number of full snake cycles completed so far."""
        return int(self.steps_done // self.steps_per_cycle)

    async def _tick(self) -> None:
        """Advance one frame: step, mirror, ease the cursor, draw + save."""
        await Timer(self.step_ns, unit="ns")
        _mirror_outputs(self.dut, self.board, self.num_leds, self.num_segs)
        step_idx = max(1, self.base_idx - 2 * self.sw_value.bit_count())
        self.steps_done += self.clocks_per_frame / float(1 << step_idx)
        self.cx += (self.tx - self.cx) * 0.34
        self.cy += (self.ty - self.cy) * 0.34
        if abs(self.tx - self.cx) < 0.5 and abs(self.ty - self.cy) < 0.5:
            self.cx, self.cy = self.tx, self.ty  # snap when arrived so parked frames dedup
        self.board._draw(flip=False)
        draw_cursor(self.board.screen, (self.cx, self.cy), pressed=self.pressed)
        draw_caption(self.board.screen, self.caption, self.font)
        pygame.image.save(
            self.board.screen, os.path.join(self.outdir, f"frame_{self.frame:04d}.png")
        )
        self.frame += 1

    def _aim(self, rect: pygame.Rect) -> None:
        """Point the cursor's target at the centre of *rect*."""
        self.tx, self.ty = float(rect.centerx), float(rect.centery)

    async def _travel(self) -> None:
        """Tick until the cursor has eased onto its target (capped for safety)."""
        for _ in range(40):
            if (self.tx - self.cx) ** 2 + (self.ty - self.cy) ** 2 < 9.0:
                return
            await self._tick()

    async def run_to_cycle(self, target: int, *, cap: int = 900) -> None:
        """Park the cursor and run the snake until *target* full cycles have elapsed."""
        self.tx, self.ty = self.park
        self.caption = ""
        while self.cycle < target and self.frame < cap:
            await self._tick()

    async def _wait_central_led(self) -> None:
        """Tick until a central LED is lit (capped), so a tap reads clearly."""
        for _ in range(40):
            if int(self.dut.led.value) & self.central_mask:  # type: ignore[attr-defined]
                return
            await self._tick()

    async def tap_button(self, idx: int, caption: str) -> None:
        """Move to button *idx*, hold it pressed (with *caption*), then release."""
        if idx >= len(self.board.buttons):
            return
        self._aim(self.board.buttons[idx].rect)
        await self._travel()
        await self._wait_central_led()
        self.board.buttons[idx].pressed = True
        self.dut.btn.value = 1 << idx  # type: ignore[attr-defined]
        self.pressed = True
        self.caption = caption
        for _ in range(self.hold):
            await self._tick()
        self.board.buttons[idx].pressed = False
        self.dut.btn.value = 0  # type: ignore[attr-defined]
        self.pressed = False
        for _ in range(5):  # let the caption linger a moment after release
            await self._tick()
        self.caption = ""

    async def toggle_switch(self, idx: int, caption: str) -> None:
        """Move to switch *idx*, flip it on (with *caption*), and hold a beat."""
        if idx >= len(self.board.switches):
            return
        self._aim(self.board.switches[idx].rect)
        await self._travel()
        self.board.switches[idx].state = True
        self.sw_value |= 1 << idx
        self.dut.sw.value = self.sw_value  # type: ignore[attr-defined]
        self.pressed = True
        self.caption = caption
        for _ in range(self.hold):
            await self._tick()
        self.pressed = False
        for _ in range(6):
            await self._tick()
        self.caption = ""

    async def coast(self, frames: int) -> None:
        """Park the cursor and run *frames* more frames (no interaction)."""
        self.tx, self.ty = self.park
        self.caption = ""
        for _ in range(frames):
            await self._tick()


async def _run_snake(
    dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int
) -> None:
    """Scripted interactive demo: BTN0 reverses, BTN1 lights all, SW0 speeds up."""
    demo = _SnakeDemo(dut, board, outdir, num_leds, num_segs)
    end_cycle = _env_int("CAPTURE_END_CYCLES", 6)
    tail = _env_int("CAPTURE_TAIL_FRAMES", 12)
    await demo.run_to_cycle(1)
    await demo.tap_button(0, "BTN0  ·  reverse the snake")
    await demo.run_to_cycle(2)
    await demo.tap_button(1, "BTN1  ·  light every segment")
    await demo.run_to_cycle(3)
    await demo.toggle_switch(0, "SW0  ·  2x update rate")
    await demo.run_to_cycle(end_cycle)
    await demo.coast(tail)


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
