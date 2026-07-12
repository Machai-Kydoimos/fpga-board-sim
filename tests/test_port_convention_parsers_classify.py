"""Tests for the dialect-agnostic classifier (scripts/port_convention_parsers/classify.py).

Builds PortTable/PinEntry values directly (not via any dialect's parse())
so these tests exercise classify()'s name-shape rules in isolation. Real
board names are used as the fixtures' vocabulary (cited per case) even
though the tables themselves are hand-built. Hermetic: no network.
"""

from port_convention_parsers.classify import classify
from port_convention_parsers.types import ClockConstraint, PinEntry, PortTable


def _table(names_and_pins: dict[str, str], clocks: tuple[ClockConstraint, ...] = ()) -> PortTable:
    return PortTable(
        pins=tuple(PinEntry(port=n, pin=p) for n, p in names_and_pins.items()),
        clocks=clocks,
    )


def test_duplicate_constraint_line_does_not_inflate_named_button_width() -> None:
    # A stray repeated line for the same port (copy-paste in the source file)
    # must not count as a sixth button.
    table = PortTable(
        pins=(
            PinEntry("btnC", "U18"),
            PinEntry("btnC", "U18"),  # accidental duplicate
            PinEntry("btnU", "T18"),
            PinEntry("btnD", "U17"),
            PinEntry("btnL", "W19"),
            PinEntry("btnR", "T17"),
        )
    )
    assert classify(table)["buttons"] == {"name": "btn", "width": 5}


def test_bracket_vector_width_is_max_index_plus_one() -> None:
    table = _table({f"led[{i}]": f"P{i}" for i in range(16)} | {"sw[0]": "P16"})
    result = classify(table)
    assert result["leds"] == {"name": "led", "width": 16}
    assert result["switches"] == {"name": "sw", "width": 1}


def test_leds_green_is_detected_separately_from_primary_leds() -> None:
    # Real DE2-115 shape: LEDR[0..17] (primary) + LEDG[0..8] (secondary bank).
    names = {f"LEDR[{i}]": f"R{i}" for i in range(18)} | {f"LEDG[{i}]": f"G{i}" for i in range(9)}
    result = classify(_table(names))
    assert result["leds"] == {"name": "LEDR", "width": 18}
    assert result["leds_green"] == {"name": "LEDG", "width": 9}


def test_leds_green_never_wins_the_primary_leds_slot_even_if_larger() -> None:
    # A hypothetically bigger LEDG group must still surface as leds_green,
    # not usurp "leds" -- classify() excludes it from the primary interest
    # filter outright rather than relying on group size.
    names = {f"LEDR[{i}]": f"R{i}" for i in range(4)} | {f"LEDG[{i}]": f"G{i}" for i in range(10)}
    result = classify(_table(names))
    assert result["leds"] == {"name": "LEDR", "width": 4}
    assert result["leds_green"] == {"name": "LEDG", "width": 10}


def test_green_only_led_bank_is_the_primary_leds() -> None:
    # DE0 has only green LEDs (LEDG). With no red bank, the green bank IS the
    # primary `leds`; leds_green is only for a secondary bank alongside a red one.
    names = {f"LEDG[{i}]": f"G{i}" for i in range(10)}
    result = classify(_table(names))
    assert result["leds"] == {"name": "LEDG", "width": 10}
    assert "leds_green" not in result


def test_single_scalar_led_and_switch_get_width_one() -> None:
    # Pipistrello's lone "SWITCH" and rv901t's lone "user_led" (see the UCF
    # parser fixtures) are single scalar ports, not vectors.
    table = _table({"user_led": "F7", "SWITCH": "N14"})
    result = classify(table)
    assert result["leds"] == {"name": "user_led", "width": 1}
    assert result["switches"] == {"name": "SWITCH", "width": 1}


def test_bare_digit_multi_count_led_group_lists_names() -> None:
    # Nandland Go's real o_LED_1..o_LED_4: four distinct scalar ports, no
    # brackets. port_mapping's `names` list (added alongside this test)
    # records the real port names rather than fabricating a vector "o_LED".
    table = _table({f"o_LED_{i}": str(i) for i in range(1, 5)})
    assert classify(table)["leds"] == {
        "names": ["o_LED_1", "o_LED_2", "o_LED_3", "o_LED_4"],
        "width": 4,
    }


def test_two_unrelated_scalar_leds_are_declined() -> None:
    # GateMate's real FPGA_LED / JTAG_LED: two distinct, unrelated scalar
    # names sharing no common prefix+index shape at all.
    table = _table({"FPGA_LED": "IO_SB_B6", "JTAG_LED": "IO_SB_B5"})
    assert "leds" not in classify(table)


def test_digilent_named_direction_buttons() -> None:
    table = _table({"btnC": "U18", "btnU": "T18", "btnD": "U17", "btnL": "W19", "btnR": "T17"})
    result = classify(table)
    assert result["buttons"] == {"name": "btn", "width": 5}


def test_bracket_indexed_buttons_do_not_need_the_direction_fallback() -> None:
    table = _table({"KEY[0]": "AA14", "KEY[1]": "AA15"})
    result = classify(table)
    assert result["buttons"] == {"name": "KEY", "width": 2}


def test_clock_prefers_explicit_frequency_constraint_over_name_shape() -> None:
    # Two clk-shaped names; only one has an explicit frequency statement --
    # that is the stronger signal (see classify.py's module docstring on why
    # bare name-shape alone is unreliable on multi-clock boards).
    table = _table(
        {"SER_CLK_N": "A1", "clk_25mhz": "G2"},
        clocks=(ClockConstraint(port="clk_25mhz", frequency_hz=25e6),),
    )
    assert classify(table)["clk"] == "clk_25mhz"


def test_clock_falls_back_to_name_shape_when_no_frequency_stated() -> None:
    table = _table({"i_Clk": "15", "spi_mosi": "F1"})
    assert classify(table)["clk"] == "i_Clk"


def test_trailing_n_suffix_is_read_as_active_low() -> None:
    # ICEBreaker's real BTN_N: no comment or overlay needed, the polarity is
    # spelled out in the name itself.
    table = _table({"BTN_N": "10"})
    assert classify(table)["buttons"] == {"name": "BTN_N", "width": 1, "active_low": True}


def test_seven_seg_individual_style_two_digits() -> None:
    # Terasic-style per-digit ports, minimal 2-digit x 3-segment case.
    names = {f"HEX{d}[{s}]": f"P{d}{s}" for d in range(2) for s in range(3)}
    result = classify(_table(names))
    assert result["seven_seg"] == {
        "style": "individual",
        "names": ["HEX0", "HEX1"],
        "width_per_digit": 3,
    }


def test_seven_seg_split_dp_style_is_individual_over_segment_ports() -> None:
    # DE0 shape: each digit is a 7-bit segment vector HEXn_D[6:0] plus a separate
    # HEXn_DP scalar. Reported as `individual` over the segment ports; the DP
    # scalars are recognized (so they don't derail classification) but not listed.
    names = {f"HEX{d}_D[{s}]": f"P{d}{s}" for d in range(4) for s in range(7)}
    names |= {f"HEX{d}_DP": f"D{d}" for d in range(4)}
    result = classify(_table(names))
    assert result["seven_seg"] == {
        "style": "individual",
        "names": ["HEX0_D", "HEX1_D", "HEX2_D", "HEX3_D"],
        "width_per_digit": 7,
    }


def test_seven_seg_per_segment_scalars_style() -> None:
    # Nandland Go's real o_Segment1_A..G / o_Segment2_A..G shape, minimal form.
    letters = ["A", "B", "C"]
    names = {f"o_Segment{d}_{s}": f"P{d}{s}" for d in (1, 2) for s in letters}
    result = classify(_table(names))
    assert result["seven_seg"]["style"] == "per_segment_scalars"
    assert result["seven_seg"]["width_per_digit"] == 3
    assert result["seven_seg"]["names"][:3] == ["o_Segment1_A", "o_Segment1_B", "o_Segment1_C"]


def test_seven_seg_scan_style_when_digit_enable_present() -> None:
    # Basys3/Mimas-A7 shape: a shared segment vector plus a separate
    # anode/enable vector.
    names = {f"seg[{i}]": f"S{i}" for i in range(7)} | {f"an[{i}]": f"A{i}" for i in range(4)}
    result = classify(_table(names))
    assert result["seven_seg"] == {
        "style": "scan",
        "name": "seg",
        "width_per_digit": 7,
        "digit_enable": {"name": "an", "width": 4},
    }


def test_seven_seg_packed_vector_style_without_digit_enable() -> None:
    names = {f"seg[{i}]": f"S{i}" for i in range(7)}
    result = classify(_table(names))
    assert result["seven_seg"] == {"style": "packed_vector", "name": "seg", "width_per_digit": 7}


def test_ddr_pinout_yields_no_matches() -> None:
    # Exclude-filter sanity check with representative DDR3 names.
    names = {"ddr3_addr[0]": "E17", "ddr3_ba[0]": "B17", "ddr3_cas_n": "B19"}
    assert classify(_table(names)) == {}


def test_empty_table_yields_empty_result() -> None:
    assert classify(PortTable()) == {}
