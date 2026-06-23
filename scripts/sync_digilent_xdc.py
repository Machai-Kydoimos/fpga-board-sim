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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from digilent_parser import build_board_json  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════
#  Archive handling
# ═══════════════════════════════════════════════════════════════════════

_REPO = "Digilent/digilent-xdc"


def resolve_commit_sha(ref: str) -> str:
    """Resolve a git ref to a commit SHA via the GitHub API."""
    url = f"https://api.github.com/repos/{_REPO}/commits/{ref}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.sha"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return str(resp.read().decode().strip())
    except Exception:
        return ref


def download_archive(ref: str) -> bytes:
    """Download the digilent-xdc archive for the given git ref."""
    url = f"https://github.com/{_REPO}/archive/{ref}.tar.gz"
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return bytes(resp.read())


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
#  Output
# ═══════════════════════════════════════════════════════════════════════


def sanitize_filename(name: str) -> str:
    """Convert a board name to a filesystem-safe base name."""
    result: list[str] = []
    for ch in name.lower():
        result.append(ch if (ch.isalnum() or ch == "-") else "_")
    safe = "".join(result)
    while "__" in safe or "--" in safe:
        safe = safe.replace("__", "_").replace("--", "-")
    return safe.strip("_-")


def write_outputs(
    output_dir: Path,
    board_jsons: dict[str, str],
    commit_sha: str,
    dry_run: bool = False,
) -> None:
    """Write JSON files and sync metadata to the output directory."""
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    for filename, content in sorted(board_jsons.items()):
        out_path = output_dir / filename
        if dry_run:
            print(f"  [dry-run] Would write {out_path}")
        else:
            out_path.write_text(content, encoding="utf-8")

    metadata = {
        "source_repo": f"https://github.com/{_REPO}",
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
    commit_sha = resolve_commit_sha(args.ref)
    print(f"Commit: {commit_sha}")

    try:
        archive_bytes = download_archive(args.ref)
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
    for filename, content in sorted(xdc_files.items()):
        try:
            board = build_board_json(content, filename, commit_sha)
        except Exception as e:
            print(f"  [skip] {filename}: {e}", file=sys.stderr)
            continue

        if board is None:
            print(f"  [skip] {filename}: no simulatable resources")
            continue

        out_name = sanitize_filename(board["name"])
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
    write_outputs(args.output_dir, board_jsons, commit_sha, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
