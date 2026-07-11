"""Tests for the shared sync scaffolding in ``scripts/sync_common.py``.

Focus: the schema-validation gate that ``write_outputs`` runs before writing, so
a parser regression is caught at sync time (not later in the board-schema test
suite). Validation is exercised against the real board schema.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Add scripts/ to path for importing (conftest also does this; kept for standalone runs).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from sync_common import validate_board_jsons, write_outputs  # noqa: E402

SCHEMA_PATH = Path(__file__).parent.parent / "boards" / "schema" / "board.schema.json"


def _valid_board() -> dict[str, Any]:
    """Return a minimal board dict satisfying every required schema field."""
    return {
        "name": "Test Board",
        "class_name": "TestPlatform",
        "vendor": "Xilinx",
        "device": "xc7test",
        "clocks": [100000000],
        "default_clock_hz": 100000000,
        "leds": [],
        "buttons": [],
        "switches": [],
    }


def _jsons(boards: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Serialize a {filename: board-dict} map the way the sync scripts do."""
    return {name: json.dumps(board, indent=2) + "\n" for name, board in boards.items()}


# ── validate_board_jsons ─────────────────────────────────────────────────────


def test_validate_passes_for_valid_board():
    validate_board_jsons(_jsons({"ok.json": _valid_board()}), SCHEMA_PATH)


def test_validate_flags_missing_required_field():
    bad = _valid_board()
    del bad["vendor"]
    with pytest.raises(ValueError) as exc:
        validate_board_jsons(_jsons({"bad.json": bad}), SCHEMA_PATH)
    assert "bad.json" in str(exc.value)
    assert "vendor" in str(exc.value)


def test_validate_flags_wrong_type():
    bad = _valid_board()
    bad["leds"] = "not-a-list"
    with pytest.raises(ValueError, match="bad.json"):
        validate_board_jsons(_jsons({"bad.json": bad}), SCHEMA_PATH)


def test_validate_reports_every_bad_board_at_once():
    b1 = _valid_board()
    del b1["vendor"]
    b2 = _valid_board()
    del b2["device"]
    with pytest.raises(ValueError) as exc:
        validate_board_jsons(_jsons({"b1.json": b1, "b2.json": b2}), SCHEMA_PATH)
    msg = str(exc.value)
    assert "b1.json" in msg and "b2.json" in msg


def test_validate_missing_schema_raises_filenotfound(tmp_path):
    with pytest.raises(FileNotFoundError, match="schema"):
        validate_board_jsons(_jsons({"ok.json": _valid_board()}), tmp_path / "nope.json")


# ── write_outputs (validation gate + write behavior) ─────────────────────────


def _boards_root(tmp_path: Path) -> Path:
    """Build a tmp boards/ layout: a schema/ dir (real schema) + return the root."""
    schema_dir = tmp_path / "schema"
    schema_dir.mkdir()
    (schema_dir / "board.schema.json").write_text(SCHEMA_PATH.read_text(), encoding="utf-8")
    return tmp_path


def test_write_outputs_writes_valid_board(tmp_path):
    root = _boards_root(tmp_path)
    out = root / "test-source"
    write_outputs(out, _jsons({"ok.json": _valid_board()}), "abc123", "owner/repo")
    assert (out / "ok.json").exists()
    assert (out / "_sync_metadata.json").exists()


def test_write_outputs_aborts_on_invalid_with_no_partial_output(tmp_path):
    root = _boards_root(tmp_path)
    out = root / "test-source"
    bad = _valid_board()
    del bad["vendor"]
    with pytest.raises(ValueError):
        write_outputs(out, _jsons({"bad.json": bad}), "abc123", "owner/repo")
    # Nothing should have been written — not even the directory.
    assert not out.exists()


def test_write_outputs_derives_default_schema_path(tmp_path):
    root = _boards_root(tmp_path)
    out = root / "test-source"
    # schema_path omitted -> derived as out.parent / "schema" / "board.schema.json".
    write_outputs(out, _jsons({"ok.json": _valid_board()}), "abc123", "owner/repo")
    assert (out / "ok.json").exists()


def test_write_outputs_dry_run_still_validates(tmp_path):
    root = _boards_root(tmp_path)
    out = root / "test-source"
    bad = _valid_board()
    del bad["vendor"]
    with pytest.raises(ValueError):
        write_outputs(out, _jsons({"bad.json": bad}), "abc123", "owner/repo", dry_run=True)


def test_write_outputs_dry_run_writes_nothing_when_valid(tmp_path):
    root = _boards_root(tmp_path)
    out = root / "test-source"
    write_outputs(out, _jsons({"ok.json": _valid_board()}), "abc123", "owner/repo", dry_run=True)
    assert not out.exists()


# ── write_outputs (re-sync preservation guard, U21 A1) ───────────────────────


def test_write_outputs_first_sync_no_existing_file(tmp_path):
    """No prior file on disk: content passes through byte-identical."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    content = json.dumps(_valid_board(), indent=2) + "\n"
    write_outputs(out, {"board.json": content}, "abc123", "owner/repo")
    assert (out / "board.json").read_text() == content


def test_write_outputs_no_conventions_round_trips_byte_identical(tmp_path):
    """An existing file with no port_conventions/peripherals: fresh content is
    written verbatim, not re-serialized -- proves a re-sync's git diff stays
    silent on the vast majority of boards that carry neither key."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["device"] = "old-device"
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    fresh = _valid_board()
    fresh["device"] = "new-device"
    fresh_content = json.dumps(fresh, indent=2) + "\n"
    write_outputs(out, {"board.json": fresh_content}, "abc123", "owner/repo")

    assert (out / "board.json").read_text() == fresh_content


def test_write_outputs_preserves_existing_port_conventions(tmp_path):
    """A hand-authored/populated port_conventions block survives a re-sync
    that itself generates none (the amaranth/litex case)."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["device"] = "old-device"
    existing["port_conventions"] = {"custom": {"clk": "CLK"}}
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    fresh = _valid_board()
    fresh["device"] = "new-device"
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo")

    written = json.loads((out / "board.json").read_text())
    assert written["device"] == "new-device"  # the parser's regenerated key updates
    assert written["port_conventions"] == {"custom": {"clk": "CLK"}}  # preserved


def test_write_outputs_digilent_per_key_merge(tmp_path):
    """sync_digilent_xdc.py generates only the 'digilent' sub-key: that one
    updates, every other convention key (hand-authored or U21-populated)
    survives untouched."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["port_conventions"] = {
        "digilent": {"clk": "CLK_STALE"},
        "terasic": {"clk": "CLOCK_50"},
    }
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    fresh = _valid_board()
    fresh["port_conventions"] = {"digilent": {"clk": "CLK_FRESH"}}
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo")

    written = json.loads((out / "board.json").read_text())
    assert written["port_conventions"]["digilent"] == {"clk": "CLK_FRESH"}
    assert written["port_conventions"]["terasic"] == {"clk": "CLOCK_50"}


def test_write_outputs_preserves_existing_peripherals(tmp_path):
    """peripherals has no generator yet, so an existing list is kept wholesale."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["peripherals"] = [{"type": "vga", "name": "ADV7123"}]
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    write_outputs(out, _jsons({"board.json": _valid_board()}), "abc123", "owner/repo")

    written = json.loads((out / "board.json").read_text())
    assert written["peripherals"] == [{"type": "vga", "name": "ADV7123"}]


def test_write_outputs_validates_merged_content_not_just_fresh(tmp_path):
    """A corrupted on-disk port_conventions block is caught by the schema
    gate, not silently folded into the output unvalidated."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["port_conventions"] = {"custom": {"seven_seg": {"style": "not-a-real-style"}}}
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="board.json"):
        write_outputs(out, _jsons({"board.json": _valid_board()}), "abc123", "owner/repo")


def test_write_outputs_dry_run_preserves_without_writing(tmp_path):
    """The merge-and-validate path runs under --dry-run too (read-only), but
    nothing is written to disk."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["port_conventions"] = {"custom": {"clk": "CLK"}}
    original = json.dumps(existing, indent=2) + "\n"
    (out / "board.json").write_text(original, encoding="utf-8")

    write_outputs(out, _jsons({"board.json": _valid_board()}), "abc123", "owner/repo", dry_run=True)

    assert (out / "board.json").read_text() == original  # untouched
