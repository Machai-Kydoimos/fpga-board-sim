#!/usr/bin/env python3
"""generate_board_images.py

Generates PNG, JPEG, and SVG preview images for every FPGA board discovered
in the amaranth-boards git submodule.  Images are written to a local
board_images/ directory that is excluded from version control.

The script uses existing project infrastructure (FPGABoard, board_loader)
without modifying any of it.  The same visual layout and color scheme used
by the interactive simulator is reproduced faithfully.

Usage:
    python generate_board_images.py [options]

    --output-dir PATH    Destination directory        (default: ./board_images)
    --width  INT         Image width  in pixels       (default: 1024)
    --height INT         Image height in pixels       (default: 700)
    --formats LIST       Comma-separated: png, jpeg, svg, all  (default: all)
    --filter  TEXT       Only process boards whose name contains TEXT
    --list               Print discovered board names and exit
    --boards-dir PATH    Override amaranth_boards directory (default: auto)

Dependencies: pygame (already in pyproject.toml).  No new dependencies needed.
"""

# SDL environment variables must be set before pygame is imported or initialized.
# The "dummy" driver runs all display operations entirely in memory —
# no window appears, but pygame.Surface objects are fully usable for rendering
# and saving to files.
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pygame

# Ensure the simulator directory is on the path so board_loader and fpga_board
# are importable when this script is invoked from another working directory.
sys.path.insert(0, str(Path(__file__).parent))

from board_loader import BoardDef, discover_boards, get_default_boards_path
from ui import LED, Button, FPGABoard, FPGAChip, Switch
from ui.constants import BG_GREEN, BLUE_OFF, GRAY, RED_OFF, WHITE, _ui_scale

# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_WIDTH:  int = 1024
DEFAULT_HEIGHT: int = 700


# ── Pygame setup ───────────────────────────────────────────────────────────────

def setup_pygame_headless() -> None:
    """Initialize pygame once for the entire batch run.

    With SDL_VIDEODRIVER=dummy (set at module load time), pygame.init()
    starts the display subsystem in memory — no window is created.
    This must be called before the first FPGABoard is instantiated.
    """
    pygame.init()


# ── Filename utilities ─────────────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    """Convert a board name to a filesystem-safe base name.

    Non-alphanumeric characters (except hyphens) become underscores;
    consecutive underscores are collapsed; leading/trailing separators
    are stripped.  The result is always lowercase.

    Examples:
        "Arty A7-35"  → "arty_a7_35"
        "iCEBreaker"  → "icebreaker"
        "Tang Nano 9K"→ "tang_nano_9k"

    """
    result: list[str] = []
    for ch in name.lower():
        result.append(ch if (ch.isalnum() or ch == "-") else "_")
    safe = "".join(result)
    # Collapse runs of underscores/hyphens
    while "__" in safe or "--" in safe:
        safe = safe.replace("__", "_").replace("--", "-")
    return safe.strip("_-")


def unique_name(base: str, seen: dict[str, int]) -> str:
    """Return a unique filename base, appending _2, _3, … on collision.

    Mutates `seen` to record usage counts.  Collisions are rare in practice
    (boards generally have distinct names) but are handled defensively.
    """
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return f"{base}_{seen[base]}"


# ── Raster rendering (PNG / JPEG) ──────────────────────────────────────────────

def render_board_raster(board: FPGABoard) -> pygame.Surface:
    """Render the board to its pygame Surface and return a snapshot copy.

    Calls FPGABoard._draw() — a private but stable method — which fills
    the screen with BG_GREEN and draws all sections (FPGA chip, LEDs,
    buttons, switches) plus the "Start Simulation" button and ESC hint.

    Those UI-chrome elements will appear in the raster images.  A future
    improvement would be a headless=True flag on FPGABoard to suppress them
    for cleaner static images without modifying existing behavior.
    """
    board._draw()
    return board.screen.copy()


def save_png(surface: pygame.Surface, path: Path) -> None:
    """Save a pygame Surface as a PNG file."""
    pygame.image.save(surface, str(path))


def save_jpeg(surface: pygame.Surface, path: Path) -> None:
    """Save a pygame Surface as a JPEG file.

    pygame.image.save() supports JPEG when libjpeg is available, which is
    standard on all common pygame distributions.  JPEG quality is not
    exposed by pygame's API; use Pillow if quality control is needed.
    """
    pygame.image.save(surface, str(path))


# ── SVG primitive helpers ──────────────────────────────────────────────────────

def _svg_color(rgb: tuple[int, int, int]) -> str:
    """Convert an RGB tuple to an SVG hex color string, e.g. (80,0,0)→'#500000'."""
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _svg_text(
    parent: ET.Element,
    x: float,
    y: float,
    text: str,
    *,
    size: int,
    color: tuple[int, int, int],
    bold: bool = False,
    anchor: str = "middle",
    baseline: str = "hanging",
) -> None:
    """Append a <text> element to `parent`.

    `baseline` controls vertical alignment:
      "hanging" — y is the top of the text box (matches pygame's blit top-left).
      "middle"  — y is the vertical center (matches pygame's get_rect centery=y).

    `anchor` controls horizontal alignment:
      "middle" — x is the horizontal center.
      "start"  — x is the left edge.
    """
    attrs: dict[str, str] = {
        "x": str(int(x)),
        "y": str(int(y)),
        "fill": _svg_color(color),
        "font-family": "monospace",
        "font-size": str(size),
        "text-anchor": anchor,
        "dominant-baseline": baseline,
    }
    if bold:
        attrs["font-weight"] = "bold"
    elem = ET.SubElement(parent, "text", attrs)
    elem.text = text


def _svg_rect(
    parent: ET.Element,
    rect: pygame.Rect,
    fill: tuple[int, int, int],
    *,
    stroke: tuple[int, int, int] | None = None,
    stroke_width: int = 2,
    radius: int = 0,
) -> None:
    """Append a <rect> element with optional rounded corners and stroke.

    When stroke is None the rect has no visible border (stroke="none").
    """
    attrs: dict[str, str] = {
        "x":      str(int(rect.x)),
        "y":      str(int(rect.y)),
        "width":  str(int(rect.width)),
        "height": str(int(rect.height)),
        "fill":   _svg_color(fill),
        "stroke": _svg_color(stroke) if stroke is not None else "none",
    }
    if stroke is not None:
        attrs["stroke-width"] = str(stroke_width)
    if radius:
        attrs["rx"] = str(radius)
        attrs["ry"] = str(radius)
    ET.SubElement(parent, "rect", attrs)


def _svg_line(
    parent: ET.Element,
    x1: float, y1: float,
    x2: float, y2: float,
    color: tuple[int, int, int],
) -> None:
    """Append a <line> element with a 1px stroke."""
    ET.SubElement(parent, "line", {
        "x1": str(int(x1)), "y1": str(int(y1)),
        "x2": str(int(x2)), "y2": str(int(y2)),
        "stroke": _svg_color(color),
        "stroke-width": "1",
    })


# ── SVG component renderers ────────────────────────────────────────────────────

def _svg_draw_fpga_chip(
    parent: ET.Element,
    chip: FPGAChip,
    font_size: int,
) -> None:
    """Draw the FPGA IC package as SVG elements.

    Replicates FPGAChip.draw() and FPGAChip._draw_pin_marks() from
    fpga_board.py:
      - Vendor-colored rounded rectangle with gray border
      - Short tick marks along all four edges (simulated IC package pins)
      - Three centered text labels: vendor name, device ID, package code

    Vendor colors are read directly from FPGAChip._VENDOR_COLORS so that
    any future additions to that dict are automatically reflected here.
    """
    r = chip.rect
    if r.width < 20:
        return  # Guard matches FPGAChip.draw() early-exit condition

    # Main body — vendor-specific fill with gray border
    fill = FPGAChip._VENDOR_COLORS.get(chip.vendor, (40, 40, 40))
    _svg_rect(parent, r, fill, stroke=FPGAChip._BORDER_COLOR, stroke_width=2, radius=6)

    # Pin tick marks — replicates _draw_pin_marks() count formula exactly
    h_count = max(4, min(20, r.width  // 14))
    v_count = max(4, min(14, r.height // 14))
    ln = FPGAChip._PIN_LENGTH

    for i in range(h_count):
        x = r.left + (i + 1) * r.width // (h_count + 1)
        _svg_line(parent, x, r.top,    x, r.top    - ln, FPGAChip._PIN_COLOR)  # top edge
        _svg_line(parent, x, r.bottom, x, r.bottom + ln, FPGAChip._PIN_COLOR)  # bottom edge

    for i in range(v_count):
        y = r.top + (i + 1) * r.height // (v_count + 1)
        _svg_line(parent, r.left,  y, r.left  - ln, y, FPGAChip._PIN_COLOR)  # left edge
        _svg_line(parent, r.right, y, r.right + ln, y, FPGAChip._PIN_COLOR)  # right edge

    # Centered text labels — mirrors the dynamic layout in FPGAChip.draw().
    # 1.2× is the standard approximation for a monospace font's line height.
    chip_font_size = max(11, font_size + 1)
    line_h = round(chip_font_size * 1.2)
    cx, cy = r.centerx, r.centery

    lines: list[tuple[str, tuple[int, int, int], bool]] = [
        (chip.vendor,          WHITE,                    True),
        (chip.device.upper(),  FPGAChip._DEVICE_COLOR,  False),
        (chip.package.upper(), FPGAChip._PACKAGE_COLOR, False),
    ]
    if chip.clock_hz:
        lines.append((FPGAChip._fmt_clock(chip.clock_hz), FPGAChip._CLOCK_COLOR, False))
    active = [(t, c, b) for t, c, b in lines if t]
    offset = -(len(active) - 1) / 2 * line_h
    for text, color, bold in active:
        _svg_text(parent, cx, cy + offset, text,
                  size=chip_font_size, color=color, bold=bold,
                  anchor="middle", baseline="middle")
        offset += line_h


def _svg_draw_led(
    parent: ET.Element,
    led: LED,
    font_size: int,
) -> None:
    """Draw a single LED as an SVG circle with a white border ring and label.

    Replicates LED.draw() from fpga_board.py.  Always renders in the OFF
    state (dark red fill) since board images show the default/reset state.
    The radius formula is identical to the pygame version.
    """
    cx, cy = led.rect.center
    radius = max(4, min(led.rect.width, led.rect.height) // 2 - 2)

    ET.SubElement(parent, "circle", {
        "cx": str(cx), "cy": str(cy), "r": str(radius),
        "fill":         _svg_color(RED_OFF),
        "stroke":       _svg_color(WHITE),
        "stroke-width": "1",
    })

    # Label sits below the LED circle; top of text aligns to rect.bottom + 1
    _svg_text(parent, cx, led.rect.bottom + 1,
              led.label, size=font_size, color=WHITE,
              anchor="middle", baseline="hanging")


def _svg_draw_switch(
    parent: ET.Element,
    sw: Switch,
    font_size: int,
) -> None:
    """Draw a toggle switch as an SVG rectangle with a sliding knob and label.

    Replicates Switch.draw() from fpga_board.py.  Always renders in the OFF
    state: BLUE_OFF background, GRAY knob positioned in the lower half of
    the switch body.
    """
    r = sw.rect

    # Switch body with white border
    _svg_rect(parent, r, BLUE_OFF, stroke=WHITE, stroke_width=2, radius=4)

    # Knob — lower half when off: rect.bottom - knob_h - 2 (same as pygame)
    knob_h = r.height // 2
    knob_y = r.bottom - knob_h - 2
    knob = pygame.Rect(r.x + 3, knob_y, r.width - 6, knob_h)
    _svg_rect(parent, knob, GRAY, radius=3)

    # Label below the switch body
    _svg_text(parent, r.centerx, r.bottom + 2,
              sw.label, size=font_size, color=WHITE,
              anchor="middle", baseline="hanging")


def _svg_draw_button(
    parent: ET.Element,
    btn: Button,
    font_size: int,
) -> None:
    """Draw a momentary button as an SVG rectangle with label.

    Replicates Button.draw() from fpga_board.py.  Always renders in the
    unpressed state: GRAY fill, white border, rounded corners.
    """
    r = btn.rect

    # Button body with white border
    _svg_rect(parent, r, GRAY, stroke=WHITE, stroke_width=2, radius=6)

    # Label below the button body
    _svg_text(parent, r.centerx, r.bottom + 2,
              btn.label, size=font_size, color=WHITE,
              anchor="middle", baseline="hanging")


# ── SVG document builder ───────────────────────────────────────────────────────

def build_svg(board: FPGABoard, width: int, height: int) -> str:
    """Build a complete SVG document from an already-laid-out FPGABoard.

    The board's component .rect fields must already be populated — this
    happens automatically inside FPGABoard.__init__ via _layout().

    The SVG mirrors FPGABoard._draw()'s visual style but intentionally omits
    UI chrome (Start Simulation button, ESC hint) since those only make sense
    in the interactive context.  Clock frequencies, if available, are embedded
    as an XML comment for informational purposes.

    Returns the full SVG document as a UTF-8 XML string.
    """
    font_size  = max(9, round(12 * _ui_scale(width, height)))  # matches FPGABoard._draw()
    title_size = font_size + 4                     # matches FPGABoard._draw() title_font

    svg = ET.Element("svg", {
        "xmlns":   "http://www.w3.org/2000/svg",
        "width":   str(width),
        "height":  str(height),
        "viewBox": f"0 0 {width} {height}",
    })

    # Board name and clock info as a leading XML comment (metadata, no visual impact)
    board_name = board.board_def.name if board.board_def else "FPGA Board"
    clocks_mhz = [
        f"{c / 1e6:.3g} MHz"
        for c in (board.board_def.clocks if board.board_def else [])
    ]
    comment = f" {board_name}"
    if clocks_mhz:
        comment += f" | Clocks: {', '.join(clocks_mhz)}"
    comment += " "
    svg.append(ET.Comment(comment))

    # PCB green background
    ET.SubElement(svg, "rect", {
        "width": str(width), "height": str(height),
        "fill": _svg_color(BG_GREEN),
    })

    # FPGA chip section — topmost, weight 2 in the layout
    if board.fpga_chip.rect.width >= 20:
        _svg_text(svg, 20, board.fpga_chip.rect.top - title_size - 10,
                  "FPGA", size=title_size, color=WHITE,
                  bold=True, anchor="start", baseline="hanging")
        _svg_draw_fpga_chip(svg, board.fpga_chip, font_size)

    # LEDs section — weight 3, gets the most vertical space
    if board.leds:
        _svg_text(svg, 20, board.leds[0].rect.top - title_size - 10,
                  "LEDs", size=title_size, color=WHITE,
                  bold=True, anchor="start", baseline="hanging")
        for led in board.leds:
            _svg_draw_led(svg, led, font_size)

    # Buttons section — weight 1
    if board.buttons:
        _svg_text(svg, 20, board.buttons[0].rect.top - title_size - 14,
                  "Buttons", size=title_size, color=WHITE,
                  bold=True, anchor="start", baseline="hanging")
        for btn in board.buttons:
            _svg_draw_button(svg, btn, font_size)

    # Switches section — weight 1
    if board.switches:
        _svg_text(svg, 20, board.switches[0].rect.top - title_size - 14,
                  "Switches", size=title_size, color=WHITE,
                  bold=True, anchor="start", baseline="hanging")
        for sw in board.switches:
            _svg_draw_switch(svg, sw, font_size)

    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(svg, encoding="unicode")


# ── Per-board orchestration ────────────────────────────────────────────────────

def generate_images_for_board(
    board_def: BoardDef,
    output_dir: Path,
    base_name: str,
    width: int,
    height: int,
    formats: set[str],
) -> tuple[bool, str]:
    """Generate all requested image formats for a single board.

    One FPGABoard instance is created and reused for all formats, so the
    layout is computed only once.  PNG and JPEG share the same rendered
    pygame Surface.  SVG is built from the same laid-out instance.

    Returns (success, message) for progress reporting in main().
    """
    try:
        # FPGABoard.__init__ calls _layout() automatically.
        board = FPGABoard(board_def=board_def, width=width, height=height)
        generated: list[str] = []

        # PNG and JPEG share one pygame render pass
        if formats & {"png", "jpeg"}:
            surface = render_board_raster(board)
            if "png" in formats:
                save_png(surface, output_dir / f"{base_name}.png")
                generated.append("png")
            if "jpeg" in formats:
                save_jpeg(surface, output_dir / f"{base_name}.jpg")
                generated.append("jpg")

        # SVG uses the already-laid-out board — no second layout needed
        if "svg" in formats:
            svg_content = build_svg(board, width, height)
            (output_dir / f"{base_name}.svg").write_text(svg_content, encoding="utf-8")
            generated.append("svg")

        return True, f"{base_name}: {', '.join(generated)}"

    except Exception as exc:
        return False, f"{base_name} ({board_def.name}): {exc}"


# ── CLI ────────────────────────────────────────────────────────────────────────

def _parse_formats(raw: str) -> set[str]:
    """Parse a comma-separated format string into a validated set.

    Accepts any combination of: png, jpeg, svg, all.
    Raises argparse.ArgumentTypeError on unrecognised tokens.
    """
    valid = {"png", "jpeg", "svg"}
    result: set[str] = set()
    for token in raw.lower().split(","):
        token = token.strip()
        if token == "all":
            return valid
        if token in valid:
            result.add(token)
        else:
            raise argparse.ArgumentTypeError(
                f"Unknown format '{token}'.  Choose from: png, jpeg, svg, all")
    if not result:
        raise argparse.ArgumentTypeError("At least one format must be specified.")
    return result


def main() -> None:
    """Entry point: discover boards, generate images, report results.

    Workflow:
      1. Parse CLI arguments.
      2. Discover all BoardDefs from the amaranth-boards submodule.
      3. Optionally filter by name and/or just list them (--list).
      4. Initialize headless pygame.
      5. For each board, generate the requested image formats.
      6. Print a per-board status line and a final summary.

    Exits with code 1 if any board fails or no boards are found.
    """
    parser = argparse.ArgumentParser(
        description="Generate PNG/JPEG/SVG preview images for all FPGA boards.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output-dir", metavar="PATH", type=Path,
        default=Path(__file__).parent / "board_images",
        help="Destination directory for generated images",
    )
    parser.add_argument(
        "--width", type=int, default=DEFAULT_WIDTH,
        help="Image width in pixels",
    )
    parser.add_argument(
        "--height", type=int, default=DEFAULT_HEIGHT,
        help="Image height in pixels",
    )
    parser.add_argument(
        "--formats", metavar="LIST", type=_parse_formats, default="all",
        help="Comma-separated formats to generate: png, jpeg, svg, all",
    )
    parser.add_argument(
        "--filter", metavar="TEXT", dest="name_filter", default="",
        help="Only process boards whose name contains TEXT (case-insensitive)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Print discovered board names and exit without generating images",
    )
    parser.add_argument(
        "--boards-dir", metavar="PATH", type=Path, default=None,
        help="Override the amaranth_boards directory (default: auto-detect from submodule)",
    )
    args = parser.parse_args()

    # ── Discover boards ────────────────────────────────────────────────────────
    boards_dir = args.boards_dir or get_default_boards_path()
    print(f"Scanning boards from: {boards_dir}")
    boards = discover_boards(boards_dir)

    if not boards:
        print("No boards found.  Run:  git submodule update --init", file=sys.stderr)
        sys.exit(1)

    # Apply optional name filter
    if args.name_filter:
        boards = [b for b in boards if args.name_filter.lower() in b.name.lower()]
        if not boards:
            print(f"No boards match filter '{args.name_filter}'.", file=sys.stderr)
            sys.exit(1)

    print(f"Found {len(boards)} board(s).")

    # ── --list: print and exit (no pygame needed) ──────────────────────────────
    if args.list:
        for b in boards:
            vendor_tag = f"  [{b.vendor}]" if b.vendor else ""
            print(f"  {b.name}{vendor_tag}  —  {b.summary}")
        return

    # ── Initialize headless pygame ─────────────────────────────────────────────
    setup_pygame_headless()

    # ── Prepare output directory ───────────────────────────────────────────────
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {args.output_dir}")

    # ── Build deduplicated filename map ────────────────────────────────────────
    # Most board names are unique after sanitization, but collisions are handled
    # defensively by appending _2, _3, … to duplicates.
    seen: dict[str, int] = {}
    name_map: list[tuple[BoardDef, str]] = [
        (b, unique_name(sanitize_filename(b.name), seen)) for b in boards
    ]

    # ── Generate images ────────────────────────────────────────────────────────
    total = len(name_map)
    succeeded = 0
    failed = 0

    for i, (board_def, base_name) in enumerate(name_map, 1):
        ok, msg = generate_images_for_board(
            board_def, args.output_dir, base_name,
            args.width, args.height, args.formats,
        )
        status = "OK  " if ok else "FAIL"
        print(f"  [{i:3}/{total}] [{status}] {msg}")
        if ok:
            succeeded += 1
        else:
            failed += 1

    pygame.quit()

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\nDone: {succeeded} succeeded, {failed} failed.")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
