"""fpga_sim.ui package — all pygame UI classes for the FPGA Board Simulator.

Import from here for public API access:
    from fpga_sim.ui import FPGABoard, BoardSelector, VHDLFilePicker, ErrorDialog
    from fpga_sim.ui import FPGAChip, LED, SevenSeg, Switch, Button
    from fpga_sim.ui import SimPanel
"""

from fpga_sim.ui.board_display import FPGABoard
from fpga_sim.ui.board_selector import BoardSelector
from fpga_sim.ui.components import LED, Button, FPGAChip, SevenSeg, Switch
from fpga_sim.ui.error_dialog import ErrorDialog
from fpga_sim.ui.sim_panel import SimPanel
from fpga_sim.ui.vhdl_picker import VHDLFilePicker

__all__ = [
    "FPGAChip",
    "LED",
    "SevenSeg",
    "Switch",
    "Button",
    "BoardSelector",
    "FPGABoard",
    "VHDLFilePicker",
    "ErrorDialog",
    "SimPanel",
]
