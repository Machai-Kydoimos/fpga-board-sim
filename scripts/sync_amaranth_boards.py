"""Sync board definitions from amaranth-boards GitHub repository.

Downloads the source archive, reads each board Python file with the
amaranth parser (parsed and interpreted, never executed -- U56 D-7), and
emits JSON board definitions to the target directory (default:
boards/amaranth-boards/).
"""

import argparse
import io
import json
import sys
import tarfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure the project src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from amaranth_parser import read_amaranth_file  # noqa: E402
from sync_common import (  # noqa: E402
    ParseOutcome,
    ProducedBoard,
    download_archive,
    resolve_commit_sha,
    sanitize_filename,
    unique_name,
)
from sync_identity import (  # noqa: E402
    Reader,
    SyncFailureError,
    load_accept_list,
    run_sync,
    summarize,
)

_REPO = "amaranth-lang/amaranth-boards"


def extract_board_files(archive_bytes: bytes) -> dict[str, str]:
    """Extract .py board files from the tarball. Returns {filename: source}."""
    board_files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            # Structure: amaranth-boards-{ref}/amaranth_boards/*.py
            if len(parts) >= 3 and parts[1] == "amaranth_boards" and parts[2].endswith(".py"):
                filename = parts[2]
                if filename.startswith("_"):
                    continue
                f = tar.extractfile(member)
                if f is not None:
                    board_files[filename] = f.read().decode("utf-8")
    return board_files


_ORIGIN = "amaranth-boards"


def make_reader(
    commit_sha: str, schema_ref: str = "../schema/board.schema.json", timestamp: str = ""
) -> Reader:
    """Return the reader ``run_sync`` calls per upstream file: read it, then stamp ``source``.

    Amaranth boards take no version arguments, so ``args`` is never needed; the identity
    is the upstream class, recorded after ``upstream_file``.
    """
    stamp = timestamp or datetime.now(UTC).isoformat()

    def read(filename: str, text: str, args: Mapping[str, Any] | None) -> ParseOutcome:
        outcome = read_amaranth_file(text, filename)
        for produced in outcome.boards:
            produced.board["$schema"] = schema_ref
            produced.board["source"] = {
                "origin": _ORIGIN,
                "upstream_file": filename,
                "upstream_class": produced.upstream_class,
                "sync_commit": commit_sha,
                "sync_timestamp": stamp,
            }
        return outcome

    return read


def describe(produced: ProducedBoard) -> str:
    """Name one board for the sync's progress line."""
    return str(produced.board.get("name", ""))


def generate_board_json(
    board_files: dict[str, str],
    commit_sha: str,
    schema_ref: str = "../schema/board.schema.json",
) -> dict[str, str]:
    """Read board files and return ``{file name: JSON}``, with no disk state.

    For tests and audits only: the write path is ``sync_identity.run_sync``, which names
    files by identity. This names them by display name, as syncs did before identities.
    """
    read = make_reader(commit_sha, schema_ref)
    seen: dict[str, int] = {}
    results: dict[str, str] = {}
    for filename, source in sorted(board_files.items()):
        for produced in read(filename, source, None).boards:
            name = unique_name(sanitize_filename(str(produced.board["name"])), seen)
            results[f"{name}.json"] = json.dumps(produced.board, indent=2) + "\n"
    return results


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Sync board definitions from amaranth-boards GitHub repository."
    )
    parser.add_argument(
        "--ref",
        default="main",
        help="Git ref to sync from (branch, tag, or commit SHA). Default: main",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "boards" / "amaranth-boards",
        help="Output directory for JSON files. Default: boards/amaranth-boards/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be written without writing anything.",
    )
    args = parser.parse_args()

    print(f"Resolving ref '{args.ref}' ...")
    commit_sha = resolve_commit_sha(_REPO, args.ref)
    print(f"Commit: {commit_sha}")

    try:
        archive_bytes = download_archive(_REPO, args.ref)
    except Exception as e:
        print(f"Error downloading archive: {e}", file=sys.stderr)
        return 1

    print("Extracting board files ...")
    board_files = extract_board_files(archive_bytes)
    print(f"Found {len(board_files)} board files.")

    if not board_files:
        print("No board files found in archive.", file=sys.stderr)
        return 1

    print(f"Reading board files (parsed, never executed) into {args.output_dir} ...")
    try:
        report = run_sync(
            origin=_ORIGIN,
            repo=_REPO,
            files=board_files,
            commit_sha=commit_sha,
            output_dir=args.output_dir,
            read=make_reader(commit_sha),
            accept_list=load_accept_list(),
            dry_run=args.dry_run,
            describe=describe,
        )
    except SyncFailureError as failure:
        print("\nSync stopped; nothing was written:", file=sys.stderr)
        for problem in failure.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(summarize(report))

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
