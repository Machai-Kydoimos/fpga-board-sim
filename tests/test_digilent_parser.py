"""Tests for the Digilent XDC parser (scripts/digilent_parser.py).

Hermetic: exercises parse_xdc() / build_board_json() with inline XDC text, no network.
"""

from digilent_parser import build_board_json, parse_xdc

_XDC = """
## Clock signal
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { clk }];
create_clock -add -name sys_clk_pin -waveform {0.000 5.000} -period 10.00 [get_ports { clk }];

## LEDs
set_property -dict { PACKAGE_PIN H5 IOSTANDARD LVCMOS33 } [get_ports { led[0] }];
set_property -dict { PACKAGE_PIN J5 IOSTANDARD LVCMOS33 } [get_ports { led[1] }];
set_property -dict { PACKAGE_PIN T9 IOSTANDARD LVCMOS33 } [get_ports { led[2] }];

## Switches
set_property -dict { PACKAGE_PIN A8 IOSTANDARD LVCMOS33 } [get_ports { sw[0] }];
set_property -dict { PACKAGE_PIN C11 IOSTANDARD LVCMOS33 } [get_ports { sw[1] }];

## Buttons
set_property -dict { PACKAGE_PIN U18 IOSTANDARD LVCMOS33 } [get_ports { btn[0] }];
"""

_XDC_NO_RES = """
## Clock signal
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { clk }];
"""


def test_parse_xdc_groups_pins_by_section():
    parsed = parse_xdc(_XDC)
    pins = parsed["pins"]
    assert len(pins["led"]) == 3
    assert len(pins["switch"]) == 2
    assert len(pins["button"]) == 1
    assert parsed["clock_period_ns"] == 10.0


def test_parse_xdc_captures_pin_and_iostandard():
    pins = parse_xdc(_XDC)["pins"]
    led0 = pins["led"][0]
    assert led0["pin"] == "H5"
    assert led0["iostandard"] == "LVCMOS33"


def test_build_board_json_counts_and_clock():
    board = build_board_json(_XDC, "Test-Master.xdc", "deadbeef")
    assert board is not None
    assert board["name"] == "Test"
    assert board["vendor"] == "Xilinx"
    assert len(board["leds"]) == 3
    assert len(board["switches"]) == 2
    assert len(board["buttons"]) == 1
    assert board["default_clock_hz"] == 100e6  # 1e9 / 10 ns
    assert board["source"]["sync_commit"] == "deadbeef"


def test_build_board_json_emits_port_conventions():
    board = build_board_json(_XDC, "Test-Master.xdc", "sha")
    assert board is not None
    assert "port_conventions" in board
    conv = board["port_conventions"]["digilent"]
    assert conv["leds"]["name"] == "led"
    assert conv["leds"]["width"] == 3


def test_build_board_json_no_resources_returns_none():
    assert build_board_json(_XDC_NO_RES, "Bare-Master.xdc", "sha") is None
