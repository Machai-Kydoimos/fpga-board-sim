"""Tests for board_loader: discovery, parsing, and spot-checks."""
import pytest
from board_loader import (
    BoardDef,
    ComponentInfo,
    discover_boards,
    get_default_boards_path,
    load_board_from_source,
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
    assert len(matches) == 1


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


def test_nexys_has_named_buttons(all_boards):
    nexys = [b for b in all_boards if "Nexys4" in b.name]
    if not nexys:
        pytest.skip("Nexys4 board not found in submodule")
    named = [b for b in nexys[0].buttons if b.name != "button"]
    assert len(named) > 0, "Expected named buttons on Nexys4"


_INLINE_SRC = '''
from amaranth.build import *
from amaranth.vendor import XilinxPlatform
__all__ = ["InlineTestPlatform"]
class InlineTestPlatform(XilinxPlatform):
    resources = [
        *LEDResources(pins="A B C", attrs=Attrs(IO="TEST")),
        *SwitchResources(pins="X Y", attrs=Attrs(IO="TEST")),
    ]
'''


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
