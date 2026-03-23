"""ui package — all pygame UI classes for the FPGA Board Simulator.

Import from here for public API access:
    from ui import FPGABoard, BoardSelector, VHDLFilePicker, ErrorDialog
    from ui import FPGAChip, LED, Switch, Button
    from ui import SimPanel
"""

from ui.board_selector import BoardSelector
from ui.components import LED, Button, FPGAChip, Switch
from ui.error_dialog import ErrorDialog
from ui.fpga_board import FPGABoard
from ui.sim_panel import SimPanel
from ui.vhdl_picker import VHDLFilePicker

__all__ = [
    "FPGAChip", "LED", "Switch", "Button",
    "BoardSelector", "FPGABoard", "VHDLFilePicker", "ErrorDialog",
    "SimPanel",
]
