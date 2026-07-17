"""Tests for the SimExit navigation enum (U7), now living in ``fpga_sim.ui.results``.

The exit-intent *file* channel is gone with the legacy window path (U34): the
single-window :class:`~fpga_sim.ui.simulation_screen.SimulationScreen` returns a
``SimExit`` from ``run()`` directly, so nothing is serialized.  This pins the
enum's shape and its new location; the routing on each member is covered in
``test_controller.py``.
"""

from __future__ import annotations

from fpga_sim.ui import SimExit
from fpga_sim.ui.results import SimExit as SimExitFromResults


def test_simexit_lives_in_results_and_is_reexported_from_ui():
    assert SimExit is SimExitFromResults


def test_simexit_has_the_navigation_members():
    assert {e.name for e in SimExit} == {
        "STOPPED",
        "BACK_TO_BOARDS",
        "CHANGE_VHDL",
        "RELOAD_VHDL",
        "QUIT",
    }


def test_simexit_values_are_stable_labels():
    assert SimExit.STOPPED.value == "stopped"
    assert SimExit.QUIT.value == "quit"
