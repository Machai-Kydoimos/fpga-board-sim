"""Tests for the shared framework-derived convention builder (U32).

Exercises scripts/framework_conventions.py directly: the ``build_bank`` grouping
rules (vector vs. names[] cluster, primary-group selection, polarity) and the
``build_convention`` assembly (partial-interface floor, naming stamp) that both
the litex and amaranth sync parsers feed.
"""

import copy
from typing import Any

import pytest
from framework_conventions import (
    LedView,
    RoleEntry,
    build_bank,
    build_convention,
    build_led_banks,
    group_by_name,
    multi_pin_shape,
    plan_led_aliases,
    reconcile_framework_polarity,
)


def _entries(*specs: tuple[str, str, int, bool]) -> list[RoleEntry]:
    return [RoleEntry(*s) for s in specs]


# ── group_by_name: the order a board lists its resources in (U56 Phase 2) ──


def _grouped(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    return group_by_name(items, lambda i: i[0], lambda i: i[1])


def test_group_by_name_keeps_a_name_together_in_number_order():
    # The Tang Primer 20K dock declares `led` 3 before `led` 2, and its WS2812 last;
    # sorting by number alone put the WS2812 between `led` 0 and `led` 1.
    dock = [("led", 0), ("led", 1), ("led", 3), ("led", 2), ("rgb_led", 0)]
    assert _grouped(dock) == [("led", 0), ("led", 1), ("led", 2), ("led", 3), ("rgb_led", 0)]


def test_group_by_name_keeps_upstream_declaration_order_of_names():
    # Names are not sorted: the first-declared name leads even when it sorts last.
    items = [("user_led", 1), ("run_led", 0), ("user_led", 0), ("alnum_led", 0)]
    assert _grouped(items) == [("user_led", 0), ("user_led", 1), ("run_led", 0), ("alnum_led", 0)]


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


def test_compass_cluster_north_is_not_active_low():
    """KCU116/ZCU216: ``user_btn_n`` amid a c/n/s/w/e compass cluster is the
    North button -- the ``_n`` must not mark the (active-high) bank active-low."""
    bank = build_bank(
        _entries(
            ("button_c", "user_btn_c", 0, False),
            ("button_n", "user_btn_n", 0, False),
            ("button_s", "user_btn_s", 0, False),
            ("button_w", "user_btn_w", 0, False),
            ("button_e", "user_btn_e", 0, False),
        )
    )
    assert bank == {
        "names": ["user_btn_c", "user_btn_e", "user_btn_n", "user_btn_s", "user_btn_w"],
        "width": 5,
    }


def test_lone_btn_n_without_compass_siblings_stays_active_low():
    """No compass siblings -> ``_n`` keeps its active-low reading."""
    bank = build_bank(_entries(("button", "user_btn_n", 0, False)))
    assert bank == {"name": "user_btn_n", "width": 1, "active_low": True}


def test_mixed_polarity_cluster_is_not_advertised():
    """gmm7550: active-high ``led_green`` + active-low ``led_red_n`` -- the single
    bank flag cannot represent both, so no bank is emitted (truth over coverage)."""
    bank = build_bank(
        _entries(("led_green", "led_green", 0, False), ("led_red_n", "led_red_n", 0, False))
    )
    assert bank is None


def test_mixed_polarity_drops_leds_and_the_whole_convention():
    """A mixed-polarity LED role fails the clk+LEDs floor, so the board simply
    isn't advertised as board-native-able."""
    mixed = _entries(("led_green", "led_green", 0, False), ("led_red_n", "led_red_n", 0, False))
    assert build_convention("litex", "clk100", mixed, [], [], description="d") is None


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


# ── multi-pin shapes (U56 Phase 5, D-3) ────────────────────────────────────────


@pytest.mark.parametrize(
    ("subsignals", "direction", "shape"),
    [
        ([], "o", "split"),  # Trenz `gpio_leds`: Pins("AB10 AA10 ...")
        ([("r", 1), ("g", 1), ("b", 1)], "o", "rgb"),  # the Efinix Ti60's `user_led`
        ([("g", 1), ("b", 1), ("r", 1)], "o", "rgb"),  # in any order
        ([("a", 1), ("b", 1), ("dp", 1)], "o", "split"),  # the Versa's `alnum_led`
        ([("r", 1), ("g", 1), ("h", 1)], "o", "split"),  # the Alibaba XCKU3P's three LEDs
        ([("cs_n", 1), ("clk", 1), ("mosi", 1), ("oe", 1)], "o", "unsupported"),  # Siglent
        ([("clk", 1), ("dat", 1)], "o", "unsupported"),  # the Tang Primer 20K's `mic_led`
        ([("en", 1), ("r", 1), ("g", 1), ("b", 1)], "o", "unsupported"),  # Chromatic
        ([("leds", 7), ("r", 1), ("g", 1), ("b", 1)], "io", "unsupported"),  # ButterStick
        ([("leds", 7), ("r", 1), ("g", 1), ("b", 1)], "o", "unsupported"),
        ([], "io", "unsupported"),  # bidirectional: Supercon badge `led_cathodes`
    ],
)
def test_a_multi_pin_resource_has_one_of_three_shapes(subsignals, direction, shape):
    assert multi_pin_shape(subsignals, direction) == shape


def test_split_bits_never_choose_the_bank():
    entries = [RoleEntry("led", "user_led", 0, False)] + [
        RoleEntry("led", "user_led2", bit, False, split=True) for bit in range(1, 4)
    ]
    assert build_bank(entries) == {"name": "user_led", "width": 1}
    assert build_bank([e for e in entries if e.split]) is None


# ── aliases and channel maps (U56 Phase 6, D-1, defect 25) ──────────────────────


def _view(*pins: str, rgb: bool = False) -> LedView:
    return LedView(tuple(pins), rgb)


def _bank(entries: list[RoleEntry]) -> dict[str, Any]:
    bank = build_bank(entries)
    assert bank is not None
    return bank


def test_a_second_name_on_one_pin_is_an_alias_of_the_first():
    # Amaranth iCEBreaker: led 0/1 on pins 11/37, then led_r/led_g on the same pins.
    plan, overlaps = plan_led_aliases([_view("11"), _view("37"), _view("11"), _view("37")])
    assert (plan, overlaps) == ({2: (0, None), 3: (1, None)}, [])


def test_a_name_on_an_rgb_pin_is_that_channel_wherever_it_is_declared():
    # OrangeCrab: user_led 0-2 on the rgb_led's r, g, b pins; the site may come last.
    leds = [_view("K4"), _view("M3"), _view("J3"), _view("K4", "M3", "J3", rgb=True)]
    plan, overlaps = plan_led_aliases(leds)
    assert (plan, overlaps) == ({0: (3, 0), 1: (3, 1), 2: (3, 2)}, [])


def test_three_names_on_one_pin_are_one_channel():
    # iCE40UP5K EVN: user_led_n and user_ledb_n are both the RGB LED's blue.
    leds = [_view("39"), _view("39"), _view("40"), _view("41"), _view("41", "40", "39", rgb=True)]
    plan, _ = plan_led_aliases(leds)
    assert plan == {0: (4, 2), 1: (4, 2), 2: (4, 1), 3: (4, 0)}


def test_other_shared_pins_merge_nothing_and_are_reported():
    rgb_overlap = [_view("A", "B", "C", rgb=True), _view("C", "D", "E", rgb=True)]
    assert plan_led_aliases(rgb_overlap) == ({}, [1])
    whole = [_view("A"), _view("A", "B")]  # a multi-pin resource kept whole (D-3)
    assert plan_led_aliases(whole) == ({}, [1])
    assert plan_led_aliases([_view("A"), _view("B")]) == ({}, [])  # different pins


def test_a_bank_carries_a_channel_map_only_where_bit_k_is_not_channel_k():
    aligned = [RoleEntry("led", "user_led", k, False, channel=k) for k in range(3)]
    assert build_bank(aligned) == {"name": "user_led", "width": 3}
    # ZCU216: each user_led is its RGB site's green channel.
    green = [RoleEntry("led", "user_led", k, False, channel=1 + 3 * k) for k in range(3)]
    assert _bank(green)["channels"] == [1, 4, 7]
    # ECP5 EVN numbers its DIP switches from 1: bit 0 reaches no switch.
    dip = [RoleEntry("switch", "user_dip_btn", k, False, channel=k - 1) for k in range(1, 4)]
    assert build_bank(dip) == {"name": "user_dip_btn", "width": 4, "channels": [None, 0, 1, 2]}
    # A parser that gives no channels gets no map.
    assert "channels" not in _bank([RoleEntry("led", "user_led", 1, False)])


def test_a_cluster_lists_names_alphabetically_and_maps_them_to_the_board():
    # Basys 3-style directional buttons, declared btnu, btnd, btnc.
    entries = [
        RoleEntry("button", "user_btnu", 0, False, channel=0),
        RoleEntry("button", "user_btnd", 0, False, channel=1),
        RoleEntry("button", "user_btnc", 0, False, channel=2),
    ]
    bank = _bank(entries)
    assert bank["names"] == ["user_btnc", "user_btnd", "user_btnu"]
    assert bank["channels"] == [2, 1, 0]


def test_a_cluster_never_holds_two_names_of_one_led():
    entries = [
        RoleEntry("led", "user_led_n", 0, False, channel=2),
        RoleEntry("led", "user_ledb_n", 0, False, channel=2),
        RoleEntry("led", "user_ledg_n", 0, False, channel=1),
    ]
    bank = _bank(entries)
    assert bank["names"] == ["user_led_n", "user_ledg_n"]
    assert bank["channels"] == [2, 1]


def test_every_other_led_name_is_a_bank_of_its_own():
    entries = [
        RoleEntry("led", "led", 0, False, channel=0),
        RoleEntry("led", "led", 1, False, channel=1),
        RoleEntry("led", "led_r", 0, False, channel=0),
        RoleEntry("led", "user_led2", 0, False, split=True, channel=2),
        RoleEntry("rgb_led", "rgb_led", 0, False, pins_per_bit=3, channel=3),
    ]
    primary = build_bank(entries)
    assert primary == {"name": "led", "width": 2}
    assert build_led_banks(entries, primary) == [
        {"name": "led_r", "width": 1, "channels": [0]},
        {"name": "user_led2", "width": 1, "channels": [2]},  # a split group (D-3)
    ]


def test_a_board_whose_only_leds_are_split_still_gets_a_convention():
    entries = [RoleEntry("led", "user_led", k, False, split=True, channel=k) for k in range(4)]
    conv = build_convention("litex", "clk25", entries, [], [], description="d")
    assert conv is not None
    assert "leds" not in conv["litex"]
    assert conv["litex"]["led_banks"] == [
        {"name": "user_led", "width": 4, "channels": [0, 1, 2, 3]}
    ]
