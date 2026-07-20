"""Shared pytest fixtures and helpers for all test modules."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from multiprocessing.connection import Connection
    from types import ModuleType

    from fpga_sim.board_loader import BoardDef
    from fpga_sim.sim_bridge import SimChild

# Make the offline sync tooling under scripts/ importable by tests
# (e.g. amaranth_parser, sync_amaranth_boards).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fpga_sim.sim_bridge import _find_ghdl, _NVCBackend  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_waveform_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep run-shaping ``FPGA_SIM_*`` vars from a developer's shell out of every test.

    ``start_simulation`` and the waveform helpers read these; a value exported
    in the dev/CI shell would silently flip capture, auto-open, the output dir,
    or (``FPGA_SIM_DUTY``) whether the generated wrapper measures duty cycles at
    all.  Tests that exercise a var set it explicitly via the same
    (function-scoped) monkeypatch, which runs after this and wins.
    """
    for var in (
        "FPGA_SIM_WAVEFORM",
        "FPGA_SIM_WAVEFORM_OPEN",
        "FPGA_SIM_WAVEFORM_MEMORIES",
        "FPGA_SIM_WAVEFORM_VIEWER",
        "FPGA_SIM_WAVEFORM_DIR",
        "FPGA_SIM_DUTY",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="session")
def headless_pygame() -> Iterator[ModuleType]:
    """Initialize pygame once per session with the dummy SDL drivers.

    Centralising init/quit here (rather than per-module) keeps pygame alive
    for the whole session, so the module-global ``get_font`` LRU cache never
    holds ``Font`` objects across a ``pygame.quit()`` / ``init()`` boundary —
    a stale ``Font`` rendered after a re-init segfaults the interpreter.  The
    cache is cleared once, just before the single quit at session end.

    Requested by name from the UI test modules (directly, or via their
    ``screen`` / ``surface`` fixtures); non-UI tests never trigger it, so
    pygame is only imported and initialized when a test actually needs it.
    """
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import pygame

    pygame.init()
    yield pygame
    from fpga_sim.ui.constants import get_font

    get_font.cache_clear()
    pygame.quit()


class _FakeProc:
    """Minimal stand-in for a running Popen: alive until told to stop."""

    def __init__(self) -> None:
        self.running = True
        self.stderr = None

    def poll(self) -> int | None:
        return None if self.running else 0

    def wait(self, timeout: float | None = None) -> int:
        self.running = False
        return 0

    def terminate(self) -> None:
        self.running = False

    def kill(self) -> None:
        self.running = False


@pytest.fixture
def fake_child(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[SimChild, Connection]]:
    """A ``SimChild`` whose link is connected to an in-process client "child".

    Lets the U34 single-window screen tests exercise the real message plumbing
    (a real ``SimLinkHost``, real serialization) with no simulator subprocess.
    Shared here rather than in one test module so the brightness tests can drive
    the same screen without rebuilding the harness.
    """
    import subprocess
    from collections import deque
    from typing import cast

    from fpga_sim import sim_link
    from fpga_sim.sim_bridge import SimChild
    from fpga_sim.sim_link import connect_from_env

    host = sim_link.SimLinkHost()
    for key, value in host.env_vars().items():
        monkeypatch.setenv(key, value)
    client = connect_from_env()
    assert host.wait_connected(2.0)
    child = SimChild(
        proc=cast("subprocess.Popen[bytes]", _FakeProc()),
        link=host,
        wave_cfg=None,
        generics={},
        match=None,
        stderr_tail=deque(),
    )
    try:
        yield child, client
    finally:
        client.close()
        host.close()


@pytest.fixture
def restore_theme() -> Iterator[None]:
    """Reset the shared THEME to the default after a test that switches themes.

    Any test that calls ``set_theme`` (directly or through the Settings
    dialog) must request this fixture, or it would leak the alternate palette
    into later tests that read ``THEME``.
    """
    from fpga_sim.ui.theme import set_theme

    yield
    set_theme("pcb-green")


def _7seg_board() -> BoardDef:
    from fpga_sim.board_loader import BoardDef, SevenSegDef

    return BoardDef("DE0", "DE0Platform", seven_seg=SevenSegDef(4, True, False, True, False))


def _plain_board() -> BoardDef:
    from fpga_sim.board_loader import BoardDef

    return BoardDef("Arty", "ArtyPlatform")


@pytest.fixture(scope="module")
def ghdl() -> str:
    """Return the ghdl binary path, or skip if GHDL is not installed."""
    import shutil

    if not shutil.which("ghdl"):
        pytest.skip("GHDL is not installed")
    return _find_ghdl()


@pytest.fixture(scope="module")
def nvc() -> str:
    """Return the nvc binary path, or skip if NVC is not installed."""
    if not _NVCBackend.available():
        pytest.skip("NVC is not installed")
    return _NVCBackend.find()
