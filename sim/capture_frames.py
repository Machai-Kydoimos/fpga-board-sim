"""Headless cocotb test that captures PNG frames of a running design.

Sibling to :mod:`sim_testbench` but non-interactive: it steps the simulation,
mirrors ``dut.led`` / ``dut.seg`` onto an :class:`~fpga_sim.ui.FPGABoard`, and
writes one ``frame_NNNN.png`` per frame into ``CAPTURE_OUTDIR``.  The orchestrator
``scripts/capture_demo.py`` builds the design, runs this module inside the
simulator, then assembles the frames into an optimized GIF (or, with ``--png``,
saves the last frame as a still) for the README / guide.

Like ``sim_testbench``, it runs inside the simulator subprocess and cannot be
imported or executed in the normal pytest environment.  Behavior is driven by
environment variables set by the orchestrator:

``FPGA_SIM_BOARD_JSON``
    Serialized :class:`~fpga_sim.board_loader.BoardDef` (same var sim_testbench uses).
``CAPTURE_OUTDIR``
    Directory to receive ``frame_NNNN.png`` files (created if absent).
``CAPTURE_SCENARIO``
    ``plain`` (default) — fixed-length capture (also carries the persistent
    info strip); ``snake`` — the interactive ``snake_7seg`` storyboard
    (reverse, lamp-test, speed-up, then back to normal so the GIF loops
    seamlessly); ``cpu_walk`` — the interactive embedded-CPU walking-counter
    storyboard (same shape as ``snake``); ``dice`` — the embedded-CPU
    dice-roller storyboard (BTN0 rolls, four times).
``CAPTURE_STEP_NS``
    Nanoseconds per ``await Timer`` step (default ``2000``).
``CAPTURE_W`` / ``CAPTURE_H``
    Board surface size in pixels (default ``900`` x ``640``).
``CAPTURE_SOURCE`` / ``CAPTURE_VHDL_NAME``
    Board source directory name / VHDL path shown in the persistent info strip.

Plain scenario only: ``CAPTURE_FRAMES`` (default 80), ``CAPTURE_EVERY`` (default 1),
``CAPTURE_SW`` (default 0).  Storyboard scenarios (snake/cpu_walk/dice) share
``CAPTURE_HOLD_FRAMES`` (default 20, frames a press/toggle is held).  Snake
only: ``CAPTURE_COUNTER_BITS``, ``CAPTURE_END_CYCLES`` (default 8),
``CAPTURE_TAIL_FRAMES`` (default 30, extra time after the speed-up).  cpu_walk
only: ``CAPTURE_PRESCALER_BITS`` (default 10) — must match the capture
variant's own ``PRESCALER_BITS`` generic so the step accounting lines up with
the design's actual visible rate.
"""

import os

import cocotb
import pygame
from capture_common import draw_caption, draw_cursor, draw_strip
from cocotb.triggers import Timer

from fpga_sim.board_loader import BoardDef
from fpga_sim.ui import FPGABoard
from fpga_sim.ui.constants import get_font

# Fixed wrapper clock half-period (ns).  The absolute clock rate is irrelevant
# for capture; pinning it makes "clocks advanced per frame" = CAPTURE_STEP_NS / 10,
# i.e. animation pace is board-independent and tunable purely via CAPTURE_STEP_NS.
_CLK_HALF_NS = 5

# Matches SKIP_BASE in firmware/mx65_walking_counter_7seg.s (each active
# switch halves it, doubling the visible step rate).
_CPU_WALK_SKIP_BASE = 8


def _env_int(name: str, default: int) -> int:
    """Return integer environment variable *name*, or *default* when unset/empty."""
    raw = os.environ.get(name, "")
    return int(raw) if raw else default


def _mirror_outputs(dut: object, board: FPGABoard, num_leds: int, num_segs: int) -> int:
    """Copy ``dut.led`` / ``dut.seg`` onto the board widgets; return the LED bits.

    *num_leds* is the boundary channel count (U37): three bits per RGB LED.
    Channels fold onto per-component widgets (an RGB widget lights when any of
    its channels is high); on the mono-only demo boards the fold is 1:1.
    """
    led_val = int(dut.led.value)  # type: ignore[attr-defined]
    targets = (
        board.board_def.led_channel_targets if board.board_def is not None else range(num_leds)
    )
    lit = [False] * len(board.leds)
    for ch, comp in enumerate(targets):
        if comp < len(lit):
            lit[comp] = lit[comp] or bool(led_val & (1 << ch))
    for i, on in enumerate(lit):
        board.set_led(i, on)
    if num_segs:
        seg_val = int(dut.seg.value)  # type: ignore[attr-defined]
        for digit in range(num_segs):
            board.set_seg(digit, (seg_val >> (8 * digit)) & 0xFF)
    return led_val


def _save_frame(
    board: FPGABoard, outdir: str, frame: int, strip: str, strip_font: pygame.font.Font
) -> None:
    """Render the board (with the persistent info strip) and write ``frame_NNNN.png``."""
    board._draw(flip=False)
    if strip:
        draw_strip(board.screen, strip, strip_font)
    pygame.image.save(board.screen, os.path.join(outdir, f"frame_{frame:04d}.png"))


async def _run_plain(
    dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int, strip: str
) -> None:
    """Fixed-length capture: step, mirror outputs, save, repeat."""
    frames = _env_int("CAPTURE_FRAMES", 80)
    every = max(1, _env_int("CAPTURE_EVERY", 1))
    step_ns = _env_int("CAPTURE_STEP_NS", 2000)
    sw_value = _env_int("CAPTURE_SW", 0)
    num_switches = len(board.switches)
    if num_switches:
        dut.sw.value = sw_value & ((1 << num_switches) - 1)  # type: ignore[attr-defined]
    if board.buttons:
        # Release all buttons: an undriven 'btn' floats at 'U', which a
        # button-reading design (e.g. the embedded CPU) would latch as garbage.
        dut.btn.value = 0  # type: ignore[attr-defined]

    strip_font = get_font(15)
    for frame in range(frames):
        for _ in range(every):
            await Timer(step_ns, unit="ns")
        _mirror_outputs(dut, board, num_leds, num_segs)
        _save_frame(board, outdir, frame, strip, strip_font)


class _Storyboard:
    """Base machinery for scripted interactive demos: eased cursor, captions, taps, toggles.

    Each ``_tick`` advances the sim one frame, eases the faux cursor toward its
    target, draws the board + cursor + strip + caption, and saves a PNG.
    Subclasses that track "how far has the design progressed" (to support
    ``run_to_cycle`` / ``run_steps``-style helpers) override
    :meth:`steps_per_frame`; a demo with nothing to count (e.g. the dice
    roller) uses the no-op default.
    """

    def __init__(
        self,
        dut: object,
        board: FPGABoard,
        outdir: str,
        num_leds: int,
        num_segs: int,
        strip: str,
    ) -> None:
        """Capture references + tuning, park the cursor, and zero the inputs."""
        self.dut = dut
        self.board = board
        self.outdir = outdir
        self.num_leds = num_leds
        self.num_segs = num_segs
        self.step_ns = _env_int("CAPTURE_STEP_NS", 12000)
        self.hold = _env_int("CAPTURE_HOLD_FRAMES", 20)
        self.clocks_per_frame = self.step_ns / (2 * _CLK_HALF_NS)
        self.font = get_font(20, bold=True)
        self.strip = strip
        self.strip_font = get_font(15)

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

    def steps_per_frame(self) -> float:
        """Design steps advanced by one ``_tick`` (0.0 = this demo doesn't track steps)."""
        return 0.0

    async def _pre_press_wait(self) -> None:
        """Block before registering a tap (hook; no-op unless overridden)."""
        return

    async def _tick(self) -> None:
        """Advance one frame: step, mirror, ease the cursor, draw + save."""
        await Timer(self.step_ns, unit="ns")
        _mirror_outputs(self.dut, self.board, self.num_leds, self.num_segs)
        self.steps_done += self.steps_per_frame()
        self.cx += (self.tx - self.cx) * 0.34
        self.cy += (self.ty - self.cy) * 0.34
        if abs(self.tx - self.cx) < 0.5 and abs(self.ty - self.cy) < 0.5:
            self.cx, self.cy = self.tx, self.ty  # snap when arrived so parked frames dedup
        self.board._draw(flip=False)
        draw_cursor(self.board.screen, (self.cx, self.cy), pressed=self.pressed)
        draw_strip(self.board.screen, self.strip, self.strip_font)
        draw_caption(self.board.screen, self.caption, self.font)
        pygame.image.save(
            self.board.screen, os.path.join(self.outdir, f"frame_{self.frame:04d}.png")
        )
        self.frame += 1

    def _aim(self, rect: pygame.Rect) -> None:
        """Point the cursor's target at the center of *rect*."""
        self.tx, self.ty = float(rect.centerx), float(rect.centery)

    async def _travel(self) -> None:
        """Tick until the cursor has eased onto its target (capped for safety)."""
        for _ in range(40):
            if (self.tx - self.cx) ** 2 + (self.ty - self.cy) ** 2 < 9.0:
                return
            await self._tick()

    async def _pause(self, n: int) -> None:
        """Tick *n* frames without moving the target (a readability beat)."""
        for _ in range(n):
            await self._tick()

    async def tap_button(self, idx: int, caption: str) -> None:
        """Move to button *idx*, hold it pressed (with *caption*), then release."""
        if idx >= len(self.board.buttons):
            return
        self._aim(self.board.buttons[idx].rect)
        await self._travel()
        await self._pause(4)  # a beat on the target before the press
        await self._pre_press_wait()
        self.board.buttons[idx].pressed = True
        self.dut.btn.value = 1 << idx  # type: ignore[attr-defined]
        self.pressed = True
        self.caption = caption
        for _ in range(self.hold):
            await self._tick()
        self.board.buttons[idx].pressed = False
        self.dut.btn.value = 0  # type: ignore[attr-defined]
        self.pressed = False
        await self._pause(3)  # a brief tail; the long hold above carries the caption
        self.caption = ""

    async def toggle_switch(self, idx: int, caption: str) -> None:
        """Move to switch *idx*, flip its state (with *caption*), and hold a beat."""
        if idx >= len(self.board.switches):
            return
        self._aim(self.board.switches[idx].rect)
        await self._travel()
        await self._pause(4)  # a beat on the target before the flip
        widget = self.board.switches[idx]
        widget.state = not widget.state
        self.sw_value ^= 1 << idx
        self.dut.sw.value = self.sw_value  # type: ignore[attr-defined]
        self.pressed = True
        self.caption = caption
        for _ in range(self.hold):
            await self._tick()
        self.pressed = False
        await self._pause(3)
        self.caption = ""

    async def coast(self, frames: int) -> None:
        """Park the cursor and run *frames* more frames (no interaction)."""
        self.tx, self.ty = self.park
        self.caption = ""
        for _ in range(frames):
            await self._tick()


class _SnakeDemo(_Storyboard):
    """Drives the interactive ``snake_7seg`` storyboard.

    The snake step count is tracked deterministically (step period =
    ``2**step_idx`` clocks; each active switch lowers ``step_idx`` by 1) so we
    know when each full cycle ends.
    """

    def __init__(
        self,
        dut: object,
        board: FPGABoard,
        outdir: str,
        num_leds: int,
        num_segs: int,
        strip: str,
    ) -> None:
        """Set up the base storyboard plus the snake's cycle-length bookkeeping."""
        super().__init__(dut, board, outdir, num_leds, num_segs, strip)
        self.base_idx = min(_env_int("CAPTURE_COUNTER_BITS", 12) - 1, 16)
        self.steps_per_cycle = 4 * num_segs + 4 if num_segs else 16
        center = num_leds // 2
        self.central_mask = ((1 << center) | (1 << max(0, center - 1))) if num_leds else 0

    def steps_per_frame(self) -> float:
        """Snake steps advanced this frame (step period halves per active switch)."""
        step_idx = max(1, self.base_idx - self.sw_value.bit_count())
        return self.clocks_per_frame / float(1 << step_idx)

    @property
    def cycle(self) -> int:
        """Number of full snake cycles completed so far."""
        return int(self.steps_done // self.steps_per_cycle)

    async def _wait_central_led(self) -> None:
        """Tick until a central LED is lit (capped), so a tap reads clearly."""
        for _ in range(40):
            if int(self.dut.led.value) & self.central_mask:  # type: ignore[attr-defined]
                return
            await self._tick()

    async def _pre_press_wait(self) -> None:
        """Wait for a central LED so a button tap lands on a legible frame."""
        await self._wait_central_led()

    async def run_to_cycle(self, target: int, *, cap: int = 900) -> None:
        """Park the cursor and run the snake until *target* full cycles have elapsed."""
        self.tx, self.ty = self.park
        self.caption = ""
        while self.cycle < target and self.frame < cap:
            await self._tick()


class _CpuWalkDemo(_Storyboard):
    """Drives the interactive embedded-CPU walking-counter storyboard.

    Step accounting mirrors the firmware's own tick/skip logic (see
    ``firmware/mx65_walking_counter_7seg.s``): a step happens every
    ``skip * 2**PRESCALER_BITS`` clocks, where ``skip`` halves per active
    switch.
    """

    def __init__(
        self,
        dut: object,
        board: FPGABoard,
        outdir: str,
        num_leds: int,
        num_segs: int,
        strip: str,
    ) -> None:
        """Set up the base storyboard plus the capture build's prescaler width."""
        super().__init__(dut, board, outdir, num_leds, num_segs, strip)
        self.prescaler_bits = _env_int("CAPTURE_PRESCALER_BITS", 10)

    def steps_per_frame(self) -> float:
        """Firmware steps advanced this frame (skip halves per active switch)."""
        skip = max(1, _CPU_WALK_SKIP_BASE >> self.sw_value.bit_count())
        return self.clocks_per_frame / float(skip * (1 << self.prescaler_bits))

    async def run_steps(self, n: float, *, cap: int = 900) -> None:
        """Park the cursor and run until *n* more firmware steps have elapsed."""
        self.tx, self.ty = self.park
        self.caption = ""
        target = self.steps_done + n
        start_frame = self.frame
        while self.steps_done < target and self.frame - start_frame < cap:
            await self._tick()


async def _run_snake(
    dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int, strip: str
) -> None:
    """Scripted interactive demo: BTN0 reverses, BTN1 lights all, SW0 speeds up.

    Ends by restoring both inputs (normal speed, forward direction) so the
    assembled GIF's loop seam is continuous in both rate and direction.
    """
    demo = _SnakeDemo(dut, board, outdir, num_leds, num_segs, strip)
    end_cycle = _env_int("CAPTURE_END_CYCLES", 8)
    tail = _env_int("CAPTURE_TAIL_FRAMES", 30)
    await demo.run_to_cycle(1)
    await demo.tap_button(0, "BTN0  →  snake reverses")
    await demo.run_to_cycle(2)
    await demo.tap_button(1, "BTN1  →  all segments on")
    await demo.run_to_cycle(3)
    await demo.toggle_switch(0, "SW0  →  2x faster")
    await demo.run_to_cycle(end_cycle)
    await demo.toggle_switch(0, "SW0  →  normal speed")
    await demo.tap_button(0, "BTN0  →  forward again")
    await demo.coast(tail)


async def _run_cpu_walk(
    dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int, strip: str
) -> None:
    """Scripted interactive demo: BTN0 reverses, BTN1 lamp-tests, SW0 doubles the rate.

    Ends by restoring both inputs so the assembled GIF's loop seam is
    continuous, mirroring ``_run_snake``.
    """
    demo = _CpuWalkDemo(dut, board, outdir, num_leds, num_segs, strip)
    await demo.run_steps(10)
    await demo.tap_button(0, "BTN0  →  counts down, LED reverses")
    await demo.run_steps(8)
    await demo.tap_button(1, "BTN1  →  lamp test")
    await demo.run_steps(4)
    await demo.toggle_switch(0, "SW0  →  2x faster")
    await demo.run_steps(10)
    await demo.toggle_switch(0, "SW0  →  normal speed")
    await demo.tap_button(0, "BTN0  →  counts up again")
    await demo.coast(40)


async def _run_dice(
    dut: object, board: FPGABoard, outdir: str, num_leds: int, num_segs: int, strip: str
) -> None:
    """Scripted interactive demo: BTN0 rolls the LFSR-driven die, four times.

    The free-running LFSR's value depends on the exact clock count at each
    press, so the post-roll pause is varied slightly per tap (all "around
    35") -- a constant gap would sample the LFSR at the same phase modulo a
    small divisor each time and risk a visually repetitive run of faces.
    """
    demo = _Storyboard(dut, board, outdir, num_leds, num_segs, strip)
    await demo._pause(25)
    for pause_after in (33, 41, 29, 37):
        await demo.tap_button(0, "BTN0  →  roll")
        await demo._pause(pause_after)
    await demo.coast(25)


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
    num_leds = board_def.num_led_channels  # boundary channels (U37)
    num_segs = (
        board_def.seven_seg.num_digits if (board_def.seven_seg and hasattr(dut, "seg")) else 0
    )

    dut.clk_half_ns.value = _CLK_HALF_NS  # type: ignore[attr-defined]

    source = os.environ.get("CAPTURE_SOURCE", "")
    vhdl_name = os.environ.get("CAPTURE_VHDL_NAME", "design.vhd")
    board_label = f"{board_def.name} ({source})" if source else board_def.name
    strip = f"live VHDL simulation   ·   {board_label}   ·   {vhdl_name}"

    if scenario == "snake":
        await _run_snake(dut, board, outdir, num_leds, num_segs, strip)
    elif scenario == "cpu_walk":
        await _run_cpu_walk(dut, board, outdir, num_leds, num_segs, strip)
    elif scenario == "dice":
        await _run_dice(dut, board, outdir, num_leds, num_segs, strip)
    else:
        await _run_plain(dut, board, outdir, num_leds, num_segs, strip)

    pygame.quit()
    cocotb.log.info("capture_frames: scenario=%s done in %s", scenario, outdir)
