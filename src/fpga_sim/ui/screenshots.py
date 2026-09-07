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

**Filenames carry SIMULATED time, not wall time.** The simulator runs far
slower than the hardware would — a 5 s GHDL run of ``blinky`` on an Arty covers
about 20 *milliseconds* of simulated time — so the two differ by orders of
magnitude and only one of them is useful.  A waveform dump (``--vcd`` /
``--wave``) is indexed in simulated time, so naming a shot ``sim8123456ns``
makes it a marker you can paste straight into GTKWave and see every signal at
the instant that PNG shows.  Wall time would only say how long you had been
sitting there.

The ``sim_ns`` a caller passes and the pixels it captures must come from the
**same** child state message for that to hold; :class:`SimulationScreen` reads
both out of ``_last_state``, so they do.  One caveat worth knowing when
comparing a pixel against a trace: LED and 7-segment *brightness* is additionally
eased over ~100 ms of wall time (``_POV_TAU_S``) to read as a fade rather than a
strobe, so a lit pixel reflects recent duty windows rather than the instantaneous
duty at that exact nanosecond.  Switch, button and segment *states* are exact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pygame

#: Name of the sidecar written beside the PNGs (issue #388).
MANIFEST_NAME = "manifest.json"


@dataclass(frozen=True)
class ShotMetrics:
    """What one captured frame was showing, in numbers rather than pixels.

    The PNG is the picture; this is the measurement behind it.  ``duty`` is what
    the child measured over :attr:`window_ns`; ``level`` is what the widget was
    actually displaying when the shot was taken -- the same duty after the
    host's persistence-of-vision easing.  Keeping both is the point of the
    manifest: their *difference* is exactly the gap that made a still
    un-reconcilable against a trace (issue #388, r = +0.02 against the
    instantaneous bit, r = +0.70 against the window's duty).
    """

    #: ``(from_ns, to_ns)`` the duties average over, or ``None`` when unmeasured
    #: (duty mode off, or the child had not reported a window yet).
    window_ns: tuple[int, int] | None = None
    led_duty: tuple[float, ...] = ()
    led_level: tuple[float, ...] = ()
    seg_duty: tuple[float, ...] = ()
    seg_level: tuple[float, ...] = ()


@dataclass
class _Shot:
    """One written PNG and the metrics that go with it."""

    path: Path
    sim_ns: int
    metrics: ShotMetrics = field(default_factory=ShotMetrics)


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
        #: Per-shot metrics, parallel to :attr:`saved`, for the #388 manifest.
        self._shots: list[_Shot] = []
        self.dropped = 0
        self._last_sig: tuple[object, ...] | None = None
        self._last_t = 0.0
        self._started = False
        # Wall/sim span of the run, reported by summary() so the two time
        # domains are related once, where the filenames are explained.
        self._wall_span = (0.0, 0.0)
        self._sim_span = (0, 0)
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def due(self, signature: tuple[object, ...], now: float) -> bool:
        """Return whether the frame described by *signature* should be captured."""
        if not self._started:
            return True  # rule 1: always capture the first frame
        if signature != self._last_sig:
            return now - self._last_t >= self.min_gap_s  # rule 2, rate-limited
        return now - self._last_t >= self.interval_s  # rule 3: liveness trail

    def capture(
        self,
        surface: pygame.Surface,
        signature: tuple[object, ...],
        now: float,
        sim_ns: int,
        metrics: ShotMetrics | None = None,
    ) -> Path | None:
        """Write *surface* as the next PNG; return its path, or ``None`` past the limit.

        *now* is wall time and only paces the gate; *sim_ns* is the simulated
        time of the state this frame was drawn from, and is what the filename
        carries — see the module docstring on why.  *metrics* is what that frame
        was measuring, recorded for the manifest (#388); omitting it still
        writes the PNG, and the manifest simply carries no numbers for it.

        Call only when :meth:`due` said so — this advances the gate state
        whether or not the limit allowed a write, so a capped run keeps
        counting drops instead of re-deciding the same frame forever.
        """
        import pygame

        if not self._started:
            self._started = True
            self._wall_span = (now, now)
            self._sim_span = (sim_ns, sim_ns)
        self._wall_span = (self._wall_span[0], now)
        self._sim_span = (self._sim_span[0], sim_ns)
        self._last_sig = signature
        self._last_t = now
        if len(self.saved) >= self.limit:
            self.dropped += 1
            return None
        # The index leads so the files sort in capture order even where two
        # shots share a sim time (a paused run, or a child not reporting one).
        path = self.out_dir / f"shot_{len(self.saved) + 1:04d}_sim{sim_ns}ns.png"
        pygame.image.save(surface, str(path))
        self.saved.append(path)
        self._shots.append(_Shot(path, sim_ns, metrics or ShotMetrics()))
        return path

    def write_manifest(
        self,
        *,
        dump: str | Path | None = None,
        board: str = "",
        design: str = "",
    ) -> Path | None:
        """Write the sidecar that makes each PNG reconcilable against a trace (#388).

        A still is an **interval, not a sample**: the duty behind every lit pixel
        is averaged over the window between two child state sends, then eased
        over ~100 ms of wall time for the eye.  A reader comparing a PNG against
        a waveform therefore has no way to know which interval to look at — so
        this states it, per shot, alongside the duty measured over it and the
        level actually displayed.

        *dump* is the run's waveform file, when one was captured: its own
        ``$timescale`` is read (never assumed) so the marker can be given in raw
        ticks as well as in nanoseconds.  Returns the manifest path, or ``None``
        when nothing was captured.
        """
        if not self._shots:
            return None
        from fpga_sim.waveform import _gtkw_path, dump_timescale_fs

        doc: dict[str, Any] = {
            "schema": 1,
            "board": board,
            "design": design,
            "how_to_read": (
                "Each PNG shows an interval, not an instant. led.duty is the exact "
                "on-time fraction the simulator measured over window_ns; led.level is "
                "what the board was displaying, which is that duty after a ~100 ms "
                "persistence-of-vision ease, so a signal stable across the window "
                "matches and a faster one (PWM, scan display) lags. Compare a trace "
                "over window_ns against duty -- not the value at sim_ns."
            ),
        }
        ticks_per_ns: int | None = None
        if dump is not None:
            dump_path = Path(dump)
            timescale_fs = dump_timescale_fs(dump_path)
            if timescale_fs:
                # A nanosecond is 1e6 fs; exact integer division because every
                # unit a dump may name divides it.
                ticks_per_ns = 1_000_000 // timescale_fs or None
            doc["waveform"] = {
                "dump": str(dump_path),
                "gtkw": str(_gtkw_path(dump_path)),
                "timescale_fs": timescale_fs,
            }

        shots: list[dict[str, Any]] = []
        for shot in self._shots:
            marker: dict[str, Any] = {"gtkwave": f"{shot.sim_ns} ns"}
            if ticks_per_ns is not None:
                # Surfer's -C parses before the waveform loads, so it wants
                # unitless ticks; its own prompt takes the "ns" form above.
                marker["surfer_ticks"] = shot.sim_ns * ticks_per_ns
            m = shot.metrics
            entry: dict[str, Any] = {
                "file": shot.path.name,
                "sim_ns": shot.sim_ns,
                "window_ns": list(m.window_ns) if m.window_ns else None,
                "marker": marker,
            }
            if m.led_duty or m.led_level:
                entry["led"] = {
                    "duty": [round(v, 4) for v in m.led_duty],
                    "level": [round(v, 4) for v in m.led_level],
                }
            if m.seg_duty or m.seg_level:
                entry["seg"] = {
                    "duty": [round(v, 4) for v in m.seg_duty],
                    "level": [round(v, 4) for v in m.seg_level],
                }
            shots.append(entry)
        doc["shots"] = shots

        path = self.out_dir / MANIFEST_NAME
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return path

    def summary(self) -> str:
        """Return a one-line report of what was written, for the benchmark output.

        States the wall→sim ratio explicitly: the filenames are in simulated
        nanoseconds, and that is surprising until you see the two spans side by
        side.
        """
        if not self.saved:
            return f"[screenshots] no frames captured in {self.out_dir}"
        capped = (
            f", {self.dropped} dropped past the {self.limit}-frame limit" if self.dropped else ""
        )
        wall = self._wall_span[1] - self._wall_span[0]
        sim_ns = self._sim_span[1] - self._sim_span[0]
        span = f"; filenames are SIMULATED time — {wall:.1f} s wall spans {sim_ns / 1e6:.4g} ms"
        return f"[screenshots] {len(self.saved)} PNGs in {self.out_dir}{capped}{span}"
