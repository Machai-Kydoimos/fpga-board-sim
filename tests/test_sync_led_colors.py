"""Tests for the cited-color applier (scripts/sync_led_colors.py, U36)."""

import json

import pytest
from led_metadata import ColorBank, load_color_registry
from sync_led_colors import apply_all, stamp_board

_REG = {"custom/x.json": [ColorBank("led", "red", "s")]}
_TWO = {"custom/x.json": [ColorBank("led", "red", "s"), ColorBank("led_g", "green", "s")]}


def test_stamp_canonical_layout_stays_canonical():
    content = json.dumps({"leds": [{"name": "led", "number": 0}]}, indent=2) + "\n"
    out, changed = stamp_board(content, "custom/x.json", _REG)
    assert changed
    assert json.loads(out)["leds"][0]["color"] == "red"
    assert out == json.dumps(json.loads(out), indent=2) + "\n"


def test_stamp_single_line_layout_preserves_format():
    content = (
        "{\n"
        '  "leds": [\n'
        '    { "name": "led", "number": 0, "pins": ["A"] },\n'
        '    { "name": "led_g", "number": 0, "pins": ["B"] }\n'
        "  ]\n"
        "}\n"
    )
    out, changed = stamp_board(content, "custom/x.json", _TWO)
    assert changed
    # color inserted right after the name; "led" never bleeds into "led_g"
    assert '{ "name": "led", "color": "red", "number": 0, "pins": ["A"] }' in out
    assert '{ "name": "led_g", "color": "green", "number": 0, "pins": ["B"] }' in out
    # one component per line preserved (not canonicalized)
    assert out.count("\n") == content.count("\n")


def test_stamp_is_idempotent():
    content = json.dumps({"leds": [{"name": "led"}]}, indent=2) + "\n"
    once, _ = stamp_board(content, "custom/x.json", _REG)
    twice, changed = stamp_board(once, "custom/x.json", _REG)
    assert twice == once
    assert changed is False


def test_stamp_unrecognized_layout_raises():
    """A layout that is neither canonical nor one-object-per-line fails loudly."""
    content = '{"leds":[{"name":"led"}]}'  # compact, no per-object lines
    with pytest.raises(ValueError, match="unrecognized format"):
        stamp_board(content, "custom/x.json", _REG)


def test_committed_boards_match_registry():
    """Every board on disk already carries exactly the colors the registry cites.

    Guards against registry/board drift: editing the registry (or a board's
    LEDs) without re-running the applier makes this fail.
    """
    assert apply_all(load_color_registry(), write=False) == []
