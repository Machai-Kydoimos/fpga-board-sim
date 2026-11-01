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


# ── orphan fields (U56 plan §4.3) ──────────────────────────────────────────────


def test_a_board_upstream_still_defines_serializes_without_a_source_block(serialized):
    assert "source" not in json.loads(serialized)


def test_orphan_fields_are_read_from_the_board_files_source_block():
    raw = json.dumps(
        {
            "name": "Efinix T8",
            "class_name": "EfinixT8F81DevKitPlatform",
            "source": {
                "origin": "litex-boards",
                "upstream_file": "efinix_t8f81_dev_kit.py",
                "upstream_status": "orphaned",
                "orphaned_at_commit": "c705606",
                "orphaned_reason": "file_removed",
                "successor": "litex-boards/efinix_trion_t8f81_dev_kit.json",
            },
        }
    )
    board = BoardDef.from_json(raw)
    assert board.upstream_status == "orphaned"
    assert board.orphaned_at_commit == "c705606"
    assert board.orphaned_reason == "file_removed"
    assert board.successor == "litex-boards/efinix_trion_t8f81_dev_kit.json"


def test_orphan_fields_survive_a_roundtrip_and_nothing_else_rides_along():
    board = BoardDef(
        name="O",
        class_name="OP",
        upstream_status="orphaned",
        orphaned_at_commit="abc",
        orphaned_reason="no_longer_defined",
    )
    data = json.loads(board.to_json())
    # Only the orphan fields travel: identity and stamps belong to the file, not the child.
    assert data["source"] == {
        "upstream_status": "orphaned",
        "orphaned_at_commit": "abc",
        "orphaned_reason": "no_longer_defined",
    }
    again = BoardDef.from_json(board.to_json())
    assert (again.upstream_status, again.orphaned_at_commit, again.orphaned_reason) == (
        "orphaned",
        "abc",
        "no_longer_defined",
    )
    assert again.successor == ""


def test_identity_fields_in_a_source_block_do_not_disturb_loading():
    raw = json.dumps(
        {
            "name": "W",
            "class_name": "WP",
            "source": {
                "origin": "litex-boards",
                "upstream_file": "qmtech_wukong.py",
                "upstream_class": "Platform",
                "upstream_args": {"revision": 2},
            },
        }
    )
    board = BoardDef.from_json(raw)
    assert board.upstream_status == ""
    assert "source" not in json.loads(board.to_json())


# ── An assumed default clock (U56 D-6) ────────────────────────────────────────


def test_an_assumed_clock_is_read_and_survives_a_roundtrip():
    raw = json.dumps({"name": "Z", "class_name": "ZedBoard", "default_clock_assumed": True})
    board = BoardDef.from_json(raw)
    assert board.default_clock_assumed is True
    assert BoardDef.from_json(board.to_json()).default_clock_assumed is True


def test_a_stated_clock_serializes_exactly_as_before():
    """The field rides only when set, like an LED's color."""
    data = json.loads(BoardDef(name="A", class_name="AP").to_json())
    assert "default_clock_assumed" not in data
    assert BoardDef.from_json(json.dumps(data)).default_clock_assumed is False
