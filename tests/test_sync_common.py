"""Tests for the shared sync scaffolding in ``scripts/sync_common.py``.

Focus: the schema-validation gate that ``write_outputs`` runs before writing, so
a parser regression is caught at sync time (not later in the board-schema test
suite). Validation is exercised against the real board schema.
"""

import json
import sys
from pathlib import Path

import pytest

# Add scripts/ to path for importing (conftest also does this; kept for standalone runs).
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from sync_common import validate_board_jsons, write_outputs  # noqa: E402

SCHEMA_PATH = Path(__file__).parent.parent / "boards" / "schema" / "board.schema.json"


def _valid_board() -> dict:
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


def _jsons(boards: dict) -> dict:
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
