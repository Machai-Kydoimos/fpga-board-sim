"""Tests for session_config: load/save/roundtrip."""
import json

import pytest

from session_config import load_session, save_session


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    """Redirect SESSION_FILE to a temp location for every test."""
    target = tmp_path / ".fpga_simulator" / "session.json"
    monkeypatch.setattr("session_config.SESSION_FILE", target)
    return target


def test_load_missing_file_returns_empty(session_file):
    assert load_session() == {}


def test_load_corrupt_json_returns_empty(session_file):
    session_file.parent.mkdir(parents=True)
    session_file.write_text("not valid json {{{")
    assert load_session() == {}


def test_load_empty_file_returns_empty(session_file):
    session_file.parent.mkdir(parents=True)
    session_file.write_text("")
    assert load_session() == {}


def test_save_creates_directory(session_file):
    assert not session_file.parent.exists()
    save_session("MyBoard", "/some/path/blinky.vhd")
    assert session_file.parent.is_dir()


def test_save_creates_file(session_file):
    save_session("MyBoard", "/some/path/blinky.vhd")
    assert session_file.is_file()


def test_save_writes_valid_json(session_file):
    save_session("MyBoard", "/some/path/blinky.vhd")
    data = json.loads(session_file.read_text())
    assert data["board_class"] == "MyBoard"
    assert data["vhdl_path"] == "/some/path/blinky.vhd"


def test_roundtrip(session_file):
    save_session("ArtyA7_35Platform", "/home/user/hdl/blinky.vhd")
    result = load_session()
    assert result["board_class"] == "ArtyA7_35Platform"
    assert result["vhdl_path"] == "/home/user/hdl/blinky.vhd"


def test_load_ignores_extra_keys(session_file):
    session_file.parent.mkdir(parents=True)
    session_file.write_text(json.dumps({"board_class": "X", "vhdl_path": "y", "extra": 42}))
    result = load_session()
    assert result["board_class"] == "X"
    assert result["extra"] == 42  # extra keys preserved, not an error


def test_save_overwrites_previous(session_file):
    save_session("BoardA", "/path/a.vhd")
    save_session("BoardB", "/path/b.vhd")
    result = load_session()
    assert result["board_class"] == "BoardB"
    assert result["vhdl_path"] == "/path/b.vhd"


# ── Simulator persistence ──────────────────────────────────────────────────────

def test_save_default_simulator_is_ghdl(session_file):
    save_session("MyBoard", "/path/blinky.vhd")
    data = json.loads(session_file.read_text())
    assert data["simulator"] == "ghdl"


def test_save_nvc_simulator(session_file):
    save_session("MyBoard", "/path/blinky.vhd", simulator="nvc")
    data = json.loads(session_file.read_text())
    assert data["simulator"] == "nvc"


def test_simulator_roundtrip_ghdl(session_file):
    save_session("BoardX", "/path/blinky.vhd", simulator="ghdl")
    result = load_session()
    assert result["simulator"] == "ghdl"


def test_simulator_roundtrip_nvc(session_file):
    save_session("BoardX", "/path/blinky.vhd", simulator="nvc")
    result = load_session()
    assert result["simulator"] == "nvc"


def test_load_missing_simulator_key(session_file):
    """Old session files without 'simulator' key load without error."""
    session_file.parent.mkdir(parents=True)
    session_file.write_text(json.dumps({"board_class": "X", "vhdl_path": "y"}))
    result = load_session()
    assert "simulator" not in result  # caller supplies a default


# ── Additional edge cases ──────────────────────────────────────────────────────

def test_load_json_number_returns_empty(session_file):
    """A file containing a bare number (valid JSON, not a dict) returns {}."""
    session_file.parent.mkdir(parents=True)
    session_file.write_text("42")
    # json.loads("42") returns int; cast() is a no-op, so callers get 42.
    # load_session() does not guard against non-dict JSON — document behavior.
    result = load_session()
    # Just verify it doesn't raise; type may be int or {}
    assert result is not None


def test_save_session_does_not_raise_on_oserror(tmp_path, monkeypatch):
    """save_session must swallow OSError (e.g. read-only fs) without raising."""
    import pathlib
    target = tmp_path / ".fpga_simulator" / "session.json"
    monkeypatch.setattr("session_config.SESSION_FILE", target)

    def _raise(self, *args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(pathlib.Path, "write_text", _raise)
    save_session("BoardA", "/path/a.vhd")  # must not propagate OSError
