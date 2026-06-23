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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project src/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from amaranth_parser import load_board_from_source  # noqa: E402


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


def resolve_commit_sha(ref: str) -> str:
    """Resolve a git ref to a commit SHA via the GitHub API."""
    url = f"https://api.github.com/repos/amaranth-lang/amaranth-boards/commits/{ref}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.sha"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return str(resp.read().decode().strip())
    except Exception:
        return ref


def download_archive(ref: str) -> bytes:
    """Download the amaranth-boards archive for the given git ref."""
    url = f"https://github.com/amaranth-lang/amaranth-boards/archive/{ref}.tar.gz"
    print(f"Downloading {url} ...")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return bytes(resp.read())


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
        "source_repo": "https://github.com/amaranth-lang/amaranth-boards",
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
    board_jsons = generate_board_json(board_files, commit_sha)
    print(f"Generated {len(board_jsons)} board definitions.")

    print(f"\nWriting to {args.output_dir} ...")
    write_outputs(args.output_dir, board_jsons, commit_sha, dry_run=args.dry_run)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
