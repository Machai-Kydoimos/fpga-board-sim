"""Tests for the shared framework-derived convention builder (U32).

Exercises scripts/framework_conventions.py directly: the ``build_bank`` grouping
rules (vector vs. names[] cluster, primary-group selection, polarity) and the
``build_convention`` assembly (partial-interface floor, naming stamp) that both
the litex and amaranth sync parsers feed.
"""

import copy

from framework_conventions import (
    RoleEntry,
    build_bank,
    build_convention,
    reconcile_framework_polarity,
)


def _entries(*specs: tuple[str, str, int, bool]) -> list[RoleEntry]:
    return [RoleEntry(*s) for s in specs]


# ── build_bank: shape ───────────────────────────────────────────────────


def test_empty_role_is_none():
    assert build_bank([]) is None


def test_single_indexed_bank_is_a_vector():
    bank = build_bank(_entries(("led", "user_led", 0, False), ("led", "user_led", 3, False)))
    assert bank == {"name": "user_led", "width": 4}  # width = max index + 1


def test_single_scalar_is_a_width_one_vector():
    assert build_bank(_entries(("led", "user_led_n", 0, False))) == {
        "name": "user_led_n",
        "width": 1,
        "active_low": True,  # `_n` suffix
    }


def test_distinct_single_bit_ports_become_a_names_cluster():
    # Basys3-style directional buttons: distinct raw names, none plain "button".
    bank = build_bank(
        _entries(
            ("button_u", "user_btnu", 0, False),
            ("button_d", "user_btnd", 0, False),
            ("button_c", "user_btnc", 0, False),
        )
    )
    assert bank == {"names": ["user_btnc", "user_btnd", "user_btnu"], "width": 3}


def test_indexed_bus_dominates_stray_scalars():
    # A real >=2-bit bus wins over a stray same-role scalar (both plain "button").
    bank = build_bank(
        _entries(
            ("button", "user_btn", 0, False),
            ("button", "user_btn", 1, False),
            ("button", "user_btn", 2, False),
            ("button", "key", 0, False),
        )
    )
    assert bank == {"name": "user_btn", "width": 3}  # `key` dropped


# ── build_bank: primary-group selection (led over rgb_led) ───────────────


def test_plain_led_beats_decorated_rgb_led():
    bank = build_bank(
        _entries(
            ("led", "user_led", 0, False),
            ("led", "user_led", 1, False),
            ("rgb_led", "rgb_led", 0, False),
            ("rgb_led", "rgb_led", 1, False),
            ("rgb_led", "rgb_led", 2, False),
        )
    )
    assert bank == {"name": "user_led", "width": 2}  # rgb_led dropped despite being wider


def test_plain_button_drops_decorated_sibling():
    bank = build_bank(
        _entries(
            ("button", "user_btn", 0, False),
            ("button", "user_btn", 1, False),
            ("button_reset", "user_btn_reset", 0, False),
        )
    )
    assert bank == {"name": "user_btn", "width": 2}


def test_single_pin_rgb_bank_is_still_emitted():
    # The exclusion is by *pin count*, not the name: a (hypothetical) genuinely
    # single-pin-per-bit bank named rgb_led is declarable, so it is emitted.
    bank = build_bank(_entries(("rgb_led", "rgb_led", 0, False), ("rgb_led", "rgb_led", 1, False)))
    assert bank == {"name": "rgb_led", "width": 2}


def test_multi_pin_rgb_bank_is_not_emittable():
    # A real RGB LED flattens r/g/b onto one bit (pins_per_bit=3): no single
    # declarable port, so the bank is dropped and an RGB-only board ships nothing.
    bank = build_bank(
        [
            RoleEntry("rgb_led", "rgb_led", 0, False, pins_per_bit=3),
            RoleEntry("rgb_led", "rgb_led", 1, False, pins_per_bit=3),
        ]
    )
    assert bank is None


def test_multi_pin_rgb_dropped_but_plain_led_kept():
    # A board with both a plain LED (1 pin) and an RGB LED (3 pins): the RGB bit is
    # dropped and the plain LED bank is emitted.
    bank = build_bank(
        [
            RoleEntry("led", "user_led", 0, False),
            RoleEntry("led", "user_led", 1, False),
            RoleEntry("rgb_led", "rgb_led", 0, False, pins_per_bit=3),
        ]
    )
    assert bank == {"name": "user_led", "width": 2}


# ── build_bank: polarity ─────────────────────────────────────────────────


def test_inverted_flag_marks_active_low():
    bank = build_bank(_entries(("led", "led", 0, True), ("led", "led", 1, True)))
    assert bank == {"name": "led", "width": 2, "active_low": True}


def test_names_cluster_polarity_from_suffix():
    bank = build_bank(
        _entries(("button_a", "btn_a_n", 0, False), ("button_b", "btn_b_n", 0, False))
    )
    assert bank is not None
    assert bank["active_low"] is True


# ── build_convention: assembly + partial-interface floor ─────────────────

_CLK = "clk100"
_LEDS = [RoleEntry("led", "user_led", 0, False), RoleEntry("led", "user_led", 3, False)]
_SW = [RoleEntry("switch", "user_sw", 0, False)]
_BTN = [RoleEntry("button", "user_btn", 0, False)]


def test_full_convention_has_all_roles_and_naming():
    conv = build_convention("litex", _CLK, _LEDS, _SW, _BTN, description="d")
    assert conv is not None
    block = conv["litex"]
    assert block["clk"] == "clk100"
    assert block["leds"] == {"name": "user_led", "width": 4}
    assert block["switches"] == {"name": "user_sw", "width": 1}
    assert block["buttons"] == {"name": "user_btn", "width": 1}
    assert block["naming"] == "framework-derived"
    assert block["description"] == "d"


def test_partial_interface_omits_absent_banks():
    # A switch-less, button-less board: only clk + LEDs (the U31 floor).
    conv = build_convention("amaranth", _CLK, _LEDS, [], [], description="d")
    assert conv is not None
    block = conv["amaranth"]
    assert "switches" not in block
    assert "buttons" not in block
    assert block["leds"] == {"name": "user_led", "width": 4}


def test_no_clock_yields_no_convention():
    assert build_convention("litex", None, _LEDS, _SW, _BTN, description="d") is None


def test_no_leds_yields_no_convention():
    # LEDs are the minimum meaningful board-native output; without them, no block.
    assert build_convention("litex", _CLK, [], _SW, _BTN, description="d") is None


def test_rgb_only_board_fails_the_led_floor():
    # The rgb survey end-to-end: a board whose only LEDs are multi-pin RGB has no
    # emittable LED bank, so it fails the clk+LEDs floor and ships no convention.
    rgb = [RoleEntry("rgb_led", "rgb_led", 0, False, pins_per_bit=3)]
    assert build_convention("amaranth", _CLK, rgb, [], [], description="d") is None


# ── reconcile_framework_polarity (F2: canonical is the physical truth) ────


def test_reconcile_framework_inherits_canonical_active_low():
    # sipeed_tang_nano_9k case: canonical (cited) active-low, framework active-high.
    pc = {
        "sipeed": {"clk": "sys_clk", "leds": {"name": "led", "width": 6, "active_low": True}},
        "litex": {
            "clk": "clk",
            "leds": {"name": "user_led", "width": 6},
            "naming": "framework-derived",
        },
    }
    out = reconcile_framework_polarity(pc)
    assert out["litex"]["leds"]["active_low"] is True  # inherited the cited truth
    assert out["sipeed"]["leds"]["active_low"] is True  # canonical untouched


def test_reconcile_framework_clears_active_low_from_canonical_high():
    # de0_cv case: canonical (terasic) active-high, framework (amaranth) active-low.
    pc = {
        "terasic": {"clk": "CLOCK_50", "leds": {"name": "LEDR", "width": 10}},
        "amaranth": {
            "clk": "clk",
            "leds": {"name": "led", "width": 10, "active_low": True},
            "naming": "framework-derived",
        },
    }
    out = reconcile_framework_polarity(pc)
    assert "active_low" not in out["amaranth"]["leds"]  # cleared to active-high


def test_reconcile_width_mismatch_is_a_no_op():
    pc = {
        "terasic": {"clk": "CLOCK_50", "leds": {"name": "LEDR", "width": 8, "active_low": True}},
        "amaranth": {
            "clk": "clk",
            "leds": {"name": "led", "width": 10},
            "naming": "framework-derived",
        },
    }
    out = reconcile_framework_polarity(pc)
    assert "active_low" not in out["amaranth"]["leds"]  # widths differ -> no inheritance


def test_reconcile_joins_names_cluster_to_vector_by_width():
    # Shape may differ: a canonical names[] of width 4 reconciles a width-4 vector.
    pc = {
        "acme": {
            "clk": "clk",
            "leds": {"names": ["o_LED_1", "o_LED_2", "o_LED_3", "o_LED_4"], "active_low": True},
        },
        "litex": {
            "clk": "clk",
            "leds": {"name": "user_led", "width": 4},
            "naming": "framework-derived",
        },
    }
    out = reconcile_framework_polarity(pc)
    assert out["litex"]["leds"]["active_low"] is True


def test_reconcile_no_canonical_leaves_framework_untouched():
    pc = {
        "litex": {
            "clk": "clk",
            "leds": {"name": "user_led", "width": 4, "active_low": True},
            "naming": "framework-derived",
        }
    }
    assert reconcile_framework_polarity(pc) == pc


def test_reconcile_is_idempotent_and_pure():
    pc = {
        "sipeed": {"clk": "c", "leds": {"name": "led", "width": 6, "active_low": True}},
        "litex": {
            "clk": "c",
            "leds": {"name": "user_led", "width": 6},
            "naming": "framework-derived",
        },
    }
    before = copy.deepcopy(pc)
    once = reconcile_framework_polarity(pc)
    twice = reconcile_framework_polarity(once)
    assert once == twice
    assert once["litex"]["leds"]["active_low"] is True
    assert pc == before  # input not mutated
