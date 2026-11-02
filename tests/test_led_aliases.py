"""LED aliases and bank channel maps at run time (U56 Phase 6, D-1, defect 25).

Upstream lists some LEDs under several names -- the iCE40UP5K EVN's RGB LED is also
``user_ledr_n`` / ``user_ledg_n`` / ``user_ledb_n``, and its blue is ``user_led_n``
too.  The sync draws one LED and lists the other names as ``aliases``; the
convention gives each name a bank with a ``channels`` map.  A design may use any of
them; one that drives a pin under two names is a near-miss that names the pin.

Hermetic: synthetic boards shaped like the real ones, the real interface parser,
matcher and wrapper renderer.
"""

from __future__ import annotations

import json
from typing import Any

from fpga_sim.board_loader import BoardDef, ComponentInfo
from fpga_sim.conventions import ConventionMatch, match_convention
from fpga_sim.manifest import _native_sources
from fpga_sim.pinmap import PinRole, board_pin_index
from fpga_sim.vhdl_interface import _parse_toplevel_interface
from fpga_sim.waveform import _native_gtkw_signals
from fpga_sim.wrapper import _render_native_wrapper

#: The iCE40UP5K EVN after the merge: one RGB LED (r 41, g 40, b 39) under four names.
_ICE40 = BoardDef(
    name="iCE40UP5K EVN",
    class_name="Ice40",
    leds=[
        ComponentInfo(
            "led",
            "rgb_led",
            0,
            ["41", "40", "39"],
            aliases=[
                {"name": "user_led_n", "number": 0, "channel": "b"},
                {"name": "user_ledb_n", "number": 0, "channel": "b"},
                {"name": "user_ledg_n", "number": 0, "channel": "g"},
                {"name": "user_ledr_n", "number": 0, "channel": "r"},
            ],
        )
    ],
    switches=[ComponentInfo("switch", "switch", i, [f"S{i}"]) for i in range(4)],
    port_conventions={
        "litex": {
            "clk": "clk12",
            "leds": {
                "names": ["user_led_n", "user_ledg_n", "user_ledr_n"],
                "width": 3,
                "active_low": True,
                "channels": [2, 1, 0],
            },
            "led_banks": [
                {"name": name, "width": 1, "active_low": True, "channels": [channel]}
                for name, channel in (
                    ("user_led_n", 2),
                    ("user_ledb_n", 2),
                    ("user_ledg_n", 1),
                    ("user_ledr_n", 0),
                )
            ],
            "naming": "framework-derived",
        }
    },
)


def _interface(ports: list[str]) -> tuple[list[Any], list[Any]]:
    body = ";\n".join(f"    {p}" for p in ports)
    text = (
        "library ieee; use ieee.std_logic_1164.all;\n"
        f"entity d is\n  port (\n{body}\n  );\nend entity;\n"
        "architecture rtl of d is begin end architecture;\n"
    )
    parsed = _parse_toplevel_interface(text, "d")
    assert parsed is not None
    return parsed


def _match(board: BoardDef, ports: list[str]) -> ConventionMatch | None:
    p, g = _interface(["clk12 : in std_logic", *ports])
    return match_convention(p, g, board)


def test_aliases_ride_along_in_the_board_json():
    data = json.loads(_ICE40.to_json())
    assert data["leds"][0]["aliases"][1] == {"name": "user_ledb_n", "number": 0, "channel": "b"}
    assert BoardDef.from_json(_ICE40.to_json()).leds[0].aliases == _ICE40.leds[0].aliases


def test_a_design_may_use_any_of_an_leds_names():
    # The three color names: none is the primary cluster, each its own bank.
    m = _match(
        _ICE40,
        [f"user_led{c}_n : out std_logic" for c in "rgb"],
    )
    assert m is not None and m.leds is None
    assert [(b.names, b.channels) for b in m.led_banks] == [
        (("user_ledb_n",), (2,)),
        (("user_ledg_n",), (1,)),
        (("user_ledr_n",), (0,)),
    ]


def test_a_whole_cluster_does_not_also_match_its_names_one_by_one():
    m = _match(
        _ICE40, [f"{n} : out std_logic" for n in ("user_led_n", "user_ledg_n", "user_ledr_n")]
    )
    assert m is not None
    assert m.leds is not None and m.leds.channels == (2, 1, 0)
    assert m.led_banks == ()


def test_two_names_of_one_led_are_a_near_miss_naming_the_pin():
    from fpga_sim.vhdl_contract import check_vhdl_contract

    text = (
        "library ieee; use ieee.std_logic_1164.all;\n"
        "entity twice is port (clk12 : in std_logic; user_led_n : out std_logic;"
        " user_ledb_n : out std_logic); end entity;\n"
        "architecture rtl of twice is begin end architecture;\n"
    )
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "twice.vhd"
        path.write_text(text, encoding="utf-8")
        result = check_vhdl_contract(str(path), board_def=_ICE40)
    assert not result.ok
    assert "user_led_n and user_ledb_n drive the same LED (pin 39)" in result.message


def test_the_wrapper_drives_each_channel_from_the_bank_its_map_names():
    m = _match(_ICE40, [f"user_led{c}_n : out std_logic" for c in "rgb"])
    assert m is not None
    vhd = _render_native_wrapper("d", m, _ICE40)
    # ledbank0 = user_ledb_n (blue), 1 = green, 2 = red; all active-low.
    assert "  led(0) <= not ledbank2_uut(0);" in vhd
    assert "  led(1) <= not ledbank1_uut(0);" in vhd
    assert "  led(2) <= not ledbank0_uut(0);" in vhd
    assert "user_ledr_n => ledbank2_uut(0)" in vhd


def test_a_bank_bit_with_no_resource_idles_released():
    # ECP5 EVN: the DIP switches are numbered from 1, so the bank's bit 0 has none.
    board = BoardDef(
        name="ECP5 EVN",
        class_name="Ecp5Evn",
        leds=[ComponentInfo("led", "led", 0, ["L0"])],
        switches=[ComponentInfo("switch", "switch", i + 1, [f"S{i}"]) for i in range(8)],
        port_conventions={
            "litex": {
                "clk": "clk12",
                "leds": {"name": "user_led", "width": 1},
                "switches": {
                    "name": "user_dip_btn",
                    "width": 9,
                    "channels": [None, 0, 1, 2, 3, 4, 5, 6, 7],
                },
                "naming": "framework-derived",
            }
        },
    )
    m = _match(
        board,
        ["user_led : out std_logic", "user_dip_btn : in std_logic_vector(8 downto 0)"],
    )
    assert m is not None
    vhd = _render_native_wrapper("d", m, board)
    assert "  sw_uut(0) <= '0';" in vhd
    assert "  sw_uut(1) <= sw(0);" in vhd
    assert "  sw_uut(8) <= sw(7);" in vhd


def test_the_still_legend_and_the_waveform_name_what_drives_each_channel():
    m = _match(_ICE40, [f"user_led{c}_n : out std_logic" for c in "rgb"])
    assert m is not None
    assert _native_sources(m, mono=0) == {
        0: ("user_ledr_n", True),
        1: ("user_ledg_n", True),
        2: ("user_ledb_n", True),
    }
    signals = _native_gtkw_signals(m)
    assert "sim_wrapper.uut.user_ledr_n" in signals


def test_a_pin_map_reaches_the_merged_led_through_any_of_its_pins():
    # Pin 39 is the RGB LED's blue: under every name it resolves to channel 2.
    assert board_pin_index(_ICE40)["39"] == PinRole("led", 2)
