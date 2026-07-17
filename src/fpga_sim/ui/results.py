"""Typed screen-transition results.

These small enums replace the stringly-typed return values of the launcher
screens' ``run()`` methods. The ``ScreenController`` in ``fpga_sim.controller``
(extracted in D6b) dispatches on enum members that mypy can check, instead of
bare strings that drift silently when a branch is renamed.

Plain ``Enum`` (not ``StrEnum``, which is 3.11+) is used because these values
are purely internal control-flow signals — they are never serialized to the
session config or crossed over the simulation subprocess boundary.
"""

from enum import Enum, auto


class ScreenResult(Enum):
    """Outcome of the board-preview screen (``FPGABoard.run``)."""

    BACK = auto()  # ESC / [Select Board] — return to the board selector
    LOAD_VHDL = auto()  # [Load VHDL File] — open the picker, then re-enter preview
    SIMULATE = auto()  # [Start Simulation] / Enter — launch (VHDL must be set)
    QUIT = auto()  # window closed — exit the application


class DialogResult(Enum):
    """Outcome of the modal :class:`~fpga_sim.ui.error_dialog.ErrorDialog`."""

    RETRY = auto()  # [Try Another File] / Enter — retry the failed operation
    BACK = auto()  # [Back to Boards] / ESC / window closed — abandon and return


class SimExit(Enum):
    """Why the interactive simulation ended — the U7 navigation contract.

    Returned by :meth:`~fpga_sim.ui.simulation_screen.SimulationScreen.run`; the
    controller routes on the member to the selector / picker / a relaunch / an
    app-quit, so the simulator child never touches launcher state.  The string
    values are human-readable labels (shown in the end-of-run console line); they
    are not serialized or crossed over the process boundary.
    """

    STOPPED = "stopped"  # ESC / [■ Stop] — return to the board preview
    BACK_TO_BOARDS = "back_to_boards"  # [Back to Boards] → board selector
    CHANGE_VHDL = "change_vhdl"  # [Change VHDL] → VHDL file picker
    RELOAD_VHDL = "reload_vhdl"  # [Reload VHDL] → re-analyze same file, relaunch
    QUIT = "quit"  # window X (single-window, U34) → exit the whole app
