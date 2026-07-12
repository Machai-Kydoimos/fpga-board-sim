"""Tests for scripts/sync_port_conventions.py (U21 Phase A3: the port_conventions generator).

Hermetic: `fetch_url`/`resolve_commit_sha` are always monkeypatched, so
nothing here touches the network. `REGISTRY_DIR`/`BOARDS_DIR` are
monkeypatched to `tmp_path` wherever a test needs real files on disk
(registry TOML / board JSON), matching the repo's existing pattern for
redirecting module-level path constants in tests (see e.g.
`sim_bridge.WAVEFORM_DIR`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import sync_port_conventions as spc

# ═══════════════════════════════════════════════════════════════════════
#  check_row_gate
# ═══════════════════════════════════════════════════════════════════════


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": "Test Board",
        "status": "verified",
        "source": [
            {"rank": 1, "kind": "vendor-official", "format": "QSF", "fetched": True, "url": "u"}
        ],
    }
    row.update(overrides)
    return row


def test_row_gate_passes_verified_trusted_kind_in_wave() -> None:
    gate = spc.check_row_gate(_row(), waves={"Test Board"})
    assert gate.ok


def test_row_gate_rejects_unverified_status() -> None:
    gate = spc.check_row_gate(_row(status="candidate"), waves={"Test Board"})
    assert not gate.ok
    assert "candidate" in gate.reason


def test_row_gate_rejects_untrusted_kind() -> None:
    row = _row(
        source=[{"rank": 1, "kind": "community", "format": "QSF", "fetched": True, "url": "u"}]
    )
    gate = spc.check_row_gate(row, waves={"Test Board"})
    assert not gate.ok
    assert "community" in gate.reason


def test_row_gate_untrusted_kind_passes_when_targeting_a_custom_board() -> None:
    # boards/custom/ is where a human already verified port names against
    # real vendor docs -- that's the trust signal, not the registry's
    # kind label (a hosting-location fact, not an accuracy one). Confirmed
    # by Rick 2026-07-12: DE10-Standard/DE2-115 are exactly this case.
    row = _row(
        files=["custom/some_board.json"],
        source=[{"rank": 1, "kind": "community", "format": "QSF", "fetched": True, "url": "u"}],
    )
    gate = spc.check_row_gate(row, waves={"Test Board"})
    assert gate.ok


def test_row_gate_custom_board_exemption_does_not_bypass_status_or_wave() -> None:
    # Only the `kind` check is exempted for boards/custom/ targets --
    # status/wave-membership are unrelated to that reasoning and still apply.
    custom_row = _row(files=["custom/some_board.json"], status="candidate")
    assert not spc.check_row_gate(custom_row, waves={"Test Board"}).ok
    custom_row_2 = _row(files=["custom/some_board.json"])
    assert not spc.check_row_gate(custom_row_2, waves=set()).ok


def test_row_gate_custom_board_exemption_requires_at_least_one_custom_file() -> None:
    # A row with no boards/custom/ target at all still needs a trusted kind --
    # e.g. DE2-115's second file (litex-boards/...) doesn't itself grant trust,
    # the row does, via its *other* (custom/) target.
    row = _row(
        files=["litex-boards/some_board.json"],
        source=[{"rank": 1, "kind": "community", "format": "QSF", "fetched": True, "url": "u"}],
    )
    assert not spc.check_row_gate(row, waves={"Test Board"}).ok


def test_row_gate_untrusted_kind_passes_when_rank1_vouched_canonical() -> None:
    # A community-/personal-hosted file can still use vendor-canonical port
    # names; an explicit, cited naming="canonical" vouch on the rank-1 source
    # bypasses the kind check the same way a boards/custom/ target does.
    row = _row(
        source=[
            {
                "rank": 1,
                "kind": "community",
                "format": "QSF",
                "fetched": True,
                "url": "u",
                "naming": "canonical",
                "naming_cite": "Terasic user-manual names, verified by direct fetch",
            }
        ]
    )
    assert spc.check_row_gate(row, waves={"Test Board"}).ok


def test_row_gate_canonical_naming_vouch_requires_a_cite() -> None:
    # naming="canonical" with no naming_cite is ignored (fail-safe): an
    # uncited claim must not grant trust, so this still fails on kind.
    row = _row(
        source=[
            {
                "rank": 1,
                "kind": "community",
                "format": "QSF",
                "fetched": True,
                "url": "u",
                "naming": "canonical",
            }
        ]
    )
    gate = spc.check_row_gate(row, waves={"Test Board"})
    assert not gate.ok
    assert "community" in gate.reason


def test_row_gate_canonical_naming_vouch_does_not_bypass_status_or_wave() -> None:
    # Like the custom/ exemption, the canonical-naming vouch skips only the
    # kind check -- status and wave-membership stay in force.
    src = {
        "rank": 1,
        "kind": "community",
        "format": "QSF",
        "fetched": True,
        "url": "u",
        "naming": "canonical",
        "naming_cite": "cited",
    }
    assert not spc.check_row_gate(_row(source=[src], status="candidate"), waves={"Test Board"}).ok
    assert not spc.check_row_gate(_row(source=[src]), waves=set()).ok


def test_row_gate_untrusted_kind_passes_when_overlay_supplies_cited_names() -> None:
    # System-CD rescue (DE10-Lite): a community QSF that renamed a resource is
    # admitted when a cited overlay name-override restores the canonical name.
    row = _row(
        source=[{"rank": 1, "kind": "community", "format": "QSF", "fetched": True, "url": "u"}]
    )
    overlay = {"Test Board": {"leds": {"name": "LEDR", "cite": "vendor System CD golden top"}}}
    assert spc.check_row_gate(row, waves={"Test Board"}, overlay=overlay).ok


def test_row_gate_overlay_name_vouch_requires_a_cite() -> None:
    # An uncited name override does not grant trust (fail-safe), exactly like the
    # naming="canonical" vouch.
    row = _row(
        source=[{"rank": 1, "kind": "community", "format": "QSF", "fetched": True, "url": "u"}]
    )
    overlay = {"Test Board": {"leds": {"name": "LEDR"}}}  # no cite
    gate = spc.check_row_gate(row, waves={"Test Board"}, overlay=overlay)
    assert not gate.ok
    assert "community" in gate.reason


def test_row_gate_overlay_name_vouch_does_not_bypass_status_or_wave() -> None:
    src = [{"rank": 1, "kind": "community", "format": "QSF", "fetched": True, "url": "u"}]
    overlay = {"Test Board": {"leds": {"name": "LEDR", "cite": "cited"}}}
    assert not spc.check_row_gate(
        _row(source=src, status="candidate"), waves={"Test Board"}, overlay=overlay
    ).ok
    assert not spc.check_row_gate(_row(source=src), waves=set(), overlay=overlay).ok


def test_row_gate_rejects_board_not_in_any_wave() -> None:
    gate = spc.check_row_gate(_row(), waves=set())
    assert not gate.ok
    assert "wave" in gate.reason


def test_row_gate_rejects_missing_rank1_source() -> None:
    gate = spc.check_row_gate(_row(source=[]), waves={"Test Board"})
    assert not gate.ok
    assert "no rank-1" in gate.reason


def test_row_gate_rejects_unfetched_source() -> None:
    row = _row(source=[{"rank": 1, "kind": "vendor-official", "format": "QSF", "fetched": False}])
    gate = spc.check_row_gate(row, waves={"Test Board"})
    assert not gate.ok
    assert "fetched" in gate.reason


def test_row_gate_rejects_unparseable_format() -> None:
    row = _row(
        source=[
            {"rank": 1, "kind": "vendor-official", "format": "PDF", "fetched": True, "url": "u"}
        ]
    )
    gate = spc.check_row_gate(row, waves={"Test Board"})
    assert not gate.ok
    assert "PDF" in gate.reason


def test_row_gate_force_bypasses_status_kind_and_wave() -> None:
    row = _row(
        status="candidate",
        source=[{"rank": 1, "kind": "community", "format": "QSF", "fetched": True, "url": "u"}],
    )
    gate = spc.check_row_gate(row, waves=set(), force=True)
    assert gate.ok


def test_row_gate_force_still_requires_fetched_and_parseable_format() -> None:
    row = _row(source=[{"rank": 1, "kind": "community", "format": "PDF", "fetched": False}])
    gate = spc.check_row_gate(row, waves=set(), force=True)
    assert not gate.ok


# ═══════════════════════════════════════════════════════════════════════
#  apply_overlay
# ═══════════════════════════════════════════════════════════════════════


def test_apply_overlay_clk_override() -> None:
    result = spc.apply_overlay({"clk": "CLOCK2_50"}, {"clk": "CLOCK_50"})
    assert result["clk"] == "CLOCK_50"


def test_apply_overlay_active_low_per_section() -> None:
    convention = {"buttons": {"name": "KEY", "width": 4}}
    overlay_row = {"buttons": {"active_low": True, "cite": "manual"}}
    result = spc.apply_overlay(convention, overlay_row)
    assert result["buttons"] == {"name": "KEY", "width": 4, "active_low": True}


def test_apply_overlay_none_is_noop() -> None:
    convention = {"clk": "clk", "leds": {"name": "led", "width": 4}}
    assert spc.apply_overlay(convention, None) == convention


def test_apply_overlay_ignores_active_low_for_unclassified_section() -> None:
    # classify() found no buttons at all; an overlay entry for buttons must
    # not fabricate a phantom {"active_low": True} port_mapping out of thin air.
    result = spc.apply_overlay({"clk": "clk"}, {"buttons": {"active_low": True}})
    assert "buttons" not in result


def test_apply_overlay_name_override() -> None:
    # Restore a vendor-canonical resource name a course source renamed (DE10-Lite: LED -> LEDR).
    convention = {"leds": {"name": "LED", "width": 10}}
    overlay_row = {"leds": {"name": "LEDR", "cite": "vendor System CD golden top"}}
    result = spc.apply_overlay(convention, overlay_row)
    assert result["leds"] == {"name": "LEDR", "width": 10}


def test_apply_overlay_name_and_active_low_together() -> None:
    convention = {"buttons": {"name": "BTN", "width": 2}}
    overlay_row = {"buttons": {"name": "KEY", "active_low": True, "cite": "manual"}}
    result = spc.apply_overlay(convention, overlay_row)
    assert result["buttons"] == {"name": "KEY", "width": 2, "active_low": True}


def test_apply_overlay_ignores_name_for_unclassified_section() -> None:
    # classify() found no leds; a name override must not fabricate a phantom port_mapping.
    result = spc.apply_overlay({"clk": "clk"}, {"leds": {"name": "LEDR", "cite": "c"}})
    assert "leds" not in result


def test_apply_overlay_does_not_name_override_seven_seg() -> None:
    # seven_seg carries a `names` list, not a single `name`; a stray `name` override is ignored,
    # while its active_low still applies.
    convention = {"seven_seg": {"style": "individual", "names": ["HEX0"], "width_per_digit": 7}}
    result = spc.apply_overlay(convention, {"seven_seg": {"name": "SEG", "active_low": True}})
    assert "name" not in result["seven_seg"]
    assert result["seven_seg"]["active_low"] is True


def test_apply_overlay_does_not_mutate_its_input() -> None:
    convention = {"buttons": {"name": "KEY", "width": 4}}
    spc.apply_overlay(convention, {"buttons": {"active_low": True}})
    assert convention == {"buttons": {"name": "KEY", "width": 4}}


# ═══════════════════════════════════════════════════════════════════════
#  cross_check_widths
# ═══════════════════════════════════════════════════════════════════════


def test_cross_check_leds_plus_leds_green_combined() -> None:
    convention = {
        "leds": {"name": "LEDR", "width": 18},
        "leds_green": {"name": "LEDG", "width": 9},
    }
    board: dict[str, Any] = {"leds": [{}] * 27}
    assert spc.cross_check_widths(convention, board) is None


def test_cross_check_leds_mismatch() -> None:
    convention = {"leds": {"name": "LEDR", "width": 18}}
    board: dict[str, Any] = {"leds": [{}] * 10}
    assert spc.cross_check_widths(convention, board) is not None


def test_cross_check_switches_and_buttons_mismatch() -> None:
    board: dict[str, Any] = {"switches": [{}] * 4, "buttons": [{}] * 2}
    assert spc.cross_check_widths({"switches": {"name": "sw", "width": 5}}, board) is not None
    assert spc.cross_check_widths({"buttons": {"name": "btn", "width": 5}}, board) is not None


def test_cross_check_seven_seg_individual_digit_count() -> None:
    convention = {
        "seven_seg": {"style": "individual", "names": ["HEX0", "HEX1"], "width_per_digit": 7}
    }
    assert spc.cross_check_widths(convention, {"seven_seg": {"num_digits": 2}}) is None
    assert spc.cross_check_widths(convention, {"seven_seg": {"num_digits": 3}}) is not None


def test_cross_check_seven_seg_per_segment_scalars_digit_count() -> None:
    names = [f"o_Segment{d}_{s}" for d in (1, 2) for s in "ABC"]
    convention = {
        "seven_seg": {"style": "per_segment_scalars", "names": names, "width_per_digit": 3}
    }
    assert spc.cross_check_widths(convention, {"seven_seg": {"num_digits": 2}}) is None


def test_cross_check_scan_style_has_no_digit_count_to_check() -> None:
    # scan/packed_vector styles don't state a names list, and the board JSON
    # has no corresponding "bits per digit" field either -- nothing to compare.
    convention = {"seven_seg": {"style": "scan", "name": "seg", "width_per_digit": 7}}
    assert spc.cross_check_widths(convention, {"seven_seg": {"num_digits": 4}}) is None


def test_cross_check_empty_convention_always_passes() -> None:
    assert spc.cross_check_widths({}, {"leds": [{}] * 99}) is None


# ═══════════════════════════════════════════════════════════════════════
#  maker_slug
# ═══════════════════════════════════════════════════════════════════════


def test_maker_slug_lowercases_and_sanitizes() -> None:
    assert spc.maker_slug("Terasic") == "terasic"
    assert spc.maker_slug("RZ Easy-FPGA") == "rz_easy_fpga"
    assert spc.maker_slug("") == "unknown"


# ═══════════════════════════════════════════════════════════════════════
#  pin_url_to_commit
# ═══════════════════════════════════════════════════════════════════════


def test_pin_url_to_commit_rewrites_ref_to_resolved_sha(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "deadbeef")
    repo, url = spc.pin_url_to_commit(
        "https://raw.githubusercontent.com/owner/repo/main/path/file.qsf"
    )
    assert repo == "owner/repo"
    assert url == "https://raw.githubusercontent.com/owner/repo/deadbeef/path/file.qsf"


def test_pin_url_to_commit_rejects_non_raw_github_host() -> None:
    with pytest.raises(ValueError):
        spc.pin_url_to_commit("https://example.com/foo.qsf")


# ═══════════════════════════════════════════════════════════════════════
#  process_board: full pipeline, network mocked out
# ═══════════════════════════════════════════════════════════════════════

_FAKE_QSF = """
set_location_assignment PIN_P11 -to Clk
set_location_assignment PIN_A8  -to LED[0]
set_location_assignment PIN_A9  -to LED[1]
set_location_assignment PIN_A10 -to LED[2]
set_location_assignment PIN_A11 -to LED[3]
set_location_assignment PIN_C10 -to SW[0]
set_location_assignment PIN_C11 -to SW[1]
set_location_assignment PIN_A7  -to KEY[0]
set_location_assignment PIN_A6  -to KEY[1]
"""


@pytest.fixture
def _board_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    board_dir = tmp_path / "custom"
    board_dir.mkdir()
    board = {
        "name": "Test Board",
        "leds": [{}] * 4,
        "switches": [{}] * 2,
        "buttons": [{}] * 2,
    }
    (board_dir / "test_board.json").write_text(json.dumps(board))
    return tmp_path


def _fake_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": "Test Board",
        "maker": "Test",
        "files": ["custom/test_board.json"],
        "notes": "test row",
        "source": [
            {
                "rank": 1,
                "kind": "vendor-official",
                "format": "QSF",
                "fetched": True,
                "url": "https://raw.githubusercontent.com/o/r/main/f.qsf",
            }
        ],
    }
    row.update(overrides)
    return row


def test_process_board_end_to_end(monkeypatch: pytest.MonkeyPatch, _board_json: Path) -> None:
    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _FAKE_QSF)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "abc123")

    result = spc.process_board(
        "Test Board", _fake_row(), overlay={}, force=True, waves=set(), cache_dir=None
    )

    assert result.skipped is None
    assert result.file_skips == {}
    conv = result.convention_by_file["custom/test_board.json"]["test"]
    assert conv["clk"] == "Clk"
    assert conv["leds"] == {"name": "LED", "width": 4}
    assert conv["switches"] == {"name": "SW", "width": 2}
    assert conv["buttons"] == {"name": "KEY", "width": 2}
    assert conv["naming"] == "canonical"
    assert conv["source"]["registry_board"] == "Test Board"
    assert conv["source"]["url"] == "https://raw.githubusercontent.com/o/r/abc123/f.qsf"


def test_process_board_applies_overlay(monkeypatch: pytest.MonkeyPatch, _board_json: Path) -> None:
    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _FAKE_QSF)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "abc123")
    overlay = {"Test Board": {"clk": "OVERRIDDEN_CLK", "buttons": {"active_low": True}}}

    result = spc.process_board(
        "Test Board", _fake_row(), overlay=overlay, force=True, waves=set(), cache_dir=None
    )

    conv = result.convention_by_file["custom/test_board.json"]["test"]
    assert conv["clk"] == "OVERRIDDEN_CLK"
    assert conv["buttons"]["active_low"] is True


def test_process_board_skips_on_width_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    board_dir = tmp_path / "custom"
    board_dir.mkdir()
    # Board JSON says only 2 LEDs; the fake QSF's classified LED width is 4.
    board = {"name": "Test Board", "leds": [{}] * 2, "switches": [{}] * 2, "buttons": [{}] * 2}
    (board_dir / "test_board.json").write_text(json.dumps(board))
    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _FAKE_QSF)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "abc123")

    result = spc.process_board(
        "Test Board", _fake_row(), overlay={}, force=True, waves=set(), cache_dir=None
    )

    assert result.skipped is None  # row-level pipeline succeeded
    assert result.convention_by_file == {}  # but the one file target was skipped
    assert "leds" in result.file_skips["custom/test_board.json"]


def test_process_board_second_files_target_independent_of_first(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    good = {"name": "Test Board", "leds": [{}] * 4, "switches": [{}] * 2, "buttons": [{}] * 2}
    bad = {"name": "Test Board", "leds": [{}] * 1, "switches": [{}] * 2, "buttons": [{}] * 2}
    (tmp_path / "a" / "good.json").write_text(json.dumps(good))
    (tmp_path / "b" / "bad.json").write_text(json.dumps(bad))
    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _FAKE_QSF)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "abc123")

    row = _fake_row(files=["a/good.json", "b/bad.json"])
    result = spc.process_board(
        "Test Board", row, overlay={}, force=True, waves=set(), cache_dir=None
    )

    assert "a/good.json" in result.convention_by_file
    assert "b/bad.json" in result.file_skips
    assert "a/good.json" not in result.file_skips


def test_process_board_missing_target_file_is_a_per_file_skip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _FAKE_QSF)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "abc123")

    row = _fake_row(files=["nonexistent/board.json"])
    result = spc.process_board(
        "Test Board", row, overlay={}, force=True, waves=set(), cache_dir=None
    )

    assert result.skipped is None
    assert "not found" in result.file_skips["nonexistent/board.json"]


def test_process_board_fetch_failure_is_a_row_level_skip(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(url: str, cache_dir: Path | None = None) -> str:
        raise TimeoutError("no route to host")

    monkeypatch.setattr(spc, "fetch_url", _boom)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "abc123")

    result = spc.process_board(
        "Test Board", _fake_row(), overlay={}, force=True, waves=set(), cache_dir=None
    )
    assert result.skipped is not None
    assert "fetch failed" in result.skipped


def test_process_board_gate_failure_short_circuits_before_any_network_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("should not be called: row-gate should have short-circuited first")

    monkeypatch.setattr(spc, "fetch_url", _fail_if_called)
    monkeypatch.setattr(spc, "resolve_commit_sha", _fail_if_called)

    result = spc.process_board(
        "Test Board",
        _fake_row(status="candidate"),
        overlay={},
        force=False,
        waves=set(),
        cache_dir=None,
    )
    assert result.skipped is not None


def test_process_board_empty_files_list_is_an_explicit_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A row with files=[] would otherwise fall through to an empty
    # convention_by_file AND empty file_skips -- main()'s reporting loop
    # treats that as "nothing to say" and prints nothing, silently hiding
    # what is very likely a malformed registry row.
    def _fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("should not be called: empty files[] should short-circuit first")

    monkeypatch.setattr(spc, "fetch_url", _fail_if_called)
    monkeypatch.setattr(spc, "resolve_commit_sha", _fail_if_called)

    result = spc.process_board(
        "Test Board", _fake_row(files=[]), overlay={}, force=True, waves=set(), cache_dir=None
    )
    assert result.skipped is not None
    assert "files" in result.skipped


# ═══════════════════════════════════════════════════════════════════════
#  write_results: schema validation + merge-without-clobbering-siblings
# ═══════════════════════════════════════════════════════════════════════


def test_write_results_merges_without_disturbing_sibling_keys(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    board_dir = tmp_path / "custom"
    board_dir.mkdir()
    board = {
        "name": "Test Board",
        "class_name": "TestBoardPlatform",
        "vendor": "Test",
        "device": "test-device",
        "clocks": [{"name": "clk", "hz": 100e6, "pin": "A1", "is_default": True}],
        "default_clock_hz": 100e6,
        "leds": [
            {"name": "led", "number": i, "pins": [f"P{i}"], "direction": "o"} for i in range(4)
        ],
        "switches": [],
        "buttons": [],
        "port_conventions": {"other_maker": {"clk": "preexisting"}},
    }
    (board_dir / "test_board.json").write_text(json.dumps(board))

    result = spc.BoardResult(
        "Test Board",
        convention_by_file={
            "custom/test_board.json": {"test": {"clk": "clk", "leds": {"name": "led", "width": 4}}}
        },
    )
    merged = spc.write_results([result], dry_run=True)

    conventions = merged["custom/test_board.json"]["port_conventions"]
    assert conventions["other_maker"] == {"clk": "preexisting"}
    assert conventions["test"]["clk"] == "clk"
    # dry_run=True must not touch the file on disk
    on_disk = json.loads((board_dir / "test_board.json").read_text())
    assert "test" not in on_disk.get("port_conventions", {})


def test_write_results_no_results_is_a_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    assert spc.write_results([]) == {}


# ═══════════════════════════════════════════════════════════════════════
#  Idempotency (structural: everything except the `retrieved` date)
# ═══════════════════════════════════════════════════════════════════════


def test_process_board_is_idempotent(monkeypatch: pytest.MonkeyPatch, _board_json: Path) -> None:
    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _FAKE_QSF)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "abc123")

    r1 = spc.process_board("Test Board", _fake_row(), {}, force=True, waves=set(), cache_dir=None)
    r2 = spc.process_board("Test Board", _fake_row(), {}, force=True, waves=set(), cache_dir=None)
    assert r1.convention_by_file == r2.convention_by_file


# ═══════════════════════════════════════════════════════════════════════
#  Trust-establishing regressions (A3's own Verify checklist, all four
#  required before any A4 write). Idempotency is covered above; schema
#  validation is exercised throughout via write_results(dry_run=True).
# ═══════════════════════════════════════════════════════════════════════

# Trimmed from https://raw.githubusercontent.com/Digilent/digilent-xdc/
# 00a3404901f35aa9567b01ecb3f2c233b6efe9f4/Basys-3-Master.xdc (same commit
# boards/digilent-xdc/basys_3.json's source cites) -- every line commented
# out, exactly like the real file.
_BASYS3_EXCERPT = """
## Clock signal
#set_property -dict { PACKAGE_PIN W5   IOSTANDARD LVCMOS33 } [get_ports clk]
#create_clock -add -name sys_clk_pin -period 10.00 -waveform {0 5} [get_ports clk]

## Switches
#set_property -dict { PACKAGE_PIN V17   IOSTANDARD LVCMOS33 } [get_ports {sw[0]}]
#set_property -dict { PACKAGE_PIN R2    IOSTANDARD LVCMOS33 } [get_ports {sw[15]}]

## LEDs
#set_property -dict { PACKAGE_PIN U16   IOSTANDARD LVCMOS33 } [get_ports {led[0]}]
#set_property -dict { PACKAGE_PIN L1    IOSTANDARD LVCMOS33 } [get_ports {led[15]}]

##7 Segment Display
#set_property -dict { PACKAGE_PIN W7   IOSTANDARD LVCMOS33 } [get_ports {seg[0]}]
#set_property -dict { PACKAGE_PIN U7   IOSTANDARD LVCMOS33 } [get_ports {seg[6]}]
#set_property -dict { PACKAGE_PIN U2   IOSTANDARD LVCMOS33 } [get_ports {an[0]}]
#set_property -dict { PACKAGE_PIN W4   IOSTANDARD LVCMOS33 } [get_ports {an[3]}]

##Buttons
#set_property -dict { PACKAGE_PIN U18   IOSTANDARD LVCMOS33 } [get_ports btnC]
#set_property -dict { PACKAGE_PIN T18   IOSTANDARD LVCMOS33 } [get_ports btnU]
#set_property -dict { PACKAGE_PIN W19   IOSTANDARD LVCMOS33 } [get_ports btnL]
#set_property -dict { PACKAGE_PIN T17   IOSTANDARD LVCMOS33 } [get_ports btnR]
#set_property -dict { PACKAGE_PIN U17   IOSTANDARD LVCMOS33 } [get_ports btnD]
"""


def test_digilent_regression(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """New generic pipeline reproduces sync_digilent_xdc.py's existing output.

    Reproduces this arc's A2 golden test (test_port_convention_parsers_golden.py)
    through the full A3 generator instead of calling xdc.parse/classify
    directly -- same expected clk/leds/switches/buttons, and the same
    documented upgrade from the stored JSON's stale "packed_vector" to the
    correct "scan" style (Basys3 has a real digit_enable, "an"; A0 added the
    "scan" style after sync_digilent_xdc.py was written).
    """
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    board_dir = tmp_path / "digilent-xdc"
    board_dir.mkdir()
    board = {
        "name": "Basys 3",
        "vendor": "Xilinx",
        "device": "xc7a35t",
        "clocks": [{"name": "clk", "hz": 100e6, "pin": "W5", "is_default": True}],
        "default_clock_hz": 100e6,
        "leds": [
            {"name": "led", "number": i, "pins": [f"P{i}"], "direction": "o"} for i in range(16)
        ],
        "switches": [
            {"name": "sw", "number": i, "pins": [f"P{i}"], "direction": "i"} for i in range(16)
        ],
        "buttons": [
            {"name": "btn", "number": i, "pins": [f"P{i}"], "direction": "i"} for i in range(5)
        ],
        "seven_seg": {"num_digits": 4, "has_dp": True, "is_multiplexed": True, "inverted": True},
    }
    (board_dir / "basys_3.json").write_text(json.dumps(board))

    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _BASYS3_EXCERPT)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "00a3404")

    row = {
        "name": "Basys 3",
        "maker": "Digilent",
        "files": ["digilent-xdc/basys_3.json"],
        "notes": "test row",
        "source": [
            {
                "rank": 1,
                "kind": "vendor-official",
                "format": "XDC",
                "fetched": True,
                "url": "https://raw.githubusercontent.com/Digilent/digilent-xdc/master/Basys-3-Master.xdc",
            }
        ],
    }
    result = spc.process_board("Basys 3", row, overlay={}, force=True, waves=set(), cache_dir=None)

    assert result.skipped is None
    assert result.file_skips == {}
    conv = result.convention_by_file["digilent-xdc/basys_3.json"]["digilent"]
    # Matches boards/digilent-xdc/basys_3.json's existing port_conventions.digilent
    # on every field that stored block states (buttons.active_low excepted --
    # see test_port_convention_parsers_golden.py for why that one is never derived).
    assert conv["clk"] == "clk"
    assert conv["leds"] == {"name": "led", "width": 16}
    assert conv["switches"] == {"name": "sw", "width": 16}
    assert conv["buttons"] == {"name": "btn", "width": 5}
    assert conv["seven_seg"] == {
        "style": "scan",
        "name": "seg",
        "width_per_digit": 7,
        "digit_enable": {"name": "an", "width": 4},
    }


# Trimmed from https://raw.githubusercontent.com/LeThanhHai-1610/DE10-Standard_miniproject/
# master/Miniproject.qsf (docs/port_convention_sources/terasic.toml's fetch-verified
# rank-1 source for DE10-Standard). CLOCK2_50 genuinely precedes CLOCK_50 in the
# real file -- kept in that order so this test proves the overlay's clk override
# actually corrects classify()'s file-order default, not just restates it. Only
# segments 0 and 6 of each digit are kept (real file has all 7 per digit) --
# A2's own test suite already covers segment-count derivation exhaustively;
# this fixture only needs internally-consistent digit *names*, not real width.
_DE10_STANDARD_EXCERPT = """
set_location_assignment PIN_AA16 -to CLOCK2_50
set_location_assignment PIN_AF14 -to CLOCK_50
set_location_assignment PIN_AJ4 -to KEY[0]
set_location_assignment PIN_AA15 -to KEY[3]
set_location_assignment PIN_AB30 -to SW[0]
set_location_assignment PIN_AA30 -to SW[9]
set_location_assignment PIN_AA24 -to LEDR[0]
set_location_assignment PIN_AC22 -to LEDR[9]
set_location_assignment PIN_AH27 -to HEX0[0]
set_location_assignment PIN_AG28 -to HEX0[6]
set_location_assignment PIN_AF16 -to HEX1[0]
set_location_assignment PIN_V17  -to HEX1[6]
set_location_assignment PIN_AA21 -to HEX2[0]
set_location_assignment PIN_W16  -to HEX2[6]
set_location_assignment PIN_Y19  -to HEX3[0]
set_location_assignment PIN_AD20 -to HEX3[6]
set_location_assignment PIN_AD21 -to HEX4[0]
set_location_assignment PIN_AH22 -to HEX4[6]
set_location_assignment PIN_AF28 -to HEX5[0]
set_location_assignment PIN_AF30 -to HEX5[6]
"""


def test_hand_authored_terasic_regression(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """New pipeline + a cited overlay entry reproduce Rick's hand-authored DE10-Standard block.

    DE10-Standard's registry row is rank-1 kind "community" (not
    vendor-official/official-repo) -- ordinarily gated out, but its
    files[] target lives in boards/custom/, which is itself the trust
    signal (a human already verified it against vendor docs), so this
    passes the *real* (unforced) gate rather than needing ``--board``.
    """
    monkeypatch.setattr(spc, "BOARDS_DIR", tmp_path)
    board_dir = tmp_path / "custom"
    board_dir.mkdir()
    board = {
        "name": "DE10-Standard",
        "vendor": "Intel",
        "device": "5CSXFC6D6",
        "clocks": [{"name": "CLOCK_50", "hz": 50e6, "pin": "AF14", "is_default": True}],
        "default_clock_hz": 50e6,
        "leds": [
            {"name": "LEDR", "number": i, "pins": [f"P{i}"], "direction": "o"} for i in range(10)
        ],
        "switches": [
            {"name": "SW", "number": i, "pins": [f"P{i}"], "direction": "i"} for i in range(10)
        ],
        "buttons": [
            {"name": "KEY", "number": i, "pins": [f"P{i}"], "direction": "i"} for i in range(4)
        ],
        "seven_seg": {"num_digits": 6, "has_dp": False, "is_multiplexed": False, "inverted": True},
    }
    (board_dir / "de10_standard.json").write_text(json.dumps(board))

    monkeypatch.setattr(spc, "fetch_url", lambda url, cache_dir=None: _DE10_STANDARD_EXCERPT)
    monkeypatch.setattr(spc, "resolve_commit_sha", lambda repo, ref: "117be9a")

    row = {
        "name": "DE10-Standard",
        "maker": "Terasic",
        "status": "verified",
        "files": ["custom/de10_standard.json"],
        "notes": "test row",
        "source": [
            {
                "rank": 1,
                "kind": "community",
                "format": "QSF",
                "fetched": True,
                "url": "https://raw.githubusercontent.com/LeThanhHai-1610/DE10-Standard_miniproject/master/Miniproject.qsf",
            }
        ],
    }
    overlay = {
        "DE10-Standard": {
            "clk": "CLOCK_50",
            "buttons": {"active_low": True},
            "seven_seg": {"active_low": True},
        }
    }
    result = spc.process_board(
        "DE10-Standard", row, overlay=overlay, force=False, waves={"DE10-Standard"}, cache_dir=None
    )

    assert result.skipped is None
    assert result.file_skips == {}
    conv = result.convention_by_file["custom/de10_standard.json"]["terasic"]
    # Matches boards/custom/de10_standard.json's existing port_conventions.terasic
    # field-for-field (description/naming/source legitimately differ -- the
    # existing block predates A0 and was never machine-sourced).
    assert conv["clk"] == "CLOCK_50"
    assert conv["leds"] == {"name": "LEDR", "width": 10}
    assert conv["switches"] == {"name": "SW", "width": 10}
    assert conv["buttons"] == {"name": "KEY", "width": 4, "active_low": True}
    assert conv["seven_seg"] == {
        "style": "individual",
        "names": ["HEX0", "HEX1", "HEX2", "HEX3", "HEX4", "HEX5"],
        "width_per_digit": 2,  # fixture only keeps 2 of the real 7 segments per digit
        "active_low": True,
    }


# ═══════════════════════════════════════════════════════════════════════
#  load_registry / load_waves / load_overlay
# ═══════════════════════════════════════════════════════════════════════


def test_load_waves_missing_file_returns_empty_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spc, "REGISTRY_DIR", tmp_path)
    assert spc.load_waves() == set()


def test_load_waves_accumulates_across_wave_entries(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spc, "REGISTRY_DIR", tmp_path)
    (tmp_path / "waves.toml").write_text(
        '[[wave]]\nnumber = 1\nboards = ["A", "B"]\n\n[[wave]]\nnumber = 2\nboards = ["C"]\n'
    )
    assert spc.load_waves() == {"A", "B", "C"}


def test_load_overlay_missing_file_returns_empty_dict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(spc, "REGISTRY_DIR", tmp_path)
    assert spc.load_overlay() == {}


def test_load_overlay_keys_by_board_name(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(spc, "REGISTRY_DIR", tmp_path)
    (tmp_path / "overlay.toml").write_text('[[board]]\nname = "X"\nclk = "CLK50"\n')
    assert spc.load_overlay() == {"X": {"name": "X", "clk": "CLK50"}}


def test_load_registry_excludes_waves_and_overlay_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Both waves.toml and overlay.toml also use a top-level [[board]] array
    # (a different row shape than the family registry files) -- if they
    # weren't excluded by filename, their rows would masquerade as registry
    # boards with nonsense fields.
    monkeypatch.setattr(spc, "REGISTRY_DIR", tmp_path)
    (tmp_path / "family.toml").write_text('[[board]]\nname = "Real Board"\nmaker = "Acme"\n')
    (tmp_path / "overlay.toml").write_text('[[board]]\nname = "Not A Registry Row"\nclk = "x"\n')
    registry = spc.load_registry()
    assert registry == {"Real Board": {"name": "Real Board", "maker": "Acme"}}


def test_registry_canonical_naming_sources_always_carry_a_cite() -> None:
    """Every source vouched naming="canonical" in the real registry states a cite.

    The gate treats an uncited canonical claim as no vouch at all
    (`_rank1_vouched_canonical` fails safe), but a claim written *without* its
    citation is almost certainly an authoring mistake -- catch it against the
    committed registry rather than let it silently grant nothing.
    """
    registry = spc.load_registry()
    offenders = [
        (name, src.get("url", "?"))
        for name, row in registry.items()
        for src in row.get("source", [])
        if src.get("naming") == "canonical" and not src.get("naming_cite")
    ]
    assert offenders == [], f"canonical-naming sources missing naming_cite: {offenders}"
