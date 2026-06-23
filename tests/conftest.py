"""Shared pytest fixtures and helpers for all test modules."""

import os
import sys
from pathlib import Path

import pytest

# Make the offline sync tooling under scripts/ importable by tests
# (e.g. amaranth_parser, sync_amaranth_boards).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fpga_sim.sim_bridge import _find_ghdl, _NVCBackend  # noqa: E402


@pytest.fixture(scope="session")
def headless_pygame():
    """Initialise pygame once per session with the dummy SDL drivers.

    Centralising init/quit here (rather than per-module) keeps pygame alive
    for the whole session, so the module-global ``get_font`` LRU cache never
    holds ``Font`` objects across a ``pygame.quit()`` / ``init()`` boundary —
    a stale ``Font`` rendered after a re-init segfaults the interpreter.  The
    cache is cleared once, just before the single quit at session end.

    Requested by name from the UI test modules (directly, or via their
    ``screen`` / ``surface`` fixtures); non-UI tests never trigger it, so
    pygame is only imported and initialised when a test actually needs it.
    """
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    pygame.init()
    yield pygame
    from fpga_sim.ui.constants import get_font

    get_font.cache_clear()
    pygame.quit()


def _7seg_board():
    from fpga_sim.board_loader import BoardDef, SevenSegDef

    return BoardDef("DE0", "DE0Platform", seven_seg=SevenSegDef(4, True, False, True, False))


def _plain_board():
    from fpga_sim.board_loader import BoardDef

    return BoardDef("Arty", "ArtyPlatform")


@pytest.fixture(scope="module")
def ghdl():
    """Return the ghdl binary path, or skip if GHDL is not installed."""
    import shutil

    if not shutil.which("ghdl"):
        pytest.skip("GHDL is not installed")
    return _find_ghdl()


@pytest.fixture(scope="module")
def nvc():
    """Return the nvc binary path, or skip if NVC is not installed."""
    if not _NVCBackend.available():
        pytest.skip("NVC is not installed")
    return _NVCBackend.find()
