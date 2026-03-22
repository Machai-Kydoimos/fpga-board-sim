"""sim_testbench.py – cocotb testbench that bridges GHDL signals
to the pygame-based FPGA board UI.

This module is loaded by cocotb inside the GHDL process.
It reads the board definition from an environment variable,
creates the pygame UI, and runs a cooperative loop that
alternates between advancing simulation time and processing
pygame events.
"""

import os

import cocotb
import pygame
from cocotb.clock import Clock
from cocotb.handle import SimHandleBase
from cocotb.triggers import Timer

from board_loader import _FALLBACK_CLOCK_HZ, BoardDef
from ui import FPGABoard


def _load_board_from_env() -> BoardDef | None:
    """Reconstruct a BoardDef from the JSON in the environment."""
    raw = os.environ.get("FPGA_SIM_BOARD_JSON", "")
    return BoardDef.from_json(raw) if raw else None


@cocotb.test()
async def interactive_sim(dut: SimHandleBase) -> None:
    """Main interactive simulation loop.

    Drives the clock, reads switch/button state from pygame,
    writes it to GHDL, reads LED outputs, and updates the display.
    """
    board_def = _load_board_from_env()

    sim_w = int(os.environ.get("FPGA_SIM_WIDTH",  "1024"))
    sim_h = int(os.environ.get("FPGA_SIM_HEIGHT", "700"))
    pygame.init()
    board = FPGABoard(board_def=board_def, width=sim_w, height=sim_h)

    # ── Start simulation clock ────────────────────────────────────
    clk_hz = board_def.default_clock_hz if board_def else _FALLBACK_CLOCK_HZ
    clk_period_ns = 1e9 / clk_hz
    cocotb.start_soon(Clock(dut.clk, clk_period_ns, unit="ns").start())

    # ── Initialize inputs ────────────────────────────────────────
    num_sw = len(board.switches)
    num_btn = len(board.buttons)
    num_led = len(board.leds)

    try:
        dut.sw.value = 0
    except AttributeError:
        pass
    try:
        dut.btn.value = 0
    except AttributeError:
        pass

    # ── Wire callbacks: pygame → GHDL inputs ─────────────────────
    def _on_switch(idx, state, info):
        """Collect all switch states into a bit vector and push to DUT."""
        sw_val = 0
        for s in board.switches:
            if s.state:
                sw_val |= (1 << s.index)
        try:
            dut.sw.value = sw_val
        except AttributeError:
            pass
        label = info.display_name if info else f"SW{idx}"
        conn = f"  [{info.connector_str}]" if info else ""
        print(f"{label}: {'ON' if state else 'OFF'}{conn}")

    def _on_button(idx, pressed, info):
        """Collect all button states into a bit vector and push to DUT."""
        btn_val = 0
        for b in board.buttons:
            if b.pressed:
                btn_val |= (1 << b.index)
        try:
            dut.btn.value = btn_val
        except AttributeError:
            pass
        label = info.display_name if info else f"BTN{idx}"
        conn = f"  [{info.connector_str}]" if info else ""
        print(f"{label}: {'PRESSED' if pressed else 'RELEASED'}{conn}")

    board.set_switch_callback(_on_switch)
    board.set_button_callback(_on_button)

    # ── Main loop ────────────────────────────────────────────────
    SIM_STEP_NS = 2000  # 2 µs per display frame

    print(f"\n{'='*60}")
    print(f"  Simulation running: {board_def.name if board_def else 'Generic'}")
    print(f"  {num_led} LEDs, {num_btn} buttons, {num_sw} switches")
    print(f"  Clock: {clk_hz / 1e6:.3g} MHz ({clk_period_ns:.3g} ns period)")
    print("  Press ESC or close window to stop")
    print(f"{'='*60}\n")

    board.running = True
    while board.running:
        # Advance simulation time
        await Timer(SIM_STEP_NS, unit="ns")

        # Read LED outputs from simulation and update pygame
        try:
            led_val = int(dut.led.value)
            for i in range(num_led):
                board.set_led(i, bool(led_val & (1 << i)))
        except Exception:
            pass

        # Process pygame events and draw
        board._handle_events()
        board._draw()
        board.clock.tick(60)

    pygame.quit()
    print("Simulation stopped.")
