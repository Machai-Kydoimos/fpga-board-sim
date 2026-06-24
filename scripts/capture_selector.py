r"""Render an animated GIF of the board selector's faceted filtering for the README.

A maintainer / documentation tool (sibling to ``capture_demo.py`` and
``src/fpga_sim/generate_board_images.py``): it renders the board-selector screen
headlessly while a faux cursor clicks filter chips one at a time — exactly as a
user would — so the board count and list visibly narrow. No simulator is required.

Examples
--------
Regenerate the README catalogue GIF::

    uv run python scripts/capture_selector.py

"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import pygame
from capture_common import assemble_gif, draw_cursor

from fpga_sim.board_loader import discover_boards, get_default_boards_path
from fpga_sim.ui import BoardSelector

_ROOT = Path(__file__).resolve().parent.parent

# (filter kind, chip key) clicked in order, one at a time.
_STEPS = [
    ("component", "has_leds"),
    ("component", "has_switches"),
    ("component", "has_buttons"),
    ("component", "has_7seg"),
    ("vendor", "Intel"),
]


def _parse_args() -> argparse.Namespace:
    """Parse command-line options for the selector capture."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "docs" / "assets" / "board_selector.gif",
        help="output GIF",
    )
    p.add_argument("--width", type=int, default=900, help="screen width in px")
    p.add_argument("--height", type=int, default=680, help="screen height in px")
    p.add_argument("--colors", type=int, default=128, help="GIF palette size")
    return p.parse_args()


def main() -> None:
    """Render the selector while a cursor clicks filter chips; save an animated GIF."""
    args = _parse_args()
    # pygame reads SDL_VIDEODRIVER at init time, so setting it here (before
    # pygame.init) is enough to render off-screen with no window.
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    screen = pygame.display.set_mode((args.width, args.height))
    boards = discover_boards(get_default_boards_path())
    selector = BoardSelector(boards, screen)
    selector._draw()  # populate chip rects
    rects = {key: rect for rect, _kind, key in selector._chip_rects}

    frames_dir = tempfile.mkdtemp(prefix="capture_selector_")
    frame_paths: list[str] = []
    durations: list[int] = []
    cursor = [args.width * 0.5, args.height * 0.52]

    def snap(duration_ms: int, *, pressed: bool = False) -> None:
        selector._draw()
        draw_cursor(screen, (cursor[0], cursor[1]), pressed=pressed)
        path = f"{frames_dir}/frame_{len(frame_paths):04d}.png"
        pygame.image.save(screen, path)
        frame_paths.append(path)
        durations.append(duration_ms)

    snap(900)  # initial: all 278 boards, no filters active
    for kind, key in _STEPS:
        target = rects[key].center
        for _ in range(6):  # ease the cursor onto the chip
            cursor[0] += (target[0] - cursor[0]) * 0.45
            cursor[1] += (target[1] - cursor[1]) * 0.45
            snap(40)
        cursor[0], cursor[1] = float(target[0]), float(target[1])
        selector._hovered_chip = key
        snap(130, pressed=True)  # press lands...
        selector._hovered_chip = None
        if kind == "component":  # ...and the list + count update on the click
            selector._component_filters.add(key)
        else:
            selector._vendor_filters.add(key)
        snap(150, pressed=True)
        snap(780)  # settle on the filtered result
    durations[-1] = 1700  # hold the final, fully filtered list a little longer

    assemble_gif(frame_paths, args.out, durations=durations, colors=args.colors)
    pygame.quit()
    size_kib = args.out.stat().st_size // 1024
    print(f"Wrote {args.out} ({len(frame_paths)} frames, {size_kib} KiB)")


if __name__ == "__main__":
    main()
