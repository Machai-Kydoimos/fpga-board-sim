"""
ui package — all pygame UI classes for the FPGA Board Simulator.

Import from here for public API access:
    from ui import FPGABoard, BoardSelector, VHDLFilePicker, ErrorDialog
    from ui import FPGAChip, LED, Switch, Button
"""

from ui.components import FPGAChip, LED, Switch, Button
from ui.board_selector import BoardSelector
from ui.fpga_board import FPGABoard
from ui.vhdl_picker import VHDLFilePicker
from ui.error_dialog import ErrorDialog

__all__ = [
    "FPGAChip", "LED", "Switch", "Button",
    "BoardSelector", "FPGABoard", "VHDLFilePicker", "ErrorDialog",
]
