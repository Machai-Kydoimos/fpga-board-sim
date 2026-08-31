"""PNG frame capture for the headless benchmark path (issue #129).

The benchmark already drives the production :class:`~fpga_sim.ui.simulation_screen.SimulationScreen`
headless under ``SDL_VIDEODRIVER=dummy``, so ``--screenshots`` needs no second
renderer — it saves the very surface the product draws.  What it does need is a
*gate*, because at 60 fps a fading LED changes the frame every single frame
(U23's signature quantizes brightness to 1000 levels, far finer than a human
reviewing stills).  Three rules, checked in order by :meth:`ScreenshotRecorder.due`:

1. the first frame is always captured — proof that anything rendered at all;
2. a frame whose signature differs from the last captured one is captured, but
   never sooner than ``min_gap_s`` after the previous shot.  Callers pass a
   *coarse* signature (see :data:`COARSE_LEVELS`), so a smooth fade yields a
   handful of stills rather than one per frame;
3. otherwise a frame is captured every ``interval_s``, so a design that never
   changes still leaves a trail instead of a single file.

A hard ``limit`` caps the output; frames dropped past it are counted and
reported, so a capped run is never silently truncated.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pygame

# Brightness steps a capture-gate signature quantizes to.  U23's redraw gate
# uses 1000 (finer than any post-gamma pixel step, so the persistence-of-vision
# easing settles to a stable value); for stills that resolution would emit one
# PNG per frame of every fade.  16 steps is ~6% brightness — coarse enough that
# a settled LED stops re-triggering, fine enough that a real fade still does.
COARSE_LEVELS = 16

#: Seconds between liveness shots when nothing on the board is changing.
_DEFAULT_INTERVAL_S = 1.0
#: Floor on the spacing of change-triggered shots.  A fading LED crosses a
#: coarse bucket most frames, so without this a 5 s run of ``blinky`` yields one
#: PNG per drawn frame (~300) instead of the "few milestone frames" issue #129
#: asks for; at 0.25 s the same run yields ~20 evenly-spaced stills.
_DEFAULT_MIN_GAP_S = 0.25
#: Hard cap on files written, so a long run cannot fill a disk unattended.
_DEFAULT_LIMIT = 240


class ScreenshotRecorder:
    """Decide when a benchmark frame is worth a PNG, and write it.

    ``due()`` is pure — it is called every frame and never mutates state — so
    the caller can fold it into its own dirty-frame decision and capture from a
    surface it knows is fully drawn.  ``capture()`` does the write and advances
    the state.
    """

    def __init__(
        self,
        out_dir: str | Path,
        *,
        interval_s: float = _DEFAULT_INTERVAL_S,
        min_gap_s: float = _DEFAULT_MIN_GAP_S,
        limit: int = _DEFAULT_LIMIT,
    ) -> None:
        """Prepare *out_dir* for capture; existing files in it are left alone."""
        self.out_dir = Path(out_dir)
        self.interval_s = interval_s
        self.min_gap_s = min_gap_s
        self.limit = limit
        self.saved: list[Path] = []
        self.dropped = 0
        self._last_sig: tuple[object, ...] | None = None
        self._last_t = 0.0
        self._t0: float | None = None
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def due(self, signature: tuple[object, ...], now: float) -> bool:
        """Return whether the frame described by *signature* should be captured."""
        if self._t0 is None:
            return True  # rule 1: always capture the first frame
        if signature != self._last_sig:
            return now - self._last_t >= self.min_gap_s  # rule 2, rate-limited
        return now - self._last_t >= self.interval_s  # rule 3: liveness trail

    def capture(
        self, surface: pygame.Surface, signature: tuple[object, ...], now: float
    ) -> Path | None:
        """Write *surface* as the next PNG; return its path, or ``None`` past the limit.

        Call only when :meth:`due` said so — this advances the gate state
        whether or not the limit allowed a write, so a capped run keeps
        counting drops instead of re-deciding the same frame forever.
        """
        import pygame

        if self._t0 is None:
            self._t0 = now
        self._last_sig = signature
        self._last_t = now
        if len(self.saved) >= self.limit:
            self.dropped += 1
            return None
        path = self.out_dir / f"shot_{len(self.saved) + 1:04d}_t{now - self._t0:06.2f}s.png"
        pygame.image.save(surface, str(path))
        self.saved.append(path)
        return path

    def summary(self) -> str:
        """Return a one-line report of what was written, for the benchmark output."""
        if not self.saved:
            return f"[screenshots] no frames captured in {self.out_dir}"
        capped = (
            f", {self.dropped} dropped past the {self.limit}-frame limit" if self.dropped else ""
        )
        return f"[screenshots] {len(self.saved)} PNGs in {self.out_dir}{capped}"
