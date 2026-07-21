"""Unit tests for the shared LED-name -> color heuristic (scripts/led_metadata.py, U36)."""

import pytest
from led_metadata import color_from_name


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
