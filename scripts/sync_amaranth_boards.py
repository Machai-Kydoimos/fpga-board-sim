"""Sync board definitions from amaranth-boards GitHub repository.

Downloads the source archive, parses each board Python file using the
existing mock-exec loader, and emits JSON board definitions to the
target directory (default: boards/amaranth-boards/).
"""

import argparse
import io
import json
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from amaranth_parser import load_board_from_source  # noqa: E402
from sync_common import (  # noqa: E402
    download_archive,
    resolve_commit_sha,
    sanitize_filename,
    unique_name,
    write_outputs,
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


def generate_board_json(
    board_files: dict[str, str],
    commit_sha: str,
    schema_ref: str = "../schema/board.schema.json",
) -> dict[str, str]:
    """Parse board files and generate JSON strings. Returns {output_filename: json_str}."""
    seen: dict[str, int] = {}
    results: dict[str, str] = {}
    timestamp = datetime.now(timezone.utc).isoformat()

    for filename, source in sorted(board_files.items()):
        try:
            boards = load_board_from_source(source, filename)
        except Exception as e:
            print(f"  [skip] {filename}: {e}", file=sys.stderr)
            continue

        if not boards:
            continue

        for board in boards:
            raw = json.loads(board.to_json())
            raw["$schema"] = schema_ref
            raw["source"] = {
                "origin": "amaranth-boards",
                "upstream_file": filename,
                "sync_commit": commit_sha,
                "sync_timestamp": timestamp,
            }

            base = sanitize_filename(board.name)
            output_name = unique_name(base, seen)
            results[f"{output_name}.json"] = json.dumps(raw, indent=2) + "\n"
            print(f"  {filename} -> {output_name}.json ({board.name})")

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

    print("Generating JSON definitions ...")
    board_jsons = generate_board_json(board_files, commit_sha)
    print(f"Generated {len(board_jsons)} board definitions.")

    print(f"\nWriting to {args.output_dir} ...")
    write_outputs(args.output_dir, board_jsons, commit_sha, _REPO, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
