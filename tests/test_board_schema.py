"""Tests that all board JSON files validate against the schema."""

import json
from pathlib import Path

import pytest

BOARDS_DIR = Path(__file__).parent.parent / "boards"
SCHEMA_PATH = BOARDS_DIR / "schema" / "board.schema.json"


def _all_board_json_files():
    """Yield all board JSON files from all source directories."""
    for source_dir in sorted(BOARDS_DIR.iterdir()):
        if not source_dir.is_dir() or source_dir.name == "schema":
            continue
        for json_file in sorted(source_dir.glob("*.json")):
            if json_file.name.startswith("_"):
                continue
            yield json_file


@pytest.fixture(scope="module")
def schema():
    return json.loads(SCHEMA_PATH.read_text())


@pytest.fixture(scope="module")
def board_files():
    return list(_all_board_json_files())


def test_schema_exists():
    assert SCHEMA_PATH.exists(), f"Schema not found: {SCHEMA_PATH}"


def test_board_files_exist(board_files):
    assert len(board_files) > 50, f"Expected 50+ boards, found {len(board_files)}"


@pytest.mark.parametrize("json_file", list(_all_board_json_files()), ids=lambda p: p.stem)
def test_board_has_required_fields(json_file):
    """Every board JSON has the required fields for BoardDef.from_json()."""
    data = json.loads(json_file.read_text())
    assert "name" in data
    assert "class_name" in data
    assert "vendor" in data
    assert "device" in data
    assert "clocks" in data
    assert "default_clock_hz" in data
    assert "leds" in data
    assert "buttons" in data
    assert "switches" in data
    assert isinstance(data["leds"], list)
    assert isinstance(data["buttons"], list)
    assert isinstance(data["switches"], list)


@pytest.mark.parametrize("json_file", list(_all_board_json_files()), ids=lambda p: p.stem)
def test_board_loads_as_boarddef(json_file):
    """Every board JSON deserializes to a valid BoardDef."""
    from fpga_sim.board_loader import BoardDef

    raw = json_file.read_text()
    board = BoardDef.from_json(raw)
    assert board.name
    assert board.class_name
    assert isinstance(board.clocks, list)
    assert board.default_clock_hz > 0


def test_schema_validates_with_jsonschema(schema, board_files):
    """Validate all boards against the JSON Schema (requires jsonschema)."""
    try:
        import jsonschema
    except ImportError:
        pytest.skip("jsonschema not installed")

    for json_file in board_files:
        data = json.loads(json_file.read_text())
        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as e:
            pytest.fail(f"{json_file.name}: {e.message}")
