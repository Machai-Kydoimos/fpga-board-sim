"""Tests for the Digilent XDC parser (scripts/digilent_parser.py).

Hermetic: exercises parse_xdc() / build_board_json() with inline XDC text, no network.
"""

from digilent_parser import _build_rgb_convention, _classify_section, build_board_json, parse_xdc

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


def test_classify_section_clock_frequency_and_system_headers():
    # Digilent varies its clock section titles; all of these name the fabric clock.
    assert _classify_section("Clock signal") == "clock"
    assert _classify_section("100MHz Clock") == "clock"
    assert _classify_section("12 MHz System Clock") == "clock"
    assert _classify_section("PL System Clock") == "clock"
    # A fabric clock that merely sources from a peripheral is still a clock.
    assert _classify_section("125MHz Clock from Ethernet PHY") == "clock"


def test_classify_section_rejects_non_fabric_clocks():
    # Prose mentions lack a frequency / system / signal qualifier.
    assert _classify_section("Note: QSPI clock can only be accessed via STARTUPE2") is None
    assert _classify_section("GTH reference clock jitter filter auxiliary") is None
    # An FMC mezzanine transceiver clock carries a frequency but belongs to the
    # mezzanine card, not the FPGA fabric, so it must not be classified as one.
    assert _classify_section("FMC Transceiver clocks (currently set to 156.25 MHz)") is None


def test_classify_section_led_word_boundary():
    assert _classify_section("LEDs") == "led"
    assert _classify_section("4 LEDs") == "led"
    # RGB rule wins over the plain-LED rule.
    assert _classify_section("RGB LEDs") == "rgb_led"
    # The word boundary keeps substring matches out.
    assert _classify_section("OLED Display") is None
    assert _classify_section("Bank = 15, Sch name = LED16_G") is None


_XDC_FREQ_CLOCK = """
## 100MHz Clock
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { clk }];
create_clock -add -name sys_clk_pin -waveform {0.000 5.000} -period 10.00 [get_ports { clk }];

## 4 LEDs
set_property -dict { PACKAGE_PIN A1 IOSTANDARD LVCMOS33 } [get_ports { led[0] }];
set_property -dict { PACKAGE_PIN A2 IOSTANDARD LVCMOS33 } [get_ports { led[1] }];
"""


def test_build_board_json_frequency_clock_and_bare_led_header():
    # A frequency-only clock header and an "N LEDs" header (neither matched by
    # the old exact-string rules) now yield a populated clk + leds convention.
    board = build_board_json(_XDC_FREQ_CLOCK, "Freq-Master.xdc", "sha")
    assert board is not None
    assert board["clocks"] and board["clocks"][0]["name"] == "clk"
    assert board["default_clock_hz"] == 100e6
    conv = board["port_conventions"]["digilent"]
    assert conv["clk"] == "clk"
    assert conv["leds"] == {"name": "led", "width": 2}


# ── RGB channels in a mono "## LEDs" section (U37, Nexys 4 shape) ─────────────

_XDC_MIXED_LEDS = """
## Clock signal
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { clk }];
create_clock -add -name sys_clk_pin -waveform {0.000 5.000} -period 10.00 [get_ports { clk }];

## LEDs
set_property -dict { PACKAGE_PIN H5 IOSTANDARD LVCMOS33 } [get_ports { led[0] }];
set_property -dict { PACKAGE_PIN J5 IOSTANDARD LVCMOS33 } [get_ports { led[1] }];
set_property -dict { PACKAGE_PIN K5 IOSTANDARD LVCMOS33 } [get_ports { led16_r }];
set_property -dict { PACKAGE_PIN F13 IOSTANDARD LVCMOS33 } [get_ports { led16_g }];
set_property -dict { PACKAGE_PIN F6 IOSTANDARD LVCMOS33 } [get_ports { led16_b }];
set_property -dict { PACKAGE_PIN K6 IOSTANDARD LVCMOS33 } [get_ports { led17_r }];
set_property -dict { PACKAGE_PIN H6 IOSTANDARD LVCMOS33 } [get_ports { led17_g }];
set_property -dict { PACKAGE_PIN L16 IOSTANDARD LVCMOS33 } [get_ports { led17_b }];
"""


def test_rgb_channels_in_mono_section_become_rgb_led_components():
    """The Nexys 4 shape: LED16_R..LED17_B share the mono "## LEDs" section but
    must come out as 3-pin rgb_led components, not six flat mono entries."""
    board = build_board_json(_XDC_MIXED_LEDS, "Mixed-Master.xdc", "sha")
    assert board is not None
    leds = board["leds"]
    assert [(c["name"], len(c["pins"])) for c in leds] == [
        ("led", 1),
        ("led", 1),
        ("rgb_led", 3),
        ("rgb_led", 3),
    ]
    # r/g/b pin order and per-site grouping both preserved.
    assert leds[2]["pins"] == ["K5", "F13", "F6"]
    assert leds[3]["pins"] == ["K6", "H6", "L16"]
    assert leds[2]["number"] == 16 and leds[3]["number"] == 17
    # Mono entries stay bare and uncolored (registry's job, not the name's).
    assert "color" not in leds[0]


def test_rgb_name_family_of_the_original_nexys4_is_recognized():
    """The original Nexys 4 names its channels RGB1_Red..RGB2_Blue (old-style
    commented XDC); they must group exactly like the led16_r family."""
    xdc = """
## Clock signal
#set_property PACKAGE_PIN E3 [get_ports clk]
create_clock -add -name sys_clk_pin -waveform {0.000 5.000} -period 10.00 [get_ports { clk }];

## LEDs
#set_property PACKAGE_PIN H5 [get_ports {led[0]}]
#set_property PACKAGE_PIN K5 [get_ports RGB1_Red]
#set_property PACKAGE_PIN F13 [get_ports RGB1_Green]
#set_property PACKAGE_PIN F6 [get_ports RGB1_Blue]
#set_property PACKAGE_PIN K6 [get_ports RGB2_Red]
#set_property PACKAGE_PIN H6 [get_ports RGB2_Green]
#set_property PACKAGE_PIN L16 [get_ports RGB2_Blue]
"""
    board = build_board_json(xdc, "Old-Master.xdc", "sha")
    assert board is not None
    leds = board["leds"]
    assert [(c["name"], len(c["pins"])) for c in leds] == [
        ("led", 1),
        ("rgb_led", 3),
        ("rgb_led", 3),
    ]
    assert leds[1]["pins"] == ["K5", "F13", "F6"]  # r, g, b
    assert leds[2]["pins"] == ["K6", "H6", "L16"]


def test_plain_indexed_leds_never_match_the_rgb_pattern():
    """A bare led[n] bank must be untouched by the U37 rerouting."""
    board = build_board_json(_XDC, "Test-Master.xdc", "sha")
    assert board is not None
    assert all(c["name"] == "led" and len(c["pins"]) == 1 for c in board["leds"])


# ── U38: leds_rgb convention bank + named-button conventions ──────────────────

# Arty shape: separate "## RGB LEDs" section, channels listed b/g/r per site
# (the real Arty-Master.xdc's alphabetical order) — the bank must come out r/g/b.
_XDC_ARTY_SHAPE = """
## Clock signal
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { CLK100MHZ }];
create_clock -add -name sys_clk_pin -waveform {0.000 5.000} -period 10.00 [get_ports { CLK100MHZ }];

## LEDs
set_property -dict { PACKAGE_PIN H5 IOSTANDARD LVCMOS33 } [get_ports { led[0] }];
set_property -dict { PACKAGE_PIN J5 IOSTANDARD LVCMOS33 } [get_ports { led[1] }];

## RGB LEDs
set_property -dict { PACKAGE_PIN E1 IOSTANDARD LVCMOS33 } [get_ports { led0_b }];
set_property -dict { PACKAGE_PIN F6 IOSTANDARD LVCMOS33 } [get_ports { led0_g }];
set_property -dict { PACKAGE_PIN G6 IOSTANDARD LVCMOS33 } [get_ports { led0_r }];
set_property -dict { PACKAGE_PIN G4 IOSTANDARD LVCMOS33 } [get_ports { led1_b }];
set_property -dict { PACKAGE_PIN J4 IOSTANDARD LVCMOS33 } [get_ports { led1_g }];
set_property -dict { PACKAGE_PIN G3 IOSTANDARD LVCMOS33 } [get_ports { led1_r }];
"""


def test_leds_rgb_convention_for_a_cited_board():
    """A board with cited RGB polarity gets a leds_rgb scalar bank: names in
    (r,g,b) order per site regardless of XDC listing order, mono width RGB-free."""
    board = build_board_json(_XDC_ARTY_SHAPE, "Arty-Master.xdc", "sha")
    assert board is not None
    conv = board["port_conventions"]["digilent"]
    assert conv["leds"] == {"name": "led", "width": 2}
    assert conv["leds_rgb"] == {
        "names": ["led0_r", "led0_g", "led0_b", "led1_r", "led1_g", "led1_b"],
        "active_low": False,
    }


def test_leds_rgb_omitted_without_cited_polarity():
    """Verify-or-omit: an uncited board key builds the rgb_led components but
    no leds_rgb bank (the convention would have to guess a polarity)."""
    board = build_board_json(_XDC_ARTY_SHAPE, "Test-Master.xdc", "sha")
    assert board is not None
    assert sum(c["name"] == "rgb_led" for c in board["leds"]) == 2
    assert "leds_rgb" not in board["port_conventions"]["digilent"]


def test_nexys_mixed_section_conv_counts_only_mono_leds():
    """The pre-U38 bug: RGB channel scalars leaked into the mono leds width
    (Nexys family claimed width 22, rejecting a correct native LED[15:0])."""
    board = build_board_json(_XDC_MIXED_LEDS, "Mixed-Master.xdc", "sha")
    assert board is not None
    assert board["port_conventions"]["digilent"]["leds"] == {"name": "led", "width": 2}


def test_rgb_convention_helper_covers_both_name_families_and_partial_sites():
    """RGB1_Red-style ports group like led16_r-style; an incomplete site (no
    channel block on the boundary) is skipped rather than half-emitted."""
    entries = [
        {"port": "RGB1_Blue"},
        {"port": "RGB1_Green"},
        {"port": "RGB1_Red"},
        {"port": "RGB2_Red"},  # partial site: no green/blue
    ]
    conv = _build_rgb_convention(entries, "Arty")  # any cited key
    assert conv == {"names": ["RGB1_Red", "RGB1_Green", "RGB1_Blue"], "active_low": False}
    assert _build_rgb_convention(entries, "Uncited-Board") is None


_XDC_NAMED_BUTTONS = """
## Clock signal
set_property -dict { PACKAGE_PIN E3 IOSTANDARD LVCMOS33 } [get_ports { clk }];
create_clock -add -name sys_clk_pin -waveform {0.000 5.000} -period 10.00 [get_ports { clk }];

## LEDs
set_property -dict { PACKAGE_PIN H5 IOSTANDARD LVCMOS33 } [get_ports { led[0] }];

## Buttons
set_property -dict { PACKAGE_PIN C12 IOSTANDARD LVCMOS33 } [get_ports { btnCpuReset }];
set_property -dict { PACKAGE_PIN N17 IOSTANDARD LVCMOS33 } [get_ports { btnC }];
set_property -dict { PACKAGE_PIN M18 IOSTANDARD LVCMOS33 } [get_ports { btnU }];
set_property -dict { PACKAGE_PIN P17 IOSTANDARD LVCMOS33 } [get_ports { btnL }];
set_property -dict { PACKAGE_PIN M17 IOSTANDARD LVCMOS33 } [get_ports { btnR }];
set_property -dict { PACKAGE_PIN P18 IOSTANDARD LVCMOS33 } [get_ports { btnD }];
"""


def test_named_buttons_components_and_convention():
    """Directionals take slots 0-4 (boundary bits btn(0..4)); the reset gets its
    own name, sorts last, and is marked inverted (it pulls low when pressed).
    The convention maps only the directionals: one bank, one polarity."""
    board = build_board_json(_XDC_NAMED_BUTTONS, "Nexys-4-DDR-Master.xdc", "sha")
    assert board is not None
    assert [(b["name"], b["number"], b["inverted"]) for b in board["buttons"]] == [
        ("button_center", 0, False),
        ("button_up", 1, False),
        ("button_down", 2, False),
        ("button_left", 3, False),
        ("button_right", 4, False),
        ("button_reset", 5, True),
    ]
    conv = board["port_conventions"]["digilent"]
    assert conv["buttons"] == {
        "names": ["btnC", "btnU", "btnD", "btnL", "btnR"],
        "active_low": False,
    }
