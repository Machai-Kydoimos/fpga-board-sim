"""Tests that all board JSON files validate against the schema."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

BOARDS_DIR = Path(__file__).parent.parent / "boards"
SCHEMA_PATH = BOARDS_DIR / "schema" / "board.schema.json"


def _all_board_json_files() -> Iterator[Path]:
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


def _minimal_valid_board() -> dict[str, Any]:
    """A board with exactly the required fields and nothing else."""
    return {
        "name": "T",
        "class_name": "TP",
        "vendor": "X",
        "device": "d",
        "clocks": [1000000],
        "default_clock_hz": 1000000,
        "leds": [],
        "buttons": [],
        "switches": [],
    }


def test_schema_forbids_unknown_top_level_key(schema):
    """additionalProperties:false on the board object catches typo'd field names."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["default_clk_hz"] = 1  # typo of default_clock_hz
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(board, schema)


def test_schema_forbids_unknown_component_key(schema):
    """Components (led/button/switch) reject undeclared keys too."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["leds"] = [{"name": "led", "number": 0, "bogus": 1}]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(board, schema)


def test_schema_allows_extra_peripheral_key(schema):
    """peripherals stay open (additionalProperties:true) for future typed fields."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["peripherals"] = [{"type": "vga", "bits_per_channel": 8, "future_field": "x"}]
    jsonschema.validate(board, schema)  # must not raise


def test_schema_allows_extra_port_convention_key(schema):
    """port_conventions stay open while the feature's shape is still settling."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {"terasic": {"some_future_field": "x"}}
    jsonschema.validate(board, schema)  # must not raise


@pytest.mark.parametrize(
    "style", ["packed_vector", "individual", "per_segment_scalars", "scan", "serial"]
)
def test_schema_validates_new_seg_styles(schema, style):
    """Every seg_port_mapping.style value (incl. U21's three new ones) validates."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {"conv": {"seven_seg": {"style": style}}}
    jsonschema.validate(board, schema)  # must not raise


def test_schema_rejects_invalid_seg_style(schema):
    """An undeclared seg_port_mapping.style value fails validation."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {"conv": {"seven_seg": {"style": "bogus"}}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(board, schema)


def test_schema_validates_scan_digit_enable(schema):
    """The 'scan' style's digit_enable port_mapping (shared segs + strobe) validates."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {
        "conv": {
            "seven_seg": {
                "style": "scan",
                "name": "seg",
                "width_per_digit": 7,
                "digit_enable": {"name": "an", "width": 4, "active_low": True},
            }
        }
    }
    jsonschema.validate(board, schema)  # must not raise


def test_schema_validates_convention_source_and_naming(schema):
    """port_convention.source (registry provenance) and .naming validate."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {
        "conv": {
            "naming": "canonical",
            "source": {
                "url": "https://example.com/board.xdc",
                "retrieved": "2026-07-11",
                "registry_board": "example_board",
            },
        }
    }
    jsonschema.validate(board, schema)  # must not raise


def test_schema_rejects_invalid_naming(schema):
    """naming is a closed enum: canonical / project-derived."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {"conv": {"naming": "bogus"}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(board, schema)


def test_schema_rejects_unknown_convention_source_key(schema):
    """convention_source is closed (additionalProperties:false) — typos get caught."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {
        "conv": {"source": {"url": "https://x", "retrieved_at": "2026-07-11"}}
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(board, schema)


def test_schema_validates_leds_green(schema):
    """leds_green (Terasic-style secondary LED bank) is now a typed port_mapping."""
    jsonschema = pytest.importorskip("jsonschema")
    board = _minimal_valid_board()
    board["port_conventions"] = {"terasic": {"leds_green": {"name": "LEDG", "width": 9}}}
    jsonschema.validate(board, schema)  # must not raise
