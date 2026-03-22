"""Tests for BoardDef JSON serialization round-trip."""
import json

import pytest

from board_loader import BoardDef, ComponentInfo


@pytest.fixture(scope="module")
def test_board():
    return BoardDef(
        name="RoundTrip",
        class_name="RTP",
        vendor="Xilinx",
        device="xc7a35ti",
        package="csg324",
        clocks=[100e6],
        default_clock_hz=100e6,
        leds=[ComponentInfo("led", "led", 0, pins=["P1"], attrs={"IO": "LVCMOS"})],
        buttons=[ComponentInfo("button", "button_up", 0, pins=["B1"],
                               connector=("pmod", 0))],
        switches=[ComponentInfo("switch", "switch", 0, pins=["S1"])],
    )


@pytest.fixture(scope="module")
def serialized(test_board):
    return test_board.to_json()


@pytest.fixture(scope="module")
def parsed(serialized):
    return json.loads(serialized)


def test_serialize_returns_string(serialized):
    assert isinstance(serialized, str) and len(serialized) > 10


def test_json_has_name(parsed):
    assert parsed["name"] == "RoundTrip"


def test_json_has_vendor(parsed):
    assert parsed["vendor"] == "Xilinx"


def test_json_has_device(parsed):
    assert parsed["device"] == "xc7a35ti"


def test_json_has_clocks(parsed):
    assert parsed["clocks"] == [100e6]


def test_json_has_default_clock_hz(parsed):
    assert parsed["default_clock_hz"] == 100e6


def test_json_has_led_pin(parsed):
    assert parsed["leds"][0]["pins"] == ["P1"]


def test_json_has_connector(parsed):
    assert parsed["buttons"][0]["connector"] == ["pmod", 0]


@pytest.fixture(scope="module")
def round_tripped(serialized):
    return BoardDef.from_json(serialized)


def test_roundtrip_name(round_tripped):
    assert round_tripped.name == "RoundTrip"


def test_roundtrip_vendor(round_tripped):
    assert round_tripped.vendor == "Xilinx"


def test_roundtrip_device(round_tripped):
    assert round_tripped.device == "xc7a35ti"


def test_roundtrip_clocks(round_tripped):
    assert round_tripped.clocks == [100e6]


def test_roundtrip_default_clock_hz(round_tripped):
    assert round_tripped.default_clock_hz == 100e6


def test_roundtrip_led_pin(round_tripped):
    assert round_tripped.leds[0].pins == ["P1"]


def test_roundtrip_btn_connector(round_tripped):
    assert round_tripped.buttons[0].connector == ("pmod", 0)
