"""Tests for the BoardStore XML parser (scripts/port_convention_parsers/boardstore_xml.py).

Fixture is a trimmed, real excerpt from a fetch-verified registry source
(docs/port_convention_sources/xilinx-official.toml). Hermetic: no network.
"""

from port_convention_parsers.boardstore_xml import parse
from port_convention_parsers.types import PortTable

# Trimmed from https://raw.githubusercontent.com/Xilinx/XilinxBoardStore/2022.2/
# boards/Xilinx/kc705/1.6/part0_pins.xml (Apache-2.0) -- note the space before
# '=' in `name ="X"`, which is valid, standard XML but would break a naive
# `name="([^"]+)"` regex.
_KC705_EXCERPT = """<?xml version="1.0" encoding="UTF-8" standalone="no" ?>
<part_info part_name="xc7k325tffg900-2">
\t<pins>
\t\t<pin index="0" name ="GPIO_DIP_SW0" iostandard="LVCMOS25" loc="Y29"/>
\t\t<pin index="1" name ="GPIO_DIP_SW1" iostandard="LVCMOS25" loc="W29"/>
\t\t<pin index="28" name ="GPIO_LED_0_LS" iostandard="LVCMOS15" loc="AB8"/>
\t\t<pin index="29" name ="GPIO_LED_1_LS" iostandard="LVCMOS15" loc="AA8"/>
\t</pins>
</part_info>
"""


def test_parse_handles_space_before_equals_quirk() -> None:
    # A regex like `name="([^"]+)"` would silently miss every pin in this
    # file; Element.get() is unaffected since the whitespace is valid XML.
    table = parse(_KC705_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["GPIO_DIP_SW0"] == "Y29"
    assert by_port["GPIO_LED_0_LS"] == "AB8"


def test_parse_extracts_all_pin_elements() -> None:
    table = parse(_KC705_EXCERPT)
    assert len(table.pins) == 4
    assert table.clocks == ()


def test_parse_malformed_xml_returns_empty_table_instead_of_raising() -> None:
    # Every other dialect module degrades gracefully on unparsable input (a
    # regex just matches nothing); ElementTree raises by default, so this
    # module must catch that itself to keep the same contract -- e.g. a
    # truncated download or a redirected error page fetched as "content".
    assert parse("<not-well-formed") == PortTable()
    assert parse("") == PortTable()
