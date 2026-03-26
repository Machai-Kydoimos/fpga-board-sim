"""sim_testbench.py – cocotb testbench bridging simulator signals to the pygame FPGA board UI.

This module is loaded by cocotb inside the simulator process.
It reads the board definition from an environment variable,
creates the pygame UI, and runs a cooperative loop that
alternates between advancing simulation time and processing
pygame events.

Clock model
-----------
The clock is generated entirely inside the VHDL ``sim_wrapper`` entity
(see ``sim/sim_wrapper_template.vhd``), not by a Python coroutine.  This
eliminates all per-half-period GPI callbacks, so the only GPI round-trips
per frame are the two endpoints of the single ``await Timer(...)`` call.

The wrapper exposes a ``clk_half_ns`` port (type ``natural``).  When the
panel's [-]/[+] buttons change the virtual clock frequency, this testbench
writes the new half-period to ``dut.clk_half_ns``; the VHDL process picks
it up on the next half-cycle without restarting the simulator.

Timing model
------------
Each frame advances simulation by ``_BASE_STEP_NS × speed_factor / _BASE_SPEED`` ns,
where ``_BASE_STEP_NS = 9_596`` ns and ``_BASE_SPEED = 0.1`` (the slider default).

At the default 0.1× speed the target step equals exactly one ``_MAX_CYCLES_PER_STEP``
worth of cycles at 1 ns/cycle, so the cap is only reached for boards whose clock
period is less than 1 ns (i.e. > 1 GHz — none in practice).  This keeps the full
slider range useful: dragging left slows the design below the default; dragging right
requests more sim time per frame up to the cycle cap.

The step is capped at ``_MAX_CYCLES_PER_STEP`` clock cycles regardless of
the speed setting, to bound simulation work per frame.
"""

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

import cocotb
import pygame
from cocotb.triggers import Timer

from board_loader import _FALLBACK_CLOCK_HZ, BoardDef, ComponentInfo
from sim_session_log import save_session_stats
from ui import FPGABoard, SimPanel

# ── Optional metrics collection (set FPGA_SIM_METRICS=<path> to enable) ──────
_METRICS_PATH: str = os.environ.get("FPGA_SIM_METRICS", "")

# ── Benchmark mode (set FPGA_SIM_BENCHMARK=<seconds> for headless run) ────────
_BENCHMARK_SECS: float = float(os.environ.get("FPGA_SIM_BENCHMARK", "0"))
_BENCHMARK_MODE: bool = _BENCHMARK_SECS > 0
if _BENCHMARK_MODE:
    # Suppress display before pygame is imported (may already be set by caller)
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

# ── Panel height (px at 1.0 scale; _panel_h is computed from window scale) ────
_PANEL_H_BASE = 130

# ── Simulation step constants ─────────────────────────────────────────────────
# Base sim step at the default speed (0.1×).
# 9596 ns = exactly _MAX_CYCLES_PER_STEP × 1 ns, so at 0.1× the slider's
# target equals the cap threshold for a hypothetical 1 GHz board — meaning the
# cap never limits the step at the default speed for any real board (max ~200 MHz,
# period 5 ns → cap = 9596 × 5 = 47980 ns > 9596 ns target).  Moving the slider
# right requests proportionally more ns, eventually hitting the cycle cap for
# high-frequency boards; moving left slows down below the default.
_BASE_STEP_NS: int = 9_596
_BASE_SPEED: float = 0.1
# Maximum clock cycles per Timer call.  With VHDL-side clock generation
# there are no per-cycle GPI callbacks; the limit is NVC/GHDL internal
# simulation throughput.
_MAX_CYCLES_PER_STEP: int = 9_596


def _simulator_version(sim_name: str) -> str:
    """Return the first line of the simulator's --version output."""
    try:
        result = subprocess.run(
            [sim_name, "--version"], capture_output=True, text=True, timeout=5,
        )
        return (result.stdout or result.stderr).splitlines()[0].strip()
    except Exception:
        return "unknown"


def _write_meta_sidecar(
    csv_path: str,
    board_def: BoardDef | None,
    clk_hz: float,
    num_leds: int,
    num_switches: int,
    num_buttons: int,
) -> None:
    """Write a JSON metadata file alongside the CSV for report context."""
    sim_name  = os.environ.get("FPGA_SIM_SIMULATOR", "unknown")
    vhdl_path = os.environ.get("FPGA_SIM_VHDL_PATH", "unknown")
    # FPGA_SIM_TOPLEVEL carries the user's entity name; TOPLEVEL is sim_wrapper
    toplevel  = os.environ.get("FPGA_SIM_TOPLEVEL") or os.environ.get("TOPLEVEL", "unknown")
    try:
        generics: dict[str, str] = json.loads(os.environ.get("FPGA_SIM_GENERICS", "{}"))
    except json.JSONDecodeError:
        generics = {}

    meta = {
        "timestamp":           datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "vhdl_file":           os.path.basename(vhdl_path),
        "vhdl_path":           vhdl_path,
        "toplevel":            toplevel,
        "simulator":           sim_name,
        "simulator_version":   _simulator_version(sim_name),
        "board_name":          board_def.name if board_def else "Generic",
        "board_clock_hz":      clk_hz,
        "generics":            generics,
        "counter_bits":        int(generics.get("COUNTER_BITS", 24)),
        "num_leds":            num_leds,
        "num_switches":        num_switches,
        "num_buttons":         num_buttons,
        "max_cycles_per_step": _MAX_CYCLES_PER_STEP,
        "base_step_ns":        _BASE_STEP_NS,
        "speed_factor_default":_BASE_SPEED,
        "python_version":      sys.version.split()[0],
        "platform":            platform.platform(),
    }

    import pathlib  # noqa: PLC0415
    meta_path = str(pathlib.Path(csv_path).with_suffix("")) + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[metrics] Metadata written to: {meta_path}")


def _load_board_from_env() -> BoardDef | None:
    """Reconstruct a BoardDef from the JSON in the environment."""
    raw = os.environ.get("FPGA_SIM_BOARD_JSON", "")
    return BoardDef.from_json(raw) if raw else None


@cocotb.test()
async def interactive_sim(dut: object) -> None:
    """Run the interactive simulation loop.

    Reads switch/button state from pygame, writes it to the simulator,
    reads LED outputs, and updates the display.  The clock is driven by
    the VHDL sim_wrapper; this coroutine only writes dut.clk_half_ns when
    the panel's [-]/[+] buttons change the virtual clock frequency.
    """
    board_def = _load_board_from_env()

    sim_w = int(os.environ.get("FPGA_SIM_WIDTH",  "1024"))
    sim_h = int(os.environ.get("FPGA_SIM_HEIGHT", "700"))

    pygame.init()

    # Create the pygame window explicitly so the panel and board share it
    screen = pygame.display.set_mode((sim_w, sim_h), pygame.RESIZABLE)

    # Scale the panel height to match the current window size so all 6 info
    # rows remain visible at large / maximised windows.
    from ui.constants import _ui_scale  # noqa: PLC0415
    _panel_h = max(_PANEL_H_BASE, round(_PANEL_H_BASE * _ui_scale(sim_w, sim_h)))

    # Build the SimPanel (occupies the bottom _panel_h px of the window)
    clk_hz = board_def.default_clock_hz if board_def else _FALLBACK_CLOCK_HZ
    panel = SimPanel(
        screen,
        height=_panel_h,
        board_clock_hz=clk_hz,
        board_clocks_hz=board_def.clocks if board_def else None,
    )

    # FPGABoard renders into the top (sim_h - _panel_h) px
    board = FPGABoard(
        board_def=board_def,
        screen=screen,
        width=sim_w,
        height=sim_h - _panel_h,
        height_offset=_panel_h,
    )

    # ── Sync initial clock half-period to the VHDL wrapper ───────────────────
    # The wrapper's CLK_HALF_NS generic seeds the port default; writing it
    # here ensures perfect agreement even if rounding differs.
    _clk_half_ns: int = max(1, int(panel.clk_state["period_ns"] / 2))
    try:
        dut.clk_half_ns.value = _clk_half_ns  # type: ignore[attr-defined]
    except AttributeError:
        pass

    # ── Initialise inputs ─────────────────────────────────────────────────────
    num_sw  = len(board.switches)
    num_btn = len(board.buttons)
    num_led = len(board.leds)

    # ── Optional metrics collector ────────────────────────────────────────────
    if _METRICS_PATH:
        from sim_metrics import SimMetrics  # noqa: PLC0415
        _metrics_obj = SimMetrics(_METRICS_PATH)
        _metrics_obj.start()
        _write_meta_sidecar(
            _METRICS_PATH, board_def, clk_hz,
            num_led, num_sw, num_btn,
        )
        print(f"[metrics] Writing per-frame data to: {_METRICS_PATH}")
        _metrics: SimMetrics | None = _metrics_obj
    else:
        _metrics = None

    try:
        dut.sw.value = 0  # type: ignore[attr-defined]
    except AttributeError:
        pass
    try:
        dut.btn.value = 0  # type: ignore[attr-defined]
    except AttributeError:
        pass

    # ── Wire pygame callbacks → GHDL inputs ──────────────────────────────────
    def _on_switch(idx: int, state: bool, info: ComponentInfo | None) -> None:
        """Collect all switch states and push to DUT."""
        sw_val = 0
        for s in board.switches:
            if s.state:
                sw_val |= (1 << s.index)
        try:
            dut.sw.value = sw_val  # type: ignore[attr-defined]
        except AttributeError:
            pass
        label = info.display_name if info else f"SW{idx}"
        conn  = f"  [{info.connector_str}]" if info else ""
        print(f"{label}: {'ON' if state else 'OFF'}{conn}")

    def _on_button(idx: int, pressed: bool, info: ComponentInfo | None) -> None:
        """Collect all button states and push to DUT."""
        btn_val = 0
        for b in board.buttons:
            if b.pressed:
                btn_val |= (1 << b.index)
        try:
            dut.btn.value = btn_val  # type: ignore[attr-defined]
        except AttributeError:
            pass
        label = info.display_name if info else f"BTN{idx}"
        conn  = f"  [{info.connector_str}]" if info else ""
        print(f"{label}: {'PRESSED' if pressed else 'RELEASED'}{conn}")

    board.set_switch_callback(_on_switch)
    board.set_button_callback(_on_button)

    # ── Print banner ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Simulation running: {board_def.name if board_def else 'Generic'}")
    print(f"  {num_led} LEDs, {num_btn} buttons, {num_sw} switches")
    print(f"  Clock: {clk_hz / 1e6:.4g} MHz  |  Speed: {panel.speed_factor:.4g}x")
    print("  Use the panel sliders to adjust speed and virtual clock.")
    print("  Press ESC or close window to stop")
    print(f"{'='*60}\n")

    # ── Main loop ─────────────────────────────────────────────────────────────
    board.running = True
    if _metrics:
        _metrics.mark_frame_start()

    # S key toggles the stats panel; track visibility here
    _show_panel: bool = True

    # Session-level accumulators for the post-run JSON summary
    _session_start = time.monotonic()
    _fps_acc: list[float] = []
    _ghdl_pct_acc: list[float] = []
    _draw_pct_acc: list[float] = []
    _idle_pct_acc: list[float] = []

    while board.running and (
        not _BENCHMARK_MODE
        or time.monotonic() - _session_start < _BENCHMARK_SECS
    ):
        # ── Compute sim step from speed slider ────────────────────────────────
        clk_period_ns = panel.clk_state["period_ns"]

        if panel.paused:
            sim_step_ns = 1
        else:
            target = max(1, int(_BASE_STEP_NS * panel.speed_factor / _BASE_SPEED))
            cap = max(1, int(clk_period_ns * _MAX_CYCLES_PER_STEP))
            sim_step_ns = min(target, cap)

        # ── Advance simulation ────────────────────────────────────────────────
        _t0 = time.monotonic_ns()
        await Timer(sim_step_ns, unit="ns")
        _t_timer = time.monotonic_ns()

        # ── Update panel stats ────────────────────────────────────────────────
        panel.update(sim_step_ns)

        # ── Read LED outputs from GHDL ────────────────────────────────────────
        try:
            led_val = int(dut.led.value)  # type: ignore[attr-defined]
            for i in range(num_led):
                board.set_led(i, bool(led_val & (1 << i)))
        except Exception:
            pass

        # ── Handle events (board + panel share the same event list) ──────────
        events = pygame.event.get()
        board._handle_events(events)
        for ev in events:
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_s:
                _show_panel = not _show_panel
                board.set_height_offset(_panel_h if _show_panel else 0)
            panel.handle_event(ev)

        # ── Propagate virtual clock changes to the VHDL wrapper ───────────────
        new_half = max(1, int(panel.clk_state["period_ns"] / 2))
        if new_half != _clk_half_ns:
            try:
                dut.clk_half_ns.value = new_half  # type: ignore[attr-defined]
            except AttributeError:
                pass
            _clk_half_ns = new_half

        # ── Render: board first (no flip), then panel (if visible), then flip ──
        _t_draw_start = time.monotonic_ns()
        board._draw(flip=False)
        if _show_panel:
            panel.draw()
        pygame.display.flip()
        _t_draw_end = time.monotonic_ns()

        board.clock.tick(60)
        _t_tick_end = time.monotonic_ns()

        # ── Update panel timing display + accumulate session stats ───────────
        _frame_fps       = board.clock.get_fps()
        _frame_timer_us  = (_t_timer    - _t0)           / 1_000
        _frame_draw_us   = (_t_draw_end - _t_draw_start) / 1_000
        _frame_idle_us   = (_t_tick_end - _t_draw_end)   / 1_000
        panel.update_timing(
            fps=_frame_fps,
            timer_us=_frame_timer_us,
            draw_us=_frame_draw_us,
            idle_us=_frame_idle_us,
        )
        if _frame_fps > 0:
            _fps_acc.append(_frame_fps)
            _total_frame = max(1.0, _frame_timer_us + _frame_draw_us + _frame_idle_us)
            _ghdl_pct_acc.append(_frame_timer_us / _total_frame * 100)
            _draw_pct_acc.append(_frame_draw_us  / _total_frame * 100)
            _idle_pct_acc.append(_frame_idle_us  / _total_frame * 100)

        # ── Post metrics (non-blocking; zero cost when metrics disabled) ──────
        if _metrics:
            _metrics.record(
                timer_us=(_t_timer - _t0) / 1_000,
                draw_us=(_t_draw_end - _t_draw_start) / 1_000,
                tick_us=(_t_tick_end - _t_draw_end) / 1_000,
                sim_step_ns=sim_step_ns,
                clk_period_ns=clk_period_ns,
                speed_factor=panel.speed_factor,
            )

    if _metrics:
        _metrics.stop()
        print(f"[metrics] Saved to: {_METRICS_PATH}")

    # ── Write per-session JSON summary ────────────────────────────────────────
    _duration_s = time.monotonic() - _session_start
    if _fps_acc:
        _n = len(_fps_acc)
        _avg_fps      = sum(_fps_acc)      / _n
        _avg_ghdl_pct = sum(_ghdl_pct_acc) / _n
        _avg_draw_pct = sum(_draw_pct_acc) / _n
        _avg_idle_pct = sum(_idle_pct_acc) / _n
        save_session_stats(
            board_name   = board_def.name if board_def else "Generic",
            simulator    = os.environ.get("FPGA_SIM_SIMULATOR", "ghdl"),
            duration_s   = _duration_s,
            avg_fps      = _avg_fps,
            sim_time_ns  = panel._sim_elapsed_ns,
            avg_ghdl_pct = _avg_ghdl_pct,
            avg_draw_pct = _avg_draw_pct,
            avg_idle_pct = _avg_idle_pct,
            clock_hz     = panel.current_clock_hz,
        )
        if _BENCHMARK_MODE:
            _sim_rate = (panel._sim_elapsed_ns / 1e9) / max(_duration_s, 1e-9)
            print(f"\n{'='*55}")
            print(f"  Benchmark Report  ({_duration_s:.1f}s wall-clock)")
            print(f"{'='*55}")
            print(f"  Board     : {board_def.name if board_def else 'Generic'}")
            print(f"  Simulator : {os.environ.get('FPGA_SIM_SIMULATOR', 'ghdl').upper()}")
            print(f"  Clock     : {panel.current_clock_hz / 1e6:.4g} MHz")
            print(f"  Frames    : {len(_fps_acc)}")
            print(f"  Avg FPS   : {_avg_fps:.1f}")
            print(f"  Sim time  : {panel._sim_elapsed_ns / 1e9:.4g} s simulated")
            print(f"  Sim rate  : {_sim_rate:.4g}x real-time")
            print(f"  GHDL step : {_avg_ghdl_pct:.1f}%")
            print(f"  Draw      : {_avg_draw_pct:.1f}%")
            print(f"  Idle      : {_avg_idle_pct:.1f}%")
            print(f"{'='*55}\n")

    pygame.quit()
    print("Simulation stopped.")
