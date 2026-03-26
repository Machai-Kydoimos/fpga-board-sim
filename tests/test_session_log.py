"""Tests for sim_session_log.save_session_stats()."""
import json

import pytest

from sim_session_log import save_session_stats


@pytest.fixture
def session_dir(tmp_path, monkeypatch):
    """Redirect _SESSION_DIR to a temp directory for every test."""
    target = tmp_path / "sessions"
    monkeypatch.setattr("sim_session_log._SESSION_DIR", target)
    return target


def _call(**overrides):
    """Call save_session_stats with valid defaults; allow field overrides."""
    kwargs = dict(
        board_name="Test Board",
        simulator="ghdl",
        duration_s=10.0,
        avg_fps=60.0,
        sim_time_ns=1_000_000,
        avg_ghdl_pct=80.0,
        avg_draw_pct=15.0,
        avg_idle_pct=5.0,
        clock_hz=100e6,
    )
    kwargs.update(overrides)
    return save_session_stats(**kwargs)


def test_creates_session_dir(session_dir):
    assert not session_dir.exists()
    _call()
    assert session_dir.is_dir()


def test_returns_path_in_session_dir(session_dir):
    path = _call()
    assert path.parent == session_dir


def test_file_is_valid_json(session_dir):
    path = _call()
    data = json.loads(path.read_text())
    assert isinstance(data, dict)


def test_json_has_required_keys(session_dir):
    path = _call()
    data = json.loads(path.read_text())
    for key in ("timestamp", "board", "simulator", "duration_s", "avg_fps",
                "sim_time_ns", "sim_rate", "avg_ghdl_pct", "avg_draw_pct",
                "avg_idle_pct", "clock_hz"):
        assert key in data, f"missing key: {key}"


def test_board_and_simulator_stored(session_dir):
    path = _call(board_name="Arty A7-35", simulator="nvc")
    data = json.loads(path.read_text())
    assert data["board"] == "Arty A7-35"
    assert data["simulator"] == "nvc"


def test_filename_contains_board_slug(session_dir):
    path = _call(board_name="Arty A7-35")
    # spaces and hyphens become underscores; specials stripped
    assert "Arty_A7-35" in path.name


def test_sim_rate_is_positive(session_dir):
    path = _call(duration_s=5.0, sim_time_ns=10_000_000)
    data = json.loads(path.read_text())
    assert data["sim_rate"] > 0.0


def test_sim_rate_zero_duration_does_not_crash(session_dir):
    """duration_s=0 must not raise ZeroDivisionError."""
    path = _call(duration_s=0.0, sim_time_ns=0)
    data = json.loads(path.read_text())
    assert data["sim_rate"] == 0.0


def test_consecutive_calls_produce_separate_files(session_dir):
    p1 = _call(board_name="BoardA")
    p2 = _call(board_name="BoardB")
    assert p1 != p2
    assert len(list(session_dir.iterdir())) == 2
