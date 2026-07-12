"""Tests for the Gowin CST parser (scripts/port_convention_parsers/cst.py).

Fixture is a trimmed, real excerpt from a fetch-verified registry source
(docs/port_convention_sources/gowin.toml). Hermetic: no network.
"""

from port_convention_parsers.cst import parse

# Trimmed from https://raw.githubusercontent.com/sipeed/TangNano-9K-example/
# master/led/src/9K_LED_project.cst -- IO_LOC/IO_PORT split (IO_PORT carries
# no location), and bare-number pin IDs (Gowin has no ball/site letters).
_TANGNANO9K_EXCERPT = """
IO_LOC "led[5]" 16;
IO_PORT "led[5]" PULL_MODE=UP DRIVE=8;
IO_LOC "led[0]" 10;
IO_PORT "led[0]" PULL_MODE=UP DRIVE=8;
IO_LOC "sys_clk" 52;
IO_PORT "sys_clk" IO_TYPE=LVCMOS33 PULL_MODE=UP;
"""


def test_parse_extracts_numeric_pin_id() -> None:
    table = parse(_TANGNANO9K_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["led[5]"] == "16"
    assert by_port["led[0]"] == "10"
    assert by_port["sys_clk"] == "52"


def test_parse_ignores_io_port_attribute_lines() -> None:
    # IO_PORT lines carry no location and must not be mistaken for a pin.
    table = parse(_TANGNANO9K_EXCERPT)
    assert len(table.pins) == 3
    assert table.clocks == ()
