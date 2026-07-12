"""Tests for the QSF parser (scripts/port_convention_parsers/qsf.py).

Fixtures are trimmed, real excerpts from two fetch-verified registry sources
(docs/port_convention_sources/terasic.toml): a community course file that
renames Terasic's canonical LEDR to LED (the "course files may rename ports"
gotcha), and a clean file with canonical names plus the DEVICE line gotcha.
Hermetic: no network.
"""

from port_convention_parsers.qsf import parse

# Trimmed from https://raw.githubusercontent.com/AllenHeartcore/ECE385_UIUC23sp/main/de10_pin_assignment.qsf
# (DE10-Lite course material) -- note LEDR renamed to plain LED; no DEVICE line.
_DE10_LITE_COURSE = """
set_location_assignment PIN_P11 -to Clk
set_location_assignment PIN_B8  -to KEY[0]
set_location_assignment PIN_A7  -to KEY[1]
set_location_assignment PIN_C10 -to SW[0]
set_location_assignment PIN_C11 -to SW[1]
set_location_assignment PIN_A8  -to LED[0]
set_location_assignment PIN_A9  -to LED[1]
set_location_assignment PIN_C14 -to HEX0[0]
set_location_assignment PIN_E15 -to HEX0[1]
"""

# Trimmed from https://raw.githubusercontent.com/norxander/DE1-SoC-HPSFPGA/master/DE1_SoC.qsf
# -- canonical LEDR/KEY names, plus the DEVICE vs DEVICE_FILTER_PACKAGE gotcha:
# a naive substring match on "DEVICE" would misfire on the second line too.
_DE1_SOC_CLEAN = """
set_global_assignment -name DEVICE 5CSEMA5F31C6
set_global_assignment -name DEVICE_FILTER_PACKAGE FBGA
set_location_assignment PIN_AA14 -to KEY[0]
set_location_assignment PIN_AA15 -to KEY[1]
set_location_assignment PIN_V16 -to LEDR[0]
set_location_assignment PIN_W16 -to LEDR[1]
"""


def test_parse_extracts_pin_and_port() -> None:
    table = parse(_DE10_LITE_COURSE)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["Clk"] == "P11"
    assert by_port["KEY[0]"] == "B8"
    assert by_port["LED[0]"] == "A8"
    assert by_port["HEX0[1]"] == "E15"


def test_parse_has_no_clock_metadata() -> None:
    # QSF states no frequency (that lives in a separate .sdc); clocks is always empty.
    assert parse(_DE10_LITE_COURSE).clocks == ()


def test_parse_ignores_device_assignment_lines() -> None:
    table = parse(_DE1_SOC_CLEAN)
    ports = {p.port for p in table.pins}
    assert "5CSEMA5F31C6" not in ports
    assert "FBGA" not in ports
    assert {"KEY[0]", "KEY[1]", "LEDR[0]", "LEDR[1]"} <= ports
