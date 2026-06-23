"""Sync board definitions from litex-boards GitHub repository.

Downloads the source archive, mocks the LiteX build system classes,
executes each board platform file, and emits JSON board definitions
to boards/litex-boards/.
"""

import argparse
import io
import json
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from litex_parser import parse_litex_board  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════
#  Archive handling
# ═══════════════════════════════════════════════════════════════════════

_REPO = "litex-hub/litex-boards"


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
    """Download the litex-boards archive for the given git ref."""
    url = f"https://github.com/{_REPO}/archive/{ref}.tar.gz"
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=120) as resp:
        return bytes(resp.read())


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


def unique_name(base: str, seen: dict[str, int]) -> str:
    """Return a unique filename base, appending _2, _3, ... on collision."""
    if base not in seen:
        seen[base] = 1
        return base
    seen[base] += 1
    return f"{base}_{seen[base]}"


def generate_all_json(
    board_files: dict[str, str],
    commit_sha: str,
    schema_ref: str = "../schema/board.schema.json",
) -> dict[str, str]:
    """Parse all board files and generate JSON strings."""
    seen: dict[str, int] = {}
    results: dict[str, str] = {}
    timestamp = datetime.now(timezone.utc).isoformat()
    skipped = 0

    for filename, source in sorted(board_files.items()):
        try:
            boards = parse_litex_board(source, filename)
        except Exception as e:
            print(f"  [skip] {filename}: {e}", file=sys.stderr)
            skipped += 1
            continue

        if not boards:
            skipped += 1
            continue

        for board in boards:
            board["$schema"] = schema_ref
            board["source"] = {
                "origin": "litex-boards",
                "upstream_file": filename,
                "sync_commit": commit_sha,
                "sync_timestamp": timestamp,
            }

            base = sanitize_filename(board["name"])
            output_name = unique_name(base, seen)
            results[f"{output_name}.json"] = json.dumps(board, indent=2) + "\n"

            n_leds = len(board.get("leds", []))
            n_btns = len(board.get("buttons", []))
            n_sw = len(board.get("switches", []))
            seg_info = ""
            if board.get("seven_seg"):
                seg_info = f", {board['seven_seg']['num_digits']}-digit 7seg"
            print(
                f"  {filename} -> {output_name}.json"
                f" ({n_leds} LEDs, {n_sw} SW, {n_btns} BTN{seg_info})"
            )

    if skipped:
        print(f"  ({skipped} files skipped — no simulatable resources or parse errors)")
    return results


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
    commit_sha = resolve_commit_sha(args.ref)
    print(f"Commit: {commit_sha}")

    try:
        archive_bytes = download_archive(args.ref)
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
    board_jsons = generate_all_json(board_files, commit_sha)
    print(f"Generated {len(board_jsons)} board definitions.")

    print(f"\nWriting to {args.output_dir} ...")
    write_outputs(args.output_dir, board_jsons, commit_sha, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
