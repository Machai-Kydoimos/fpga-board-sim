r"""Render an annotated waveform PNG of the mx65_hello_7seg design's reset/boot story.

Simulates `hdl/mx65_hello_7seg.vhd` under GHDL against a tiny inline testbench,
dumps a VCD, and renders it in a GTKWave-like visual idiom (black background,
green digital traces, hexagonal bus lanes) with five annotations -- the POR
release, the reset-vector fetch, the first opcode, the LED-on store, and the
terminal spin loop -- located programmatically from the trace, not hardcoded.

This is a maintainer / documentation tool (a sibling to `capture_demo.py`);
stdlib + Pillow only, no new dependencies (Pillow is already a `dev`-group
dependency). Also (re)writes a GTKWave `.gtkw` save file listing the same
signals, so `gtkwave <vcd> docs/assets/mx65_hello_7seg.gtkw` (with a VCD kept
via `--vcd-out`) opens the identical view in real GTKWave.

Examples
--------
Regenerate the guide's waveform figure::

    uv run python scripts/capture_waveform.py

Keep the VCD to open in GTKWave::

    uv run python scripts/capture_waveform.py --vcd-out /tmp/hello.vcd
    gtkwave /tmp/hello.vcd docs/assets/mx65_hello_7seg.gtkw

"""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont

REPO = Path(__file__).resolve().parent.parent
HELLO_VHD = REPO / "hdl" / "mx65_hello_7seg.vhd"
PNG_OUT = REPO / "docs" / "assets" / "mx65_hello_waveform.png"
GTKW_OUT = REPO / "docs" / "assets" / "mx65_hello_7seg.gtkw"

STOP_TIME_NS = 3000  # whole hello story (POR, vector fetch, ~15 insns, spin) fits in <1us
# The rendered figure only plots the first RENDER_END_NS: the spin loop repeats every
# 30 ns, so ~650 ns already shows several cycles clearly. Simulating the full
# STOP_TIME_NS still matters -- find_spin_loop() checks the pattern holds all the way
# to the end, which is what makes it trustworthy to render as "repeats forever."
RENDER_END_NS = 650

_TESTBENCH = """\
library ieee;
use ieee.std_logic_1164.all;

entity wave_tb is
end entity;

architecture sim of wave_tb is
  signal clk : std_logic := '0';
  signal sw  : std_logic_vector(3 downto 0) := (others => '0');
  signal btn : std_logic_vector(3 downto 0) := (others => '0');
  signal led : std_logic_vector(3 downto 0);
  signal seg : std_logic_vector(31 downto 0);
begin
  dut : entity work.mx65_hello_7seg
    generic map (
      NUM_SWITCHES => 4,
      NUM_BUTTONS  => 4,
      NUM_LEDS     => 4,
      NUM_SEGS     => 4,
      COUNTER_BITS => 17
    )
    port map (
      clk => clk,
      sw  => sw,
      btn => btn,
      led => led,
      seg => seg
    );

  clk_gen : process
  begin
    clk <= '0';
    wait for 5 ns;
    clk <= '1';
    wait for 5 ns;
  end process;
end architecture;
"""

# --- 1. Simulate ------------------------------------------------------------


def _run(cmd: list[str], cwd: Path, what: str) -> None:
    """Run a build subprocess, raising with captured output on failure."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(
            f"{what} failed (rc={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )


def simulate(vcd_out: Path) -> None:
    """Analyze/elaborate/run the hello design plus the inline testbench, writing a VCD."""
    with tempfile.TemporaryDirectory(prefix="capture_waveform_") as tmp:
        work = Path(tmp)
        (work / "wave_tb.vhd").write_text(_TESTBENCH)
        _run(["ghdl", "-a", "--std=08", str(HELLO_VHD), "wave_tb.vhd"], work, "analyze")
        _run(["ghdl", "-e", "--std=08", "wave_tb"], work, "elaborate")
        _run(
            [
                "ghdl",
                "-r",
                "--std=08",
                "wave_tb",
                f"--vcd={vcd_out}",
                f"--stop-time={STOP_TIME_NS}ns",
            ],
            work,
            "simulate",
        )


# --- 2. Parse -----------------------------------------------------------------

Sample = tuple[int, "int | None"]  # (time_ns, value; None = metavalue)


@dataclass(frozen=True)
class Signal:
    """A parsed VCD variable: its id, bit width, and dot-joined hierarchical path."""

    id: str
    size: int
    path: str


def parse_vcd(vcd_path: Path) -> tuple[dict[str, Signal], dict[str, list[Sample]]]:
    """Parse a VCD file into (signals keyed by path, value-change samples keyed by id).

    GHDL's default VCD timescale is femtoseconds; sample times are converted
    to whole nanoseconds. A sample value of ``None`` means the sample
    contained an ``x``/``z`` bit (a metavalue).
    """
    scope: list[str] = []
    signals: dict[str, Signal] = {}
    changes: dict[str, list[Sample]] = {}
    header = True
    time_ns = 0

    for raw_line in vcd_path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if header:
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope.pop()
            elif line.startswith("$var"):
                parts = line.split()
                size, vid, name = int(parts[2]), parts[3], re.sub(r"\[.*\]$", "", parts[4])
                path = ".".join((*scope, name))
                signals[path] = Signal(id=vid, size=size, path=path)
                changes.setdefault(vid, [])
            elif line.startswith("$enddefinitions"):
                header = False
            continue
        if line[0] == "#":
            time_ns = int(line[1:]) // 1_000_000
        elif line[0] in "01xXzZ":
            value = None if line[0] in "xXzZ" else int(line[0])
            changes.setdefault(line[1:], []).append((time_ns, value))
        elif line[0] in "bB":
            bits, vid = line[1:].split()
            value = None if any(c not in "01" for c in bits) else int(bits, 2)
            changes.setdefault(vid, []).append((time_ns, value))
    return signals, changes


def trace_for(
    signals: dict[str, Signal], changes: dict[str, list[Sample]], suffix: str
) -> list[Sample]:
    """Return the value-change trace for the shortest-path signal ending in *suffix*."""
    matches = sorted(
        (s for path, s in signals.items() if path == suffix or path.endswith("." + suffix)),
        key=lambda s: len(s.path),
    )
    if not matches:
        raise SystemExit(f"signal not found in VCD: {suffix}")
    return changes[matches[0].id]


def value_at(trace: list[Sample], time_ns: int) -> int | None:
    """Return *trace*'s value at *time_ns* (the most recent sample at or before it)."""
    value: int | None = None
    for t, v in trace:
        if t > time_ns:
            break
        value = v
    return value


# --- 3. Locate the five annotation events, programmatically -------------------


@dataclass(frozen=True)
class Annotation:
    """A single labeled event: where it happens and what row it points at."""

    time_ns: int
    label: str
    row: str


def find_reset_release(reset_trace: list[Sample]) -> int:
    """Return the time (ns) of cpu_reset's first 1 -> 0 transition."""
    prev: int | None = None
    for t, v in reset_trace:
        if prev == 1 and v == 0:
            return t
        prev = v
    raise SystemExit("cpu_reset never releases within the captured window")


def find_vector_fetch(addr_trace: list[Sample], after_ns: int) -> tuple[int, int]:
    """Return (fffc_time, first_opcode_time): the reset-vector fetch and the fetch after it."""
    numeric = [(t, v) for t, v in addr_trace if v is not None and t >= after_ns]
    fffc_time = next((t for t, v in numeric if v == 0xFFFC), None)
    if fffc_time is None:
        raise SystemExit("cpu_addr never reads $FFFC after cpu_reset releases")
    fffd_time = next((t for t, v in numeric if v == 0xFFFD and t > fffc_time), None)
    if fffd_time is None:
        raise SystemExit("cpu_addr never reads $FFFD after $FFFC")
    first_fetch = next(
        ((t, v) for t, v in numeric if t > fffd_time and v not in (0xFFFC, 0xFFFD)), None
    )
    if first_fetch is None:
        raise SystemExit("cpu_addr never fetches the reset target after $FFFD")
    return fffc_time, first_fetch[0]


def find_led_write(
    addr_trace: list[Sample], we_trace: list[Sample], led_trace: list[Sample]
) -> tuple[int, int]:
    """Return (time, address) of the cpu_we pulse whose write coincides with led's rising edge."""
    prev: int | None = None
    led_rise: int | None = None
    for t, v in led_trace:
        if v is not None and v != 0 and (prev or 0) == 0:
            led_rise = t
            break
        prev = v
    if led_rise is None:
        raise SystemExit("led never rises within the captured window")
    we_times = [t for t, v in we_trace if v == 1 and t <= led_rise]
    if not we_times:
        raise SystemExit("no cpu_we pulse found at or before led rises")
    we_time = we_times[-1]
    addr = value_at(addr_trace, we_time)
    if addr is None:
        raise SystemExit("cpu_addr is a metavalue at the led-write pulse")
    return we_time, addr


def find_spin_loop(addr_trace: list[Sample], after_ns: int) -> tuple[int, list[int]]:
    """Find where a short address pattern begins and repeats to the end of the trace."""
    numeric = [(t, v) for t, v in addr_trace if v is not None and t >= after_ns]
    values = [v for _, v in numeric]
    n = len(values)
    for period in (3, 2, 4, 1):
        if n < period * 3:
            continue
        tail = values[-period:]
        if not all(values[i] == tail[i % period] for i in range(n - period, n)):
            continue
        start = n - period
        while start - period >= 0 and values[start - period : start] == tail:
            start -= period
        return numeric[start][0], sorted(set(tail))
    raise SystemExit("could not detect a repeating spin-loop address pattern")


def count_rising_edges(clk_trace: list[Sample], up_to_ns: int) -> int:
    """Count 0 -> 1 transitions in *clk_trace* at or before *up_to_ns*."""
    count = 0
    prev: int | None = None
    for t, v in clk_trace:
        if t > up_to_ns:
            break
        if prev == 0 and v == 1:
            count += 1
        prev = v
    return count


def locate_annotations(
    signals: dict[str, Signal], changes: dict[str, list[Sample]]
) -> list[Annotation]:
    """Locate the five guide-callout events purely from the parsed VCD traces."""
    clk = trace_for(signals, changes, "clk")
    reset = trace_for(signals, changes, "dut.cpu_reset")
    addr = trace_for(signals, changes, "dut.cpu_addr")
    we = trace_for(signals, changes, "dut.cpu_we")
    led = trace_for(signals, changes, "dut.led")

    release_time = find_reset_release(reset)
    release_clocks = count_rising_edges(clk, release_time)
    fffc_time, first_fetch_time = find_vector_fetch(addr, release_time)
    we_time, we_addr = find_led_write(addr, we, led)
    spin_time, spin_addrs = find_spin_loop(addr, we_time)
    lo, hi = min(spin_addrs), max(spin_addrs)

    return [
        Annotation(release_time, f"POR releases after {release_clocks} clocks", "cpu_reset"),
        Annotation(fffc_time, "6502 fetches the reset vector ($FFFC/$FFFD)", "cpu_addr"),
        Annotation(first_fetch_time, "first opcode (SEI)", "cpu_addr"),
        Annotation(we_time, f"STA ${we_addr:04X} -> LED0 on", "cpu_we"),
        Annotation(spin_time, f"spin: JMP spin (${lo:04X}-${hi:04X})", "cpu_addr"),
    ]


# --- 4. Render (Pillow, GTKWave visual idiom) ----------------------------------

_SS = 2  # supersample factor; everything is drawn at _SS scale then downsampled

_BG = (0, 0, 0)
_GUTTER_BG = (8, 10, 9)
_GRID = (36, 42, 40)
_TRACE = (66, 224, 122)
_TEXT = (222, 228, 225)
_TEXT_DIM = (120, 132, 128)
_META = (232, 70, 70)
_ANNOTATION = (255, 196, 71)

_ROW_LABELS = ("clk", "cpu_reset", "cpu_addr[15:0]", "cpu_din[7:0]", "cpu_we", "led[3:0]")
_ROW_KEYS = ("clk", "cpu_reset", "cpu_addr", "cpu_din", "cpu_we", "led")
_ROW_WIDTH = {"clk": 1, "cpu_reset": 1, "cpu_addr": 16, "cpu_din": 8, "cpu_we": 1, "led": 4}

_FINAL_W = 1600
_GUTTER_W = 210
_RIGHT_MARGIN = 30
_TOP_MARGIN = 16
_RULER_H = 34
_ANNOT_LANES = 3
_ANNOT_LANE_H = 26
_ROW_H = 44
_ROW_GAP = 6
_BOTTOM_MARGIN = 30

_PLOT_W = _FINAL_W - _GUTTER_W - _RIGHT_MARGIN
_ANNOT_H = _ANNOT_LANES * _ANNOT_LANE_H
_FINAL_H = (
    _TOP_MARGIN
    + _RULER_H
    + _ANNOT_H
    + len(_ROW_KEYS) * _ROW_H
    + (len(_ROW_KEYS) - 1) * _ROW_GAP
    + _BOTTOM_MARGIN
)


def _font(size: int) -> FreeTypeFont:
    """Return Pillow's bundled scalable default font at *size* (no system font needed)."""
    return cast("FreeTypeFont", ImageFont.load_default(size=size))


def _time_to_x(time_ns: int) -> float:
    """Map a trace time (ns) to a plot-area x coordinate at the base (non-supersampled) scale."""
    return _GUTTER_W + (time_ns / RENDER_END_NS) * _PLOT_W


def _row_y(index: int) -> tuple[float, float]:
    """Return (top, bottom) y coordinates for row *index*, at the base scale."""
    top = _TOP_MARGIN + _RULER_H + _ANNOT_H + index * (_ROW_H + _ROW_GAP)
    return top, top + _ROW_H


def _bus_polygon(
    x0: float, x1: float, y0: float, y1: float, notch: float, first: bool, last: bool
) -> list[tuple[float, float]]:
    """Return the GTKWave-style hexagonal bus-lane polygon points for one value segment."""
    y_mid = (y0 + y1) / 2
    pts: list[tuple[float, float]] = []
    pts.append((x0, y0) if first else (x0 + notch, y0))
    pts.append((x1, y0) if last else (x1 - notch, y0))
    if not last:
        pts.append((x1, y_mid))
    pts.append((x1, y1) if last else (x1 - notch, y1))
    pts.append((x0, y1) if first else (x0 + notch, y1))
    if not first:
        pts.append((x0, y_mid))
    return pts


def _segments(trace: list[Sample], end_ns: int) -> list[tuple[int, int, int | None]]:
    """Turn a sparse value-change trace into (start, end, value) segments covering [0, end_ns]."""
    points = sorted(trace)
    if not points or points[0][0] > 0:
        points = [(0, None), *points]
    segs = []
    for i, (t, v) in enumerate(points):
        t_next = points[i + 1][0] if i + 1 < len(points) else end_ns
        if t_next > t:
            segs.append((t, t_next, v))
    return segs


def _draw_scalar_row(
    draw: ImageDraw.ImageDraw,
    y0: float,
    y1: float,
    segs: list[tuple[int, int, int | None]],
    font: FreeTypeFont,
) -> None:
    """Draw a digital step trace: low near y1, high near y0, red where metavalue."""
    hi, lo = y0 + (y1 - y0) * 0.18, y0 + (y1 - y0) * 0.82
    for t0, t1, v in segs:
        x0, x1 = _time_to_x(t0) * _SS, _time_to_x(t1) * _SS
        if v is None:
            draw.line([(x0, (hi + lo) / 2 * 1), (x1, (hi + lo) / 2)], fill=_META, width=3 * _SS)
            continue
        y = hi if v else lo
        draw.line([(x0, y), (x1, y)], fill=_TRACE, width=2 * _SS)
        draw.line([(x0, y0), (x0, y1)], fill=_TRACE, width=1)


def _draw_bus_row(
    draw: ImageDraw.ImageDraw,
    y0: float,
    y1: float,
    segs: list[tuple[int, int, int | None]],
    hex_digits: int,
    font: FreeTypeFont,
) -> None:
    """Draw a GTKWave-style hexagonal bus lane with centered hex values."""
    max_notch = 9 * _SS
    for i, (t0, t1, v) in enumerate(segs):
        x0, x1 = _time_to_x(t0) * _SS, _time_to_x(t1) * _SS
        width_px = x1 - x0
        color = _META if v is None else _TRACE
        if width_px < 3 * _SS:
            # Too narrow for a hex lane: a fixed notch would exceed the segment
            # width and self-intersect, so fall back to a plain thin fill.
            draw.rectangle([x0, y0, max(x1, x0 + 1), y1], outline=color, width=1)
            continue
        notch = min(max_notch, width_px * 0.4)
        pts = _bus_polygon(x0, x1, y0, y1, notch, i == 0, i == len(segs) - 1)
        draw.polygon(pts, outline=color, width=2)
        label = "X" if v is None else f"{v:0{hex_digits}X}"
        bbox = font.getbbox(label)
        text_w = bbox[2] - bbox[0]
        if text_w + notch * 2 < width_px:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            draw.text(
                (cx - text_w / 2, cy - (bbox[3] - bbox[1]) / 2 - bbox[1]),
                label,
                fill=_TEXT,
                font=font,
            )


def _assign_lanes(annotations: list[Annotation], font: FreeTypeFont) -> list[int]:
    """Greedily assign each (time-sorted) annotation to the lowest lane clear of its label."""
    lane_right_edge: list[float] = []
    lanes: list[int] = []
    pad = 24.0  # base-scale px of breathing room between adjacent labels
    for annotation in annotations:
        x = _time_to_x(annotation.time_ns)
        bbox = font.getbbox(annotation.label)
        text_w = (bbox[2] - bbox[0]) / _SS
        for i, last_right in enumerate(lane_right_edge):
            if x - pad > last_right:
                lane_right_edge[i] = x + text_w
                lanes.append(i)
                break
        else:
            lane_right_edge.append(x + text_w)
            lanes.append(len(lane_right_edge) - 1)
    return lanes


def render(
    signals: dict[str, Signal],
    changes: dict[str, list[Sample]],
    annotations: list[Annotation],
    out_path: Path,
) -> None:
    """Render the full annotated waveform PNG."""
    img = Image.new("RGB", (_FINAL_W * _SS, _FINAL_H * _SS), _BG)
    draw = ImageDraw.Draw(img)

    gutter_font = _font(15 * _SS)
    ruler_font = _font(13 * _SS)
    bus_font = _font(14 * _SS)
    annot_font = _font(14 * _SS)

    draw.rectangle([0, 0, _GUTTER_W * _SS, _FINAL_H * _SS], fill=_GUTTER_BG)

    # Time ruler: gridlines + labels every 100 ns.
    ruler_top = _TOP_MARGIN * _SS
    ruler_bottom = (_TOP_MARGIN + _RULER_H) * _SS
    plot_bottom = (_FINAL_H - _BOTTOM_MARGIN) * _SS
    step_ns = 100
    t = 0
    while t <= RENDER_END_NS:
        x = _time_to_x(t) * _SS
        draw.line([(x, ruler_bottom), (x, plot_bottom)], fill=_GRID, width=1)
        label = f"{t} ns"
        bbox = ruler_font.getbbox(label)
        draw.text(
            (x - (bbox[2] - bbox[0]) / 2, ruler_top + 2 * _SS),
            label,
            fill=_TEXT_DIM,
            font=ruler_font,
        )
        t += step_ns
    draw.line(
        [(_GUTTER_W * _SS, ruler_bottom), (_FINAL_W * _SS, ruler_bottom)], fill=_GRID, width=1
    )

    # Signal rows.
    for i, (label, key) in enumerate(zip(_ROW_LABELS, _ROW_KEYS, strict=True)):
        y0, y1 = _row_y(i)
        y0, y1 = y0 * _SS, y1 * _SS
        trace = trace_for(signals, changes, f"dut.{key}" if key != "clk" else "clk")
        segs = _segments(trace, RENDER_END_NS)
        bbox = gutter_font.getbbox(label)
        draw.text(
            (10 * _SS, (y0 + y1) / 2 - (bbox[3] - bbox[1]) / 2 - bbox[1]),
            label,
            fill=_TEXT,
            font=gutter_font,
        )
        if _ROW_WIDTH[key] == 1:
            _draw_scalar_row(draw, y0, y1, segs, bus_font)
        else:
            _draw_bus_row(draw, y0, y1, segs, (_ROW_WIDTH[key] + 3) // 4, bus_font)

    # Annotations: a dashed marker line through every row + a label in a free lane.
    ordered = sorted(annotations, key=lambda a: a.time_ns)
    lanes = _assign_lanes(ordered, annot_font)
    annot_bottom = (_TOP_MARGIN + _RULER_H + _ANNOT_H) * _SS
    for annotation, lane in zip(ordered, lanes, strict=True):
        x = _time_to_x(annotation.time_ns) * _SS
        dash_top = (_TOP_MARGIN + _RULER_H + lane * _ANNOT_LANE_H + 6) * _SS
        y = dash_top
        while y < plot_bottom:
            draw.line([(x, y), (x, min(y + 6 * _SS, plot_bottom))], fill=_ANNOTATION, width=1)
            y += 11 * _SS
        draw.ellipse(
            [x - 3 * _SS, dash_top - 3 * _SS, x + 3 * _SS, dash_top + 3 * _SS], fill=_ANNOTATION
        )
        label_y = (_TOP_MARGIN + _RULER_H + lane * _ANNOT_LANE_H + 2) * _SS
        bbox = annot_font.getbbox(annotation.label)
        text_w = bbox[2] - bbox[0]
        label_x = min(max(x + 6 * _SS, _GUTTER_W * _SS + 2), _FINAL_W * _SS - text_w - 4 * _SS)
        # Faux-bold: the bundled default font has no bold weight, so double-stroke it.
        draw.text((label_x + 1, label_y), annotation.label, fill=_ANNOTATION, font=annot_font)
        draw.text((label_x, label_y), annotation.label, fill=_ANNOTATION, font=annot_font)
    del annot_bottom

    caption = (
        f"only the first {RENDER_END_NS} ns are plotted -- the spin loop repeats "
        f"unchanged through the full {STOP_TIME_NS} ns simulated window (checked "
        "programmatically, not just eyeballed)"
    )
    caption_font = _font(12 * _SS)
    draw.text((_GUTTER_W * _SS, plot_bottom + 6 * _SS), caption, fill=_TEXT_DIM, font=caption_font)

    final = img.resize((_FINAL_W, _FINAL_H), Image.Resampling.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(out_path)


# --- 5. GTKWave save file -------------------------------------------------------


def write_gtkw(gtkw_path: Path, vcd_hint: str) -> None:
    """(Re)write a GTKWave save file listing the same signals this script renders.

    GTKWave's default display for multi-bit signals is already hexadecimal, so
    no radix flags are needed here for the guide's "hex radix" requirement.
    """
    lines = [
        "[*]",
        "[*] GTKWave save file for the mx65_hello_7seg annotated waveform.",
        "[*] Regenerate with: uv run python scripts/capture_waveform.py",
        "[*]",
        f'[dumpfile] "{vcd_hint}"',
        "[timestart] 0",
        "[size] 1600 640",
        "[pos] -1 -1",
        "[sst_width] 220",
        "[signals_width] 220",
        "-mx65_hello_7seg",
        "wave_tb.dut.clk",
        "wave_tb.dut.cpu_reset",
        "wave_tb.dut.cpu_addr[15:0]",
        "wave_tb.dut.cpu_din[7:0]",
        "wave_tb.dut.cpu_we",
        "wave_tb.dut.led[3:0]",
    ]
    gtkw_path.write_text("\n".join(lines) + "\n")


# --- CLI -----------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """Parse command-line options."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--vcd-out", type=Path, default=None, help="keep the VCD at this path (default: discarded)"
    )
    return parser.parse_args()


def main() -> None:
    """Simulate, parse, locate the five annotations, and render the PNG + .gtkw."""
    args = _parse_args()
    with tempfile.TemporaryDirectory(prefix="capture_waveform_vcd_") as tmp:
        vcd_path = args.vcd_out if args.vcd_out is not None else Path(tmp) / "mx65_hello_7seg.vcd"
        simulate(vcd_path)
        signals, changes = parse_vcd(vcd_path)
        annotations = locate_annotations(signals, changes)
        render(signals, changes, annotations, PNG_OUT)
        vcd_hint = str(args.vcd_out) if args.vcd_out is not None else "mx65_hello_7seg.vcd"
        write_gtkw(GTKW_OUT, vcd_hint)

    print(f"wrote {PNG_OUT}")
    print(f"wrote {GTKW_OUT}")
    for annotation in annotations:
        print(f"  {annotation.time_ns:>5} ns  {annotation.label}")


if __name__ == "__main__":
    main()
