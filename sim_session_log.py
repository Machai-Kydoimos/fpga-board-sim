"""sim_session_log.py – Write a compact per-session performance summary to disk.

Each completed simulation run appends one JSON file under
``~/.fpga_simulator/sessions/``.  The file name encodes the UTC timestamp
and board name so sessions can be compared across runs without opening the
files::

    ~/.fpga_simulator/sessions/
        20260326T143012Z_Arty_A7_35T.json
        20260326T144500Z_ICEstick.json
        ...

The JSON is intentionally compact (one level deep, human-readable) so it
can be grep'd, plotted, or fed into a spreadsheet without a custom tool.

Usage
-----
Call :func:`save_session_stats` once after the simulation loop exits::

    save_session_stats(
        board_name  = board_def.name if board_def else "Generic",
        simulator   = "ghdl",
        duration_s  = 42.3,
        avg_fps     = 58.7,
        sim_time_ns = panel._sim_elapsed_ns,
        avg_ghdl_pct = 79.2,
        avg_draw_pct = 14.1,
        avg_idle_pct = 6.7,
        clock_hz    = 12e6,
    )
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

_SESSION_DIR = Path.home() / ".fpga_simulator" / "sessions"


def _safe_name(name: str) -> str:
    """Convert *name* to a filesystem-safe slug (spaces → underscores, strip specials)."""
    slug = name.replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_\-]", "", slug)


def save_session_stats(
    *,
    board_name: str,
    simulator: str,
    duration_s: float,
    avg_fps: float,
    sim_time_ns: int,
    avg_ghdl_pct: float,
    avg_draw_pct: float,
    avg_idle_pct: float,
    clock_hz: float,
) -> Path:
    """Write a compact JSON performance summary for the just-completed session.

    Parameters
    ----------
    board_name:
        Human-readable board name (e.g. ``"Arty A7-35T"``).
    simulator:
        Simulator backend used (``"ghdl"`` or ``"nvc"``).
    duration_s:
        Total wall-clock seconds the simulation ran.
    avg_fps:
        Mean GUI frames per second over the session.
    sim_time_ns:
        Total simulated nanoseconds elapsed.
    avg_ghdl_pct:
        Mean percentage of each frame spent inside ``await Timer(...)``
        (GHDL/NVC step time).
    avg_draw_pct:
        Mean percentage of each frame spent in board draw + panel draw +
        ``pygame.display.flip``.
    avg_idle_pct:
        Mean percentage of each frame spent in ``board.clock.tick``
        (frame-rate cap sleep).
    clock_hz:
        Virtual clock frequency in Hz at the end of the session.

    Returns
    -------
    Path
        Path to the newly written JSON file.

    """
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = _safe_name(board_name)
    path = _SESSION_DIR / f"{ts}_{slug}.json"

    sim_us_per_s = (sim_time_ns / 1_000) / max(duration_s, 1e-9)
    sim_rate = sim_us_per_s / 1e6  # simulated seconds per real second

    data = {
        "timestamp": ts,
        "board": board_name,
        "simulator": simulator,
        "duration_s": round(duration_s, 2),
        "avg_fps": round(avg_fps, 1),
        "sim_time_ns": sim_time_ns,
        "sim_rate": round(sim_rate, 6),
        "avg_ghdl_pct": round(avg_ghdl_pct, 1),
        "avg_draw_pct": round(avg_draw_pct, 1),
        "avg_idle_pct": round(avg_idle_pct, 1),
        "clock_hz": clock_hz,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"[session] Stats saved → {path}")
    return path
