"""Tests for the UCF parser (scripts/port_convention_parsers/ucf.py).

Fixtures are trimmed, real excerpts from three fetch-verified registry
sources (docs/port_convention_sources/maker-xilinx.toml, cn-xilinx-misc.toml),
plus one hand-authored line for the classic XST/ISE angle-bracket vector
convention (well documented, but not present in any of this arc's fetched
files, so it is not claimed as a live fetch). Hermetic: no network.
"""

from port_convention_parsers.ucf import parse

# Trimmed from https://raw.githubusercontent.com/Saanlima/Pipistrello/master/
# Projects/Oberon_lpddr/src/Pipistrello.ucf -- covers: a bracketed vector name,
# a parenthesized vector name, PULLUP/PULLDOWN and other pipe-separated
# attributes trailing the LOC clause, and a scalar's LOC on its own line
# (separate from an earlier IOSTANDARD-only line for the same net).
_PIPISTRELLO_EXCERPT = """
NET "sys_clk" IOSTANDARD = LVCMOS33;
NET "sys_clk" LOC = "H17";
NET "SWITCH" LOC = "N14" | IOSTANDARD = LVCMOS33 | PULLDOWN ;
NET "MOSI[0]" LOC = "B3" | IOSTANDARD = LVCMOS33;
NET "PS2C" LOC = "D8" | IOSTANDARD = LVCMOS33 | PULLUP;
NET "TMDS(0)"  	LOC = "T6" | IOSTANDARD = TMDS_33 ; # Blue
"""

# Classic Xilinx ISE/XST-generated UCF vector convention (angle brackets);
# not from a fresh fetch this arc, included because the plan's dialect table
# names it explicitly and the syntax is otherwise untested here.
_ANGLE_BRACKET_VECTOR = 'NET "led<0>" LOC = "U16" | IOSTANDARD = LVCMOS33;\n'

# Trimmed from https://raw.githubusercontent.com/q3k/chubby75/master/rv901t/blink/rv901t.ucf
# -- unquoted, unspaced LOC value, plus the TIMESPEC/PERIOD clock-frequency statement.
_RV901T_EXCERPT = """
NET "clk25" LOC = M9 | IOSTANDARD = LVCMOS33;
TIMESPEC TS_CLK = PERIOD "clk25" 25 MHz HIGH 50%;
NET "user_led" LOC=F7 | IOSTANDARD = LVCMOS33;
"""

# Trimmed from https://raw.githubusercontent.com/ChinaQMTECH/QM_XC7A100T_WUKONG_BOARD/
# master/V3/Software/XC7A100T/DDR3.ucf -- pure DDR3 pinout, nothing LED/switch/
# button/clock-shaped; stresses the exclude side of classify's interest filter.
_QMTECH_DDR3_EXCERPT = """
NET   "ddr3_addr[0]"                           LOC = "E17"   |     IOSTANDARD = SSTL135              ;
NET   "ddr3_ba[0]"                             LOC = "B17"   |     IOSTANDARD = SSTL135              ;
NET   "ddr3_cas_n"                             LOC = "B19"   |     IOSTANDARD = SSTL135              ;
NET   "ddr3_ck_n[0]"                           LOC = "F19"   |     IOSTANDARD = DIFF_SSTL135         ;
"""


def test_parse_extracts_quoted_and_bare_pin_values() -> None:
    table = parse(_PIPISTRELLO_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["sys_clk"] == "H17"
    assert by_port["SWITCH"] == "N14"


def test_parse_bracket_and_paren_vector_names() -> None:
    table = parse(_PIPISTRELLO_EXCERPT)
    ports = {p.port for p in table.pins}
    assert "MOSI[0]" in ports
    assert "TMDS(0)" in ports


def test_parse_angle_bracket_vector_name() -> None:
    table = parse(_ANGLE_BRACKET_VECTOR)
    assert len(table.pins) == 1
    assert table.pins[0].port == "led<0>"
    assert table.pins[0].pin == "U16"


def test_parse_ignores_iostandard_only_line_without_loc() -> None:
    # The first "sys_clk" line has no LOC at all; only the second should match.
    table = parse(_PIPISTRELLO_EXCERPT)
    assert sum(1 for p in table.pins if p.port == "sys_clk") == 1


def test_parse_unquoted_unspaced_loc_value() -> None:
    table = parse(_RV901T_EXCERPT)
    by_port = {p.port: p.pin for p in table.pins}
    assert by_port["clk25"] == "M9"
    assert by_port["user_led"] == "F7"


def test_parse_timespec_period_gives_clock_frequency() -> None:
    table = parse(_RV901T_EXCERPT)
    assert len(table.clocks) == 1
    assert table.clocks[0].port == "clk25"
    assert table.clocks[0].frequency_hz == 25e6


def test_parse_ddr3_pinout_yields_no_clock_metadata() -> None:
    table = parse(_QMTECH_DDR3_EXCERPT)
    assert len(table.pins) == 4
    assert table.clocks == ()
