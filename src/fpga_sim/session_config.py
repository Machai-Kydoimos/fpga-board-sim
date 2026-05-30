"""session_config.py - Lightweight session persistence for the FPGA simulator.

Saves and restores the last-used board, VHDL file path, and simulator
so the user doesn't have to re-navigate on every launch.

Session file: ~/.fpga_simulator/session.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from fpga_sim.sim_bridge import Simulator

SESSION_FILE = Path.home() / ".fpga_simulator" / "session.json"


def load_session() -> dict[str, Any]:
    """Load the saved session.

    Returns a dict with keys 'board_class', 'vhdl_path', and 'simulator',
    or an empty dict if the file is missing or corrupt.  Never raises.
    """
    try:
        return cast(dict[str, Any], json.loads(SESSION_FILE.read_text()))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def save_session(
    board_class: str,
    vhdl_path: str,
    simulator: Simulator = "ghdl",
    board_source: str = "",
    board_sort: str = "",
    component_filters: list[str] | None = None,
    vendor_filters: list[str] | None = None,
) -> None:
    """Persist the board class name, VHDL file path, simulator, and filter state.

    Creates ~/.fpga_simulator/ if it does not exist.
    Silently ignores write failures (read-only filesystem, etc.).
    """
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(
            json.dumps(
                {
                    "board_class": board_class,
                    "board_source": board_source,
                    "vhdl_path": vhdl_path,
                    "simulator": simulator,
                    "board_sort": board_sort,
                    "component_filters": component_filters or [],
                    "vendor_filters": vendor_filters or [],
                },
                indent=2,
            )
        )
    except OSError:
        pass
