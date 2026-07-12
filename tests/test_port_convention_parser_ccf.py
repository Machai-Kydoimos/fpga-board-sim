"""Tests for the GateMate CCF parser (scripts/port_convention_parsers/ccf.py).

Fixture combines two real ``Net`` lines fetched from a registry source
(docs/port_convention_sources/intel-gatemate-misc.toml) with one ``Pin_in``
line built from that same file's own format-and-keyword documentation (its
header comment spells out the ``Pin_in``/``Pin_out``/``Pin_inout`` directional
forms and the ``SCHMITT_TRIGGER``/``PULLUP``/``PULLDOWN`` pipe-attribute
keywords; the fetched example board just never happens to use them). Hermetic:
no network.
"""

from port_convention_parsers.ccf import parse

# First two lines fetched verbatim from https://raw.githubusercontent.com/
# chili-chips-ba/openCologne/main/1.Blinky--Verilog-VHDL-Python.Amaranth/
# 3.build/GateMateA1-EVB.ccf; the Pin_in line follows that file's own
# format comment ("<pin-direction> "<pin-name>" Loc = "<pin-location>" |
# <opt.-constraints>;") and documented constraint keywords.
_GATEMATE_EXCERPT = """
Net "FPGA_LED" Loc = "IO_SB_B6"; # FPGA LED
Net "JTAG_LED" Loc = "IO_SB_B5"; # GPIO25
Pin_in "USER_BTN" Loc = "IO_SA_A0" | SCHMITT_TRIGGER=true | PULLUP=true;
"""


def test_parse_extracts_net_form() -> None:
    table = parse(_GATEMATE_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["FPGA_LED"] == "IO_SB_B6"
    assert by_port["JTAG_LED"] == "IO_SB_B5"


def test_parse_extracts_directional_pin_form_with_attributes() -> None:
    table = parse(_GATEMATE_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["USER_BTN"] == "IO_SA_A0"


def test_parse_has_no_clock_metadata() -> None:
    # No FREQUENCY/PERIOD-style statement was found in any fetched GateMate file.
    assert parse(_GATEMATE_EXCERPT).clocks == ()
