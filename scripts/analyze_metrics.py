#!/usr/bin/env python3
"""analyze_metrics.py – Analyse a sim_metrics CSV and report performance.

Usage::

    uv run python analyze_metrics.py [path/to/sim_metrics.csv]

If no path is given, looks for ``sim_metrics.csv`` in the current directory.
"""

from __future__ import annotations

import csv
import json
import math
import statistics
import sys
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    idx = int(len(vals) * p)
    return sorted(vals)[min(idx, len(vals) - 1)]


def _fmt_us(us: float) -> str:
    if us >= 1_000:
        return f"{us / 1000:.2f} ms"
    return f"{us:.1f} µs"


def _fmt_hz(hz: float) -> str:
    if hz >= 1e6:
        return f"{hz / 1e6:.4g} MHz"
    if hz >= 1e3:
        return f"{hz / 1e3:.4g} kHz"
    return f"{hz:.4g} Hz"


def _stats_row(label: str, vals: list[float], fmt: str = ".1f") -> None:
    vals = [v for v in vals if math.isfinite(v) and v >= 0]
    if not vals:
        print(f"  {label}: (no data)")
        return
    mean = statistics.mean(vals)
    med = statistics.median(vals)
    p95 = _pct(vals, 0.95)
    mx = max(vals)
    print(f"  {label:<34}  mean={mean:{fmt}}  p50={med:{fmt}}  p95={p95:{fmt}}  max={mx:{fmt}}")


# ── Main analysis ─────────────────────────────────────────────────────────────


def _load_meta(csv_path: Path) -> dict:
    """Load the JSON sidecar written by sim_testbench, or return empty dict."""
    meta_path = csv_path.with_suffix("").with_suffix(".meta.json")
    # Also try stripping .csv and appending .meta.json for any extension
    if not meta_path.exists():
        meta_path = Path(str(csv_path) + ".meta.json")
    if not meta_path.exists():
        # Fallback: same stem, .meta.json extension
        meta_path = csv_path.with_name(csv_path.stem + ".meta.json")
    try:
        return json.loads(meta_path.read_text()) if meta_path.exists() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def analyze(path: Path) -> None:  # noqa: PLR0912, PLR0915
    """Load *path* and print a full performance report."""
    rows: list[dict[str, float]] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            rows.append({str(k): float(v) for k, v in row.items()})

    if not rows:
        print("CSV is empty — nothing to analyse.")
        return

    meta = _load_meta(path)

    # Drop first 5 frames (start-up transient)
    data = rows[5:] if len(rows) > 5 else rows
    n = len(data)
    print(f"\n{'=' * 65}")
    print(f"  Simulation Performance Report  ({n} frames from {path.name})")
    print(f"{'=' * 65}\n")

    # ── Section 0: Run context ────────────────────────────────────────────────
    if meta:
        print("── Run context ─────────────────────────────────────────────────\n")
        _mf = meta.get
        vhdl = _mf("vhdl_file", "unknown")
        top = _mf("toplevel", "unknown")
        sim = _mf("simulator", "unknown").upper()
        simver = _mf("simulator_version", "")
        board = _mf("board_name", "Generic")
        clk_hz = _mf("board_clock_hz", 0.0)
        ts = _mf("timestamp", "")
        generics: dict = _mf("generics", {})
        cb = _mf("counter_bits", generics.get("COUNTER_BITS", "?"))
        pyver = _mf("python_version", "")
        plat = _mf("platform", "")
        mcs = _mf("max_cycles_per_step", "?")
        bsns = _mf("base_step_ns", "?")
        nleds = _mf("num_leds", "?")
        nsw = _mf("num_switches", "?")
        nbtn = _mf("num_buttons", "?")

        print(f"  Design        : {vhdl}  (entity: {top})")
        print(f"  Simulator     : {sim}  {simver}")
        print(f"  Board         : {board}")
        print(f"  Board clock   : {_fmt_hz(clk_hz)}")
        print(f"  Components    : {int(nleds)} LEDs, {int(nsw)} switches, {int(nbtn)} buttons")
        # Generics
        gen_str = "  ".join(f"{k}={v}" for k, v in generics.items()) if generics else "defaults"
        print(f"  Generics      : {gen_str}")
        print(
            f"  COUNTER_BITS  : {cb}  "
            f"(half-period = 2^{int(cb) - 1} = {2 ** (int(cb) - 1):,} cycles)"
        )
        print()
        print(
            f"  Sim settings  : _BASE_STEP_NS={bsns}  _MAX_CYCLES_PER_STEP={mcs}"
            f"  speed_default={_mf('speed_factor_default', '?')}×"
        )
        print(f"  Python        : {pyver}")
        print(f"  Platform      : {plat}")
        if ts:
            print(f"  Timestamp     : {ts}")
        print()

    # ── Derive per-frame quantities ───────────────────────────────────────────
    for r in data:
        r["fps"] = 1e6 / r["wall_us"] if r["wall_us"] > 0 else 0.0
        r["clk_per_frame"] = (
            r["sim_step_ns"] / r["clk_period_ns"] if r["clk_period_ns"] > 0 else 0.0
        )
        r["gpi_cbs_per_frame"] = 2.0 * r["clk_per_frame"]  # 1 callback per half-period
        r["gpi_us_per_cb"] = (
            r["timer_us"] / r["gpi_cbs_per_frame"] if r["gpi_cbs_per_frame"] > 0 else 0.0
        )
        r["sim_ns_per_sec"] = r["fps"] * r["sim_step_ns"]  # simulated ns per wall-clock second

    # ── Section 1: Frame timing breakdown ────────────────────────────────────
    print("── Frame timing breakdown ──────────────────────────────────────\n")
    _stats_row("Total frame (µs)", [r["wall_us"] for r in data], ".1f")
    _stats_row("  await Timer / GHDL (µs)", [r["timer_us"] for r in data], ".1f")
    _stats_row("  draw + flip (µs)", [r["draw_us"] for r in data], ".1f")
    _stats_row("  clock.tick sleep (µs)", [r["tick_us"] for r in data], ".1f")

    mean_wall = statistics.mean([r["wall_us"] for r in data])
    mean_timer = statistics.mean([r["timer_us"] for r in data])
    mean_draw = statistics.mean([r["draw_us"] for r in data])
    mean_tick = statistics.mean([r["tick_us"] for r in data])

    print()
    print("  Frame budget breakdown (mean):")
    print(f"    GHDL step  : {mean_timer / mean_wall * 100:5.1f}%  ({_fmt_us(mean_timer)})")
    print(f"    Draw/flip  : {mean_draw / mean_wall * 100:5.1f}%  ({_fmt_us(mean_draw)})")
    print(f"    Idle sleep : {mean_tick / mean_wall * 100:5.1f}%  ({_fmt_us(mean_tick)})")

    # ── Section 2: Display rate ───────────────────────────────────────────────
    print("\n── Display frame rate ──────────────────────────────────────────\n")
    _stats_row("FPS", [r["fps"] for r in data], ".1f")

    p5_fps = _pct([r["fps"] for r in data], 0.05)
    print()
    if p5_fps < 30:
        print(f"  *** DISPLAY IS SLOW: p5 FPS = {p5_fps:.1f}  (target ≥ 55)")
    elif p5_fps < 55:
        print(f"  ! Display occasionally drops below 55 FPS (p5 = {p5_fps:.1f})")
    else:
        print(f"  Display rate looks healthy (p5 FPS = {p5_fps:.1f})")

    # ── Section 3: GPI performance ────────────────────────────────────────────
    print("\n── GPI callback analysis ───────────────────────────────────────\n")
    _stats_row("Clock cycles / frame", [r["clk_per_frame"] for r in data], ".1f")
    _stats_row("GPI callbacks / frame", [r["gpi_cbs_per_frame"] for r in data], ".1f")
    _stats_row("Estimated µs / GPI call", [r["gpi_us_per_cb"] for r in data], ".3f")

    mean_gpi_us = statistics.mean([r["gpi_us_per_cb"] for r in data])
    mean_cbs = statistics.mean([r["gpi_cbs_per_frame"] for r in data])
    mean_cycles = statistics.mean([r["clk_per_frame"] for r in data])

    # How many callbacks fit inside the non-draw, non-sleep frame budget?
    ghdl_budget_us = mean_wall - mean_draw  # ignore sleep — it's flexible
    max_viable_cbs = (ghdl_budget_us * 0.5) / mean_gpi_us if mean_gpi_us > 0 else 0
    max_viable_cyc = max_viable_cbs / 2

    print()
    print(f"  Measured GPI cost : {mean_gpi_us:.3f} µs / callback")
    print(f"  Current callbacks : {mean_cbs:.0f} / frame  ({mean_cycles:.0f} clock cycles)")
    print(f"  Max safe callbacks: ~{max_viable_cbs:.0f} / frame  (keeps GHDL ≤ 50% of frame)")
    print(f"  Max safe cycles   : ~{max_viable_cyc:.0f} / frame")

    # ── Section 4: Simulation rate ────────────────────────────────────────────
    print("\n── Simulation rate ─────────────────────────────────────────────\n")
    mean_clk_period_ns = statistics.mean([r["clk_period_ns"] for r in data])
    mean_speed = statistics.mean([r["speed_factor"] for r in data])
    mean_sim_ns_per_s = statistics.mean([r["sim_ns_per_sec"] for r in data])
    mean_sim_cyc_per_s = mean_sim_ns_per_s / mean_clk_period_ns
    real_time_frac = mean_sim_ns_per_s / 1e9

    clk_hz = 1e9 / mean_clk_period_ns
    print(f"  Virtual clock     : {_fmt_hz(clk_hz)}")
    print(f"  Speed slider      : {mean_speed:.4g}×")
    print(f"  Sim time / sec    : {_fmt_us(mean_sim_ns_per_s / 1000)} sim")
    print(f"  Sim cycles / sec  : {mean_sim_cyc_per_s:,.0f}")
    print(f"  Real-time ratio   : {real_time_frac * 100:.5f}%")

    # With COUNTER_BITS=10: MSB of 10-bit counter toggles every 2^9=512 cycles
    blink_hz_cb10 = mean_sim_cyc_per_s / 512
    blink_hz_cb24 = mean_sim_cyc_per_s / (2**23)
    print()
    print(
        f"  Blinky LED rate (COUNTER_BITS=10): {blink_hz_cb10:.2f} Hz  "
        f"({'visible ✓' if 0.3 < blink_hz_cb10 < 25 else 'too fast/slow ✗'})"
    )
    print(
        f"  Blinky LED rate (COUNTER_BITS=24): {blink_hz_cb24:.4f} Hz  "
        f"({'visible ✓' if 0.3 < blink_hz_cb24 < 25 else 'too fast/slow ✗'})"
    )

    # ── Section 5: Bottleneck diagnosis + recommendations ────────────────────
    print("\n── Diagnosis & recommendations ─────────────────────────────────\n")

    issues: list[str] = []
    suggestions: list[str] = []

    # Read settings from sidecar (if available) to give precise advice
    max_cyc_setting = int(meta.get("max_cycles_per_step", 0))
    base_step_ns = int(meta.get("base_step_ns", 2000))
    counter_bits = int(meta.get("counter_bits", 10))

    # Is GHDL the bottleneck (display is slow)?
    ghdl_pct = mean_timer / mean_wall * 100
    if ghdl_pct > 70:
        issues.append(
            f"GHDL step consumes {ghdl_pct:.0f}% of frame time — display will drop below 60 FPS."
        )
        safe_cycles = max(24, int(max_viable_cyc * 0.8))
        suggestions.append(
            f"Reduce _MAX_CYCLES_PER_STEP from {max_cyc_setting or '?'} "
            f"to {safe_cycles} in sim_testbench.py"
        )

    # Is the machine sleeping a lot (idle headroom available)?
    if mean_tick / mean_wall > 0.5 and mean_cycles < max_viable_cyc * 0.5:
        # Determine which lever is limiting: the cap, the base step, or both.
        cap_is_active = max_cyc_setting > 0 and mean_cycles >= max_cyc_setting * 0.9
        headroom_pct = mean_tick / mean_wall * 100
        target_cyc = int(max_viable_cyc * 0.6)  # aim for 60% of the safe maximum

        # Detect co-binding: target_ns (base step at current speed) ≈ cap_ns.
        # Example: 25 MHz board, _BASE_STEP_NS=8000, _MAX_CYCLES_PER_STEP=200 →
        #   target_ns=8000  cap_ns=40×200=8000  → both binding; only raising cap
        #   is useless because the base step still pins sim_step_ns at 8000.
        speed_default = float(meta.get("speed_factor_default", 0.1))
        effective_base_ns = (
            int(base_step_ns * mean_speed / speed_default) if speed_default > 0 else base_step_ns
        )
        cap_ns = int(max_cyc_setting * mean_clk_period_ns) if max_cyc_setting > 0 else 0
        both_binding = (
            cap_is_active and cap_ns > 0 and abs(effective_base_ns - cap_ns) / max(1, cap_ns) < 0.05
        )

        target_base_ns = int(target_cyc * mean_clk_period_ns)
        if both_binding:
            suggestions.append(
                f"Machine has {headroom_pct:.0f}% idle — cap and base step are co-binding at "
                f"{cap_ns} ns.  Increase _MAX_CYCLES_PER_STEP from {max_cyc_setting} to "
                f"{target_cyc} AND _BASE_STEP_NS from {base_step_ns} to {target_base_ns} "
                f"in sim_testbench.py"
            )
        elif cap_is_active:
            suggestions.append(
                f"Machine has {headroom_pct:.0f}% idle — cap is limiting.  "
                f"Increase _MAX_CYCLES_PER_STEP from {max_cyc_setting} to {target_cyc} "
                f"in sim_testbench.py"
            )
        else:
            # Base step is limiting (cap not being hit)
            suggestions.append(
                f"Machine has {headroom_pct:.0f}% idle — base step is limiting "
                f"(cap={max_cyc_setting} cycles not reached; current={mean_cycles:.0f} cycles).  "
                f"Increase _BASE_STEP_NS from {base_step_ns} to {target_base_ns} "
                f"in sim_testbench.py"
            )

    # Is the drawing phase a significant fraction of frame time?
    draw_pct = mean_draw / mean_wall * 100
    if draw_pct > 25 and mean_draw > 3_000:
        issues.append(
            f"Drawing/flip takes {draw_pct:.0f}% of frame ({_fmt_us(mean_draw)}) — "
            f"consider caching font surfaces or reducing per-frame SysFont() calls."
        )

    # Is the current COUNTER_BITS producing a good blink rate?
    # Use actual COUNTER_BITS from sidecar; fall back to 10 for backward compat.
    blink_hz_actual = mean_sim_cyc_per_s / (2 ** (counter_bits - 1))
    if counter_bits != 10:  # report already showed CB=10 rates; add actual CB rate
        vis = "visible ✓" if 0.3 < blink_hz_actual < 25 else "too fast/slow ✗"
        print(
            f"  Blinky LED rate (current COUNTER_BITS={counter_bits}): "
            f"{blink_hz_actual:.2f} Hz  ({vis})"
        )
        print()

    if not (0.3 < blink_hz_actual < 25):
        target_cb = max(4, int(math.log2(max(1, mean_sim_cyc_per_s / 2.0))))
        direction = "too fast" if blink_hz_actual > 25 else "too slow"
        suggestions.append(
            f"COUNTER_BITS={counter_bits} gives {blink_hz_actual:.2f} Hz LED blink ({direction}).  "
            f"Suggest COUNTER_BITS={target_cb} for ~2 Hz blink at this sim rate."
        )

    if not issues and not suggestions:
        print("  No issues detected — simulation looks well-tuned.\n")
    else:
        if issues:
            print("  Issues:")
            for i in issues:
                print(f"    • {i}")
            print()
        if suggestions:
            print("  Suggestions:")
            for s in suggestions:
                print(f"    → {s}")
            print()

    print(f"{'=' * 65}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sim_metrics.csv")
    if not csv_path.exists():
        print(f"Error: {csv_path} not found.")
        print("Run the simulator with FPGA_SIM_METRICS=<path> first.")
        sys.exit(1)
    analyze(csv_path)
