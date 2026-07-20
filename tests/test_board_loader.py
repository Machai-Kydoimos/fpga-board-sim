"""Tests for board_loader: discovery, parsing, and spot-checks."""

import pytest
from amaranth_parser import load_board_from_source

from fpga_sim.board_loader import (
    BoardDef,
    ComponentInfo,
    discover_boards,
    get_default_boards_path,
)


@pytest.fixture(scope="module")
def boards_path():
    path = get_default_boards_path()
    assert path.is_dir(), f"Boards path not found: {path}"
    return path


@pytest.fixture(scope="module")
def all_boards(boards_path):
    return discover_boards(boards_path)


def test_boards_path_exists(boards_path):
    assert boards_path.is_dir()


def test_discovers_enough_boards(all_boards):
    assert len(all_boards) > 50, f"Only found {len(all_boards)} boards"


def test_arty_a7_found(all_boards):
    matches = [b for b in all_boards if "Arty A7-35" in b.name]
    assert len(matches) >= 1


@pytest.fixture(scope="module")
def arty(all_boards):
    matches = [b for b in all_boards if "Arty A7-35" in b.name]
    assert matches, "Arty A7-35 not found"
    return matches[0]


def test_arty_has_leds(arty):
    assert len(arty.leds) > 0


def test_arty_has_buttons(arty):
    assert len(arty.buttons) > 0


def test_arty_has_switches(arty):
    assert len(arty.switches) > 0


def test_arty_led_has_pin_info(arty):
    assert len(arty.leds[0].pins) > 0


def test_arty_led_display_name(arty):
    assert arty.leds[0].display_name == "LED0"


def test_arty_vendor_is_xilinx(arty):
    assert arty.vendor == "Xilinx"


def test_arty_has_device(arty):
    assert arty.device != ""


def test_arty_has_clocks(arty):
    assert len(arty.clocks) > 0


def test_arty_default_clock_is_100mhz(arty):
    assert arty.default_clock_hz == 100e6


@pytest.fixture(scope="module")
def icestick(all_boards):
    matches = [b for b in all_boards if "icestick" in b.name.lower()]
    if not matches:
        pytest.skip("Icestick board not found")
    return matches[0]


def test_icestick_default_clock_is_12mhz(icestick):
    assert icestick.default_clock_hz == 12e6


def test_inline_board_uses_fallback_clock(inline_board):
    from fpga_sim.board_loader import _FALLBACK_CLOCK_HZ

    assert inline_board.default_clock_hz == _FALLBACK_CLOCK_HZ


def test_nexys_has_named_buttons(all_boards):
    nexys = [b for b in all_boards if "Nexys4" in b.name]
    if not nexys:
        pytest.skip("Nexys4 board not found in submodule")
    named = [b for b in nexys[0].buttons if b.name != "button"]
    assert len(named) > 0, "Expected named buttons on Nexys4"


_INLINE_SRC = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
__all__ = ["InlineTestPlatform"]
class InlineTestPlatform(XilinxPlatform):
    resources = [
        *LEDResources(pins="A B C", attrs=Attrs(IO="TEST")),
        *SwitchResources(pins="X Y", attrs=Attrs(IO="TEST")),
    ]
"""

_INLINE_SRC_WITH_CLOCK = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
class InlineClockPlatform(XilinxPlatform):
    default_clk = "clk50"
    resources = [
        Resource("clk50", 0, Pins("E3", dir="i"), Clock(50e6), Attrs(IO="LVCMOS")),
        *LEDResources(pins="A B", attrs=Attrs(IO="TEST")),
    ]
"""


@pytest.fixture(scope="module")
def inline_board():
    boards = load_board_from_source(_INLINE_SRC, "<inline>")
    assert len(boards) == 1, f"Expected 1 board, got {len(boards)}"
    return boards[0]


def test_inline_parse(inline_board):
    assert inline_board is not None


def test_inline_three_leds(inline_board):
    assert len(inline_board.leds) == 3


def test_inline_two_switches(inline_board):
    assert len(inline_board.switches) == 2


def test_inline_vendor_is_xilinx(inline_board):
    assert inline_board.vendor == "Xilinx"


@pytest.fixture(scope="module")
def inline_clocked_board():
    boards = load_board_from_source(_INLINE_SRC_WITH_CLOCK, "<inline_clk>")
    assert boards
    return boards[0]


def test_inline_explicit_50mhz_clock(inline_clocked_board):
    assert inline_clocked_board.default_clock_hz == 50e6


# ── Edge cases ────────────────────────────────────────────────────────────────

_BUTTONS_ONLY_SRC = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
class ButtonsOnlyPlatform(XilinxPlatform):
    resources = [
        *ButtonResources(pins="A B C", attrs=Attrs(IO="TEST")),
        *SwitchResources(pins="X Y", attrs=Attrs(IO="TEST")),
    ]
"""


def test_board_with_no_leds_is_included():
    """A board with only buttons and switches (no LEDs) must still be parsed."""
    boards = load_board_from_source(_BUTTONS_ONLY_SRC, "<buttons_only>")
    assert len(boards) == 1
    assert boards[0].leds == []
    assert len(boards[0].buttons) == 3
    assert len(boards[0].switches) == 2


_PINS_N_SRC = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
class InvertedLedPlatform(XilinxPlatform):
    resources = [
        Resource("led", 0, PinsN("A", dir="o")),
    ]
"""


def test_pinsn_led_sets_inverted_flag():
    """LEDs defined with PinsN must have inverted=True in the parsed ComponentInfo."""
    boards = load_board_from_source(_PINS_N_SRC, "<pinsn>")
    assert len(boards) == 1
    assert boards[0].leds[0].inverted is True


_NO_CLK_SRC = """
from amaranth.build import *
from amaranth.vendor import LatticeICE40Platform
class NoClkPlatform(LatticeICE40Platform):
    resources = [
        *LEDResources(pins="A B", attrs=Attrs(IO="TEST")),
    ]
"""


def test_board_without_default_clk_uses_fallback():
    """Board with no default_clk attribute must fall back to _FALLBACK_CLOCK_HZ."""
    from fpga_sim.board_loader import _FALLBACK_CLOCK_HZ

    boards = load_board_from_source(_NO_CLK_SRC, "<noclk>")
    assert len(boards) == 1
    assert boards[0].default_clock_hz == _FALLBACK_CLOCK_HZ


def test_to_json_with_empty_components_is_valid():
    """BoardDef with no components round-trips to valid JSON with empty lists."""
    import json

    board = BoardDef(name="Empty", class_name="EmptyPlatform")
    data = json.loads(board.to_json())
    assert data["leds"] == []
    assert data["buttons"] == []
    assert data["switches"] == []


def test_discover_boards_ignores_stray_root_files(tmp_path):
    """discover_boards() ignores stray files in the boards root; only subdirs are sources."""
    (tmp_path / "stray.json").write_text("not valid json {{{")
    (tmp_path / "notes.txt").write_text("hello\n")
    boards = discover_boards(tmp_path)
    assert boards == []  # no source subdirectories → nothing discovered


# ═══════════════════════════════════════════════════════════════════════
#  JSON board loading tests
# ═══════════════════════════════════════════════════════════════════════

_SAMPLE_BOARD_JSON = """{
  "name": "Test Board",
  "class_name": "TestBoardPlatform",
  "vendor": "Xilinx",
  "device": "xc7test",
  "package": "csg324",
  "clocks": [100000000],
  "default_clock_hz": 100000000,
  "leds": [{"name": "led", "number": 0, "pins": ["A1"], "direction": "o",
            "inverted": false, "connector": null, "attrs": {}}],
  "buttons": [{"name": "button", "number": 0, "pins": ["B1"], "direction": "i",
               "inverted": true, "connector": null, "attrs": {}}],
  "switches": []
}"""

_SAMPLE_BOARD2_JSON = """{
  "name": "Other Board",
  "class_name": "OtherPlatform",
  "vendor": "Lattice",
  "device": "ice40",
  "package": "",
  "clocks": [12000000],
  "default_clock_hz": 12000000,
  "leds": [{"name": "led", "number": 0}],
  "buttons": [],
  "switches": [{"name": "switch", "number": 0}]
}"""


def test_discover_boards_json_basic(tmp_path):
    """discover_boards() loads JSON files from source subdirectories."""
    src = tmp_path / "source_a"
    src.mkdir()
    (src / "test.json").write_text(_SAMPLE_BOARD_JSON)
    boards = discover_boards(tmp_path)
    assert len(boards) == 1
    assert boards[0].name == "Test Board"
    assert boards[0].vendor == "Xilinx"
    assert len(boards[0].leds) == 1


def test_all_sources_loaded(tmp_path):
    """All sources are loaded; no masking on class_name collision."""
    src_a = tmp_path / "source_a"
    src_b = tmp_path / "source_b"
    src_a.mkdir()
    src_b.mkdir()
    (src_a / "board.json").write_text(_SAMPLE_BOARD_JSON)
    (src_b / "board.json").write_text(_SAMPLE_BOARD_JSON)
    boards = discover_boards(tmp_path)
    assert len(boards) == 2
    assert boards[0].class_name == boards[1].class_name


def test_source_field_set(tmp_path):
    """BoardDef.source is set to the subdirectory name."""
    src = tmp_path / "my-source"
    src.mkdir()
    (src / "board.json").write_text(_SAMPLE_BOARD_JSON)
    boards = discover_boards(tmp_path)
    assert boards[0].source == "my-source"


def test_discover_boards_json_skips_invalid(tmp_path):
    """Malformed JSON files are silently skipped."""
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "bad.json").write_text("not valid json {{{")
    (src / "good.json").write_text(_SAMPLE_BOARD_JSON)
    boards = discover_boards(tmp_path)
    assert len(boards) == 1


def test_json_unknown_fields_ignored_but_port_conventions_loaded(tmp_path):
    """Unknown extra fields don't break loading; port_conventions is now loaded (U21 B1).

    The board-JSON provenance ``source`` object, ``peripherals``, and ``$schema``
    remain unread by the runtime loader, but ``port_conventions`` is threaded into
    ``BoardDef`` for the board-native VHDL matcher.
    """
    import json

    data = json.loads(_SAMPLE_BOARD_JSON)
    data["source"] = {"origin": "custom", "reference_url": "https://example.com"}
    data["peripherals"] = [{"type": "vga", "name": "test"}]
    data["port_conventions"] = {"vendor": {"clk": "CLK50"}}
    data["$schema"] = "../schema/board.schema.json"

    src = tmp_path / "custom"
    src.mkdir()
    (src / "board.json").write_text(json.dumps(data))
    boards = discover_boards(tmp_path)
    assert len(boards) == 1
    assert boards[0].name == "Test Board"
    assert boards[0].port_conventions == {"vendor": {"clk": "CLK50"}}
    # the provenance `source` object is not the runtime `source` field (subdir name)
    assert boards[0].source == "custom"


def test_discover_board_without_conventions_gets_empty_mapping(tmp_path):
    """A board JSON with no port_conventions key loads with an empty mapping."""
    src = tmp_path / "source_a"
    src.mkdir()
    (src / "test.json").write_text(_SAMPLE_BOARD_JSON)  # has no port_conventions
    boards = discover_boards(tmp_path)
    assert boards[0].port_conventions == {}


def test_clocks_object_format(tmp_path):
    """Richer clock format [{name, hz, pin, is_default}] is normalized to Hz list."""
    import json

    data = json.loads(_SAMPLE_BOARD_JSON)
    data["clocks"] = [
        {"name": "clk50", "hz": 50000000, "pin": "AF14", "is_default": True},
        {"name": "clk50_1", "hz": 50000000, "pin": "AA16"},
    ]
    data["default_clock_hz"] = 50000000

    src = tmp_path / "test"
    src.mkdir()
    (src / "board.json").write_text(json.dumps(data))
    boards = discover_boards(tmp_path)
    assert boards[0].clocks == [50000000, 50000000]
    assert boards[0].default_clock_hz == 50000000


def test_clocks_empty_array(tmp_path):
    """Empty clocks array is preserved as-is."""
    import json

    data = json.loads(_SAMPLE_BOARD_JSON)
    data["clocks"] = []

    src = tmp_path / "test"
    src.mkdir()
    (src / "board.json").write_text(json.dumps(data))
    boards = discover_boards(tmp_path)
    assert boards[0].clocks == []


def test_schema_dir_excluded(tmp_path):
    """The schema/ subdirectory is not treated as a source."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "board.schema.json").write_text('{"type": "object"}')
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "board.json").write_text(_SAMPLE_BOARD_JSON)
    boards = discover_boards(tmp_path)
    assert len(boards) == 1


def test_metadata_files_skipped(tmp_path):
    """Files starting with _ (like _sync_metadata.json) are skipped."""
    src = tmp_path / "upstream"
    src.mkdir()
    (src / "_sync_metadata.json").write_text('{"source_commit": "abc123"}')
    (src / "board.json").write_text(_SAMPLE_BOARD_JSON)
    boards = discover_boards(tmp_path)
    assert len(boards) == 1


# ═══════════════════════════════════════════════════════════════════════
#  led_banks -- consecutive same-name runs (U36)
# ═══════════════════════════════════════════════════════════════════════


def _leds(*names: str) -> list[ComponentInfo]:
    return [ComponentInfo("led", n, i) for i, n in enumerate(names)]


def test_led_banks_groups_consecutive_same_name():
    board = BoardDef(name="B", class_name="B", leds=_leds("led", "led", "led_g", "led_g"))
    assert [(n, len(cs)) for n, cs in board.led_banks] == [("led", 2), ("led_g", 2)]


def test_led_banks_de2_115_shape():
    # 18 red LEDR + 9 green LEDG -> two banks (the U36 showcase board)
    leds = _leds(*(["led"] * 18 + ["led_g"] * 9))
    board = BoardDef(name="DE2", class_name="DE2", leds=leds)
    assert [(n, len(cs)) for n, cs in board.led_banks] == [("led", 18), ("led_g", 9)]


def test_led_banks_interleaved_names_split_into_runs():
    board = BoardDef(name="B", class_name="B", leds=_leds("led", "led_g", "led"))
    assert [n for n, _ in board.led_banks] == ["led", "led_g", "led"]


def test_led_banks_empty_when_no_leds():
    assert BoardDef(name="B", class_name="B").led_banks == []


def test_led_banks_components_are_the_actual_leds():
    leds = _leds("led", "led")
    _, comps = BoardDef(name="B", class_name="B", leds=leds).led_banks[0]
    assert comps[0] is leds[0] and comps[1] is leds[1]
