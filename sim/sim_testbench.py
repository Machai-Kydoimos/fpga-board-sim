"""sim_testbench.py - headless cocotb testbench (no pygame, no window).

Single-window simulation (docs/architecture.md): the pygame UI stays in the
launcher process, which owns the one and only window.  This module runs inside
the GHDL/NVC process and shuttles signal state over the ``sim_link`` connection
to the launcher's ``SimulationScreen``.  It never imports pygame, directly or
transitively -- its only ``fpga_sim`` imports are ``board_loader``,
``sim_link`` and (when metrics are enabled) ``sim_metrics``, all pygame-free.
Each frame it:

  1. computes the sim step from the current speed factor
     (``_REAL_STEP_NS`` / ``_MAX_CYCLES_PER_STEP`` math)
  2. ``await Timer(step)``
  3. reads ``led`` / ``seg``, drains control messages, applies inputs/speed/clock
  4. sends throttled state to the host
  5. sleeps to pace sim time to the speed target (skipped when free-running)

Send throttling.  A changed-value flood at tiny sim steps must not turn into
thousands of pipe writes per second, yet the host must still see a fresh value
promptly and never sit staring at a stale one.  So a send is forced whenever an
input was just applied; otherwise it is rate-limited to at most one every
``_SEND_MIN_S`` (4 ms) on a value change, with a ``_SEND_MAX_S`` (50 ms)
heartbeat while values are static.

Environment:
  FPGA_SIM_LINK_PORT / FPGA_SIM_LINK_KEY   host listener (required)
  FPGA_SIM_BOARD_JSON                      board definition (resource counts)
  FPGA_SIM_SPEED                           initial speed factor (default 0.1)
  FPGA_SIM_BENCHMARK=<secs>                free-run (no pacing) for N wall
                                           seconds, then exit with a report
  FPGA_SIM_METRICS=<path>                  per-frame CSV + meta sidecar; the
                                           draw/tick columns are 0.0 here (the
                                           host owns rendering now)
  FPGA_SIM_SIMULATOR / FPGA_SIM_VHDL_PATH / FPGA_SIM_TOPLEVEL / FPGA_SIM_GENERICS
                                           metadata for the metrics meta sidecar
  FPGA_SIM_SPIKE_STEP_MULT=<n>             multiply the per-Timer cycle cap
                                           (GPI-overhead experiment; default 1)
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from fpga_sim.board_loader import _FALLBACK_CLOCK_HZ, BoardDef
from fpga_sim.sim_link import connect_from_env, drain, send

# Loop-pacing constants.  _SPEED_DEFAULT mirrors the host slider default
# (ui.sim_panel.SPEED_DEFAULT), kept local: importing fpga_sim.ui would pull
# pygame into the headless child.
_TARGET_FPS: float = 60.0
_REAL_STEP_NS: int = round(1e9 / _TARGET_FPS)
_MAX_CYCLES_PER_STEP: int = 9_596
_SPEED_DEFAULT: float = 0.1

#: Minimum wall time between unforced state sends (a changed-value flood at
#: tiny sim steps must not turn into thousands of pipe writes per second).
_SEND_MIN_S: float = 0.004
#: Maximum wall time between state sends (heartbeat while values are static).
_SEND_MAX_S: float = 0.05


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _simulator_version(sim_name: str) -> str:
    """Return the first line of the simulator's --version output."""
    try:
        result = subprocess.run(
            [sim_name, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (result.stdout or result.stderr).splitlines()[0].strip()
    except Exception:  # noqa: BLE001 - best-effort metadata only
        return "unknown"


def _write_meta_sidecar(
    csv_path: str,
    board_def: BoardDef | None,
    clk_hz: float,
    num_leds: int,
    num_switches: int,
    num_buttons: int,
) -> None:
    """Write a JSON metadata file alongside the metrics CSV for report context.

    Same format the pre-U34 pygame testbench wrote, but pygame-free: the
    slider default comes from this module's ``_SPEED_DEFAULT`` rather than
    ``ui.sim_panel.SPEED_DEFAULT`` (importing that would pull in pygame).
    """
    sim_name = os.environ.get("FPGA_SIM_SIMULATOR", "unknown")
    vhdl_path = os.environ.get("FPGA_SIM_VHDL_PATH", "unknown")
    # FPGA_SIM_TOPLEVEL carries the user's entity name; TOPLEVEL is sim_wrapper
    toplevel = os.environ.get("FPGA_SIM_TOPLEVEL") or os.environ.get("TOPLEVEL", "unknown")
    try:
        generics: dict[str, str] = json.loads(os.environ.get("FPGA_SIM_GENERICS", "{}"))
    except json.JSONDecodeError:
        generics = {}

    meta = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        "vhdl_file": os.path.basename(vhdl_path),
        "vhdl_path": vhdl_path,
        "toplevel": toplevel,
        "simulator": sim_name,
        "simulator_version": _simulator_version(sim_name),
        "board_name": board_def.name if board_def else "Generic",
        "board_clock_hz": clk_hz,
        "generics": generics,
        "counter_bits": int(generics.get("COUNTER_BITS", 24)),
        "num_leds": num_leds,
        "num_switches": num_switches,
        "num_buttons": num_buttons,
        "num_segs": board_def.seven_seg.num_digits if board_def and board_def.seven_seg else 0,
        "max_cycles_per_step": _MAX_CYCLES_PER_STEP,
        "real_step_ns": _REAL_STEP_NS,
        "speed_factor_default": _SPEED_DEFAULT,
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
    }

    meta_path = str(Path(csv_path).with_suffix("")) + ".meta.json"
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"[bridge] metrics metadata written to: {meta_path}")


@cocotb.test()
async def bridge_sim(dut: object) -> None:
    """Headless interactive loop: DUT <-> sim_link, no display."""
    raw = os.environ.get("FPGA_SIM_BOARD_JSON", "")
    board_def = BoardDef.from_json(raw) if raw else None

    clk_hz = board_def.default_clock_hz if board_def else _FALLBACK_CLOCK_HZ
    clk_period_ns = max(1.0, 1e9 / clk_hz)
    num_leds = len(board_def.leds) if board_def else 4
    num_switches = len(board_def.switches) if board_def else 4
    num_buttons = len(board_def.buttons) if board_def else 4
    seg_digits = board_def.seven_seg.num_digits if board_def and board_def.seven_seg else 0

    speed = _env_float("FPGA_SIM_SPEED", _SPEED_DEFAULT)
    bench_secs = _env_float("FPGA_SIM_BENCHMARK", 0.0)
    free_run = bench_secs > 0
    step_mult = max(1, int(_env_float("FPGA_SIM_SPIKE_STEP_MULT", 1)))

    conn = connect_from_env()
    send(conn, "hello", {"pid": os.getpid()})

    # Initialize inputs (same guards as sim_testbench: ports may be absent).
    for name, value in (("sw", 0), ("btn", 0)):
        try:
            getattr(dut, name).value = value
        except AttributeError:
            pass

    # -- Optional metrics collector (FPGA_SIM_METRICS=<path>) ------------------
    metrics_path = os.environ.get("FPGA_SIM_METRICS", "")
    if metrics_path:
        from fpga_sim.sim_metrics import SimMetrics  # noqa: PLC0415

        _m = SimMetrics(metrics_path)
        _m.start()
        _write_meta_sidecar(metrics_path, board_def, clk_hz, num_leds, num_switches, num_buttons)
        print(f"[bridge] writing per-frame metrics to: {metrics_path}")
        _m.mark_frame_start()
        metrics: SimMetrics | None = _m
    else:
        metrics = None

    led_mask = (1 << max(1, num_leds)) - 1
    paused = False
    running = True
    input_seq = 0  # last applied host input, echoed in every state send
    input_dirty = False  # force a prompt state send after applying an input
    last_led: int | None = None
    last_seg: int | None = None
    last_send = 0.0

    sim_elapsed_ns = 0
    steps = 0
    timer_wall_ns = 0
    loop_wall_ns = 0
    t_start = time.monotonic()

    print(
        f"[bridge] headless sim: {num_leds} LEDs, {seg_digits} seg digits, "
        f"clock {clk_hz / 1e6:.4g} MHz, speed {speed:g}x"
        + (f", FREE-RUN {bench_secs:g}s x{step_mult} step" if free_run else "")
    )

    while running and (not free_run or time.monotonic() - t_start < bench_secs):
        t0 = time.monotonic_ns()

        # -- Step size (sim_testbench math; free-run pins the cap) ------------
        cap = max(1, int(clk_period_ns * _MAX_CYCLES_PER_STEP * step_mult))
        if free_run:
            sim_step_ns = cap
        elif paused:
            sim_step_ns = 1
        else:
            sim_step_ns = min(max(1, round(_REAL_STEP_NS * speed)), cap)
        # CPU-limited indicator: the requested step hit the cycle cap unpaused.
        at_max = (not paused) and sim_step_ns >= cap

        await Timer(sim_step_ns, unit="ns")
        t_timer = time.monotonic_ns()
        sim_elapsed_ns += sim_step_ns
        steps += 1

        # -- Read outputs ------------------------------------------------------
        led_val = last_led
        try:
            led_val = int(dut.led.value) & led_mask  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - X/Z at t=0
            pass
        seg_val = last_seg
        if seg_digits:
            try:
                seg_val = int(dut.seg.value)  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001 - X/Z at t=0
                pass

        # -- Apply control messages -------------------------------------------
        for kind, payload in drain(conn):
            if kind == "input":
                for name in ("sw", "btn"):
                    try:
                        getattr(dut, name).value = int(payload.get(name, 0))
                    except AttributeError:
                        pass
                input_seq = int(payload.get("seq", input_seq))
                input_dirty = True
            elif kind == "speed":
                speed = max(1e-4, float(payload.get("factor", speed)))
            elif kind == "clk":
                half = max(1, int(payload.get("half_ns", 1)))
                try:
                    dut.clk_half_ns.value = half  # type: ignore[attr-defined]
                except AttributeError:
                    pass
                clk_period_ns = 2.0 * half
            elif kind == "pause":
                paused = bool(payload.get("on", False))
            elif kind in ("stop", "eof"):
                running = False

        # -- Throttled state send ----------------------------------------------
        now = time.monotonic()
        elapsed = now - last_send
        changed = led_val != last_led or seg_val != last_seg
        if input_dirty or elapsed >= _SEND_MAX_S or (changed and elapsed >= _SEND_MIN_S):
            total = max(1, loop_wall_ns)
            if not send(
                conn,
                "state",
                {
                    "led": led_val or 0,
                    "seg": seg_val if seg_digits else None,
                    "sim_ns": sim_elapsed_ns,
                    "steps": steps,
                    "input_seq": input_seq,
                    "step_ns": sim_step_ns,
                    "timer_pct": 100.0 * timer_wall_ns / total,
                    "at_max": at_max,
                },
            ):
                running = False  # host went away
            last_led, last_seg = led_val, seg_val
            last_send = now
            input_dirty = False

        # -- Pace to the speed target (the child's replacement for tick(60)) --
        t_loop = time.monotonic_ns()
        timer_wall_ns += t_timer - t0
        loop_wall_ns += t_loop - t0
        if not free_run:
            if paused:
                time.sleep(1.0 / _TARGET_FPS)
            else:
                target_s = (sim_step_ns / 1e9) / speed
                shortfall = target_s - (t_loop - t0) / 1e9
                if shortfall > 0:
                    time.sleep(min(shortfall, 0.1))

        # -- Per-frame metrics (draw/tick are 0.0: the host renders now) -------
        if metrics is not None:
            metrics.record(
                timer_us=(t_timer - t0) / 1_000,
                draw_us=0.0,
                tick_us=0.0,
                sim_step_ns=sim_step_ns,
                clk_period_ns=clk_period_ns,
                speed_factor=speed,
            )

    if metrics is not None:
        metrics.stop()
        print(f"[bridge] metrics saved to: {metrics_path}")

    wall_s = time.monotonic() - t_start
    send(conn, "bye", {"sim_ns": sim_elapsed_ns, "steps": steps, "wall_s": wall_s})
    conn.close()

    rate = (sim_elapsed_ns / 1e9) / max(wall_s, 1e-9)
    print(
        f"[bridge] done: {steps} steps, {sim_elapsed_ns / 1e9:.4g}s simulated in "
        f"{wall_s:.1f}s wall ({rate:.4g}x real-time), "
        f"timer {100.0 * timer_wall_ns / max(1, loop_wall_ns):.1f}% of loop"
    )
