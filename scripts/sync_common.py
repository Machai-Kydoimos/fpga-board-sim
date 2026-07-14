"""Shared scaffolding for the board-sync scripts.

Archive download, GitHub ref resolution, filesystem-safe naming, and JSON/metadata
output — the source-agnostic plumbing every ``sync_*.py`` script needs identically.
Each parser lives in its own module (``amaranth_parser`` / ``litex_parser`` /
``digilent_parser``); this module is the plumbing they share.
"""

import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from jsonschema.validators import validator_for


def sanitize_filename(name: str) -> str:
    """Convert a board name to a filesystem-safe base name."""
    result: list[str] = []
    for ch in name.lower():
        result.append(ch if (ch.isalnum() or ch == "-") else "_")
    safe = "".join(result)
    while "__" in safe or "--" in safe:
        safe = safe.replace("__", "_").replace("--", "-")
    return safe.strip("_-")


def unique_name(base: str, seen: dict[str, int]) -> str:
    """Return a unique filename base, appending _2, _3, ... on collision."""
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return f"{base}_{seen[base]}"


def resolve_commit_sha(repo: str, ref: str) -> str:
    """Resolve a git ref to a commit SHA via the GitHub API (falls back to ref).

    Sends ``GITHUB_TOKEN`` / ``GH_TOKEN`` as a bearer credential when either is
    set. The port-convention generator resolves one ref per board to pin its
    source URL; the unauthenticated GitHub API's 60-request/hour limit is low
    enough that a real population wave otherwise exhausts it mid-run and
    silently falls back to unpinned branch URLs. Auth is optional -- with no
    token the request is unchanged.
    """
    url = f"https://api.github.com/repos/{repo}/commits/{ref}"
    headers = {"Accept": "application/vnd.github.sha"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return str(resp.read().decode().strip())
    except Exception:
        return ref


def download_archive(repo: str, ref: str, timeout: int = 120) -> bytes:
    """Download a GitHub repo's source archive for the given git ref."""
    url = f"https://github.com/{repo}/archive/{ref}.tar.gz"
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return bytes(resp.read())


def fetch_url(url: str, cache_dir: Path | None = None, timeout: int = 30) -> str:
    """Fetch a single URL's text content, optionally through an on-disk cache.

    Unlike ``download_archive`` (one whole-repo tarball per sync run), the A3
    port-convention generator fetches one small file per board from whatever
    repo that board's registry row cites -- a different repo per call, so
    per-URL caching (keyed by a hash of the URL) is what actually helps
    repeated ``--check``/debugging runs avoid re-fetching the same file.
    """
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / hashlib.sha256(url.encode()).hexdigest()
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

    with urllib.request.urlopen(url, timeout=timeout) as resp:
        text: str = resp.read().decode("utf-8")

    if cache_dir is not None:
        cache_path.write_text(text, encoding="utf-8")
    return text


def validate_board_jsons(board_jsons: dict[str, str], schema_path: Path) -> None:
    """Validate every serialized board JSON against the board schema.

    Runs at sync time so a parser regression is caught when the JSON is
    generated, rather than later in the test suite. All violations across all
    boards are collected and reported together in a single ``ValueError``;
    raises ``FileNotFoundError`` if the schema itself is missing.
    """
    if not schema_path.exists():
        raise FileNotFoundError(
            f"Board schema not found at {schema_path}; cannot validate sync output."
        )

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_cls = validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)

    errors: list[str] = []
    for filename, content in sorted(board_jsons.items()):
        data = json.loads(content)
        for err in validator.iter_errors(data):
            location = "/".join(str(p) for p in err.absolute_path) or "<root>"
            errors.append(f"{filename}: {err.message} (at {location})")

    if errors:
        errors.sort()
        listing = "\n".join(f"  - {e}" for e in errors)
        raise ValueError(f"Board schema validation failed ({len(errors)} issue(s)):\n{listing}")


def _fold_forward_unmanaged_keys(content: str, out_path: Path) -> str:
    """Fold board-JSON keys a sync script doesn't generate forward from disk.

    A parser regenerates a board file from scratch each run, so anything it
    doesn't itself produce -- today, ``port_conventions`` / ``peripherals`` --
    would otherwise be silently wiped on the next sync. ``port_conventions`` is
    merged per top-level sub-key (new overlays old): a parser that generates no
    conventions at all (amaranth, litex) contributes an empty overlay and every
    existing sub-key survives untouched; ``sync_digilent_xdc.py``, which
    generates only the ``digilent`` sub-key, correctly overwrites just that key
    while any other convention (hand-authored or populated by U21's later
    generator) survives. ``peripherals`` has no sync-script generator yet, so
    it is preserved wholesale when the fresh content doesn't supply one.

    Returns ``content`` unchanged (same string, no re-parse/re-serialize) when
    there is nothing on disk to preserve, so files with no existing
    ``port_conventions``/``peripherals`` are byte-identical to a from-scratch
    write -- the common case, and the one a re-sync's ``git diff`` must stay
    silent on.

    Raises ``ValueError`` (naming ``out_path``) if the existing file is not
    valid JSON, or not a JSON object -- a re-sync that reads a board file for
    the first time is the first thing to notice a corrupted one, and should
    say so clearly rather than crash on a raw ``.get()`` call.
    """
    if not out_path.exists():
        return content

    try:
        existing = json.loads(out_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(
            f"{out_path}: existing file is not valid JSON ({e}); fix or remove it before re-syncing"
        ) from e
    if not isinstance(existing, dict):
        raise ValueError(
            f"{out_path}: existing file's top level is a "
            f"{type(existing).__name__}, not an object; fix or remove it before re-syncing"
        )

    existing_conventions = existing.get("port_conventions") or {}
    existing_peripherals = existing.get("peripherals") or []
    if not existing_conventions and not existing_peripherals:
        return content

    data = json.loads(content)

    merged_conventions = {**existing_conventions, **(data.get("port_conventions") or {})}
    if merged_conventions:
        data["port_conventions"] = merged_conventions

    if not data.get("peripherals") and existing_peripherals:
        data["peripherals"] = existing_peripherals

    return json.dumps(data, indent=2) + "\n"


def write_outputs(
    output_dir: Path,
    board_jsons: dict[str, str],
    commit_sha: str,
    repo: str,
    dry_run: bool = False,
    schema_path: Path | None = None,
) -> None:
    """Fold forward unmanaged keys, validate, then write board files + metadata.

    Every board is first merged against whatever is already on disk (see
    ``_fold_forward_unmanaged_keys``), so hand-authored or previously
    populated ``port_conventions``/``peripherals`` survive a re-sync. The
    *merged* result is what gets validated against the schema, so a corrupt
    on-disk convention block is caught here rather than written silently.
    Validation runs before anything is written, so a single invalid board
    aborts the whole sync with no partial output (and ``--dry-run`` doubles as
    a schema check). ``schema_path`` defaults to
    ``<output_dir>/../schema/board.schema.json``.
    """
    if schema_path is None:
        schema_path = output_dir.parent / "schema" / "board.schema.json"

    board_jsons = {
        filename: _fold_forward_unmanaged_keys(content, output_dir / filename)
        for filename, content in board_jsons.items()
    }
    validate_board_jsons(board_jsons, schema_path)

    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in sorted(board_jsons.items()):
        out_path = output_dir / filename
        if dry_run:
            print(f"  [dry-run] Would write {out_path}")
        else:
            out_path.write_text(content, encoding="utf-8")

    metadata = {
        "source_repo": f"https://github.com/{repo}",
        "source_commit": commit_sha,
        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
        "board_count": len(board_jsons),
        "files_written": sorted(board_jsons.keys()),
    }
    meta_path = output_dir / "_sync_metadata.json"
    if dry_run:
        print(f"  [dry-run] Would write {meta_path} ({len(board_jsons)} boards)")
    else:
        meta_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
