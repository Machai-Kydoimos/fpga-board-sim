"""Tests for BoardDef JSON serialization round-trip."""

import json

import pytest

from fpga_sim.board_loader import BoardDef, ComponentInfo


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
        buttons=[ComponentInfo("button", "button_up", 0, pins=["B1"], connector=("pmod", 0))],
        switches=[ComponentInfo("switch", "switch", 0, pins=["S1"])],
        port_conventions={
            "terasic": {
                "clk": "CLOCK_50",
                "leds": {"name": "LEDR", "width": 1},
                "naming": "canonical",
            }
        },
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


def test_json_has_port_conventions(parsed):
    assert parsed["port_conventions"]["terasic"]["clk"] == "CLOCK_50"
    assert parsed["port_conventions"]["terasic"]["leds"] == {"name": "LEDR", "width": 1}


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


def test_roundtrip_port_conventions(round_tripped):
    # U21 B1: conventions survive the to_json -> from_json round-trip verbatim
    # (the same trip the launcher -> subprocess handoff makes via FPGA_SIM_BOARD_JSON).
    assert round_tripped.port_conventions == {
        "terasic": {
            "clk": "CLOCK_50",
            "leds": {"name": "LEDR", "width": 1},
            "naming": "canonical",
        }
    }


def test_board_without_conventions_roundtrips_to_empty_mapping():
    # A board that declares no conventions gets an empty mapping, not None --
    # both freshly constructed and after a serialization round-trip.
    board = BoardDef(name="Bare", class_name="Bare")
    assert board.port_conventions == {}
    assert BoardDef.from_json(board.to_json()).port_conventions == {}


def test_from_json_treats_null_port_conventions_as_empty():
    # An explicit "port_conventions": null on disk must not become None.
    raw = json.dumps({"name": "N", "class_name": "N", "port_conventions": None})
    assert BoardDef.from_json(raw).port_conventions == {}


# ── LED color round-trip (U36) ────────────────────────────────────────────────


def test_color_emitted_only_when_set():
    # Set -> present; unset -> the key is absent (not "", which the schema rejects)
    # so a colorless board's JSON stays byte-identical to pre-U36.
    board = BoardDef(
        name="C",
        class_name="C",
        leds=[
            ComponentInfo("led", "led_r", 0, pins=["A1"], color="red"),
            ComponentInfo("led", "led", 1, pins=["A2"]),
        ],
    )
    data = json.loads(board.to_json())
    assert data["leds"][0]["color"] == "red"
    assert "color" not in data["leds"][1]


def test_color_survives_roundtrip():
    led = ComponentInfo("led", "led_g", 0, color="green")
    board = BoardDef(name="C", class_name="C", leds=[led])
    assert BoardDef.from_json(board.to_json()).leds[0].color == "green"


def test_missing_color_defaults_to_empty_string():
    raw = json.dumps({"name": "N", "class_name": "N", "leds": [{"name": "led", "number": 0}]})
    assert BoardDef.from_json(raw).leds[0].color == ""
