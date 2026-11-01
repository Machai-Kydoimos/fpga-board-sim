"""Board identity, the ledger, orphans and the accept-list (U56 plan §4.1–4.3).

Every test drives the real write path, :func:`sync_identity.run_sync`, with a stub parser
and a temporary ``boards/<source>`` folder, and asserts on what lands on disk -- the file
names, the ``source`` blocks, the orphan marks and ``_sync_metadata.json``.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

import jsonschema  # noqa: E402
from sync_common import ParseOutcome, ProducedBoard, normalize_error  # noqa: E402
from sync_identity import (  # noqa: E402
    ACCEPT_LIST,
    ACCEPT_SCHEMA,
    Acceptance,
    SyncFailureError,
    load_accept_list,
    run_sync,
)
from upstream_reader import UnsupportedConstructError  # noqa: E402

ORIGIN = "litex-boards"
SCHEMA = REPO / "boards" / "schema" / "board.schema.json"
COMMIT = "c0ffee"


def _board(name, upstream_file, cls="Platform", args=None, leds=1, legacy=False):
    source = {"origin": ORIGIN, "upstream_file": upstream_file}
    if not legacy:
        source["upstream_class"] = cls
        if args:
            source["upstream_args"] = dict(args)
    source.update({"sync_commit": "old", "sync_timestamp": "2026-07-22T00:00:00+00:00"})
    return {
        "name": name,
        "class_name": name.replace(" ", "") + "Platform",
        "vendor": "V",
        "device": "dev",
        "clocks": [],
        "default_clock_hz": 100e6,
        "leds": [{"name": "led", "number": i, "pins": [f"P{i}"]} for i in range(leds)],
        "buttons": [],
        "switches": [],
        "$schema": "../schema/board.schema.json",
        "source": source,
    }


def _produced(name, upstream_file, cls="Platform", args=None, default=True, leds=1):
    return ProducedBoard(
        board=_board(name, upstream_file, cls, args, leds),
        upstream_file=upstream_file,
        upstream_class=cls,
        upstream_args=dict(args or {}),
        default=default,
    )


def _write(folder, filename, data):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _sync(folder, table, accept=None):
    """Run the real write path; *table* maps upstream file -> fn(args) -> ParseOutcome."""
    calls = []

    def read(filename, text, args):
        calls.append((filename, dict(args) if args else None))
        return table[filename](args)

    report = run_sync(
        origin=ORIGIN,
        repo="example/repo",
        files={name: "" for name in table},
        commit_sha=COMMIT,
        output_dir=folder,
        read=read,
        accept_list=accept or [],
        schema_path=SCHEMA,
        color_registry={},
    )
    return report, calls


def _boards(*produced):
    return lambda args: ParseOutcome(boards=list(produced))


def _load(folder, name):
    return json.loads((folder / name).read_text(encoding="utf-8"))


def _meta(folder):
    return _load(folder, "_sync_metadata.json")


# ── identity and pairing (§4.1) ────────────────────────────────────────────────


def test_first_run_gives_existing_files_their_identity_by_todays_names(tmp_path):
    folder = tmp_path / ORIGIN
    _write(folder, "foo_board.json", _board("Foo Board", "foo_board.py", legacy=True))
    report, _ = _sync(
        folder,
        {"foo_board.py": _boards(_produced("Foo Board", "foo_board.py", args={"revision": 1}))},
    )
    assert report.new == [] and report.orphans == []
    source = _load(folder, "foo_board.json")["source"]
    assert source["upstream_class"] == "Platform" and source["upstream_args"] == {"revision": 1}
    assert _meta(folder)["ledger"] == {"foo_board.py": "boards: foo_board.json"}


def test_a_version_key_the_file_lacks_is_no_obstacle(tmp_path):
    folder = tmp_path / ORIGIN
    _write(folder, "foo.json", _board("Foo", "foo.py"))
    report, _ = _sync(
        folder, {"foo.py": _boards(_produced("Foo", "foo.py", args={"variant": "a"}))}
    )
    assert report.new == []
    assert _load(folder, "foo.json")["source"]["upstream_args"] == {"variant": "a"}


def test_a_recorded_identity_keeps_its_file_when_upstream_changes_the_default(tmp_path):
    # Wukong: qmtech_wukong.json holds revision 2; the default construction is revision 1.
    folder = tmp_path / ORIGIN
    _write(
        folder,
        "qmtech_wukong.json",
        _board("Qmtech Wukong", "qmtech_wukong.py", args={"revision": 2}, leds=2),
    )

    def wukong(args):
        revision = (args or {}).get("revision", 1)
        return ParseOutcome(
            boards=[
                _produced(
                    "Qmtech Wukong", "qmtech_wukong.py", args={"revision": revision}, leds=revision
                )
            ]
        )

    report, calls = _sync(folder, {"qmtech_wukong.py": wukong})
    assert ("qmtech_wukong.py", {"revision": 2}) in calls  # the on-disk identity was built
    assert len(_load(folder, "qmtech_wukong.json")["leds"]) == 2  # still revision 2
    assert report.new == ["qmtech_wukong_revision-1.json"]  # the default arrives as a new file
    assert _load(folder, "qmtech_wukong_revision-1.json")["source"]["upstream_args"] == {
        "revision": 1
    }
    revision_1 = _load(folder, "qmtech_wukong_revision-1.json")
    # (class_name, source) stays unique for recents: the version joins both names (§4.1).
    assert revision_1["class_name"] == "QmtechWukongRevision1Platform"
    assert revision_1["name"] == "Qmtech Wukong (revision 1)"
    assert _load(folder, "qmtech_wukong.json")["class_name"] == "QmtechWukongPlatform"

    # A second sync pairs both files by identity, and each keeps its own names.
    snapshot = {p.name: p.read_bytes() for p in folder.glob("*.json")}
    _sync(folder, {"qmtech_wukong.py": wukong})
    assert {p.name: p.read_bytes() for p in folder.glob("*.json")} == snapshot


def test_new_boards_are_named_from_their_upstream_file_never_their_display_name(tmp_path):
    folder = tmp_path / ORIGIN
    report, _ = _sync(
        folder,
        {
            "two.py": _boards(
                _produced("Display Alpha", "two.py", cls="AlphaPlatform"),
                _produced("Display Beta", "two.py", cls="BetaPlatform"),
            ),
            "solo.py": _boards(
                _produced("Solo", "solo.py", args={"revision": 1}),
                _produced("Solo", "solo.py", args={"revision": 3}, default=False),
            ),
        },
    )
    assert report.new == ["solo.json", "solo_revision-3.json", "two_alpha.json", "two_beta.json"]


def test_a_name_clash_with_another_identity_fails_and_writes_nothing(tmp_path):
    folder = tmp_path / ORIGIN
    _write(folder, "solo.json", _board("Other", "other.py"))
    before = (folder / "solo.json").read_bytes()
    with pytest.raises(SyncFailureError, match="already taken by other.py"):
        _sync(
            folder,
            {
                "other.py": _boards(_produced("Other", "other.py")),
                "solo.py": _boards(_produced("Solo", "solo.py")),
            },
        )
    assert (folder / "solo.json").read_bytes() == before
    assert not (folder / "_sync_metadata.json").exists()


# ── orphans (§4.3) ─────────────────────────────────────────────────────────────


def test_a_removed_upstream_file_orphans_its_board_and_names_a_successor(tmp_path):
    folder = tmp_path / ORIGIN
    _write(folder, "old.json", _board("Old", "old.py"))
    table = {"new.py": _boards(_produced("Old", "new.py"))}  # same content, renamed upstream
    report, _ = _sync(folder, table)
    source = _load(folder, "old.json")["source"]
    assert source["upstream_status"] == "orphaned"
    assert source["orphaned_at_commit"] == COMMIT
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["orphaned_at_date"])
    assert source["orphaned_reason"] == "file_removed"
    assert source["successor"] == "litex-boards/new.json"
    assert source["sync_commit"] == "old"  # everything else stays frozen
    assert _meta(folder)["orphans"] == ["old.json"]

    # A second run at the same pin changes nothing: the mark is stable.
    snapshot = {p.name: p.read_bytes() for p in folder.glob("*.json") if not p.name.startswith("_")}
    _sync(folder, table)
    assert {
        p.name: p.read_bytes() for p in folder.glob("*.json") if not p.name.startswith("_")
    } == snapshot


def test_an_orphan_returns_when_upstream_defines_it_again(tmp_path):
    folder = tmp_path / ORIGIN
    orphan = _board("Old", "old.py")
    orphan["source"].update(
        upstream_status="orphaned", orphaned_at_commit="x", orphaned_reason="file_removed"
    )
    _write(folder, "old.json", orphan)
    report, _ = _sync(folder, {"old.py": _boards(_produced("Old", "old.py"))})
    assert report.orphans == []
    assert "upstream_status" not in _load(folder, "old.json")["source"]


def test_a_parser_error_never_orphans_a_board_upstream_still_has(tmp_path):
    folder = tmp_path / ORIGIN
    _write(folder, "x.json", _board("X", "x.py"))
    failing = {"x.py": lambda args: ParseOutcome(outcome="error", detail="NameError: Pmod")}
    with pytest.raises(
        SyncFailureError, match="would orphan x.json because our parser failed on x.py"
    ):
        _sync(folder, failing)

    accept = [Acceptance(ORIGIN, "x.py", "error", "Upstream helper we cannot read yet.")]
    _sync(folder, failing, accept)
    assert "upstream_status" not in _load(folder, "x.json")["source"]  # untouched, unmarked
    assert _meta(folder)["ledger"] == {"x.py": "error: NameError: Pmod (accepted)"}


@pytest.mark.parametrize(
    ("outcome", "reason"),
    [
        (ParseOutcome(outcome="skipped", detail="no_simulatable_io"), "no_simulatable_io"),
        (ParseOutcome(boards=[]), "no_longer_defined"),  # parses, but not this board
    ],
)
def test_a_board_that_vanishes_from_a_clean_parse_needs_a_person(tmp_path, outcome, reason):
    folder = tmp_path / ORIGIN
    _write(folder, "y.json", _board("Y", "y.py"))
    table = {"y.py": lambda args: outcome}
    with pytest.raises(
        SyncFailureError,
        match=f"y.json: y.py parsed but no longer produces this board \\({reason}\\)",
    ):
        _sync(folder, table)

    accept = [
        Acceptance(
            ORIGIN, "y.py", "orphan", "Checked upstream: the board is gone.", "y.json", reason
        )
    ]
    _sync(folder, table, accept)
    assert _load(folder, "y.json")["source"]["orphaned_reason"] == reason
    _sync(folder, table, accept)  # the acceptance keeps matching while the orphan exists


def test_a_stale_acceptance_fails(tmp_path):
    folder = tmp_path / ORIGIN
    accept = [Acceptance(ORIGIN, "z.py", "error", "This file errored once, long ago.")]
    with pytest.raises(SyncFailureError, match="stale acceptance: z.py"):
        _sync(folder, {"z.py": _boards(_produced("Z", "z.py"))}, accept)


# ── the ledger (§4.2) ──────────────────────────────────────────────────────────


def test_the_ledger_and_its_warnings_land_in_the_metadata(tmp_path):
    folder = tmp_path / ORIGIN
    table = {
        "a.py": lambda args: ParseOutcome(
            boards=[_produced("A", "a.py")], warnings=["io_fallback: _io"]
        ),
        "b.py": lambda args: ParseOutcome(outcome="skipped", detail="not_a_board"),
        "c.py": lambda args: ParseOutcome(outcome="error", detail="TypeError"),
    }
    _sync(folder, table, [Acceptance(ORIGIN, "c.py", "error", "Upstream's file is broken.")])
    meta = _meta(folder)
    assert meta["ledger"] == {
        "a.py": "boards: a.json",
        "b.py": "skipped: not_a_board",
        "c.py": "error: TypeError (accepted)",
    }
    assert meta["warnings"] == {"a.py": ["io_fallback: _io"]}
    assert meta["orphans"] == []


def test_a_parser_that_raises_still_reaches_the_ledger(tmp_path):
    folder = tmp_path / ORIGIN

    def boom(args):
        raise KeyError("unexpected")

    with pytest.raises(SyncFailureError, match="our parser failed on k.py \\(KeyError\\)"):
        _sync(folder, {"k.py": boom})
    _sync(folder, {"k.py": boom}, [Acceptance(ORIGIN, "k.py", "error", "Accepted for the test.")])
    assert _meta(folder)["ledger"] == {"k.py": "error: KeyError (accepted)"}


def test_error_details_stay_stable_across_python_versions():
    assert normalize_error(NameError("name 'Pmod' is not defined")) == "NameError: Pmod"
    assert normalize_error(NameError("x", name="Pmod")) == "NameError: Pmod"
    assert (
        normalize_error(AttributeError("words differ by version", name="toolchain"))
        == "AttributeError: toolchain"
    )
    assert normalize_error(TypeError("__init__() takes 2 positional arguments")) == "TypeError"
    refusal = UnsupportedConstructError("x.py", 12, "attribute '__class__'")
    assert normalize_error(refusal) == "UnsupportedConstructError: attribute '__class__'"


# ── the accept-list file ───────────────────────────────────────────────────────


def test_the_committed_accept_list_is_valid():
    assert isinstance(load_accept_list(ACCEPT_LIST, ACCEPT_SCHEMA), list)


@pytest.mark.parametrize(
    "entry",
    [
        {
            "source": ORIGIN,
            "upstream_file": "a.py",
            "outcome": "orphan",
            "reason": "a long enough reason",
        },
        {
            "source": ORIGIN,
            "upstream_file": "a.py",
            "outcome": "error",
            "reason": "a long enough reason",
            "file": "a.json",
        },
        {
            "source": "custom",
            "upstream_file": "a.py",
            "outcome": "error",
            "reason": "a long enough reason",
        },
        {"source": ORIGIN, "upstream_file": "a.py", "outcome": "error", "reason": "short"},
        {
            "source": ORIGIN,
            "upstream_file": "a.py",
            "outcome": "error",
            "reason": "a long enough reason",
            "why": "?",
        },
    ],
)
def test_the_accept_list_schema_rejects_malformed_entries(entry):
    schema = json.loads(ACCEPT_SCHEMA.read_text(encoding="utf-8"))
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"accept": [entry]}, schema)


def test_a_parser_that_raises_on_a_recorded_identity_reports_it_as_failed(tmp_path):
    folder = tmp_path / ORIGIN
    _write(folder, "w.json", _board("W", "w.py", args={"revision": 2}))

    def wukong(args):
        if args:
            raise RuntimeError("parser bug")
        return ParseOutcome(boards=[_produced("W", "w.py", args={"revision": 1})])

    accept = [
        Acceptance(
            ORIGIN,
            "w.py",
            "orphan",
            "Checked: upstream dropped revision 2.",
            "w.json",
            "no_longer_defined",
        )
    ]
    report, _ = _sync(folder, {"w.py": wukong}, accept)
    assert report.warnings == {"w.py": ['version_failed: {"revision": 2}: RuntimeError']}
    assert _load(folder, "w.json")["source"]["orphaned_reason"] == "no_longer_defined"
    assert _load(folder, "w.json")["source"]["successor"] == "litex-boards/w_revision-1.json"


def test_a_source_can_shape_the_stem_new_boards_are_named_after(tmp_path):
    # Digilent: every XDC file is <Board>-Master.xdc, so the suffix is dropped.
    from sync_digilent_xdc import digilent_stem

    folder = tmp_path / ORIGIN

    def read(filename, text, args):
        return ParseOutcome(boards=[_produced("Zedboard", filename, cls="")])

    report = run_sync(
        origin=ORIGIN,
        repo="example/repo",
        files={"Zedboard-Master.xdc": ""},
        commit_sha=COMMIT,
        output_dir=folder,
        read=read,
        schema_path=SCHEMA,
        color_registry={},
        classless=True,
        file_stem=digilent_stem,
    )
    assert report.new == ["zedboard.json"]
    assert digilent_stem("Arty-A7-35-Master.xdc") == "Arty-A7-35"


def test_a_file_the_sync_does_not_own_is_never_overwritten(tmp_path):
    folder = tmp_path / ORIGIN
    foreign = _board("Solo", "solo.py")
    del foreign["source"]  # hand-placed: no source block, so not this sync's file
    _write(folder, "solo.json", foreign)
    before = (folder / "solo.json").read_bytes()
    with pytest.raises(SyncFailureError, match="already taken by a file this sync does not own"):
        _sync(folder, {"solo.py": _boards(_produced("Solo", "solo.py"))})
    assert (folder / "solo.json").read_bytes() == before


def test_two_boards_never_share_a_class_name(tmp_path):
    folder = tmp_path / ORIGIN
    _write(folder, "a.json", _board("Same", "a.py"))
    clash = _produced("Same", "b.py")  # a different file whose board has the same class_name
    with pytest.raises(SyncFailureError, match="would share class_name SamePlatform"):
        _sync(folder, {"a.py": _boards(_produced("Same", "a.py")), "b.py": _boards(clash)})
