"""Tests for __main__._initial_window_size (U5 window-size restore)."""

from __future__ import annotations

from fpga_sim.__main__ import _initial_window_size

_DESKTOP = (1920, 1080)
# The pre-U5 default calculation for that desktop: 80% capped to 1600x1000.
_DEFAULT = (1536, 864)


def test_saved_size_is_restored():
    assert _initial_window_size({"window_w": 1280, "window_h": 800}, _DESKTOP) == (1280, 800)


def test_saved_size_clamped_to_desktop():
    assert _initial_window_size({"window_w": 5000, "window_h": 4000}, _DESKTOP) == _DESKTOP


def test_no_saved_size_uses_default_calc():
    assert _initial_window_size({}, _DESKTOP) == _DEFAULT


def test_too_small_saved_size_falls_back():
    assert _initial_window_size({"window_w": 320, "window_h": 200}, _DESKTOP) == _DEFAULT


def test_junk_saved_size_falls_back():
    assert _initial_window_size({"window_w": "wide", "window_h": None}, _DESKTOP) == _DEFAULT


def test_default_calc_floors_small_desktop():
    # An 800x600 desktop still gets the 1024x700 minimum window.
    assert _initial_window_size({}, (800, 600)) == (1024, 700)


def test_float_saved_size_is_accepted():
    # JSON numbers may round-trip as floats; int() them.
    assert _initial_window_size({"window_w": 1280.0, "window_h": 800.0}, _DESKTOP) == (1280, 800)
