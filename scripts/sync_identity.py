"""Board identity, the sync ledger, orphans and the accept-list (U56 plan §4.1–4.3).

Every board a sync produces has an identity -- ``(origin, upstream_file, upstream_class,
upstream_args)`` -- recorded in its file's ``source`` block, and a board file keeps its
name forever once it has one. :func:`run_sync` is the write path all three syncs share:

1. read every upstream file (the parser returns a :class:`~sync_common.ParseOutcome`), and
   build the identities already on disk that the default construction does not cover;
2. pair the produced boards with the existing files by identity -- most specific first,
   the default construction preferred -- or, for a file written before identities
   existed, by the file name today's naming gives it;
3. name each new identity from its upstream file (never from its display name);
4. find the existing files nothing produced, and decide per §4.3: mark an orphan, leave
   it untouched, or **fail the sync** when only a person can tell a renamed upstream
   class from our own misreading (the accept-list records that a person did);
5. write the boards, the orphan marks and ``_sync_metadata.json`` -- with the ledger: one
   outcome per upstream file and any warnings.

Everything is decided before anything is written, so a failure leaves ``boards/``
untouched. Self-contained: no ``fpga_sim`` dependency.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
from sync_common import (
    ParseOutcome,
    ProducedBoard,
    normalize_error,
    sanitize_filename,
    write_outputs,
)

#: Constructor parameters that select a board version (§4.1); Phase 7 enumerates their values.
#: Not ``device``, ``toolchain`` or ``speedgrade``: part variants are D-4's business.
VERSION_PARAMS = (
    "variant",
    "revision",
    "board_version",
    "version",
    "dock",
    "expansion",
    "baseboard",
    "som",
    "board",
)

ACCEPT_LIST = Path(__file__).with_name("board_sync_accepted.toml")
ACCEPT_SCHEMA = Path(__file__).with_name("board_sync_accepted.schema.json")

#: Fields compared when looking for an orphan's successor by content (§4.3).
_CONTENT_KEYS = ("leds", "switches", "buttons", "seven_seg", "clocks", "device")

Reader = Callable[[str, str, Mapping[str, Any] | None], ParseOutcome]


def summarize(report: SyncReport) -> str:
    """Return the one-paragraph summary a sync prints after writing."""
    kinds: dict[str, int] = {}
    for text in report.ledger.values():
        kind = text.split(":")[0] if not text.startswith("skipped") else text.split(" (")[0]
        kinds[kind] = kinds.get(kind, 0) + 1
    parts = [f"{n} {kind}" for kind, n in sorted(kinds.items())]
    warned = sum(len(w) for w in report.warnings.values())
    return (
        f"Ledger: {len(report.ledger)} upstream files -- {', '.join(parts) or 'none'}; "
        f"{warned} warning(s); {len(report.written)} boards written "
        f"({len(report.new)} new); {len(report.orphans)} orphaned."
    )


class SyncFailureError(Exception):
    """The sync cannot proceed without a person; nothing was written."""

    def __init__(self, problems: list[str]) -> None:
        """Collect every problem, so one run reports them all."""
        super().__init__("\n".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Acceptance:
    """One accept-list entry: an outcome a person has looked at (§4.2)."""

    source: str
    upstream_file: str
    outcome: str  # "error" | "orphan"
    reason: str
    file: str = ""  # the board file, for an orphan
    orphaned_reason: str = ""
    issue: str = ""


def load_accept_list(path: Path = ACCEPT_LIST, schema: Path = ACCEPT_SCHEMA) -> list[Acceptance]:
    """Read and validate the accept-list; a missing file is an empty list."""
    if not path.exists():
        return []
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    jsonschema.validate(data, json.loads(schema.read_text(encoding="utf-8")))
    return [Acceptance(**entry) for entry in data.get("accept", [])]


@dataclass
class _Existing:
    filename: str
    data: dict[str, Any]
    upstream_file: str
    upstream_class: str | None  # None: written before identities existed (backfill by name)
    upstream_args: dict[str, Any]
    orphaned: bool


@dataclass
class SyncReport:
    """What a sync did, for the caller to print or test."""

    ledger: dict[str, str] = field(default_factory=dict)
    warnings: dict[str, list[str]] = field(default_factory=dict)
    written: dict[str, ProducedBoard] = field(default_factory=dict)
    new: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)


def _args_match(recorded: Mapping[str, Any], produced: Mapping[str, Any]) -> bool:
    """Return whether every recorded version key has the same effective value (§4.1)."""
    return all(key in produced and produced[key] == value for key, value in recorded.items())


def _load_existing(output_dir: Path, origin: str, classless: bool) -> list[_Existing]:
    existing: list[_Existing] = []
    if not output_dir.is_dir():
        return existing
    for path in sorted(output_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        source = data.get("source") if isinstance(data, dict) else None
        if not isinstance(source, dict) or source.get("origin") != origin:
            continue  # not a file this sync owns: never paired, never orphaned
        existing.append(
            _Existing(
                filename=path.name,
                data=data,
                upstream_file=str(source.get("upstream_file", "")),
                upstream_class=source.get("upstream_class", "" if classless else None),
                upstream_args=dict(source.get("upstream_args") or {}),
                orphaned=source.get("upstream_status") == "orphaned",
            )
        )
    return existing


def _construct_recorded(
    read: Reader,
    filename: str,
    text: str,
    outcome: ParseOutcome,
    existing: list[_Existing],
) -> list[ProducedBoard]:
    """Build each on-disk identity of *filename* that the default construction misses (§4.1)."""
    extra: list[ProducedBoard] = []
    if outcome.outcome != "boards" or any(w.startswith("io_fallback") for w in outcome.warnings):
        return extra  # while the fallback exists, a failed default yields its one board only
    for entry in existing:
        if entry.upstream_file != filename or entry.upstream_class is None:
            continue
        if not entry.upstream_args:
            continue
        if any(
            b.upstream_class == entry.upstream_class
            and _args_match(entry.upstream_args, b.upstream_args)
            for b in outcome.boards + extra
        ):
            continue
        try:
            alternative = read(filename, text, entry.upstream_args)
        except Exception as exc:  # a parser bug: report the version, never crash the sync
            alternative = ParseOutcome(outcome="error", detail=normalize_error(exc))
        built = [
            b
            for b in alternative.boards
            if b.upstream_class == entry.upstream_class
            and _args_match(entry.upstream_args, b.upstream_args)
        ]
        if alternative.outcome == "boards" and built:
            for board in built:
                board.default = False
            extra.extend(built)
        else:
            args = json.dumps(entry.upstream_args, sort_keys=True)
            detail = alternative.detail if alternative.outcome == "error" else alternative.outcome
            outcome.warnings.append(f"version_failed: {args}: {detail.split(':')[0]}")
    return extra


def _pair(
    existing: list[_Existing], produced: list[ProducedBoard]
) -> tuple[dict[str, ProducedBoard], list[ProducedBoard]]:
    """Pair produced boards with existing files (§4.1); return the pairs and the unpaired."""
    free = list(produced)
    pairs: dict[str, ProducedBoard] = {}
    with_identity = [e for e in existing if e.upstream_class is not None]
    with_identity.sort(key=lambda e: (-len(e.upstream_args), e.filename))
    for entry in with_identity:
        candidates = [
            b
            for b in free
            if b.upstream_file == entry.upstream_file
            and b.upstream_class == entry.upstream_class
            and _args_match(entry.upstream_args, b.upstream_args)
        ]
        if candidates:
            chosen = min(candidates, key=lambda b: not b.default)
            pairs[entry.filename] = chosen
            free.remove(chosen)
    # Files written before identities existed pair by the name today's naming gives the
    # board -- exact for every synced file (§2.6) -- and the same upstream file.
    legacy = {e.filename: e for e in existing if e.upstream_class is None}
    for board in list(free):
        name = f"{sanitize_filename(str(board.board.get('name', '')))}.json"
        old = legacy.get(name)
        if old is not None and name not in pairs and old.upstream_file == board.upstream_file:
            pairs[name] = board
            free.remove(board)
    return pairs, free


def _version_suffix(board: ProducedBoard, keys: list[str]) -> str:
    return "".join(
        f"_{sanitize_filename(key)}-{sanitize_filename(str(board.upstream_args[key]))}"
        for key in keys
    )


def _plain_stem(upstream_file: str) -> str:
    return Path(upstream_file).stem


def _name_new(
    board: ProducedBoard,
    produced: list[ProducedBoard],
    taken: dict[str, tuple[str, str]],
    file_stem: Callable[[str], str] = _plain_stem,
) -> str:
    """Return the file name for a new identity (§4.1), or raise a clash."""
    same_file = [b for b in produced if b.upstream_file == board.upstream_file]
    stem = sanitize_filename(file_stem(board.upstream_file))
    name = stem
    if len({b.upstream_class for b in same_file}) > 1:
        cls = sanitize_filename(board.upstream_class.removesuffix("Platform"))
        if cls:
            name += f"_{cls}"
    default = next(
        (b for b in same_file if b.default and b.upstream_class == board.upstream_class), None
    )
    params = [k for k in VERSION_PARAMS if k in board.upstream_args]
    if default is not None and default is not board:
        changed = [k for k in params if default.upstream_args.get(k) != board.upstream_args[k]]
        name += _version_suffix(board, changed)
    owner = taken.get(f"{name}.json")
    if owner == (board.upstream_file, board.upstream_class):
        # Held by another identity of the same file and class (Wukong's default revision 1
        # arriving after revision 2 holds qmtech_wukong.json): spell every version key.
        name = stem + _version_suffix(board, params)
        owner = taken.get(f"{name}.json")
    if owner is not None:
        raise SyncFailureError(
            [
                f"{board.upstream_file}: new board would be named {name}.json, already taken by "
                f"{owner[0]} ({owner[1] or 'no class'})"
            ]
        )
    return f"{name}.json"


def _content(data: Mapping[str, Any]) -> str:
    return json.dumps({k: data.get(k) for k in _CONTENT_KEYS}, sort_keys=True)


def _ledger_text(outcome: ParseOutcome, names: list[str], accepted: bool) -> str:
    if outcome.outcome == "boards":
        return "boards: " + ", ".join(sorted(names))
    text = f"{outcome.outcome}: {outcome.detail}"
    return f"{text} (accepted)" if accepted else text


def run_sync(
    *,
    origin: str,
    repo: str,
    files: Mapping[str, str],
    commit_sha: str,
    output_dir: Path,
    read: Reader,
    accept_list: list[Acceptance] | None = None,
    dry_run: bool = False,
    describe: Callable[[ProducedBoard], str] | None = None,
    schema_path: Path | None = None,
    color_registry: dict[str, Any] | None = None,
    classless: bool = False,
    file_stem: Callable[[str], str] = _plain_stem,
) -> SyncReport:
    """Read every upstream file, decide each board's file, and write (module docstring).

    ``classless`` is for a source whose files define no classes (Digilent XDC): its
    identity is ``(origin, upstream_file)``, so every existing file already has one.
    ``file_stem`` turns an upstream file name into the stem a new board's file is named
    after (Digilent drops the ``-Master`` every XDC file name ends in).
    """
    acceptances = [a for a in (accept_list or []) if a.source == origin]
    used: set[Acceptance] = set()
    existing = _load_existing(output_dir, origin, classless)

    outcomes: dict[str, ParseOutcome] = {}
    produced: list[ProducedBoard] = []
    for filename, text in sorted(files.items()):
        try:
            outcome = read(filename, text, None)
        except Exception as exc:  # a parser bug must still reach the ledger
            outcome = ParseOutcome(outcome="error", detail=normalize_error(exc))
        produced.extend(outcome.boards)
        produced.extend(_construct_recorded(read, filename, text, outcome, existing))
        outcomes[filename] = outcome

    pairs, unpaired = _pair(existing, produced)
    report = SyncReport()
    problems: list[str] = []
    taken = {e.filename: (e.upstream_file, e.upstream_class or "") for e in existing}
    if output_dir.is_dir():  # a file this sync does not own is never overwritten either
        for path in output_dir.glob("*.json"):
            if not path.name.startswith("_") and path.name not in taken:
                taken[path.name] = ("a file this sync does not own", "")
    new_names: dict[str, ProducedBoard] = {}
    for board in unpaired:
        try:
            name = _name_new(board, produced, taken, file_stem)
        except SyncFailureError as failure:
            problems.extend(failure.problems)
            continue
        taken[name] = (board.upstream_file, board.upstream_class)
        new_names[name] = board

    by_file: dict[str, list[str]] = {}
    for name, board in [*pairs.items(), *new_names.items()]:
        by_file.setdefault(board.upstream_file, []).append(name)

    orphan_jsons: dict[str, str] = {}
    for entry in existing:
        if entry.filename in pairs:
            continue
        if entry.orphaned:
            # Still orphaned: the mark stays exactly as it is (stable re-syncs), and the
            # acceptance that allowed it keeps matching for as long as the orphan exists.
            reason = str(entry.data["source"].get("orphaned_reason", ""))
            used.update(
                a
                for a in acceptances
                if a.outcome == "orphan"
                and a.file == entry.filename
                and a.orphaned_reason == reason
            )
            report.orphans.append(entry.filename)
            continue
        found = outcomes.get(entry.upstream_file)
        reason = ""
        if found is None:
            reason = "file_removed"
        elif found.outcome == "error":
            acceptance = next(
                (
                    a
                    for a in acceptances
                    if a.outcome == "error" and a.upstream_file == entry.upstream_file
                ),
                None,
            )
            if acceptance is None:
                problems.append(
                    f"would orphan {entry.filename} because our parser failed on "
                    f"{entry.upstream_file} ({found.detail})"
                )
            else:
                used.add(acceptance)  # upstream still has it; we cannot read the current file
            continue
        else:
            reason = (
                "no_simulatable_io" if found.detail == "no_simulatable_io" else "no_longer_defined"
            )
            acceptance = next(
                (
                    a
                    for a in acceptances
                    if a.outcome == "orphan"
                    and a.file == entry.filename
                    and a.orphaned_reason == reason
                ),
                None,
            )
            if acceptance is None:
                problems.append(
                    f"{entry.filename}: {entry.upstream_file} parsed but no longer produces "
                    f"this board ({reason}); a person must check it and accept the orphan"
                )
                continue
            used.add(acceptance)
        same_file = [n for n, b in new_names.items() if b.upstream_file == entry.upstream_file]
        if len(same_file) == 1:
            successor = same_file[0]
        else:
            matches = [n for n, b in new_names.items() if _content(b.board) == _content(entry.data)]
            successor = matches[0] if len(matches) == 1 else ""
        source = dict(entry.data["source"])
        source["upstream_status"] = "orphaned"
        source["orphaned_at_commit"] = source.get("orphaned_at_commit") or commit_sha
        source["orphaned_reason"] = reason
        if successor:
            source["successor"] = f"{origin}/{successor}"
        marked = {**entry.data, "source": source}
        orphan_jsons[entry.filename] = json.dumps(marked, indent=2) + "\n"
        report.orphans.append(entry.filename)

    for acceptance in acceptances:
        if acceptance.outcome == "error":
            seen = outcomes.get(acceptance.upstream_file)
            if seen is not None and seen.outcome == "error":
                used.add(acceptance)
        if acceptance not in used:
            problems.append(
                f"stale acceptance: {acceptance.upstream_file} {acceptance.outcome} "
                f"{acceptance.file} no longer matches anything; remove it"
            )
    if problems:
        raise SyncFailureError(sorted(problems))

    accepted_errors = {a.upstream_file for a in used if a.outcome == "error"}
    for filename, outcome in outcomes.items():
        names = by_file.get(filename, [])
        report.ledger[filename] = _ledger_text(outcome, names, filename in accepted_errors)
        if outcome.warnings:
            report.warnings[filename] = sorted(outcome.warnings)

    board_jsons: dict[str, str] = {}
    for name, board in sorted([*pairs.items(), *new_names.items()]):
        board_jsons[name] = json.dumps(board.board, indent=2) + "\n"
        report.written[name] = board
        if describe is not None:
            print(f"  {board.upstream_file} -> {name} ({describe(board)})")
    report.new = sorted(new_names)
    report.orphans.sort()

    write_outputs(
        output_dir,
        board_jsons,
        commit_sha,
        repo,
        dry_run=dry_run,
        schema_path=schema_path,
        color_registry=color_registry,
        frozen=orphan_jsons,
        extra_metadata={
            "ledger": dict(sorted(report.ledger.items())),
            "warnings": dict(sorted(report.warnings.items())),
            "orphans": report.orphans,
        },
    )
    return report
