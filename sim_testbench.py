"""
sim_testbench.py – cocotb testbench that bridges GHDL signals
to the pygame-based FPGA board UI.

This module is loaded by cocotb inside the GHDL process.
It reads the board definition from an environment variable,
creates the pygame UI, and runs a cooperative loop that
alternates between advancing simulation time and processing
pygame events.
"""

import os
import json

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

import pygame

# Imported here so the testbench can reconstruct the board UI
from board_loader import BoardDef, ComponentInfo
from fpga_board import FPGABoard


def _load_board_from_env():
    """Reconstruct a BoardDef from the JSON in the environment."""
    raw = os.environ.get("FPGA_SIM_BOARD_JSON", "")
    if not raw:
        return None
    data = json.loads(raw)

    def _make_components(items, kind):
        return [ComponentInfo(
            kind=kind,
            name=c["name"],
            number=c["number"],
            pins=c.get("pins", []),
            direction=c.get("direction", ""),
            inverted=c.get("inverted", False),
            connector=tuple(c["connector"]) if c.get("connector") else None,
            attrs=c.get("attrs", {}),
        ) for c in items]

    return BoardDef(
        name=data["name"],
        class_name=data["class_name"],
        leds=_make_components(data.get("leds", []), "led"),
        buttons=_make_components(data.get("buttons", []), "button"),
        switches=_make_components(data.get("switches", []), "switch"),
    )


def _board_to_json(board_def):
    """Serialize a BoardDef to JSON (called from the launcher side)."""
    def _comp(c):
        return {
            "name": c.name, "number": c.number,
            "pins": c.pins, "direction": c.direction,
            "inverted": c.inverted,
            "connector": list(c.connector) if c.connector else None,
            "attrs": c.attrs,
        }
    return json.dumps({
        "name": board_def.name,
        "class_name": board_def.class_name,
        "leds": [_comp(c) for c in board_def.leds],
        "buttons": [_comp(c) for c in board_def.buttons],
        "switches": [_comp(c) for c in board_def.switches],
    })


@cocotb.test()
async def interactive_sim(dut):
    """
    Main interactive simulation loop.

    Drives the clock, reads switch/button state from pygame,
    writes it to GHDL, reads LED outputs, and updates the display.
    """
    board_def = _load_board_from_env()

    pygame.init()
    board = FPGABoard(board_def=board_def, width=1024, height=700)

    # ── Start simulation clock (10ns period = 100MHz) ────────────
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

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
    SIM_STEP_NS = 2000  # 2us per frame = 200 clock cycles at 100MHz

    print(f"\n{'='*60}")
    print(f"  Simulation running: {board_def.name if board_def else 'Generic'}")
    print(f"  {num_led} LEDs, {num_btn} buttons, {num_sw} switches")
    print(f"  Press ESC or close window to stop")
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
