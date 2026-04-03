"""sim_metrics.py – Non-intrusive per-frame performance instrumentation.

Activated by setting the environment variable ``FPGA_SIM_METRICS`` to a
CSV file path before launching the simulator::

    FPGA_SIM_METRICS=/tmp/sim_metrics.csv uv run fpga-sim

When the variable is unset this module is never imported and has zero
effect on the simulation loop.

Architecture
------------
The simulation loop calls ``SimMetrics.record()`` once per frame.  That call
does only two things: one ``time.monotonic_ns()`` read and one non-blocking
``queue.SimpleQueue.put_nowait()`` (~1 µs total overhead per frame).  A
background daemon thread drains the queue and writes rows to the CSV, so all
I/O is completely off the hot path.

CSV columns
-----------
wall_us       Total frame wall time (µs) — includes every phase below.
timer_us      Time inside ``await Timer(sim_step_ns)`` — pure GHDL/GPI cost.
draw_us       Time for board._draw + panel.draw + pygame.display.flip.
tick_us       Time sleeping in board.clock.tick(60).
sim_step_ns   Simulated nanoseconds advanced this frame.
clk_period_ns Current virtual-clock period (ns).
speed_factor  Current SimPanel speed multiplier.
"""

from __future__ import annotations

import csv
import queue
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# Fields in the order they appear in the CSV
_FIELDS = [
    "wall_us",
    "timer_us",
    "draw_us",
    "tick_us",
    "sim_step_ns",
    "clk_period_ns",
    "speed_factor",
]


class SimMetrics:
    """Collect per-frame simulation timing metrics and stream them to a CSV.

    Parameters
    ----------
    path:
        Destination CSV file path.  Created (or overwritten) on ``start()``.
    flush_interval:
        Background thread flushes the file to disk after this many rows
        have been written, or whenever the queue drains, whichever comes first.

    """

    def __init__(self, path: str | Path, flush_interval: int = 60) -> None:
        """Initialise the collector.  Call ``start()`` before the sim loop."""
        self._path = Path(path)
        self._flush_interval = flush_interval
        self._q: queue.SimpleQueue[dict | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._writer, daemon=True, name="sim-metrics")
        self._frame_start_ns: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the CSV and launch the background writer thread."""
        self._thread.start()
        self._frame_start_ns = time.monotonic_ns()

    def mark_frame_start(self) -> None:
        """Call at the very top of each main-loop iteration."""
        self._frame_start_ns = time.monotonic_ns()

    def record(
        self,
        *,
        timer_us: float,
        draw_us: float,
        tick_us: float,
        sim_step_ns: int,
        clk_period_ns: float,
        speed_factor: float,
    ) -> None:
        """Post one frame's metrics to the background writer (non-blocking).

        Must be called *after* ``clock.tick()`` completes so that
        ``wall_us`` captures the full frame including the sleep.
        """
        now = time.monotonic_ns()
        wall_us = (now - self._frame_start_ns) / 1_000
        self._frame_start_ns = now  # start of next frame
        self._q.put_nowait(
            {
                "wall_us": round(wall_us, 1),
                "timer_us": round(timer_us, 1),
                "draw_us": round(draw_us, 1),
                "tick_us": round(tick_us, 1),
                "sim_step_ns": sim_step_ns,
                "clk_period_ns": round(clk_period_ns, 2),
                "speed_factor": round(speed_factor, 6),
            }
        )

    def stop(self) -> None:
        """Flush remaining rows and shut down the background thread."""
        self._q.put_nowait(None)  # sentinel
        self._thread.join(timeout=10)

    # ── Background writer ─────────────────────────────────────────────────────

    def _writer(self) -> None:
        with self._path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_FIELDS)
            writer.writeheader()
            f.flush()
            unflushed = 0
            while True:
                row = self._q.get()
                if row is None:
                    f.flush()
                    break
                writer.writerow(row)
                unflushed += 1
                # Flush periodically or whenever the queue drains
                if unflushed >= self._flush_interval or self._q.empty():
                    f.flush()
                    unflushed = 0
