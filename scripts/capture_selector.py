r"""Render an animated GIF of the board selector's faceted filtering for the README.

A maintainer / documentation tool (sibling to ``capture_demo.py`` and
``src/fpga_sim/generate_board_images.py``): it renders the board-selector screen
headlessly while toggling filter chips one at a time — exactly as a user would —
so the board count and list visibly narrow. No simulator is required.

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
from capture_common import assemble_gif

from fpga_sim.board_loader import discover_boards, get_default_boards_path
from fpga_sim.ui import BoardSelector

_ROOT = Path(__file__).resolve().parent.parent

# (filter kind, chip key) applied in order, one "click" each.
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
    p.add_argument("--width", type=int, default=1000, help="screen width in px")
    p.add_argument("--height", type=int, default=720, help="screen height in px")
    p.add_argument("--colors", type=int, default=128, help="GIF palette size")
    return p.parse_args()


def main() -> None:
    """Render the selector while toggling filter chips and save an animated GIF."""
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

    frames_dir = tempfile.mkdtemp(prefix="capture_selector_")
    frame_paths: list[str] = []
    durations: list[int] = []

    def snap(duration_ms: int) -> None:
        selector._draw()
        path = f"{frames_dir}/frame_{len(frame_paths):04d}.png"
        pygame.image.save(screen, path)
        frame_paths.append(path)
        durations.append(duration_ms)

    snap(1100)  # initial: all 278 boards, no filters active
    for kind, key in _STEPS:
        selector._hovered_chip = key  # highlight the chip under the cursor...
        snap(170)
        selector._hovered_chip = None
        if kind == "component":  # ...then "click" it: the list + count update
            selector._component_filters.add(key)
        else:
            selector._vendor_filters.add(key)
        snap(1000)
    durations[-1] = 1800  # hold the final, fully filtered list a little longer

    assemble_gif(frame_paths, args.out, durations=durations, colors=args.colors)
    pygame.quit()
    size_kib = args.out.stat().st_size // 1024
    print(f"Wrote {args.out} ({len(frame_paths)} frames, {size_kib} KiB)")


if __name__ == "__main__":
    main()
