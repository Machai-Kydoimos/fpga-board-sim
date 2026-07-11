"""session_config.py - Lightweight session persistence for the FPGA simulator.

Saves and restores the launcher and simulation preferences so the user
doesn't have to re-navigate on every launch.

Session file: ~/.fpga_simulator/session.json

Schema (every key is optional; readers fall back to defaults):

- ``board_class`` / ``board_source`` — last board (selector preselection)
- ``vhdl_path`` — last VHDL file (also seeds the picker start directory)
- ``simulator`` — ``"ghdl"`` or ``"nvc"``
- ``board_sort`` / ``component_filters`` / ``vendor_filters`` — selector prefs
- ``window_w`` / ``window_h`` — launcher window size, restored at startup
- ``speed_factor`` — sim speed multiplier (the sim subprocess writes the
  slider's final value at exit; the launcher passes it back in at launch)
- ``theme`` — UI theme name (the Settings dialog writes and applies it; the
  launcher restores it at startup and forwards it to the sim subprocess)
- ``metrics_enabled`` — reserved for the Settings metrics toggle that U19 adds
- ``waveform`` — ``"off"`` / ``"vcd"`` / ``"fst"``: native simulator waveform
  capture; the Settings dialog's Waveform row writes it and the launcher passes
  it to the sim run subprocess (U10)
- ``waveform_open`` — ``true`` / ``false``: after a capture run, launch a viewer
  on the dump (the Settings dialog's Auto-open row writes it; the launcher passes
  it to the sim run subprocess) (U29)
- ``recent`` — the last :data:`RECENT_MAX` (board, VHDL) picks, newest first,
  as ``{"board_class", "board_source", "vhdl_path"}`` dicts (U18 surfaces
  them in the file picker)

Writers **merge** into the existing file (read-modify-write) so each writer
only touches the keys it owns: the sim subprocess persists ``speed_factor``
without clobbering the launcher's fields, and vice versa.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fpga_sim.sim_bridge import Simulator

SESSION_FILE = Path.home() / ".fpga_simulator" / "session.json"

#: Maximum number of entries kept in the ``recent`` list.
RECENT_MAX = 10


def load_session() -> dict[str, Any]:
    """Load the saved session.

    Returns the persisted dict (see the module docstring for the keys), or an
    empty dict if the file is missing, corrupt, or not a JSON object.  Never
    raises.
    """
    try:
        data = json.loads(SESSION_FILE.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def update_session(**fields: object) -> None:
    """Merge *fields* into the session file, preserving all other keys.

    Creates ~/.fpga_simulator/ if it does not exist.  Silently ignores write
    failures (read-only filesystem, etc.).
    """
    try:
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = load_session()
        data.update(fields)
        SESSION_FILE.write_text(json.dumps(data, indent=2))
    except OSError:
        pass


def save_session(
    board_class: str,
    vhdl_path: str,
    simulator: Simulator = "ghdl",
    board_source: str = "",
    board_sort: str = "",
    component_filters: list[str] | None = None,
    vendor_filters: list[str] | None = None,
    *,
    window_size: tuple[int, int] | None = None,
) -> None:
    """Persist the launcher state: board, VHDL file, simulator, and prefs.

    *window_size* is stored as ``window_w`` / ``window_h`` when given and left
    untouched when ``None``.  Keys owned by other writers (``speed_factor``,
    ``theme``, ``recent``, …) always survive — this is a merge, not a rewrite.
    """
    fields: dict[str, Any] = {
        "board_class": board_class,
        "board_source": board_source,
        "vhdl_path": vhdl_path,
        "simulator": simulator,
        "board_sort": board_sort,
        "component_filters": component_filters or [],
        "vendor_filters": vendor_filters or [],
    }
    if window_size is not None:
        fields["window_w"], fields["window_h"] = window_size
    update_session(**fields)


def push_recent(board_class: str, board_source: str, vhdl_path: str) -> None:
    """Prepend a (board, VHDL) pair to ``recent``, newest first.

    An existing entry for the same (*board_class*, *vhdl_path*) pair moves to
    the front instead of duplicating; the list is capped at
    :data:`RECENT_MAX`.  Malformed entries (from a hand-edited file) are
    dropped.
    """
    raw = load_session().get("recent", [])
    entries = raw if isinstance(raw, list) else []
    kept = [
        e
        for e in entries
        if isinstance(e, dict)
        and not (e.get("board_class") == board_class and e.get("vhdl_path") == vhdl_path)
    ]
    entry = {"board_class": board_class, "board_source": board_source, "vhdl_path": vhdl_path}
    update_session(recent=[entry, *kept][:RECENT_MAX])
