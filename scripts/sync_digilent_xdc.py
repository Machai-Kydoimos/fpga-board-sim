"""Sync board definitions from Digilent master XDC constraint files.

Downloads the digilent-xdc GitHub repository, parses each .xdc file
using section-aware regex, and emits JSON board definitions with
port_conventions to boards/digilent-xdc/.
"""

import argparse
import io
import json
import sys
import tarfile
from pathlib import Path

from digilent_parser import build_board_json  # noqa: E402
from sync_common import (  # noqa: E402
    download_archive,
    resolve_commit_sha,
    sanitize_filename,
    unique_name,
    write_outputs,
)

# ═══════════════════════════════════════════════════════════════════════
#  Archive handling
# ═══════════════════════════════════════════════════════════════════════

_REPO = "Digilent/digilent-xdc"


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

    print("Generating JSON definitions ...")
    board_jsons: dict[str, str] = {}
    seen: dict[str, int] = {}
    for filename, content in sorted(xdc_files.items()):
        try:
            board = build_board_json(content, filename, commit_sha)
        except Exception as e:
            print(f"  [skip] {filename}: {e}", file=sys.stderr)
            continue

        if board is None:
            print(f"  [skip] {filename}: no simulatable resources")
            continue

        out_name = unique_name(sanitize_filename(board["name"]), seen)
        board_jsons[f"{out_name}.json"] = json.dumps(board, indent=2) + "\n"
        seg_info = ""
        if board.get("seven_seg"):
            seg_info = f", {board['seven_seg']['num_digits']}-digit 7seg"
        conv_info = " +port_conventions" if board.get("port_conventions") else ""
        print(
            f"  {filename} -> {out_name}.json"
            f" ({len(board['leds'])} LEDs, {len(board['switches'])} SW,"
            f" {len(board['buttons'])} BTN{seg_info}{conv_info})"
        )

    print(f"Generated {len(board_jsons)} board definitions.")

    print(f"\nWriting to {args.output_dir} ...")
    write_outputs(args.output_dir, board_jsons, commit_sha, _REPO, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
