"""The screenshot manifest: what each PNG was showing, in numbers (issue #388).

``--screenshots`` names every PNG by *simulated* time, which makes it a waveform
marker.  But a still is an **interval, not a sample**: the U9 engine measures each
channel's duty over the window between two child state sends, and the host then
eases that over ~100 ms for persistence of vision.  Over 72 (frame, LED) samples
of ``blinky`` on an Arty, pixel brightness correlates **r = +0.02** with the
instantaneous ``led`` bit at the named time and **r = +0.70** with the duty over
the preceding window.  So the manifest writes the window down, with the duty
measured over it and the level actually displayed.

**The legend is the other half.**  ``led.duty[7]`` is a number with no meaning
until you know which LED it is -- and on an RGB board it is not even an LED but a
*channel*: an Arty A7-35 has 16 boundary channels for 8 visible components, so
channel 7 is the red of RGB site 1, on pin G3.  Worse, the answer to "which bit of
*my VHDL* is this?" depends on how the design was matched:

* **generic contract** -- channel *i* is ``led(i)`` in the design, directly;
* **board-native** -- the design writes the board's own names and the wrapper
  adapts, **inverting where the board is active-low**, so a channel can read 1.0
  while the design's own signal sits at ``'0'``.  Both are correct; they are
  opposite sides of an inverter.  A convention bank narrower than the board
  zero-extends, so some channels have no source in the design at all;
* **pin map** -- the constraint file binds the design's port bits to pins, and
  the pin decides the channel.

None of that is inferable from the numbers, and all of it is known at write time,
so :func:`build` emits it as a ``channels`` legend beside the shots.  This module
is pygame-free: it holds the document, and ``ui.screenshots`` holds the capture
gate that feeds it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef
    from fpga_sim.conventions import ConventionMatch
    from fpga_sim.pinmap import PinMapMatch

#: Name of the sidecar written beside the PNGs.
MANIFEST_NAME = "manifest.json"

#: Segment order within a digit's byte, low bit first.  The VHDL contract puts
#: digit *i* at ``seg(8i+7 downto 8i)`` as ``{dp, g, f, e, d, c, b, a}`` -- which
#: is MSB-first, so read low-to-high it is a..g then dp.  Confirmed by decoding a
#: real capture: a digit reading ``[0,1,1,0,0,1,1,0]`` is b+c+f+g = "4".
SEGMENT_ORDER = ("a", "b", "c", "d", "e", "f", "g", "dp")


@dataclass(frozen=True)
class ShotMetrics:
    """What one captured frame was showing, in numbers rather than pixels.

    ``duty`` is what the child measured over :attr:`window_ns`; ``level`` is what
    the widget was displaying -- that duty after the host's persistence-of-vision
    easing.  Their *difference* is the gap that made a still un-reconcilable
    against a trace, so both are kept.
    """

    #: ``(from_ns, to_ns)`` the duties average over, or ``None`` when unmeasured
    #: -- LED PWM off drops the duty integrator from the wrapper entirely, so
    #: there is no window and ``level`` is the exact bit at ``sim_ns``.
    window_ns: tuple[int, int] | None = None
    led_duty: tuple[float, ...] = ()
    led_level: tuple[float, ...] = ()
    seg_duty: tuple[float, ...] = ()
    seg_level: tuple[float, ...] = ()


@dataclass
class Shot:
    """One written PNG and the metrics that go with it."""

    path: Path
    sim_ns: int
    metrics: ShotMetrics = field(default_factory=ShotMetrics)


# ── The legend ────────────────────────────────────────────────────────────────


def _pinmap_sources(pinmap: PinMapMatch) -> dict[int, tuple[str, bool]]:
    """Boundary LED channel -> (design signal, board active-low), from the pin map.

    The constraint file binds a port *bit* to a *pin*, and the pin decides which
    board LED -- so the channel index comes from the board, never from the order
    the ports were declared in.
    """
    out: dict[int, tuple[str, bool]] = {}
    for binding in pinmap.outputs:
        if binding.role.kind != "led":
            continue
        signal = binding.port if binding.bit is None else f"{binding.port}({binding.bit})"
        out[binding.role.index] = (signal, binding.role.active_low)
    return out


def _native_sources(match: ConventionMatch, mono: int) -> dict[int, tuple[str, bool]]:
    """Boundary LED channel -> (design signal, board active-low), for a native run.

    The mono bank occupies the low channels and the RGB channel bank starts at
    *mono*; a bank narrower than the board simply leaves the rest unmapped, which
    is the zero-extension the wrapper does.  The secondary *green* bank is
    deliberately absent: the wrapper gives it a driver but routes it to no
    boundary channel, so no still can show it.
    """
    out: dict[int, tuple[str, bool]] = {}

    def _name(port: object, i: int) -> str:
        names: tuple[str, ...] = port.names  # type: ignore[attr-defined]
        if port.scalar_ports:  # type: ignore[attr-defined]
            return names[i] if i < len(names) else ""
        return f"{names[0]}({i})"

    if match.leds is not None:
        for i in range(min(match.leds.width, mono)):
            name = _name(match.leds, i)
            if name:
                out[i] = (name, match.leds.active_low)
    if match.leds_rgb is not None:
        for k in range(match.leds_rgb.width):
            name = _name(match.leds_rgb, k)
            if name:
                out[mono + k] = (name, match.leds_rgb.active_low)
    return out


def led_legend(
    board_def: BoardDef | None,
    match: ConventionMatch | None = None,
    pinmap: PinMapMatch | None = None,
) -> list[dict[str, Any]]:
    """One row per boundary LED channel: what it is, and what drives it.

    The index is the position in every shot's ``led.duty`` / ``led.level`` array.
    ``label`` is the text the board draws under the widget, so a reader can tie a
    number to the picture by eye.
    """
    if board_def is None:
        return []
    channels = board_def.led_channels
    mono = board_def.num_led_channels - 3 * board_def.num_rgb_leds
    if pinmap is not None:
        sources = _pinmap_sources(pinmap)
    elif match is not None:
        sources = _native_sources(match, mono)
    else:
        # Generic contract: the design drives the boundary vector itself.
        sources = {i: (f"led({i})", False) for i in range(len(channels))}

    rows: list[dict[str, Any]] = []
    for i, (comp, role) in enumerate(channels):
        label = comp.display_name if role == "mono" else f"{comp.display_name}.{role}"
        row: dict[str, Any] = {
            "i": i,
            "label": label,
            "name": comp.name,
            "number": comp.number,
            "role": role,
            "pins": _channel_pins(comp, role),
        }
        if comp.color:
            row["color"] = comp.color
        signal, active_low = sources.get(i, ("", False))
        # An empty source is not a gap in the data: it is a board LED the design
        # never reaches, which the wrapper drives dark.  Say so rather than
        # leaving the reader to wonder which it was.
        row["vhdl"] = signal or None
        row["active_low"] = active_low
        rows.append(row)
    return rows


def _channel_pins(comp: object, role: str) -> list[str]:
    """Return the pin(s) behind one channel; for an RGB site, just that color's pin."""
    pins: list[str] = list(comp.pins)  # type: ignore[attr-defined]
    if role in ("r", "g", "b") and len(pins) == 3:
        return [pins["rgb".index(role)]]
    return pins


def seg_legend(board_def: BoardDef | None) -> dict[str, Any] | None:
    """How to read a shot's ``seg`` arrays, as a rule rather than 8N rows.

    The rule is exact and far shorter than enumerating every channel, and the two
    facts a reader cannot guess are stated outright: which digit index 0 is, and
    that the board's own polarity is the opposite of the boundary's.
    """
    if board_def is None or board_def.seven_seg is None:
        return None
    ssd = board_def.seven_seg
    out: dict[str, Any] = {
        "index": "8 * digit + segment",
        "segments": list(SEGMENT_ORDER),
        "digits": ssd.num_digits,
        "digit_0": (
            "the rightmost digit as drawn -- the least-significant one "
            "(HEX0 on Terasic boards, AN0 on Digilent)"
        ),
        "has_dp": ssd.has_dp,
        "boundary_polarity": "active-high: 1.0 means the segment is lit",
    }
    if ssd.inverted:
        out["board_note"] = (
            "this board's display is wired active-low; the wrapper inverts it, so "
            "these values are lit-ness, not the level on the pin"
        )
    return out


def run_block(
    match: ConventionMatch | None = None, pinmap: PinMapMatch | None = None
) -> dict[str, Any]:
    """How the design was matched -- which decides what ``vhdl`` above means."""
    if pinmap is not None:
        return {"mode": "pin map", "source": pinmap.source}
    if match is not None:
        return {"mode": "board-native", "source": match.maker}
    return {"mode": "generic"}


# ── The document ──────────────────────────────────────────────────────────────

_HOW_TO_READ = (
    "Each PNG shows an interval, not an instant. duty is the exact on-time "
    "fraction the simulator measured over window_ns; level is what the board was "
    "displaying, which is that duty after a ~100 ms persistence-of-vision ease -- "
    "so a signal stable across the window matches and a faster one (PWM, scan "
    "display) lags. Compare a trace over window_ns against duty, not the value at "
    "sim_ns. Array indices are explained by `channels`. See "
    "docs/screenshot_manifest.md."
)

_HOW_TO_READ_NO_DUTY = (
    "This run measured no duty: LED PWM was off, which drops the U9 integrator "
    "from the generated wrapper entirely. level is therefore the exact bit at "
    "sim_ns with no averaging and no easing, duty is empty and window_ns is null "
    "-- a PNG really is an instantaneous sample here. Array indices are explained "
    "by `channels`. See docs/screenshot_manifest.md."
)


def _ticks(ns: int, timescale_fs: int | None) -> int | None:
    """*ns* as a whole number of the dump's own ticks, or ``None`` if it is not one.

    Computed from the nanoseconds rather than from a ticks-per-ns multiplier,
    because that multiplier is not always a whole number: a dump scaled at 10 ns
    per tick has one tick per *ten* nanoseconds, and integer-dividing to get
    "ticks per ns" collapses it to zero -- dropping a figure (729296) that is
    exactly representable. Going the other way keeps every scale that divides,
    and refuses the ones that do not instead of truncating them into a number
    that looks right and is not.
    """
    if not timescale_fs:
        return None
    ticks, remainder = divmod(ns * 1_000_000, timescale_fs)  # a ns is 1e6 fs
    return ticks if remainder == 0 else None


def _dialects(values: list[int], timescale_fs: int | None) -> dict[str, Any]:
    """One time, or a pair, in both dialects the two viewers disagree about.

    GTKWave parses ``7292960 ns`` (so does Surfer's own command prompt); Surfer's
    ``-C`` parses before the waveform loads and needs the unitless tick count.
    A pair is all-or-nothing: half a window in ticks is worse than none.
    """
    out: dict[str, Any] = {"time": [f"{v} ns" for v in values]}
    ticks = [_ticks(v, timescale_fs) for v in values]
    if all(t is not None for t in ticks):
        out["ticks"] = ticks
    if len(values) == 1:
        return {k: v[0] for k, v in out.items()}
    return out


def build(
    shots: list[Shot],
    *,
    board: str = "",
    design: str = "",
    dump: str | Path | None = None,
    board_def: BoardDef | None = None,
    match: ConventionMatch | None = None,
    pinmap: PinMapMatch | None = None,
) -> dict[str, Any]:
    """Assemble the manifest document for *shots*."""
    from fpga_sim.waveform import _gtkw_path, dump_timescale_fs

    measured = any(s.metrics.window_ns is not None for s in shots)
    doc: dict[str, Any] = {
        "board": board,
        "design": design,
        "run": run_block(match, pinmap),
        "how_to_read": _HOW_TO_READ if measured else _HOW_TO_READ_NO_DUTY,
    }

    timescale_fs: int | None = None
    if dump is not None:
        dump_path = Path(dump)
        timescale_fs = dump_timescale_fs(dump_path)
        doc["waveform"] = {
            "dump": str(dump_path),
            "gtkw": str(_gtkw_path(dump_path)),
            "timescale_fs": timescale_fs,
        }

    channels: dict[str, Any] = {}
    leds = led_legend(board_def, match, pinmap)
    if leds:
        channels["led"] = leds
    seg = seg_legend(board_def)
    if seg is not None:
        channels["seg"] = seg
    if channels:
        doc["channels"] = channels

    rows: list[dict[str, Any]] = []
    for shot in shots:
        m = shot.metrics
        entry: dict[str, Any] = {
            "file": shot.path.name,
            "sim_ns": shot.sim_ns,
            "window_ns": list(m.window_ns) if m.window_ns else None,
            "marker": _dialects([shot.sim_ns], timescale_fs),
        }
        if m.window_ns:
            entry["window"] = _dialects(list(m.window_ns), timescale_fs)
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
        rows.append(entry)
    doc["shots"] = rows
    return doc
