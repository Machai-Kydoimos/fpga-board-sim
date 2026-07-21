"""Unit tests for the shared LED color helpers (scripts/led_metadata.py, U36)."""

import json

import pytest
from led_metadata import (
    ColorBank,
    apply_registry_colors,
    color_from_name,
    colorize_content,
    load_color_registry,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        # single-letter color suffixes -- the forms that actually occur upstream
        ("led_r", "red"),
        ("led_g", "green"),
        ("led_b", "blue"),
        ("led_o", "orange"),
        # the active-low marker `_n` is ignored, never read as a color
        ("led_g_n", "green"),
        ("led_r_n", "red"),
        ("led_n", ""),
        # spelled-out colors (future sources)
        ("led_red", "red"),
        ("led_white", "white"),
        ("led_yellow", "yellow"),
        ("led_amber", "amber"),
        # names that encode no color
        ("led", ""),
        ("rgb_led", ""),
        ("user_led", ""),
        ("power_led", ""),
        ("disk_led", ""),
        ("m2led", ""),
        ("alnum_led", ""),
        ("sfp_led", ""),
        ("gpio_leds", ""),
        ("led_frontpanel", ""),
        # case-insensitive
        ("LED_R", "red"),
        ("Led_Green", "green"),
    ],
)
def test_color_from_name(name, expected):
    assert color_from_name(name) == expected


def test_result_is_a_schema_color_or_empty():
    """Every result is either "" or one of the schema's named colors."""
    valid = {"red", "green", "blue", "yellow", "orange", "amber", "white", ""}
    for n in ("led_r", "led_g", "led_b", "led_o", "led_amber", "led", "foo", "user_led"):
        assert color_from_name(n) in valid


# ═══════════════════════════════════════════════════════════════════════
#  Cited color registry
# ═══════════════════════════════════════════════════════════════════════

_SCHEMA_COLORS = {"red", "green", "blue", "yellow", "orange", "amber", "white"}


def _registry(tmp_path, toml_text):
    (tmp_path / "fam.toml").write_text(toml_text, encoding="utf-8")
    return load_color_registry(tmp_path)


def test_load_color_registry_parses(tmp_path):
    reg = _registry(
        tmp_path,
        '[[board]]\nname = "X"\nfiles = ["custom/x.json", "litex-boards/x.json"]\n'
        '  [[board.bank]]\n  match = "led"\n  color = "red"\n  source = "X Manual: red LEDs"\n',
    )
    bank = ColorBank(match="led", color="red", source="X Manual: red LEDs")
    assert reg == {"custom/x.json": [bank], "litex-boards/x.json": [bank]}


_MISSING_CITATION = """
[[board]]
name = "X"
files = ["a.json"]
  [[board.bank]]
  match = "led"
  color = "red"
  source = " "
"""
_EMPTY_MATCH = """
[[board]]
name = "X"
files = ["a.json"]
  [[board.bank]]
  match = ""
  color = "red"
  source = "s"
"""
_BAD_COLOR = """
[[board]]
name = "X"
files = ["a.json"]
  [[board.bank]]
  match = "led"
  color = "reddish"
  source = "s"
"""
_NO_BANKS = """
[[board]]
name = "X"
files = ["a.json"]
"""
_NO_FILES = """
[[board]]
name = "X"
  [[board.bank]]
  match = "led"
  color = "red"
  source = "s"
"""


@pytest.mark.parametrize(
    ("toml_text", "match_msg"),
    [
        (_MISSING_CITATION, "source"),  # verify-or-omit
        (_EMPTY_MATCH, "match"),
        (_BAD_COLOR, "color"),
        (_NO_BANKS, "bank"),
        (_NO_FILES, "files"),
    ],
)
def test_load_color_registry_rejects_malformed(tmp_path, toml_text, match_msg):
    with pytest.raises(ValueError, match=match_msg):
        _registry(tmp_path, toml_text)


def test_load_color_registry_accepts_hex_color(tmp_path):
    reg = _registry(
        tmp_path,
        '[[board]]\nname="X"\nfiles=["a.json"]\n[[board.bank]]\n'
        'match="led"\ncolor="#ff8800"\nsource="s"\n',
    )
    assert reg["a.json"][0].color == "#ff8800"


def test_apply_registry_colors_stamps_by_bank():
    reg = {"f.json": [ColorBank("led", "red", "s"), ColorBank("led_g", "green", "s")]}
    board = {"leds": [{"name": "led"}, {"name": "led"}, {"name": "led_g"}, {"name": "other"}]}
    assert apply_registry_colors(board, "f.json", reg) is True
    assert [led.get("color", "") for led in board["leds"]] == ["red", "red", "green", ""]


def test_apply_registry_colors_overrides_name_heuristic():
    """A cited registry color outranks a name-inferred one."""
    reg = {"f.json": [ColorBank("led", "blue", "s")]}
    board = {"leds": [{"name": "led", "color": "red"}]}
    assert apply_registry_colors(board, "f.json", reg) is True
    assert board["leds"][0]["color"] == "blue"


def test_apply_registry_colors_noop_without_entry():
    board = {"leds": [{"name": "led"}]}
    assert apply_registry_colors(board, "f.json", {}) is False
    assert "color" not in board["leds"][0]


def test_colorize_content_reapplies_on_canonical_board():
    reg = {"custom/x.json": [ColorBank("led", "red", "s")]}
    stripped = json.dumps({"leds": [{"name": "led", "number": 0}]}, indent=2) + "\n"
    out = colorize_content(stripped, "custom/x.json", reg)
    assert json.loads(out)["leds"][0]["color"] == "red"
    # idempotent, and byte-identical when there is nothing to do
    assert colorize_content(out, "custom/x.json", reg) == out
    assert colorize_content(stripped, "not-in-registry.json", reg) == stripped


def test_real_registry_loads_and_is_cited():
    """The shipped registry parses (so every entry is cited + schema-valid)."""
    reg = load_color_registry()
    assert reg, "the on-disk LED color registry should not be empty"
    for banks in reg.values():
        for bank in banks:
            assert bank.source.strip()
            assert bank.color in _SCHEMA_COLORS or bank.color.startswith("#")
