"""Tests for the U21 B2 board-native port-convention matcher.

`match_convention()` recognizes a VHDL file that uses a board's *native* port
names + fixed widths (e.g. DE10-Standard's CLOCK_50 / SW / KEY / LEDR / HEX0..5)
against the selected board's `port_conventions`.  `check_vhdl_contract()` reports
such a design precisely (naming the convention) and carries the `ConventionMatch`
on its result.  Since U21 B3 a full native match returns ``ok=True`` (the native
wrapper runs it); the B3-specific execution/wrapper behavior is covered by
`test_native_convention.py`.

All matcher tests are hermetic (synthetic BoardDef + parsed interface, no I/O).
"""

import dataclasses
from typing import Any

import pytest

from fpga_sim.board_loader import BoardDef, ComponentInfo, SevenSegDef
from fpga_sim.sim_bridge import (
    ContractResult,
    ConventionMatch,
    check_vhdl_contract,
    match_convention,
)
from fpga_sim.sim_bridge import (
    _parse_toplevel_interface as _parse_iface,
)

# ── synthetic fixtures ────────────────────────────────────────────────────────


def _mk(kind: str, n: int) -> list[ComponentInfo]:
    return [ComponentInfo(kind, kind, i) for i in range(n)]


def _board(
    conv: dict[str, Any], *, digits: int | None = 6, name: str = "DE10-Standard"
) -> BoardDef:
    """A synthetic board with the given port_conventions (resource counts are nominal)."""
    return BoardDef(
        name=name,
        class_name="X",
        leds=_mk("led", 10),
        buttons=_mk("button", 4),
        switches=_mk("switch", 10),
        seven_seg=SevenSegDef(digits, False, False, True, False) if digits else None,
        port_conventions=conv,
    )


def _terasic_conv(
    *, naming: str | None = "canonical", seg_style: str = "individual", leds_green: bool = False
) -> dict[str, Any]:
    conv: dict[str, Any] = {
        "clk": "CLOCK_50",
        "leds": {"name": "LEDR", "width": 10},
        "switches": {"name": "SW", "width": 10},
        "buttons": {"name": "KEY", "width": 4, "active_low": True},
        "seven_seg": {
            "style": seg_style,
            "names": [f"HEX{i}" for i in range(6)],
            "width_per_digit": 7,
            "active_low": True,
        },
    }
    if naming is not None:
        conv["naming"] = naming
    if leds_green:
        conv["leds_green"] = {"name": "LEDG", "width": 8}
    return {"terasic": conv}


_NANO_CONV: dict[str, Any] = {
    "terasic": {
        "clk": "CLOCK_50",
        "leds": {"name": "LED", "width": 8},
        "switches": {"name": "SW", "width": 4},
        "buttons": {"name": "KEY", "width": 2, "active_low": True},
        "naming": "canonical",
    }
}


def _de10_decls(
    *,
    led_w: int = 10,
    sw_w: int = 10,
    key_w: int = 4,
    seg_w: int = 7,
    digits: int = 6,
    clk: str = "CLOCK_50",
    key: bool = True,
    hexs: bool = True,
) -> list[str]:
    """Port declarations for a DE10-Standard-native entity (widths overridable)."""
    d = [f"{clk} : in  std_logic", f"SW  : in  std_logic_vector({sw_w - 1} downto 0)"]
    if key:
        d.append(f"KEY : in  std_logic_vector({key_w - 1} downto 0)")
    d.append(f"LEDR : out std_logic_vector({led_w - 1} downto 0)")
    if hexs:
        d += [f"HEX{i} : out std_logic_vector({seg_w - 1} downto 0)" for i in range(digits)]
    return d


def _parse(
    name: str, ports: list[str], generics: list[str] | None = None
) -> tuple[list[Any], list[Any]]:
    """Parse a synthetic entity's (ports, generics) via the real interface parser."""
    g = ""
    if generics:
        g = "  generic (\n" + ";\n".join(f"    {x}" for x in generics) + "\n  );\n"
    p = ";\n".join(f"    {x}" for x in ports)
    text = (
        "library ieee; use ieee.std_logic_1164.all;\n"
        f"entity {name} is\n{g}  port (\n{p}\n  );\nend entity;\n"
        f"architecture rtl of {name} is begin end architecture;\n"
    )
    parsed = _parse_iface(text, name)
    assert parsed is not None, "synthetic entity should parse"
    return parsed


def _match(
    name: str, ports: list[str], board: BoardDef, generics: list[str] | None = None
) -> ConventionMatch | None:
    p, g = _parse(name, ports, generics)
    return match_convention(p, g, board)


def _write(tmp_path: Any, name: str, ports: list[str]) -> str:
    p = ";\n".join(f"    {x}" for x in ports)
    text = (
        "library ieee; use ieee.std_logic_1164.all;\n"
        f"entity {name} is\n  port (\n{p}\n  );\nend entity;\n"
        f"architecture rtl of {name} is begin end architecture;\n"
    )
    f = tmp_path / f"{name}.vhd"
    f.write_text(text)
    return str(f)


# ── match_convention: the happy path ─────────────────────────────────────────


def test_matches_full_de10_native_interface() -> None:
    m = _match("de10", _de10_decls(), _board(_terasic_conv()))
    assert isinstance(m, ConventionMatch)
    assert m.maker == "terasic"
    assert m.board_name == "DE10-Standard"
    assert m.clk == "CLOCK_50"
    assert (m.leds.names, m.leds.width) == (("LEDR",), 10)
    assert m.switches is not None and m.buttons is not None
    assert (m.switches.names, m.switches.width) == (("SW",), 10)
    assert (m.buttons.names, m.buttons.width, m.buttons.active_low) == (("KEY",), 4, True)
    assert m.leds.active_low is False  # LEDR is active-high on this board
    assert m.seven_seg is not None
    assert m.seven_seg.style == "individual"
    assert m.seven_seg.names == tuple(f"HEX{i}" for i in range(6))
    assert m.seven_seg.width_per_digit == 7
    assert m.seven_seg.active_low is True


def test_native_fixed_widths_equal_to_convention_are_accepted() -> None:
    # The generic contract *rejects* a fixed-width led; native mode expects fixed
    # widths that equal the convention width (decision #5 inverts for native).
    m = _match("de10", _de10_decls(), _board(_terasic_conv()))
    assert m is not None and m.leds.width == 10


def test_board_without_7seg_matches_without_seg() -> None:
    board = _board(_NANO_CONV, digits=None, name="DE0 Nano")
    ports = [
        "CLOCK_50 : in std_logic",
        "LED : out std_logic_vector(7 downto 0)",
        "SW : in std_logic_vector(3 downto 0)",
        "KEY : in std_logic_vector(1 downto 0)",
    ]
    m = _match("nano", ports, board)
    assert m is not None
    assert (m.leds.names, m.leds.width) == (("LED",), 8)
    assert m.seven_seg is None  # board has no display, so no seg role is required


# ── match_convention: rejections ─────────────────────────────────────────────


def test_no_conventions_returns_none() -> None:
    assert _match("de10", _de10_decls(), _board({})) is None


def test_board_def_none_returns_none() -> None:
    p, g = _parse("de10", _de10_decls())
    assert match_convention(p, g, None) is None


def test_wrong_led_width_no_match() -> None:
    assert _match("de10", _de10_decls(led_w=8), _board(_terasic_conv())) is None


def test_wrong_button_width_no_match() -> None:
    assert _match("de10", _de10_decls(key_w=3), _board(_terasic_conv())) is None


def test_missing_button_role_no_match() -> None:
    assert _match("de10", _de10_decls(key=False), _board(_terasic_conv())) is None


def test_missing_seg_on_7seg_board_no_match() -> None:
    # Board physically has a display, so its seg role is required for a full match.
    assert _match("de10", _de10_decls(hexs=False), _board(_terasic_conv())) is None


def test_wrong_seg_width_no_match() -> None:
    assert _match("de10", _de10_decls(seg_w=8), _board(_terasic_conv())) is None


def test_led_wrong_direction_no_match() -> None:
    # LEDR declared as an input is not a valid native LED bank.
    ports = _de10_decls()
    ports[3] = "LEDR : in  std_logic_vector(9 downto 0)"
    assert _match("de10", ports, _board(_terasic_conv())) is None


# ── match_convention: scope + trust rules ────────────────────────────────────


@pytest.mark.parametrize("style", ["packed_vector", "scan", "serial", "per_segment_scalars"])
def test_declines_non_individual_seg_styles(style: str) -> None:
    # Only `individual` is in B2 scope; other styles decline the seg role, so a
    # 7-seg board never fully matches through them.
    m = _match("de10", _de10_decls(), _board(_terasic_conv(seg_style=style)))
    assert m is None


def test_project_derived_naming_is_skipped() -> None:
    # Renamed-by-a-downstream-project names are not the board's native ones.
    assert _match("de10", _de10_decls(), _board(_terasic_conv(naming="project-derived"))) is None


def test_absent_naming_is_treated_as_canonical() -> None:
    # Hand-authored blocks (all the custom Terasic boards, incl. DE10-Standard)
    # omit `naming`; the schema documents absent == canonical.
    assert _match("de10", _de10_decls(), _board(_terasic_conv(naming=None))) is not None


def test_sizing_generics_disqualify_native_match() -> None:
    # A design that declares the simulator's own sizing generics is a generic
    # design that failed for some other reason -- never board-native.
    generics = ["NUM_LEDS : positive := 10", "COUNTER_BITS : positive := 24"]
    assert _match("de10", _de10_decls(), _board(_terasic_conv()), generics) is None


def test_non_sizing_generic_does_not_block_native_match() -> None:
    # COUNTER_BITS alone is not a sizing generic, so it does not disqualify.
    m = _match("de10", _de10_decls(), _board(_terasic_conv()), ["COUNTER_BITS : positive := 24"])
    assert m is not None


# ── leds_green (optional secondary bank) ─────────────────────────────────────


def test_leds_green_captured_when_present() -> None:
    ports = _de10_decls() + ["LEDG : out std_logic_vector(7 downto 0)"]
    m = _match("de10", ports, _board(_terasic_conv(leds_green=True)))
    assert m is not None and m.leds_green is not None
    assert (m.leds_green.names, m.leds_green.width) == (("LEDG",), 8)


def test_leds_green_optional_when_absent_from_design() -> None:
    # The convention declares LEDG but the design omits it -> still a full match.
    m = _match("de10", _de10_decls(), _board(_terasic_conv(leds_green=True)))
    assert m is not None and m.leds_green is None


# ── scalar-port banks (e.g. Nandland Go's o_LED_1..o_LED_4) ──────────────────


def test_scalar_led_bank_matches() -> None:
    conv: dict[str, Any] = {
        "acme": {
            "clk": "i_Clk",
            "leds": {"names": ["o_LED_1", "o_LED_2", "o_LED_3", "o_LED_4"]},
            "switches": {"names": ["i_SW_1", "i_SW_2"]},
            "buttons": {"names": ["i_BTN_1"]},
            "naming": "canonical",
        }
    }
    ports = [
        "i_Clk : in std_logic",
        "i_SW_1 : in std_logic",
        "i_SW_2 : in std_logic",
        "i_BTN_1 : in std_logic",
        "o_LED_1 : out std_logic",
        "o_LED_2 : out std_logic",
        "o_LED_3 : out std_logic",
        "o_LED_4 : out std_logic",
    ]
    m = _match("go", ports, _board(conv, digits=None, name="Nandland Go"))
    assert m is not None
    assert m.leds.names == ("o_LED_1", "o_LED_2", "o_LED_3", "o_LED_4")
    assert m.leds.width == 4
    assert m.leds.scalar_ports is True  # each o_LED_n is an individual scalar port
    assert m.switches is not None
    assert m.switches.width == 2


def test_scalar_led_bank_rejects_vector_member() -> None:
    # F6: a names[] member declared as a vector (not a scalar) disqualifies the
    # bank cleanly here, instead of "matching" then failing at elaboration.
    conv: dict[str, Any] = {
        "acme": {
            "clk": "i_Clk",
            "leds": {"names": ["o_LED_1", "o_LED_2"]},
            "naming": "canonical",
        }
    }
    ports = [
        "i_Clk : in std_logic",
        "o_LED_1 : out std_logic",
        "o_LED_2 : out std_logic_vector(7 downto 0)",  # vector, not a scalar
    ]
    assert _match("go", ports, _board(conv, digits=None, name="Go")) is None


# ── width-1 LED banks: scalar or std_logic_vector(0 downto 0) (F1) ────────────


def _led1_board() -> BoardDef:
    """A one-LED board carrying a width-1 shared-vector LED convention."""
    conv: dict[str, Any] = {"amaranth": {"clk": "clk16", "leds": {"name": "led", "width": 1}}}
    return _board(conv, digits=None, name="Tiny FPGABX")


def test_width1_led_bank_matches_scalar_port() -> None:
    # F1: `led : out std_logic` -- the natural one-LED spelling -- matches a
    # width-1 vector bank, yielding a scalar_ports bank the wrapper maps per bit.
    m = _match("bx", ["clk16 : in std_logic", "led : out std_logic"], _led1_board())
    assert m is not None
    assert (m.leds.names, m.leds.width) == (("led",), 1)
    assert m.leds.scalar_ports is True


def test_width1_led_bank_matches_vector_0_downto_0() -> None:
    # F1: the std_logic_vector(0 downto 0) spelling still matches as a plain
    # (non-scalar) vector, so both forms work.
    m = _match(
        "bx", ["clk16 : in std_logic", "led : out std_logic_vector(0 downto 0)"], _led1_board()
    )
    assert m is not None
    assert (m.leds.names, m.leds.width) == (("led",), 1)
    assert m.leds.scalar_ports is False


def test_wide_bank_still_rejects_scalar_port() -> None:
    # A width>=2 bank is not satisfiable by a scalar -- only a width-1 bank is.
    conv: dict[str, Any] = {"amaranth": {"clk": "clk16", "leds": {"name": "led", "width": 4}}}
    m = _match(
        "bx", ["clk16 : in std_logic", "led : out std_logic"], _board(conv, digits=None, name="X")
    )
    assert m is None


# ── check_vhdl_contract integration ──────────────────────────────────────────


def test_contract_native_file_is_ok_with_match(tmp_path: Any) -> None:
    f = _write(tmp_path, "de10_native", _de10_decls())
    res = check_vhdl_contract(f, board_def=_board(_terasic_conv()))
    assert isinstance(res, ContractResult)
    assert res.ok is True  # U21 B3: a full native match runs
    assert res.match is not None and res.match.maker == "terasic"
    # message names the board, the convention, and the native ports
    for token in ("DE10-Standard", "board-native", "terasic", "CLOCK_50", "LEDR", "HEX0..HEX5"):
        assert token in res.message


def test_contract_generic_design_unchanged(tmp_path: Any) -> None:
    # A valid generic-contract design passes untouched: ok, no match, no message.
    text = (
        "library ieee; use ieee.std_logic_1164.all;\n"
        "entity gen is\n"
        "  generic (\n"
        "    NUM_SWITCHES : positive := 4;\n"
        "    NUM_BUTTONS  : positive := 4;\n"
        "    NUM_LEDS     : positive := 4;\n"
        "    COUNTER_BITS : positive := 24\n"
        "  );\n"
        "  port (\n"
        "    clk : in  std_logic;\n"
        "    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);\n"
        "    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);\n"
        "    led : out std_logic_vector(NUM_LEDS - 1 downto 0)\n"
        "  );\n"
        "end entity;\n"
        "architecture rtl of gen is begin led <= (others => '0'); end architecture;\n"
    )
    f = tmp_path / "gen.vhd"
    f.write_text(text)
    res = check_vhdl_contract(f, board_def=_board(_terasic_conv()))
    assert res.ok is True
    assert res.match is None
    assert res.message == ""


def test_contract_near_miss_names_the_convention(tmp_path: Any) -> None:
    # CLOCK_50 + SW + LEDR match (3 roles) but KEY and the HEX digits are absent.
    ports = [
        "CLOCK_50 : in std_logic",
        "SW : in std_logic_vector(9 downto 0)",
        "LEDR : out std_logic_vector(9 downto 0)",
    ]
    f = _write(tmp_path, "de10_partial", ports)
    res = check_vhdl_contract(f, board_def=_board(_terasic_conv()))
    assert res.ok is False
    assert res.match is None  # not a full match
    assert "DE10-Standard" in res.message
    assert "terasic" in res.message  # F4: names the specific convention (maker)
    assert "close to" in res.message
    assert "buttons" in res.message and "7-segment display" in res.message
    # F4: no stale internal ticket ID / "until then" phrasing in user-facing text
    assert "U21 B3" not in res.message
    assert "until then" not in res.message


def test_contract_unrelated_failure_keeps_generic_error(tmp_path: Any) -> None:
    # A design with no native-name overlap keeps the ordinary contract error.
    ports = ["clk : in std_logic", "foo : in std_logic", "bar : out std_logic"]
    f = _write(tmp_path, "weird", ports)
    res = check_vhdl_contract(f, board_def=_board(_terasic_conv()))
    assert res.ok is False
    assert res.match is None
    assert "Missing required port" in res.message  # the generic contract message


# ── typed result shape ───────────────────────────────────────────────────────


def test_contract_result_is_frozen() -> None:
    res = ContractResult(True)
    assert (res.ok, res.message, res.match) == (True, "", None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.ok = False  # type: ignore[misc]
