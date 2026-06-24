r"""Render a static screenshot of the board-selector screen for the README.

A maintainer / documentation tool (sibling to ``capture_demo.py`` and
``src/fpga_sim/generate_board_images.py``): it renders the board-selector
launcher screen headlessly and saves it as a PNG.  No simulator is required.

Examples
--------
Regenerate the README catalogue screenshot::

    uv run python scripts/capture_screenshot.py

"""

from __future__ import annotations

import argparse
from pathlib import Path

import pygame

from fpga_sim.board_loader import discover_boards, get_default_boards_path
from fpga_sim.ui import BoardSelector

_ROOT = Path(__file__).resolve().parent.parent


def _parse_args() -> argparse.Namespace:
    """Parse command-line options for the screenshot run."""
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "docs" / "assets" / "board_selector.png",
        help="output PNG path",
    )
    p.add_argument("--width", type=int, default=1000, help="screen width in px")
    p.add_argument("--height", type=int, default=720, help="screen height in px")
    return p.parse_args()


def main() -> None:
    """Render the board selector headlessly and save it as a PNG."""
    args = _parse_args()
    # pygame reads SDL_VIDEODRIVER at init time, so setting it here (before
    # pygame.init) is sufficient to render off-screen with no window.
    import os

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    pygame.init()
    screen = pygame.display.set_mode((args.width, args.height))
    boards = discover_boards(get_default_boards_path())
    selector = BoardSelector(boards, screen)
    selector._draw()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(screen, str(args.out))
    pygame.quit()
    print(f"Wrote {args.out} ({len(boards)} boards)")


if __name__ == "__main__":
    main()
