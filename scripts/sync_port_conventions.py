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
of ``kind`` in ``vendor-official``/``official-repo`` (or a `files[]` target
under ``boards/custom/`` -- see `_targets_a_custom_board`; or a rank-1 source
citedly vouched ``naming = "canonical"`` -- see `_rank1_vouched_canonical`;
or a cited overlay resource-name override that restores a vendor-canonical
name a course source renamed -- see `_overlay_supplies_cited_canonical_names`;
all because ``kind`` is a hosting-location label, not an accuracy one), a
fetched source in a dialect this package parses, and the board listed in
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

from framework_conventions import reconcile_framework_polarity
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
# Sections whose port *name* an overlay may override to restore a vendor-canonical
# name a course source renamed. `seven_seg` is excluded: it carries a `names` list,
# not a single `name`.
_NAME_OVERRIDABLE = ("leds", "leds_green", "switches", "buttons")


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


def _targets_a_custom_board(row: dict[str, Any]) -> bool:
    """Return whether any of `row`'s files[] targets live under boards/custom/.

    ``boards/custom/`` (per CLAUDE.md: "manually maintained boards") is
    where a human has independently verified a board's port names against
    real vendor documentation -- that already happened for e.g. DE10-Standard
    and DE2-115 (confirmed by Rick 2026-07-12), regardless of what the
    registry's own ``kind`` field says about *where the constraint file
    happens to be hosted*. ``kind`` is a hosting-location label, not an
    accuracy label -- A3 already proved this empirically, twice, by
    reproducing those two boards' hand-authored blocks field-for-field from
    community-hosted course QSFs. A board living in boards/custom/ is the
    trust signal itself; it doesn't need a second one from ``kind``.
    """
    return any(f.startswith("custom/") for f in row.get("files", []))


def _rank1_vouched_canonical(rank1: dict[str, Any]) -> bool:
    """Return whether a rank-1 source is explicitly, citedly vouched canonical.

    A community-/personal-hosted constraint file can still use the vendor's
    *canonical* port names -- Terasic's ``CLOCK_50``/``SW``/``LEDR``/``KEY``/
    ``HEXn`` are a family-wide standard set by the board manuals and Quartus
    System Builder, whoever happens to re-host a course QSF that uses them.
    ``kind`` labels *where a file is hosted*, not *whether its names are
    canonical* -- the same distinction `_targets_a_custom_board` rests on.
    This is the affirmative, per-source, *cited* form of that trust: a
    maintainer records ``naming = "canonical"`` plus a ``naming_cite`` on the
    registry row's rank-1 source. Both are required -- an uncited claim is
    ignored (fails safe), and a project-renamed course file, by construction,
    never earns the vouch (this is where the plan's "exclude project-renamed
    naming" rule is actually enforced).
    """
    return rank1.get("naming") == "canonical" and bool(rank1.get("naming_cite"))


def _overlay_supplies_cited_canonical_names(overlay_row: dict[str, Any] | None) -> bool:
    """Whether the overlay supplies a cited canonical port-*name* correction.

    The System-CD rescue case (U21 A4 follow-up): a verified community QSF uses
    the vendor's canonical names for most ports but *renames* a few (e.g.
    DE10-Lite's LEDR -> LED). A maintainer restores the canonical name with a
    cited `name` override in overlay.toml (see `apply_overlay`), verified against
    the vendor's official System CD golden-top. That cited correction is the
    per-board signal that the *shipped* convention's names are vendor-canonical
    -- parallel to `_rank1_vouched_canonical`, but for the source-plus-overlay
    case rather than source-alone. Both a `name` and a `cite` are required on the
    same section; an uncited name override does not count (fails safe), just as
    the naming vouch requires its cite.
    """
    if not overlay_row:
        return False
    return any(
        isinstance(ov, dict) and bool(ov.get("name")) and bool(ov.get("cite"))
        for ov in (overlay_row.get(s) for s in _NAME_OVERRIDABLE)
    )


def check_row_gate(
    row: dict[str, Any],
    waves: set[str],
    overlay: dict[str, Any] | None = None,
    *,
    force: bool = False,
) -> GateResult:
    """Decide whether `row` may be processed.

    `force` (``--board``) bypasses the status/kind/wave-membership checks --
    it exists precisely to let a maintainer run a specific board for
    curation or regression-testing ahead of (or regardless of) its trust
    tier -- but never bypasses having a usable, structured-format source:
    there is nothing to parse otherwise, forced or not.

    Independently of `force`, three things skip the ``kind`` check
    specifically (never `status`/wave-membership, which stay meaningful
    regardless): a row that targets a board in ``boards/custom/`` (see
    `_targets_a_custom_board`), a rank-1 source citedly vouched
    ``naming = "canonical"`` (see `_rank1_vouched_canonical`), and a cited
    overlay resource-name override that restores canonical names a course
    source renamed (see `_overlay_supplies_cited_canonical_names`) -- all
    encode that ``kind`` is a hosting-location label, not a port-name-accuracy
    one.
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
    overlay_row = (overlay or {}).get(row.get("name", ""))
    if (
        rank1.get("kind") not in _TRUSTED_KINDS
        and not _targets_a_custom_board(row)
        and not _rank1_vouched_canonical(rank1)
        and not _overlay_supplies_cited_canonical_names(overlay_row)
    ):
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
    is only ever a fallback. `clk` overrides the whole clk name;
    `leds`/`leds_green`/`switches`/`buttons`/`seven_seg` may override
    `active_low` (classify() derives polarity only from a literal `_N`/`_n`
    suffix -- see classify.py's module docstring); and `leds`/`leds_green`/
    `switches`/`buttons` may also override the port `name`, to restore a
    vendor-canonical name a course source renamed (e.g. DE10-Lite's LED ->
    LEDR). Each override is cited in overlay.toml.
    """
    result = {k: (dict(v) if isinstance(v, dict) else v) for k, v in convention.items()}
    if overlay_row is None:
        return result

    if "clk" in overlay_row:
        result["clk"] = overlay_row["clk"]

    for section in _ACTIVE_LOW_OVERRIDABLE:
        override = overlay_row.get(section)
        if not isinstance(override, dict) or section not in result:
            continue  # no override for this section, or nothing classified to attach it to
        if "active_low" in override:
            result[section]["active_low"] = override["active_low"]
        if "name" in override and section in _NAME_OVERRIDABLE:
            result[section]["name"] = override["name"]

    return result


# ═══════════════════════════════════════════════════════════════════════
#  Width cross-check
# ═══════════════════════════════════════════════════════════════════════


def cross_check_widths(convention: dict[str, Any], board: dict[str, Any]) -> str | None:
    """Return a mismatch description, or None if every present bank fits the board.

    Compares against the board JSON's *own* already-known resource counts
    (its `leds`/`switches`/`buttons`/`seven_seg` lists/dict) -- never against
    another convention or the registry. A board's `leds` count includes both
    the primary and `leds_green` banks (DE2-115-style boards list all 27 LEDs
    together), so those two widths are summed before comparing.

    A source bank *narrower* than the board is allowed: it is a legitimate
    partial convention (a board's own constraint file often wires up only some
    of its LEDs/buttons), and the native wrapper already adapts it -- zero-
    extending a short LED bank and feeding the low bits of a short input bank,
    exactly as it does for U32's framework-derived banks. Only a bank *wider*
    than the board is a real mismatch: it claims resources the board JSON does
    not model, so either the source is for a different variant or the board is
    under-modeled -- either way, not safe to write. 7-segment digit counts stay
    exact (the wrapper packs a fixed digit count, not a partial one).
    """
    if "leds" in convention:
        total = convention["leds"]["width"] + convention.get("leds_green", {}).get("width", 0)
        board_total = len(board.get("leds", []))
        if total > board_total:
            return f"leds(+leds_green) width {total} exceeds board's {board_total} LEDs"

    if "switches" in convention:
        want = convention["switches"]["width"]
        got = len(board.get("switches", []))
        if want > got:
            return f"switches width {want} exceeds board's {got} switches"

    if "buttons" in convention:
        want = convention["buttons"]["width"]
        got = len(board.get("buttons", []))
        if want > got:
            return f"buttons width {want} exceeds board's {got} buttons"

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
    gate = check_row_gate(row, waves, overlay, force=force)
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


def carry_forward_retrieved(new_block: dict[str, Any], existing_block: object) -> dict[str, Any]:
    """Keep the on-disk ``source.retrieved`` date when a block is otherwise unchanged.

    ``process_board`` stamps ``source.retrieved`` with *today's* date on every run,
    so without this a no-op re-sync rewrites that timestamp on every board it can
    still regenerate -- churn that buries real drift and makes the release
    pre-flight ``--check`` cry wolf (it did, on v0.17.0). When the freshly
    generated block equals the existing one apart from that single field, the
    existing date is carried forward so the merge is a true byte-for-byte no-op;
    any real change -- including the pinned source URL moving to a new commit --
    still updates ``retrieved`` as before.
    """
    if not isinstance(existing_block, dict):
        return new_block
    new_src, old_src = new_block.get("source"), existing_block.get("source")
    if not (isinstance(new_src, dict) and isinstance(old_src, dict) and "retrieved" in old_src):
        return new_block

    def _without_retrieved(block: dict[str, Any]) -> dict[str, Any]:
        src = {k: v for k, v in block["source"].items() if k != "retrieved"}
        return {**block, "source": src}

    if _without_retrieved(new_block) == _without_retrieved(existing_block):
        return {**new_block, "source": {**new_src, "retrieved": old_src["retrieved"]}}
    return new_block


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

    Returns ``{relative_path: full_merged_board_dict}`` for every touched
    file -- used both to write (schema-validated first) and by ``--check``
    to diff against what is already on disk without writing anything.
    """
    per_file: dict[str, dict[str, Any]] = {}
    for result in results:
        for rel_path, new_sub_keys in result.convention_by_file.items():
            board_path = BOARDS_DIR / rel_path
            board_json = per_file.get(rel_path) or json.load(board_path.open())
            existing = board_json.get("port_conventions") or {}
            # Preserve the on-disk retrieval date for any sub-key whose content is
            # otherwise identical, so a no-op re-sync doesn't churn the timestamp.
            new_sub_keys = {
                slug: carry_forward_retrieved(block, existing.get(slug))
                for slug, block in new_sub_keys.items()
            }
            board_json["port_conventions"] = {**existing, **new_sub_keys}
            per_file[rel_path] = board_json

    # F2: once every canonical block is merged in, let each board's framework-
    # derived banks inherit polarity from a same-role, same-width canonical bank.
    for board_json in per_file.values():
        pc = board_json.get("port_conventions")
        if isinstance(pc, dict):
            board_json["port_conventions"] = reconcile_framework_polarity(pc)

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
