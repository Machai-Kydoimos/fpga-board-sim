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

from led_metadata import ColorBank  # noqa: E402
from sync_common import resolve_commit_sha, validate_board_jsons, write_outputs  # noqa: E402

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


def _led(name: str, number: int) -> dict[str, Any]:
    return {"name": name, "number": number, "pins": ["A1"], "direction": "o"}


def test_write_outputs_stamps_cited_colors(tmp_path):
    """A re-sync re-applies registry colors, keyed by ``<source>/<filename>`` (U36)."""
    root = _boards_root(tmp_path)
    out = root / "amaranth-boards"  # out.name is the source key prefix
    board = _valid_board()
    board["leds"] = [_led("led", 0)]
    registry = {"amaranth-boards/led_board.json": [ColorBank("led", "red", "cited")]}
    write_outputs(
        out, _jsons({"led_board.json": board}), "sha", "owner/repo", color_registry=registry
    )
    written = json.loads((out / "led_board.json").read_text(encoding="utf-8"))
    assert written["leds"][0]["color"] == "red"


def test_write_outputs_leaves_unregistered_boards_byte_identical(tmp_path):
    """A board absent from the color registry is written verbatim (silent diff)."""
    root = _boards_root(tmp_path)
    out = root / "amaranth-boards"
    content = _jsons({"plain.json": _valid_board()})
    write_outputs(out, content, "sha", "owner/repo", color_registry={})
    assert (out / "plain.json").read_text(encoding="utf-8") == content["plain.json"]


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


def test_write_outputs_drops_framework_derived_key_the_parser_stopped_emitting(tmp_path):
    """A ``naming: "framework-derived"`` sub-key is parser-owned: when a
    regeneration no longer emits it (gmm7550's mixed-polarity LED bank), the
    stale block must drop instead of folding forward forever -- while a
    hand-authored/canonical key on the same board still survives."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["port_conventions"] = {
        "litex": {
            "clk": "clk60",
            "leds": {"name": "user_led", "width": 1},
            "naming": "framework-derived",
        },
        "vendor": {"clk": "CLK"},  # no naming stamp: hand-authored tier
    }
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    fresh = _valid_board()  # parser emits no port_conventions this run
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo", color_registry={})

    written = json.loads((out / "board.json").read_text())
    assert written["port_conventions"] == {"vendor": {"clk": "CLK"}}


def test_write_outputs_framework_derived_key_reemitted_is_updated_not_dropped(tmp_path):
    """The drop rule only fires on absence: a framework-derived key the parser
    re-emits is overwritten with the fresh shape as before."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["port_conventions"] = {
        "litex": {
            "clk": "clk60",
            "leds": {"name": "user_led", "width": 2},
            "naming": "framework-derived",
        },
    }
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    fresh = _valid_board()
    fresh["port_conventions"] = {
        "litex": {
            "clk": "clk60",
            "leds": {"name": "user_led", "width": 1},
            "naming": "framework-derived",
        },
    }
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo", color_registry={})

    written = json.loads((out / "board.json").read_text())
    assert written["port_conventions"]["litex"]["leds"]["width"] == 1


def test_write_outputs_reconciles_framework_polarity_to_canonical(tmp_path):
    """F2: on re-sync, a framework-derived bank inherits a same-width canonical
    bank's polarity (the de0_cv shape: a cited active-high canonical wins over the
    parser's active-low guess), and the result is idempotent."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["port_conventions"] = {
        "terasic": {"clk": "CLOCK_50", "leds": {"name": "LEDR", "width": 10}},
        "amaranth": {
            "clk": "clk",
            "leds": {"name": "led", "width": 10, "active_low": True},
            "naming": "framework-derived",
        },
    }
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    # The parser regenerates the framework block with its active-low guess.
    fresh = _valid_board()
    fresh["port_conventions"] = {
        "amaranth": {
            "clk": "clk",
            "leds": {"name": "led", "width": 10, "active_low": True},
            "naming": "framework-derived",
        }
    }
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo")

    written = json.loads((out / "board.json").read_text())
    # The framework bank inherited the canonical (active-high) truth; canonical intact.
    assert "active_low" not in written["port_conventions"]["amaranth"]["leds"]
    assert written["port_conventions"]["terasic"]["leds"] == {"name": "LEDR", "width": 10}

    # Idempotent: a second identical re-sync produces byte-identical output.
    first = (out / "board.json").read_text()
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo")
    assert (out / "board.json").read_text() == first


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


def test_write_outputs_rejects_corrupt_existing_json(tmp_path):
    """An existing file that isn't valid JSON (crashed prior write, bad hand
    edit, merge-conflict markers, ...) fails with a clear error naming the
    file, not a raw JSONDecodeError with no context."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    (out / "board.json").write_text('{"name": "T", "port_conventions": {oops', encoding="utf-8")

    with pytest.raises(ValueError, match="board.json.*not valid JSON"):
        write_outputs(out, _jsons({"board.json": _valid_board()}), "abc123", "owner/repo")


def test_write_outputs_rejects_non_object_existing_json(tmp_path):
    """An existing file that's valid JSON but not an object (e.g. someone
    overwrote it with an array) fails clearly instead of an AttributeError
    from a bare .get() call."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    (out / "board.json").write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError, match="board.json.*not an object"):
        write_outputs(out, _jsons({"board.json": _valid_board()}), "abc123", "owner/repo")


def test_write_outputs_tolerates_explicit_null_fresh_conventions(tmp_path):
    """A fresh board dict with port_conventions explicitly None (not absent --
    a hypothetical future generator bug) is treated the same as absent, not a
    crash, and existing data is still preserved."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["port_conventions"] = {"custom": {"clk": "CLK"}}
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    fresh = _valid_board()
    fresh["port_conventions"] = None
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo")

    written = json.loads((out / "board.json").read_text())
    assert written["port_conventions"] == {"custom": {"clk": "CLK"}}


def test_write_outputs_fresh_peripherals_wins_over_existing(tmp_path):
    """When both sides supply a non-empty peripherals list, the fresh value
    wins outright -- no per-item merge, since list entries aren't keyed.
    Locks in the current behavior so a future peripherals-generating parser
    doesn't silently change it."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _valid_board()
    existing["peripherals"] = [{"type": "vga", "name": "OLD"}]
    (out / "board.json").write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

    fresh = _valid_board()
    fresh["peripherals"] = [{"type": "audio", "name": "NEW"}]
    write_outputs(out, _jsons({"board.json": fresh}), "abc123", "owner/repo")

    written = json.loads((out / "board.json").read_text())
    assert written["peripherals"] == [{"type": "audio", "name": "NEW"}]


# ── write_outputs (sync-stamp carry-forward, U37 PR-0) ───────────────────────


def _stamped_board(sync_commit: str, sync_timestamp: str, **overrides: Any) -> dict[str, Any]:
    """A valid board carrying the per-board ``source`` stamp the sync scripts emit."""
    board = _valid_board()
    board["source"] = {
        "origin": "test-source",
        "upstream_file": "board.py",
        "sync_commit": sync_commit,
        "sync_timestamp": sync_timestamp,
    }
    board.update(overrides)
    return board


def test_write_outputs_noop_resync_keeps_on_disk_stamp(tmp_path):
    """A re-sync that changes nothing keeps the board byte-identical -- the
    fresh run's sync_commit/sync_timestamp must NOT churn ~250 files."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    on_disk = json.dumps(_stamped_board("oldsha", "2026-01-01T00:00:00+00:00"), indent=2) + "\n"
    (out / "board.json").write_text(on_disk, encoding="utf-8")

    fresh = _stamped_board("newsha", "2026-07-22T00:00:00+00:00")
    write_outputs(out, _jsons({"board.json": fresh}), "newsha", "owner/repo", color_registry={})

    assert (out / "board.json").read_text() == on_disk


def test_write_outputs_real_change_takes_fresh_stamp(tmp_path):
    """Any real content change still lands with the fresh run's stamp."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    old = _stamped_board("oldsha", "2026-01-01T00:00:00+00:00")
    (out / "board.json").write_text(json.dumps(old, indent=2) + "\n", encoding="utf-8")

    fresh = _stamped_board("newsha", "2026-07-22T00:00:00+00:00", device="new-device")
    write_outputs(out, _jsons({"board.json": fresh}), "newsha", "owner/repo", color_registry={})

    written = json.loads((out / "board.json").read_text())
    assert written["device"] == "new-device"
    assert written["source"]["sync_commit"] == "newsha"
    assert written["source"]["sync_timestamp"] == "2026-07-22T00:00:00+00:00"


def test_write_outputs_first_sync_takes_fresh_stamp(tmp_path):
    """A brand-new board (no file on disk) is stamped with the run's values."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    fresh = _stamped_board("newsha", "2026-07-22T00:00:00+00:00")
    write_outputs(out, _jsons({"board.json": fresh}), "newsha", "owner/repo", color_registry={})

    written = json.loads((out / "board.json").read_text())
    assert written["source"]["sync_commit"] == "newsha"


def test_write_outputs_noop_resync_with_folded_conventions_keeps_stamp(tmp_path):
    """The #296 real-world shape: the parser regenerates a board without
    port_conventions, fold-forward merges the on-disk block back in, and the
    result differs from disk only by the stamp -- must round-trip byte-identical
    (previously this exact case produced the 240-board stamp-only diff)."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    out.mkdir()
    existing = _stamped_board("oldsha", "2026-01-01T00:00:00+00:00")
    existing["port_conventions"] = {"custom": {"clk": "CLK"}}
    on_disk = json.dumps(existing, indent=2) + "\n"
    (out / "board.json").write_text(on_disk, encoding="utf-8")

    fresh = _stamped_board("newsha", "2026-07-22T00:00:00+00:00")  # parser emits no conventions
    write_outputs(out, _jsons({"board.json": fresh}), "newsha", "owner/repo", color_registry={})

    assert (out / "board.json").read_text() == on_disk


def test_write_outputs_metadata_noop_resync_keeps_timestamp(tmp_path):
    """_sync_metadata.json follows the same rule: an unchanged source (same pin,
    same file list) keeps the existing metadata verbatim."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    fresh = _stamped_board("sha1", "2026-07-22T00:00:00+00:00")
    write_outputs(out, _jsons({"board.json": fresh}), "sha1", "owner/repo", color_registry={})
    first_meta = (out / "_sync_metadata.json").read_text()

    write_outputs(out, _jsons({"board.json": fresh}), "sha1", "owner/repo", color_registry={})
    assert (out / "_sync_metadata.json").read_text() == first_meta


def test_write_outputs_metadata_pin_bump_rewrites(tmp_path):
    """A pin bump with unchanged boards is a data-only diff: every unchanged
    board keeps its old stamp, and the new pin lands in _sync_metadata.json."""
    root = _boards_root(tmp_path)
    out = root / "test-source"
    fresh = _stamped_board("sha1", "2026-07-22T00:00:00+00:00")
    write_outputs(out, _jsons({"board.json": fresh}), "sha1", "owner/repo", color_registry={})
    board_v1 = (out / "board.json").read_text()

    bumped = _stamped_board("sha2", "2026-07-23T00:00:00+00:00")
    write_outputs(out, _jsons({"board.json": bumped}), "sha2", "owner/repo", color_registry={})

    assert (out / "board.json").read_text() == board_v1  # board: no churn
    meta = json.loads((out / "_sync_metadata.json").read_text())
    assert meta["source_commit"] == "sha2"  # metadata: records the new pin


# ── resolve_commit_sha (GITHUB_TOKEN auth, U33) ──────────────────────────────


class _FakeResp:
    """Minimal context-manager stand-in for an ``http.client.HTTPResponse``."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> "_FakeResp":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _capture_urlopen(captured: list[Any]) -> Any:
    """Return a urlopen stand-in that records each Request and returns a SHA."""

    def _fake(req: Any, timeout: int = 30) -> _FakeResp:
        captured.append(req)
        return _FakeResp(b"abcdef1234\n")

    return _fake


def test_resolve_commit_sha_adds_auth_header_when_token_set(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    captured: list[Any] = []
    monkeypatch.setattr("sync_common.urllib.request.urlopen", _capture_urlopen(captured))

    assert resolve_commit_sha("owner/repo", "main") == "abcdef1234"
    assert captured[0].get_header("Authorization") == "Bearer secret-token"


def test_resolve_commit_sha_uses_gh_token_fallback(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "gh-secret")
    captured: list[Any] = []
    monkeypatch.setattr("sync_common.urllib.request.urlopen", _capture_urlopen(captured))

    resolve_commit_sha("owner/repo", "main")
    assert captured[0].get_header("Authorization") == "Bearer gh-secret"


def test_resolve_commit_sha_no_auth_header_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    captured: list[Any] = []
    monkeypatch.setattr("sync_common.urllib.request.urlopen", _capture_urlopen(captured))

    assert resolve_commit_sha("owner/repo", "main") == "abcdef1234"
    assert captured[0].get_header("Authorization") is None


def test_resolve_commit_sha_falls_back_to_ref_on_error(monkeypatch):
    def _boom(req: Any, timeout: int = 30) -> None:
        raise OSError("network down")

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr("sync_common.urllib.request.urlopen", _boom)

    # A resolution failure must never break a sync -- fall back to the ref.
    assert resolve_commit_sha("owner/repo", "v1.2.3") == "v1.2.3"
