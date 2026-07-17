"""fpga_sim.ui package — all pygame UI classes for the FPGA Board Simulator.

Import from here for public API access:
    from fpga_sim.ui import FPGABoard, BoardSelector, VHDLFilePicker, ErrorDialog
    from fpga_sim.ui import UIComponent, FPGAChip, LED, SevenSeg, Switch, Button
    from fpga_sim.ui import SimPanel, HelpDialog, SpinnerOverlay, run_with_spinner
"""

from fpga_sim.ui.board_display import FPGABoard
from fpga_sim.ui.board_selector import BoardSelector
from fpga_sim.ui.components import LED, Button, FPGAChip, SevenSeg, Switch, UIComponent
from fpga_sim.ui.error_dialog import ErrorDialog
from fpga_sim.ui.help_dialog import HelpDialog
from fpga_sim.ui.results import DialogResult, ScreenResult, SimExit
from fpga_sim.ui.settings_dialog import SettingsDialog
from fpga_sim.ui.sim_panel import SimPanel
from fpga_sim.ui.sim_toolbar import SimToolbar

# simulation_screen imports several of the submodules above directly (not this
# package), so it composes cleanly regardless of position here (U34).
from fpga_sim.ui.simulation_screen import RunStats, SimulationScreen
from fpga_sim.ui.spinner import SpinnerOverlay, run_with_spinner
from fpga_sim.ui.tooltip import Tooltip
from fpga_sim.ui.vhdl_picker import VHDLFilePicker

__all__ = [
    "UIComponent",
    "FPGAChip",
    "LED",
    "SevenSeg",
    "Switch",
    "Button",
    "BoardSelector",
    "FPGABoard",
    "VHDLFilePicker",
    "ErrorDialog",
    "HelpDialog",
    "SettingsDialog",
    "ScreenResult",
    "DialogResult",
    "SimExit",
    "SimPanel",
    "SimToolbar",
    "SimulationScreen",
    "RunStats",
    "SpinnerOverlay",
    "run_with_spinner",
    "Tooltip",
]
