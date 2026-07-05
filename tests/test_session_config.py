"""Tests for session_config: load/save/roundtrip, merge semantics, recent[]."""

import json

import pytest

from fpga_sim.session_config import (
    RECENT_MAX,
    load_session,
    push_recent,
    save_session,
    update_session,
)


@pytest.fixture
def session_file(tmp_path, monkeypatch):
    """Redirect SESSION_FILE to a temp location for every test."""
    target = tmp_path / ".fpga_simulator" / "session.json"
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", target)
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
    # Non-dict JSON is treated as corrupt: merge-on-write needs a real dict.
    assert load_session() == {}


def test_save_session_does_not_raise_on_oserror(tmp_path, monkeypatch):
    """save_session must swallow OSError (e.g. read-only fs) without raising."""
    import pathlib

    target = tmp_path / ".fpga_simulator" / "session.json"
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", target)

    def _raise(self, *args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(pathlib.Path, "write_text", _raise)
    save_session("BoardA", "/path/a.vhd")  # must not propagate OSError


# ── Sort and filter persistence ──────────────────────────────────────────────


def test_save_board_sort(session_file):
    save_session("MyBoard", "/path/b.vhd", board_sort="leds")
    data = json.loads(session_file.read_text())
    assert data["board_sort"] == "leds"


def test_save_component_filters(session_file):
    save_session(
        "MyBoard",
        "/path/b.vhd",
        component_filters=["has_leds", "has_7seg"],
    )
    data = json.loads(session_file.read_text())
    assert data["component_filters"] == ["has_leds", "has_7seg"]


def test_save_vendor_filters(session_file):
    save_session(
        "MyBoard",
        "/path/b.vhd",
        vendor_filters=["Xilinx", "Lattice"],
    )
    data = json.loads(session_file.read_text())
    assert data["vendor_filters"] == ["Xilinx", "Lattice"]


def test_filter_fields_default_to_empty(session_file):
    save_session("MyBoard", "/path/b.vhd")
    data = json.loads(session_file.read_text())
    assert data["board_sort"] == ""
    assert data["component_filters"] == []
    assert data["vendor_filters"] == []


def test_filter_roundtrip(session_file):
    save_session(
        "B",
        "/p.vhd",
        board_sort="vendor",
        component_filters=["has_switches"],
        vendor_filters=["Intel"],
    )
    result = load_session()
    assert result["board_sort"] == "vendor"
    assert result["component_filters"] == ["has_switches"]
    assert result["vendor_filters"] == ["Intel"]


def test_load_old_session_without_filter_keys(session_file):
    """Old session files without filter keys load without error."""
    session_file.parent.mkdir(parents=True)
    session_file.write_text(json.dumps({"board_class": "X", "vhdl_path": "y", "simulator": "ghdl"}))
    result = load_session()
    assert "component_filters" not in result
    assert "vendor_filters" not in result


# ── U5: merge-on-write ────────────────────────────────────────────────────────


def test_save_preserves_keys_owned_by_other_writers(session_file):
    """save_session must not clobber speed_factor / theme / recent."""
    update_session(speed_factor=2.5, theme="dark", recent=[{"vhdl_path": "a.vhd"}])
    save_session("BoardA", "/path/a.vhd")
    data = load_session()
    assert data["speed_factor"] == 2.5
    assert data["theme"] == "dark"
    assert data["recent"] == [{"vhdl_path": "a.vhd"}]
    assert data["board_class"] == "BoardA"  # …while still writing its own keys


def test_save_window_size(session_file):
    save_session("B", "/p.vhd", window_size=(1280, 800))
    data = load_session()
    assert (data["window_w"], data["window_h"]) == (1280, 800)


def test_save_without_window_size_keeps_previous(session_file):
    save_session("B", "/p.vhd", window_size=(1280, 800))
    save_session("C", "/q.vhd")  # no window_size → previous one survives
    data = load_session()
    assert (data["window_w"], data["window_h"]) == (1280, 800)
    assert data["board_class"] == "C"


# ── U5: update_session ────────────────────────────────────────────────────────


def test_update_session_creates_file_and_directory(session_file):
    assert not session_file.parent.exists()
    update_session(speed_factor=1.5)
    assert json.loads(session_file.read_text()) == {"speed_factor": 1.5}


def test_update_session_merges_into_existing(session_file):
    save_session("BoardA", "/path/a.vhd", simulator="nvc")
    update_session(speed_factor=0.5)
    data = load_session()
    assert data["speed_factor"] == 0.5
    assert data["board_class"] == "BoardA"
    assert data["simulator"] == "nvc"


def test_update_session_over_corrupt_file_starts_fresh(session_file):
    session_file.parent.mkdir(parents=True)
    session_file.write_text("not valid json {{{")
    update_session(theme="dark")
    assert load_session() == {"theme": "dark"}


def test_update_session_over_non_dict_json_starts_fresh(session_file):
    session_file.parent.mkdir(parents=True)
    session_file.write_text("42")
    update_session(theme="dark")
    assert load_session() == {"theme": "dark"}


def test_update_session_swallows_oserror(tmp_path, monkeypatch):
    import pathlib

    target = tmp_path / ".fpga_simulator" / "session.json"
    monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", target)

    def _raise(self, *args, **kwargs):
        raise OSError("simulated disk full")

    monkeypatch.setattr(pathlib.Path, "write_text", _raise)
    update_session(speed_factor=1.0)  # must not propagate OSError


def test_update_session_reserved_toggle_keys_roundtrip(session_file):
    """The U10/U19 toggle keys persist through the generic writer."""
    update_session(metrics_enabled=True, waveform_enabled=False)
    data = load_session()
    assert data["metrics_enabled"] is True
    assert data["waveform_enabled"] is False


# ── U5: push_recent ───────────────────────────────────────────────────────────


def test_push_recent_first_entry(session_file):
    push_recent("BoardA", "custom", "/path/a.vhd")
    assert load_session()["recent"] == [
        {"board_class": "BoardA", "board_source": "custom", "vhdl_path": "/path/a.vhd"}
    ]


def test_push_recent_newest_first(session_file):
    push_recent("BoardA", "custom", "/path/a.vhd")
    push_recent("BoardB", "custom", "/path/b.vhd")
    recent = load_session()["recent"]
    assert [e["vhdl_path"] for e in recent] == ["/path/b.vhd", "/path/a.vhd"]


def test_push_recent_dedup_moves_to_front(session_file):
    push_recent("BoardA", "custom", "/path/a.vhd")
    push_recent("BoardB", "custom", "/path/b.vhd")
    push_recent("BoardA", "custom", "/path/a.vhd")  # re-pick the oldest
    recent = load_session()["recent"]
    assert [e["board_class"] for e in recent] == ["BoardA", "BoardB"]
    assert len(recent) == 2


def test_push_recent_same_file_different_board_kept_separate(session_file):
    push_recent("BoardA", "custom", "/path/a.vhd")
    push_recent("BoardB", "custom", "/path/a.vhd")  # same file, other board
    recent = load_session()["recent"]
    assert [e["board_class"] for e in recent] == ["BoardB", "BoardA"]


def test_push_recent_caps_at_recent_max(session_file):
    for i in range(RECENT_MAX + 5):
        push_recent(f"Board{i}", "custom", f"/path/{i}.vhd")
    recent = load_session()["recent"]
    assert len(recent) == RECENT_MAX
    assert recent[0]["board_class"] == f"Board{RECENT_MAX + 4}"  # newest kept


def test_push_recent_preserves_other_keys(session_file):
    save_session("BoardA", "/path/a.vhd")
    push_recent("BoardA", "custom", "/path/a.vhd")
    assert load_session()["board_class"] == "BoardA"


def test_push_recent_tolerates_corrupt_recent_value(session_file):
    update_session(recent="junk")  # hand-edited file
    push_recent("BoardA", "custom", "/path/a.vhd")
    assert len(load_session()["recent"]) == 1


def test_push_recent_drops_non_dict_entries(session_file):
    update_session(recent=["junk", 42])
    push_recent("BoardA", "custom", "/path/a.vhd")
    recent = load_session()["recent"]
    assert recent == [
        {"board_class": "BoardA", "board_source": "custom", "vhdl_path": "/path/a.vhd"}
    ]
