"""Tests for scripts/check_board_drift.py (the U38 board-data drift tripwire).

The script is subprocess orchestration; these cover its pure pieces — the
pin reading and the source table — not the git/network choreography (which
the CI job itself exercises on every PR).
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import check_board_drift as cbd


def test_sources_cover_every_generated_boards_directory() -> None:
    generated = {
        p.parent.name
        for p in (Path(__file__).parent.parent / "boards").glob("*/_sync_metadata.json")
    }
    assert generated == {subdir for _script, subdir in cbd.SOURCES}


def test_read_pins_returns_a_sha_per_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cbd, "BOARDS_DIR", tmp_path)
    for _script, subdir in cbd.SOURCES:
        d = tmp_path / subdir
        d.mkdir()
        (d / "_sync_metadata.json").write_text(json.dumps({"source_commit": f"sha-{subdir}"}))
    pins = cbd.read_pins()
    assert pins == {subdir: f"sha-{subdir}" for _s, subdir in cbd.SOURCES}
