"""Shared pytest fixtures and helpers for all test modules."""

import pytest

from fpga_sim.sim_bridge import _find_ghdl, _NVCBackend


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
