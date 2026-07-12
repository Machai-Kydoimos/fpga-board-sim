"""Tests for the LPF parser (scripts/port_convention_parsers/lpf.py).

Fixture is a trimmed, real excerpt from a fetch-verified registry source
(docs/port_convention_sources/ulx3s-openhw.toml). Hermetic: no network.
"""

from port_convention_parsers.lpf import parse

# Trimmed from https://raw.githubusercontent.com/emard/ulx3s/master/doc/constraints/ulx3s_v20.lpf
# -- LOCATE COMP/SITE pin binding, the companion IOBUF PORT attribute line
# (no site, so nothing to extract), and the FREQUENCY PORT clock statement.
_ULX3S_EXCERPT = """
LOCATE COMP "clk_25mhz" SITE "G2";
IOBUF PORT "clk_25mhz" IO_TYPE=LVCMOS33;
FREQUENCY PORT "clk_25mhz" 25 MHZ;

LOCATE COMP "led[0]" SITE "B2";
LOCATE COMP "led[1]" SITE "C2";
IOBUF PORT "led[0]" IO_TYPE=LVCMOS25;

LOCATE COMP "btn[0]" SITE "D6";  # BTN_PWRn (inverted logic)
"""


def test_parse_extracts_locate_comp_pin() -> None:
    table = parse(_ULX3S_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["clk_25mhz"] == "G2"
    assert by_port["led[0]"] == "B2"
    assert by_port["led[1]"] == "C2"
    assert by_port["btn[0]"] == "D6"


def test_parse_ignores_iobuf_port_attribute_lines() -> None:
    # IOBUF PORT lines carry no SITE/pin and must not be mistaken for one.
    table = parse(_ULX3S_EXCERPT)
    assert len(table.pins) == 4


def test_parse_frequency_port_gives_clock_hz() -> None:
    table = parse(_ULX3S_EXCERPT)
    assert len(table.clocks) == 1
    assert table.clocks[0].port == "clk_25mhz"
    assert table.clocks[0].frequency_hz == 25e6
