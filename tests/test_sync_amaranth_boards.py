"""Tests for the board sync script's core functions."""

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to path for importing
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from sync_amaranth_boards import generate_board_json  # noqa: E402
from sync_common import sanitize_filename, unique_name  # noqa: E402


def test_sanitize_filename_basic():
    assert sanitize_filename("Arty A7-35") == "arty_a7-35"
    assert sanitize_filename("iCEBreaker") == "icebreaker"
    assert sanitize_filename("Tang Nano 9K") == "tang_nano_9k"
    assert sanitize_filename("DE10-Lite") == "de10-lite"


def test_sanitize_filename_edge_cases():
    assert sanitize_filename("  Leading Spaces  ") == "leading_spaces"
    assert sanitize_filename("A__B") == "a_b"
    assert sanitize_filename("") == ""


def test_unique_name_no_collision():
    seen: dict[str, int] = {}
    assert unique_name("board_a", seen) == "board_a"
    assert unique_name("board_b", seen) == "board_b"


def test_unique_name_collision():
    seen: dict[str, int] = {}
    assert unique_name("board", seen) == "board"
    assert unique_name("board", seen) == "board_2"
    assert unique_name("board", seen) == "board_3"


_INLINE_BOARD_SOURCE = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
__all__ = ["SyncTestPlatform"]
class SyncTestPlatform(XilinxPlatform):
    default_clk = "clk100"
    resources = [
        Resource("clk100", 0, Pins("E3", dir="i"), Clock(100e6), Attrs(IO="LVCMOS")),
        *LEDResources(pins="A B C D", attrs=Attrs(IO="TEST")),
        *ButtonResources(pins="X Y", attrs=Attrs(IO="TEST")),
        *SwitchResources(pins="S1 S2 S3", attrs=Attrs(IO="TEST")),
    ]
"""


def test_generate_board_json_roundtrip():
    """generate_board_json() produces valid JSON from board source."""
    board_files = {"sync_test.py": _INLINE_BOARD_SOURCE}
    results = generate_board_json(board_files, "abc123def")
    assert len(results) == 1

    filename = list(results.keys())[0]
    assert filename.endswith(".json")

    data = json.loads(results[filename])
    assert data["name"] == "Sync Test"
    assert data["class_name"] == "SyncTestPlatform"
    assert data["vendor"] == "Xilinx"
    assert len(data["leds"]) == 4
    assert len(data["buttons"]) == 2
    assert len(data["switches"]) == 3
    assert data["default_clock_hz"] == 100e6
    assert data["$schema"] == "../schema/board.schema.json"
    assert data["source"]["origin"] == "amaranth-boards"
    assert data["source"]["sync_commit"] == "abc123def"
    assert data["source"]["upstream_file"] == "sync_test.py"


def test_generate_board_json_emits_amaranth_convention():
    """U32: the amaranth parser emits a framework-derived port_conventions block."""
    results = generate_board_json({"sync_test.py": _INLINE_BOARD_SOURCE}, "abc123def")
    data = json.loads(next(iter(results.values())))
    conv = data["port_conventions"]["amaranth"]
    assert conv["clk"] == "clk100"
    assert conv["leds"] == {"name": "led", "width": 4}
    assert conv["switches"] == {"name": "switch", "width": 3}
    assert conv["buttons"] == {"name": "button", "width": 2}
    assert conv["naming"] == "framework-derived"


# U56 Phase 2: the Nexys 4 DDR declares switches 8 and 9 in a second call (they sit
# on a 1.8 V bank), after 10-15.
_SWITCHES_SPLIT_SOURCE = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
__all__ = ["SwitchSplitPlatform"]
class SwitchSplitPlatform(XilinxPlatform):
    default_clk = "clk100"
    resources = [
        Resource("clk100", 0, Pins("E3", dir="i"), Clock(100e6), Attrs(IO="LVCMOS")),
        *LEDResources(pins="A B", attrs=Attrs(IO="TEST")),
        *SwitchResources(pins={0: "S0", 1: "S1", 10: "S10"}, attrs=Attrs(IO="LVCMOS33")),
        *SwitchResources(pins={8: "S8", 9: "S9"}, attrs=Attrs(IO="LVCMOS18")),
    ]
"""


def test_switches_follow_their_numbers_not_their_declaration():
    """A design's sw(8) is switch 8: the board lists a name's switches in number order."""
    results = generate_board_json({"split.py": _SWITCHES_SPLIT_SOURCE}, "abc123def")
    data = json.loads(next(iter(results.values())))
    assert [c["number"] for c in data["switches"]] == [0, 1, 8, 9, 10]
    assert [c["pins"] for c in data["switches"]] == [["S0"], ["S1"], ["S8"], ["S9"], ["S10"]]


_OLED_SOURCE = """
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
__all__ = ["OledPlatform"]
class OledPlatform(XilinxPlatform):
    default_clk = "clk100"
    resources = [
        Resource("clk100", 0, Pins("E3", dir="i"), Clock(100e6), Attrs(IO="LVCMOS")),
        *LEDResources(pins="A B C D", attrs=Attrs(IO="TEST")),
        Resource("m2led", 0, Pins("M1", dir="o"), Attrs(IO="TEST")),
        Resource("oled", 0, Pins("P1 P2 P3", dir="o"), Attrs(IO="TEST")),
    ]
"""


def test_oled_dropped_but_m2led_kept():
    """U33 Wave 4: `oled` (OLED bus) is not a LED; `m2led` (M.2 status LED) is."""
    results = generate_board_json({"oled_test.py": _OLED_SOURCE}, "abc123def")
    data = json.loads(next(iter(results.values())))
    names = [c["name"] for c in data["leds"]]
    assert names.count("led") == 4  # the LEDResources
    assert "m2led" in names  # digit before "led" -> kept
    assert not any("oled" in n for n in names)  # OLED bus dropped
    assert len(data["leds"]) == 5


def test_generate_board_json_skips_broken():
    """Broken board files are skipped without raising."""
    board_files = {
        "broken.py": "class Broken(: syntax error",
        "sync_test.py": _INLINE_BOARD_SOURCE,
    }
    results = generate_board_json(board_files, "abc123")
    assert len(results) == 1


def test_sync_metadata_structure():
    """Verify _sync_metadata.json is written correctly."""
    boards_dir = Path(__file__).parent.parent / "boards" / "amaranth-boards"
    meta_path = boards_dir / "_sync_metadata.json"
    if not meta_path.exists():
        pytest.skip("Sync metadata not generated yet")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert "source_repo" in meta
    assert "source_commit" in meta
    assert "sync_timestamp" in meta
    assert "board_count" in meta
    assert "files_written" in meta
    assert meta["board_count"] > 50
    assert isinstance(meta["files_written"], list)


# ═══════════════════════════════════════════════════════════════════════
#  LED colors + RGB-trio reclassification (U36)
# ═══════════════════════════════════════════════════════════════════════

_RGB_TRIO_SOURCE = """
from amaranth.build import *
from amaranth.vendor import LatticeICE40Platform
__all__ = ["TrioPlatform"]
class TrioPlatform(LatticeICE40Platform):
    resources = [
        *LEDResources(pins="A B C", attrs=Attrs(IO="T")),
        Resource("led_r", 0, PinsN("D", dir="o")),
        Resource("led_g", 0, PinsN("E", dir="o")),
        Resource("led_b", 0, PinsN("F", dir="o")),
    ]
"""

_DISCRETE_4COLOR_SOURCE = """
from amaranth.build import *
from amaranth.vendor import LatticeICE40Platform
__all__ = ["QuadPlatform"]
class QuadPlatform(LatticeICE40Platform):
    resources = [
        *LEDResources(pins="P0 P1 P2 P3", attrs=Attrs(IO="T")),
        Resource("led_r", 0, Pins("R0", dir="o")),
        Resource("led_g", 0, Pins("G0", dir="o")),
        Resource("led_b", 0, Pins("B0", dir="o")),
        Resource("led_o", 0, Pins("O0", dir="o")),
    ]
"""

_DISCRETE_PAIR_SOURCE = """
from amaranth.build import *
from amaranth.vendor import LatticeICE40Platform
__all__ = ["PairPlatform"]
class PairPlatform(LatticeICE40Platform):
    resources = [
        *LEDResources(pins="A B", attrs=Attrs(IO="T")),
        Resource("led_r", 0, Pins("R0", dir="o")),
        Resource("led_g", 0, Pins("G0", dir="o")),
    ]
"""


def _leds_of(source: str) -> list[dict[str, object]]:
    results = generate_board_json({"t.py": source}, "abc")
    leds: list[dict[str, object]] = json.loads(next(iter(results.values())))["leds"]
    return leds


def test_rgb_trio_coalesced_to_one_rgb_led():
    """U36: a scalar led_r/led_g/led_b trio folds into one 3-pin rgb_led (r,g,b order)."""
    leds = _leds_of(_RGB_TRIO_SOURCE)
    names = [c["name"] for c in leds]
    assert names.count("led") == 3
    assert names.count("rgb_led") == 1
    assert not any(n in ("led_r", "led_g", "led_b") for n in names)
    rgb = next(c for c in leds if c["name"] == "rgb_led")
    assert rgb["pins"] == ["D", "E", "F"]  # red, green, blue
    assert "color" not in rgb  # an rgb_led carries no single color


def test_rgb_trio_with_fourth_color_stays_discrete():
    """U36: a 4th color (orange) proves the bank is discrete -- no coalescing."""
    by_name = {c["name"]: c for c in _leds_of(_DISCRETE_4COLOR_SOURCE)}
    assert "rgb_led" not in by_name
    assert by_name["led_r"]["color"] == "red"
    assert by_name["led_g"]["color"] == "green"
    assert by_name["led_b"]["color"] == "blue"
    assert by_name["led_o"]["color"] == "orange"


def test_red_green_pair_stays_discrete():
    """U36: a red+green pair (no blue) is two discrete LEDs, not one RGB."""
    by_name = {c["name"]: c for c in _leds_of(_DISCRETE_PAIR_SOURCE)}
    assert "rgb_led" not in by_name
    assert by_name["led_r"]["color"] == "red"
    assert by_name["led_g"]["color"] == "green"


def test_plain_led_bank_has_no_color():
    """U36: a bare `led` gets no name-derived color (only registry/custom populate those)."""
    assert all("color" not in c for c in _leds_of(_INLINE_BOARD_SOURCE))


def test_led_generation_is_deterministic():
    """U36: color + reclassification are pure -> identical LED output across runs."""
    assert _leds_of(_RGB_TRIO_SOURCE) == _leds_of(_RGB_TRIO_SOURCE)


# ── identity and outcomes (U56 plan §4.1–4.2) ──────────────────────────────────


def test_read_amaranth_file_records_each_class_as_identity():
    from amaranth_parser import read_amaranth_file

    outcome = read_amaranth_file(_INLINE_BOARD_SOURCE, "sync_test.py")
    assert outcome.outcome == "boards"
    assert [b.upstream_class for b in outcome.boards] == [
        b.board["class_name"] for b in outcome.boards
    ]
    assert all(b.upstream_args == {} for b in outcome.boards)


def test_read_amaranth_file_tells_an_empty_board_from_a_non_board():
    from amaranth_parser import read_amaranth_file

    empty = "class BarePlatform(LatticeICE40Platform):\n    resources = []\n"
    assert read_amaranth_file(empty, "bare.py").detail == "not_a_board"
    no_io = (
        "class UartOnlyPlatform(LatticeICE40Platform):\n"
        "    resources = [UARTResource(0, rx='1', tx='2')]\n"
    )
    assert read_amaranth_file(no_io, "uart_only.py").detail == "no_simulatable_io"
    broken = read_amaranth_file("class X(Missing):\n    pass\n", "broken.py")
    assert (broken.outcome, broken.detail) == ("error", "NameError: Missing")


# ── The default clock: on-chip oscillators and D-6 (U56 Phases 1c and 2) ─────

_OSCILLATOR_BOARD = """
from amaranth.build import *
from amaranth.vendor import {base}
__all__ = ["OscTestPlatform"]
class OscTestPlatform({base}):
    default_clk = "{clk}"
{attrs}
    resources = [*LEDResources(pins="A B", attrs=Attrs(IO="TEST"))]
"""


@pytest.mark.parametrize(
    ("base", "clk", "attrs", "hz"),
    [
        ("LatticeECP5Platform", "OSCG", "    oscg_div = 2", 155e6),
        ("LatticeMachXO2Platform", "OSCH", "    osch_frequency = 2.08", 2.08e6),
        ("LatticeECP5Platform", "OSCA", "    osca_div = 9", 50e6),
        ("LatticeICE40Platform", "SB_HFOSC", "    hfosc_div = 2", 12e6),
        ("LatticeICE40Platform", "SB_LFOSC", "", 10e3),
        ("IntelPlatform", "cyclonev_oscillator", "", 100e6),
        ("QuicklogicPlatform", "sys_clk0", "    osc_freq = 60e6\n    osc_div = 2", 30e6),
        ("GowinPlatform", "OSC", "    osc_frequency = 27e6", 27e6),
    ],
)
def test_an_on_chip_oscillator_sets_the_default_clock(base, clk, attrs, hz):
    """Each ``default_clk`` that names an oscillator reads its frequency from the class."""
    source = _OSCILLATOR_BOARD.format(base=base, clk=clk, attrs=attrs)
    data = json.loads(next(iter(generate_board_json({"osc_test.py": source}, "c0ffee").values())))
    assert data["default_clock_hz"] == pytest.approx(hz)
    assert "default_clock_assumed" not in data, "upstream states this frequency"


def test_a_default_clock_upstream_gives_no_frequency_is_marked_assumed():
    """The oscillator's divider is unset, so 12 MHz is our fallback, and says so (D-6)."""
    source = _OSCILLATOR_BOARD.format(base="LatticeICE40Platform", clk="SB_HFOSC", attrs="")
    data = json.loads(next(iter(generate_board_json({"osc_test.py": source}, "c0ffee").values())))
    assert data["default_clock_hz"] == 12e6
    assert data["default_clock_assumed"] is True


# ── multi-pin resources (U56 Phase 5, D-3) ─────────────────────────────────────

_MULTI_PIN_SOURCE = """
from amaranth.build import *
from amaranth.vendor import LatticeECP5Platform
__all__ = ["MultiPinPlatform"]
class MultiPinPlatform(LatticeECP5Platform):
    default_clk = "clk100"
    resources = [
        Resource("clk100", 0, Pins("P3", dir="i"), Clock(100e6)),
        *LEDResources(pins="E16 D17", invert=True),
        Resource("alnum_led", 0,
            Subsignal("a", PinsN("M20", dir="o")),
            Subsignal("b", PinsN("L18", dir="o")),
            Subsignal("dp", Pins("U1", dir="o"))),
        Resource("led_cathodes", 0, Pins("P19 L18 K18")),
        Resource("mic_led", 0,
            Subsignal("clk", Pins("P9", dir="o")),
            Subsignal("dat", Pins("T9", dir="o"))),
    ]
"""


def test_multi_pin_resources_split_or_stay_whole_by_shape():
    from amaranth_parser import read_amaranth_file

    outcome = read_amaranth_file(_MULTI_PIN_SOURCE, "multi_pin.py")
    leds = outcome.boards[0].board["leds"]
    assert [(c["name"], c["number"], c["pins"], c["inverted"]) for c in leds] == [
        ("led", 0, ["E16"], True),
        ("led", 1, ["D17"], True),
        # The Versa's segments: one LED each, each with its own pins' polarity.
        ("alnum_led", 0, ["M20"], True),
        ("alnum_led", 1, ["L18"], True),
        ("alnum_led", 2, ["U1"], False),
        # Bidirectional (Amaranth's default direction) and a bus: whole, as before.
        ("led_cathodes", 0, ["P19", "L18", "K18"], False),
        ("mic_led", 0, ["P9", "T9"], False),
    ]
    assert outcome.warnings == [
        "MultiPinPlatform: unsupported_shape: led_cathodes 0 (bidirectional)",
        "MultiPinPlatform: unsupported_shape: mic_led 0 (sub-signals clk, dat)",
    ]
    # The split segments never become the LED bank (D-3); `led` stays it.
    conv = outcome.boards[0].board["port_conventions"]["amaranth"]
    assert conv["leds"] == {"name": "led", "width": 2, "active_low": True}
