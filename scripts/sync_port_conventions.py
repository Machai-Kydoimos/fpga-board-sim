"""U21 Phase A3: generate ``port_conventions`` blocks from the registry + overlay.

Turns a `docs/port_convention_sources/` registry row into a board JSON's
``port_conventions.<maker-slug>`` block: resolve the row's rank-1 source URL
to a commit-pinned raw URL, fetch it, parse it with the matching A2 dialect
module, classify the parsed ports, apply any `overlay.toml` overrides, and
shallow-merge the result into every board JSON the row's ``files`` lists --
after cross-checking widths against *that specific file's* own
already-known resource counts. A row's ``files`` can name more than one
board JSON for the same physical board (different sync pipelines capture
different subsets of a board's resources), so this check -- and the
write it gates -- is evaluated per target file, not once for the whole row:
one target can be written while a sibling target is skipped.

Trust gate (a board only reaches a write if *all* of these hold, unless
``--board`` forces it): registry ``status == "verified"``, a rank-1 source
of ``kind`` in ``vendor-official``/``official-repo``, a fetched source in a
dialect this package parses, and the board listed in
`docs/port_convention_sources/waves.toml`. ``--board`` overrides trust,
never correctness -- a width mismatch always skips that target file
regardless.

Self-contained CLI, no `fpga_sim` dependency (mirrors `sync_digilent_xdc.py`
et al.). Network access happens only in `main()`/`generate_boards()`; every
other function here is pure, so tests exercise them with in-memory registry/
board data instead of live fetches.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

from port_convention_parsers import boardstore_xml, ccf, classify, cst, lpf, pcf, qsf, ucf, xdc
from port_convention_parsers.types import PortTable
from sync_common import fetch_url, resolve_commit_sha, validate_board_jsons

REGISTRY_DIR = Path(__file__).parent.parent / "docs" / "port_convention_sources"
BOARDS_DIR = Path(__file__).parent.parent / "boards"
SCHEMA_PATH = BOARDS_DIR / "schema" / "board.schema.json"
CACHE_DIR = Path(__file__).parent.parent / ".cache" / "port_conventions"

_TRUSTED_KINDS = {"vendor-official", "official-repo"}

_DIALECT_PARSERS = {
    "QSF": qsf.parse,
    "XDC": xdc.parse,
    "UCF": ucf.parse,
    "PCF": pcf.parse,
    "LPF": lpf.parse,
    "CST": cst.parse,
    "CCF": ccf.parse,
    "XML": boardstore_xml.parse,
}

_RAW_GITHUB_RE = re.compile(r"^https://raw\.githubusercontent\.com/([^/]+/[^/]+)/([^/]+)/(.+)$")

_ACTIVE_LOW_OVERRIDABLE = ("leds", "leds_green", "switches", "buttons", "seven_seg")


# ═══════════════════════════════════════════════════════════════════════
#  Registry / waves / overlay loading
# ═══════════════════════════════════════════════════════════════════════


def load_registry() -> dict[str, dict[str, Any]]:
    """Load every family TOML in `docs/port_convention_sources/`, keyed by board name.

    Excludes ``waves.toml``/``overlay.toml`` -- both also use a ``[[board]]``
    array like the family files, but for a completely different row shape.
    """
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(REGISTRY_DIR.glob("*.toml")):
        if path.name in ("waves.toml", "overlay.toml"):
            continue
        with path.open("rb") as f:
            data = tomllib.load(f)
        for board in data.get("board", []):
            rows[board["name"]] = board
    return rows


def load_waves() -> set[str]:
    """Every board name listed in any wave of `waves.toml` (waves accumulate)."""
    path = REGISTRY_DIR / "waves.toml"
    if not path.exists():
        return set()
    with path.open("rb") as f:
        data = tomllib.load(f)
    names: set[str] = set()
    for wave in data.get("wave", []):
        names.update(wave.get("boards", []))
    return names


def load_overlay() -> dict[str, dict[str, Any]]:
    """Every hand-maintained override row in `overlay.toml`, keyed by board name."""
    path = REGISTRY_DIR / "overlay.toml"
    if not path.exists():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    return {row["name"]: row for row in data.get("board", [])}


# ═══════════════════════════════════════════════════════════════════════
#  Row gate
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class GateResult:
    """Whether a registry row may proceed, and why not if it can't."""

    ok: bool
    reason: str = ""
    rank1: dict[str, Any] | None = None


def check_row_gate(row: dict[str, Any], waves: set[str], *, force: bool = False) -> GateResult:
    """Decide whether `row` may be processed.

    `force` (``--board``) bypasses the status/kind/wave-membership checks --
    it exists precisely to let a maintainer run a specific board for
    curation or regression-testing ahead of (or regardless of) its trust
    tier -- but never bypasses having a usable, structured-format source:
    there is nothing to parse otherwise, forced or not.
    """
    sources = row.get("source", [])
    rank1 = next((s for s in sources if s.get("rank") == 1), None)
    if rank1 is None:
        return GateResult(False, "no rank-1 source")
    if not rank1.get("fetched"):
        return GateResult(False, "rank-1 source is not marked fetched")
    if rank1.get("format") not in _DIALECT_PARSERS:
        return GateResult(False, f"format {rank1.get('format')!r} has no parser")

    if force:
        return GateResult(True, rank1=rank1)

    if row.get("status") != "verified":
        return GateResult(False, f"status is {row.get('status')!r}, not verified")
    if rank1.get("kind") not in _TRUSTED_KINDS:
        return GateResult(False, f"rank-1 kind is {rank1.get('kind')!r}")
    if row["name"] not in waves:
        return GateResult(False, "not listed in any wave")
    return GateResult(True, rank1=rank1)


# ═══════════════════════════════════════════════════════════════════════
#  Fetch + parse + classify
# ═══════════════════════════════════════════════════════════════════════


def pin_url_to_commit(url: str) -> tuple[str, str]:
    """Resolve a raw.githubusercontent.com URL's ref to a commit SHA.

    Returns ``(repo, pinned_url)``. Raises ``ValueError`` for a URL shape
    this can't resolve (e.g. not raw.githubusercontent.com) -- callers treat
    that the same as any other per-board fetch failure: warn and skip.
    """
    m = _RAW_GITHUB_RE.match(url)
    if not m:
        raise ValueError(f"not a raw.githubusercontent.com URL: {url}")
    repo, ref, path = m.groups()
    sha = resolve_commit_sha(repo, ref)
    return repo, f"https://raw.githubusercontent.com/{repo}/{sha}/{path}"


def parse_and_classify(text: str, dialect_format: str) -> dict[str, Any]:
    """Run the matching A2 dialect parser, then classify() the result."""
    parser = _DIALECT_PARSERS[dialect_format]
    table: PortTable = parser(text)
    return classify.classify(table)


# ═══════════════════════════════════════════════════════════════════════
#  Overlay application
# ═══════════════════════════════════════════════════════════════════════


def apply_overlay(convention: dict[str, Any], overlay_row: dict[str, Any] | None) -> dict[str, Any]:
    """Layer `overlay_row`'s cited overrides on top of a classified convention dict.

    An overlay value always wins for the field it states; classify()'s value
    is only ever a fallback. `clk` overrides the whole clk name; the other
    overridable sections (`leds`/`leds_green`/`switches`/`buttons`/
    `seven_seg`) only ever override `active_low` -- see classify.py's module
    docstring for why that field is the one thing overlay data routinely
    needs to supply.
    """
    result = {k: (dict(v) if isinstance(v, dict) else v) for k, v in convention.items()}
    if overlay_row is None:
        return result

    if "clk" in overlay_row:
        result["clk"] = overlay_row["clk"]

    for section in _ACTIVE_LOW_OVERRIDABLE:
        override = overlay_row.get(section)
        if not isinstance(override, dict) or "active_low" not in override:
            continue
        if section not in result:
            continue  # nothing classified for this section; no port_mapping to attach polarity to
        result[section]["active_low"] = override["active_low"]

    return result


# ═══════════════════════════════════════════════════════════════════════
#  Width cross-check
# ═══════════════════════════════════════════════════════════════════════


def cross_check_widths(convention: dict[str, Any], board: dict[str, Any]) -> str | None:
    """Return a mismatch description, or None if everything present agrees.

    Compares against the board JSON's *own* already-known resource counts
    (its `leds`/`switches`/`buttons`/`seven_seg` lists/dict) -- never against
    another convention or the registry. A board's `leds` count includes both
    the primary and `leds_green` banks (DE2-115-style boards list all 27 LEDs
    together), so those two widths are summed before comparing.
    """
    if "leds" in convention:
        total = convention["leds"]["width"] + convention.get("leds_green", {}).get("width", 0)
        board_total = len(board.get("leds", []))
        if total != board_total:
            return f"leds(+leds_green) width {total} != board's {board_total} LEDs"

    if "switches" in convention:
        want = convention["switches"]["width"]
        got = len(board.get("switches", []))
        if want != got:
            return f"switches width {want} != board's {got} switches"

    if "buttons" in convention:
        want = convention["buttons"]["width"]
        got = len(board.get("buttons", []))
        if want != got:
            return f"buttons width {want} != board's {got} buttons"

    seg = convention.get("seven_seg")
    if seg and seg["style"] in ("individual", "per_segment_scalars"):
        board_seg = board.get("seven_seg") or {}
        num_digits = board_seg.get("num_digits")
        if num_digits is not None:
            got_digits = len(seg["names"])
            if seg["style"] == "per_segment_scalars":
                got_digits //= seg["width_per_digit"]
            if got_digits != num_digits:
                return f"seven_seg digit count {got_digits} != board's {num_digits}"

    return None


# ═══════════════════════════════════════════════════════════════════════
#  Per-board pipeline
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BoardResult:
    """The outcome of processing one registry row.

    `skipped` is a *row-level* failure (gate, fetch, or classification) that
    blocks every `files[]` target alike. Below that point, each target file
    is judged independently by its own width cross-check: a row with two
    `files[]` targets (the same physical board reached via two different
    board-JSON sources, which do happen -- see `file_skips`' docstring)
    can have one target written and the other skipped without either
    outcome affecting the other.
    """

    name: str
    skipped: str | None = None
    convention_by_file: dict[str, dict[str, Any]] = field(default_factory=dict)
    file_skips: dict[str, str] = field(default_factory=dict)


def maker_slug(maker: str) -> str:
    """Sanitize a registry row's `maker` field into a port_conventions sub-key."""
    slug = re.sub(r"[^a-z0-9]+", "_", maker.lower()).strip("_")
    return slug or "unknown"


def process_board(
    name: str,
    row: dict[str, Any],
    overlay: dict[str, Any],
    *,
    force: bool,
    waves: set[str],
    cache_dir: Path | None,
) -> BoardResult:
    """Run one board through gate -> fetch -> parse -> classify -> overlay -> cross-check.

    Returns a `BoardResult` with either a `skipped` reason or one convention
    dict per `files[]` target -- writing (or not) is the caller's job.
    """
    gate = check_row_gate(row, waves, force=force)
    if not gate.ok:
        return BoardResult(name, skipped=gate.reason)
    assert gate.rank1 is not None

    if not row.get("files"):
        # Not itself invalid syntax, but nothing to do -- and without this
        # check the row would fall through to an empty convention_by_file
        # AND empty file_skips, which main()'s reporting loop treats as "no
        # news" and prints nothing for. A malformed row (e.g. a copy-paste
        # that dropped `files`) deserves an explicit skip line, not silence.
        return BoardResult(name, skipped="row has no files[] targets")

    try:
        repo, pinned_url = pin_url_to_commit(gate.rank1["url"])
    except ValueError as e:
        return BoardResult(name, skipped=str(e))

    try:
        text = fetch_url(pinned_url, cache_dir=cache_dir)
    except Exception as e:  # noqa: BLE001 - any network/HTTP failure is a per-board skip
        return BoardResult(name, skipped=f"fetch failed: {e}")

    convention = parse_and_classify(text, gate.rank1["format"])
    convention = apply_overlay(convention, overlay.get(name))
    if not convention:
        return BoardResult(name, skipped="classifier found nothing recognizable")

    convention["description"] = row.get(
        "notes", f"{row.get('maker', 'unknown')} {name} auto-generated convention"
    )
    convention["naming"] = "canonical"
    convention["source"] = {
        "url": pinned_url,
        "retrieved": date.today().isoformat(),
        "registry_board": name,
    }

    slug = maker_slug(row.get("maker", "unknown"))
    convention_by_file: dict[str, dict[str, Any]] = {}
    file_skips: dict[str, str] = {}
    for rel_path in row.get("files", []):
        board_path = BOARDS_DIR / rel_path
        if not board_path.exists():
            file_skips[rel_path] = "board JSON not found"
            continue
        with board_path.open() as f:
            board_json = json.load(f)
        mismatch = cross_check_widths(convention, board_json)
        if mismatch:
            file_skips[rel_path] = mismatch
            continue
        convention_by_file[rel_path] = {slug: convention}

    return BoardResult(name, convention_by_file=convention_by_file, file_skips=file_skips)


# ═══════════════════════════════════════════════════════════════════════
#  Writing
# ═══════════════════════════════════════════════════════════════════════


def merged_board_json(board_path: Path, new_sub_keys: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge `new_sub_keys` into `board_path`'s existing `port_conventions`.

    Every other top-level key -- and every other maker's convention already
    under `port_conventions` -- is left exactly as it was.
    """
    with board_path.open() as f:
        board_json: dict[str, Any] = json.load(f)
    existing = board_json.get("port_conventions") or {}
    board_json["port_conventions"] = {**existing, **new_sub_keys}
    return board_json


def generate_boards(
    *,
    board_filter: str | None = None,
    cache_dir: Path | None = CACHE_DIR,
) -> list[BoardResult]:
    """Process every in-scope board (or just `board_filter`, forced through the gate)."""
    registry = load_registry()
    waves = load_waves()
    overlay = load_overlay()

    if board_filter is not None:
        row = registry.get(board_filter)
        if row is None:
            return [BoardResult(board_filter, skipped="not found in the registry")]
        names = [board_filter]
        force = True
    else:
        names = sorted(registry)
        force = False

    results = []
    for name in names:
        results.append(
            process_board(
                name, registry[name], overlay, force=force, waves=waves, cache_dir=cache_dir
            )
        )
    return results


def write_results(
    results: list[BoardResult], *, dry_run: bool = False
) -> dict[str, dict[str, Any]]:
    """Merge every result's convention blocks into their target board JSONs.

    Returns ``{relative_path: full_merged_board_json}`` for every touched
    file -- used both to write (schema-validated first) and by ``--check``
    to diff against what is already on disk without writing anything.
    """
    per_file: dict[str, dict[str, Any]] = {}
    for result in results:
        for rel_path, new_sub_keys in result.convention_by_file.items():
            board_path = BOARDS_DIR / rel_path
            board_json = per_file.get(rel_path) or json.load(board_path.open())
            existing = board_json.get("port_conventions") or {}
            board_json["port_conventions"] = {**existing, **new_sub_keys}
            per_file[rel_path] = board_json

    if not per_file:
        return per_file

    serialized = {path: json.dumps(data, indent=2) + "\n" for path, data in per_file.items()}
    validate_board_jsons(serialized, SCHEMA_PATH)

    if not dry_run:
        for rel_path, content in serialized.items():
            (BOARDS_DIR / rel_path).write_text(content, encoding="utf-8")

    return per_file


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate port_conventions blocks from the port-convention registry."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Regenerate in memory and diff against what's on disk; exit non-zero on drift.",
    )
    parser.add_argument("--board", help="Process a single board by its registry row name.")
    args = parser.parse_args(argv)

    results = generate_boards(board_filter=args.board)

    for result in results:
        if result.skipped:
            print(f"  [skip] {result.name}: {result.skipped}")
            continue
        for rel_path in result.convention_by_file:
            print(f"  {result.name} -> {rel_path}")
        for rel_path, reason in result.file_skips.items():
            print(f"  [skip] {result.name} -> {rel_path}: {reason}")

    written_count = sum(1 for r in results if r.convention_by_file)
    print(f"\n{written_count}/{len(results)} board(s) produced a convention.")

    if args.check:
        drifted = []
        for rel_path, merged in write_results(results, dry_run=True).items():
            with (BOARDS_DIR / rel_path).open() as f:
                on_disk = json.load(f)
            if merged != on_disk:
                drifted.append(rel_path)
        if drifted:
            print("\nDrift detected in:")
            for rel_path in drifted:
                print(f"  {rel_path}")
            return 1
        print("\nNo drift.")
        return 0

    write_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
