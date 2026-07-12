"""Tests for the XDC parser (scripts/port_convention_parsers/xdc.py).

Fixtures are trimmed, real excerpts from two fetch-verified registry sources
(docs/port_convention_sources/digilent.toml, maker-xilinx.toml). The full
Basys3 master XDC (same family as the first fixture here) is exercised
end-to-end in test_port_convention_parsers_golden.py. Hermetic: no network.
"""

from port_convention_parsers.xdc import parse

# Trimmed from Digilent's published Basys-3-Master.xdc (commit 00a3404, see
# boards/digilent-xdc/basys_3.json's source block). Digilent's master files
# comment out every line with a leading '#' -- the user uncomments what they
# need. Also covers the non-braced scalar get_ports form (clk) alongside the
# braced vector form (sw[N]).
_BASYS3_EXCERPT = """
## Clock signal
#set_property -dict { PACKAGE_PIN W5   IOSTANDARD LVCMOS33 } [get_ports clk]
#create_clock -add -name sys_clk_pin -period 10.00 -waveform {0 5} [get_ports clk]

## Switches
#set_property -dict { PACKAGE_PIN V17   IOSTANDARD LVCMOS33 } [get_ports {sw[0]}]
#set_property -dict { PACKAGE_PIN V16   IOSTANDARD LVCMOS33 } [get_ports {sw[1]}]
"""

# Trimmed from https://raw.githubusercontent.com/numato/Mimas-A7/main/MimasA7_TopModule/
# MimasA7_TopModule.srcs/constrs_1/new/MimasA7TopModule.xdc -- the PACKAGE_PIN
# value is quoted here ("H4") but bare a few lines later (N3), in the same file.
_MIMAS_A7_EXCERPT = """
set_property -dict { PACKAGE_PIN "H4"    IOSTANDARD LVCMOS33  } [get_ports { Clk }]     ;                # Sch = CLK1
set_property -dict { PACKAGE_PIN N3    IOSTANDARD LVCMOS33 } [get_ports { Enable[0] }];
set_property -dict { PACKAGE_PIN R1    IOSTANDARD LVCMOS33 } [get_ports { Enable[1] }];
"""


def test_parse_handles_commented_master_file_lines() -> None:
    # Every real line is prefixed '#'; search()-based matching must still find them.
    table = parse(_BASYS3_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["clk"] == "W5"
    assert by_port["sw[0]"] == "V17"
    assert by_port["sw[1]"] == "V16"


def test_parse_bracketed_port_name_is_not_truncated() -> None:
    # Regression: a naive non-greedy port capture can stop at the port's own
    # ']' instead of the surrounding get_ports ']', truncating "sw[0]" to "sw[0".
    table = parse(_BASYS3_EXCERPT)
    ports = {p.port for p in table.pins}
    assert "sw[0]" in ports
    assert "sw[0" not in ports


def test_parse_create_clock_period_converts_to_hz() -> None:
    table = parse(_BASYS3_EXCERPT)
    assert len(table.clocks) == 1
    assert table.clocks[0].port == "clk"
    assert table.clocks[0].frequency_hz == 100e6  # 1e9 / 10.00 ns


def test_parse_handles_quoted_and_bare_package_pin_in_same_file() -> None:
    table = parse(_MIMAS_A7_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["Clk"] == "H4"  # quoted in the source
    assert by_port["Enable[0]"] == "N3"  # bare in the source
    assert by_port["Enable[1]"] == "R1"
