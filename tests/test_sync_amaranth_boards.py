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

    meta = json.loads(meta_path.read_text())
    assert "source_repo" in meta
    assert "source_commit" in meta
    assert "sync_timestamp" in meta
    assert "board_count" in meta
    assert "files_written" in meta
    assert meta["board_count"] > 50
    assert isinstance(meta["files_written"], list)
