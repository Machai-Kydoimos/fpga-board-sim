"""Sync board definitions from Digilent master XDC constraint files.

Downloads the digilent-xdc GitHub repository, parses each .xdc file
using section-aware regex, and emits JSON board definitions with
port_conventions to boards/digilent-xdc/.
"""

import argparse
import io
import sys
import tarfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from digilent_parser import build_board_json  # noqa: E402
from sync_common import (  # noqa: E402
    ParseOutcome,
    ProducedBoard,
    download_archive,
    normalize_error,
    resolve_commit_sha,
)
from sync_identity import SyncFailureError, load_accept_list, run_sync, summarize  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════
#  Archive handling
# ═══════════════════════════════════════════════════════════════════════

_REPO = "Digilent/digilent-xdc"
_ORIGIN = "digilent-xdc"


def digilent_stem(upstream_file: str) -> str:
    """Return the stem a new Digilent board's file is named after.

    Every Digilent XDC file is called ``<Board>-Master.xdc``, so the suffix says nothing:
    a new ZedBoard is ``zedboard.json``, in the style of the existing ``basys_3.json``
    (decided 2026-11-01, Rick). Existing files keep their names forever (U56 §4.1).
    """
    return Path(upstream_file).stem.removesuffix("-Master")


def extract_xdc_files(archive_bytes: bytes) -> dict[str, str]:
    """Extract .xdc files from the tarball. Returns {filename: source}."""
    xdc_files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            name = Path(member.name).name
            if name.endswith(".xdc") and name.endswith("-Master.xdc"):
                f = tar.extractfile(member)
                if f is not None:
                    xdc_files[name] = f.read().decode("utf-8")
    return xdc_files


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Sync board definitions from Digilent master XDC files."
    )
    parser.add_argument(
        "--ref",
        default="master",
        help="Git ref to sync from (branch, tag, or commit SHA). Default: master",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "boards" / "digilent-xdc",
        help="Output directory for JSON files. Default: boards/digilent-xdc/",
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

    print("Extracting XDC files ...")
    xdc_files = extract_xdc_files(archive_bytes)
    print(f"Found {len(xdc_files)} XDC files.")

    if not xdc_files:
        print("No XDC files found in archive.", file=sys.stderr)
        return 1

    def read(filename: str, text: str, args: Mapping[str, Any] | None) -> ParseOutcome:
        # An XDC file defines no classes, so its identity is (origin, upstream_file) and
        # its board dict -- `source` included -- is exactly what `build_board_json` builds.
        try:
            board = build_board_json(text, filename, commit_sha)
        except Exception as exc:
            return ParseOutcome(outcome="error", detail=normalize_error(exc))
        if board is None:
            return ParseOutcome(outcome="skipped", detail="no_simulatable_io")
        return ParseOutcome(boards=[ProducedBoard(board=board, upstream_file=filename)])

    def describe(produced: ProducedBoard) -> str:
        board = produced.board
        seg = f", {board['seven_seg']['num_digits']}-digit 7seg" if board.get("seven_seg") else ""
        conv = " +port_conventions" if board.get("port_conventions") else ""
        return (
            f"{len(board['leds'])} LEDs, {len(board['switches'])} SW,"
            f" {len(board['buttons'])} BTN{seg}{conv}"
        )

    print(f"Reading XDC files into {args.output_dir} ...")
    try:
        report = run_sync(
            origin=_ORIGIN,
            repo=_REPO,
            files=xdc_files,
            commit_sha=commit_sha,
            output_dir=args.output_dir,
            read=read,
            accept_list=load_accept_list(),
            dry_run=args.dry_run,
            describe=describe,
            classless=True,
            file_stem=digilent_stem,
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
