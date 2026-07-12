"""Tests for the PCF parser (scripts/port_convention_parsers/pcf.py).

Fixtures are trimmed, real excerpts from two fetch-verified registry sources
(docs/port_convention_sources/ice40-hobbyist.toml). Hermetic: no network.
"""

from port_convention_parsers.pcf import parse

# Trimmed from https://raw.githubusercontent.com/im-tomu/fomu-workshop/master/pcf/fomu-hacker.pcf
# -- tab-separated pin/comment, role hints in trailing comments.
_FOMU_HACKER_EXCERPT = """
# Configuration for the Fomu hacker board.
set_io rgb0 A5		# Blue LED
set_io rgb1 B5		# Green LED
set_io clki F5		# Clock input from 48MHz Oscillator
"""

# Trimmed from https://raw.githubusercontent.com/icebreaker-fpga/icebreaker-verilog-examples/
# main/icebreaker/icebreaker.pcf -- the optional -nowarn flag, and the board's
# own active-low naming convention: a trailing _N/_n on the port name.
_ICEBREAKER_EXCERPT = """
set_io -nowarn CLK        35
set_io -nowarn BTN_N      10
set_io -nowarn LED_RGB[0] 39
set_io -nowarn LED_RGB[1] 40
set_io -nowarn LED_RGB[2] 41
"""


def test_parse_extracts_pin_ignoring_trailing_comment() -> None:
    table = parse(_FOMU_HACKER_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["rgb0"] == "A5"
    assert by_port["clki"] == "F5"


def test_parse_has_no_clock_metadata() -> None:
    # iCE40 PCF has no frequency statement; clocks is always empty.
    assert parse(_FOMU_HACKER_EXCERPT).clocks == ()


def test_parse_handles_optional_nowarn_flag() -> None:
    table = parse(_ICEBREAKER_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["CLK"] == "35"
    assert by_port["BTN_N"] == "10"
    assert by_port["LED_RGB[0]"] == "39"
