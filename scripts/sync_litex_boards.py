"""Sync board definitions from litex-boards GitHub repository.

Downloads the source archive, mocks the LiteX build system classes,
reads each board platform file against them (parsed and interpreted,
never executed -- U56 D-7), and emits JSON board definitions to
boards/litex-boards/.
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

from litex_parser import read_litex_file  # noqa: E402
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

# ═══════════════════════════════════════════════════════════════════════
#  Archive handling
# ═══════════════════════════════════════════════════════════════════════

_REPO = "litex-hub/litex-boards"


def extract_board_files(archive_bytes: bytes) -> dict[str, str]:
    """Extract board platform .py files from the tarball."""
    board_files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            # Structure: litex-boards-{ref}/litex_boards/platforms/*.py
            if (
                len(parts) >= 4
                and parts[1] == "litex_boards"
                and parts[2] == "platforms"
                and parts[3].endswith(".py")
            ):
                filename = parts[3]
                if filename.startswith("_"):
                    continue
                f = tar.extractfile(member)
                if f is not None:
                    board_files[filename] = f.read().decode("utf-8")
    return board_files


#: The upstream modules a board file may import that the parser reads (never runs)
#: rather than stubs: the extension classes, whose I/O add_extension needs.  Never
#: another board file, whose Platform class could pass for the importer's own; and
#: not ``compat``, whose helpers only emit deprecation warnings (U56 Phase 4).
_READ_MODULES = ("extensions",)


def extract_modules(archive_bytes: bytes) -> dict[str, str]:
    """Extract the importable upstream modules as ``{dotted name: source}``."""
    modules: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            parts = Path(member.name).parts
            if not member.isfile() or len(parts) < 3 or parts[1] != "litex_boards":
                continue
            inside = parts[2:]
            if inside[0] not in _READ_MODULES or not inside[-1].endswith(".py"):
                continue
            dotted = ".".join(("litex_boards", *inside)).removesuffix(".py")
            dotted = dotted.removesuffix(".__init__")
            f = tar.extractfile(member)
            if f is not None:
                modules[dotted] = f.read().decode("utf-8")
    return modules


# ═══════════════════════════════════════════════════════════════════════
#  Output
# ═══════════════════════════════════════════════════════════════════════


_ORIGIN = "litex-boards"


def make_reader(
    commit_sha: str,
    schema_ref: str = "../schema/board.schema.json",
    timestamp: str = "",
    modules: Mapping[str, str] | None = None,
) -> Reader:
    """Return the reader ``run_sync`` calls per upstream file: read it, then stamp ``source``.

    The identity fields sit after ``upstream_file`` and the board keys keep today's order,
    so a re-sync rewrites a board only where its content really changed.  ``modules`` are
    the upstream modules a board file may import (:func:`extract_modules`).
    """
    stamp = timestamp or datetime.now(UTC).isoformat()

    def read(filename: str, text: str, args: Mapping[str, Any] | None) -> ParseOutcome:
        outcome = read_litex_file(text, filename, args, modules)
        for produced in outcome.boards:
            source: dict[str, Any] = {
                "origin": _ORIGIN,
                "upstream_file": filename,
                "upstream_class": produced.upstream_class,
            }
            if produced.upstream_args:
                source["upstream_args"] = dict(produced.upstream_args)
            source["sync_commit"] = commit_sha
            source["sync_timestamp"] = stamp
            produced.board["$schema"] = schema_ref
            produced.board["source"] = source
        return outcome

    return read


def describe(produced: ProducedBoard) -> str:
    """Summarize one board for the sync's progress line."""
    board = produced.board
    seg = f", {board['seven_seg']['num_digits']}-digit 7seg" if board.get("seven_seg") else ""
    return (
        f"{len(board.get('leds', []))} LEDs, {len(board.get('switches', []))} SW,"
        f" {len(board.get('buttons', []))} BTN{seg}"
    )


def generate_all_json(
    board_files: dict[str, str],
    commit_sha: str,
    schema_ref: str = "../schema/board.schema.json",
) -> dict[str, str]:
    """Read every board file and return ``{file name: JSON}``, with no disk state.

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


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Sync board definitions from litex-boards GitHub repository."
    )
    parser.add_argument(
        "--ref",
        default="master",
        help="Git ref to sync from (branch, tag, or commit SHA). Default: master",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "boards" / "litex-boards",
        help="Output directory for JSON files. Default: boards/litex-boards/",
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
            read=make_reader(commit_sha, modules=extract_modules(archive_bytes)),
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
