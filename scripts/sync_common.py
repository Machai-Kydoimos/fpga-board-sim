"""Shared scaffolding for the board-sync scripts.

Archive download, GitHub ref resolution, filesystem-safe naming, and JSON/metadata
output — the source-agnostic plumbing every ``sync_*.py`` script needs identically.
Each parser lives in its own module (``amaranth_parser`` / ``litex_parser`` /
``digilent_parser``); this module is the plumbing they share.
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


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
    """Resolve a git ref to a commit SHA via the GitHub API (falls back to ref)."""
    url = f"https://api.github.com/repos/{repo}/commits/{ref}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.sha"})
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


def write_outputs(
    output_dir: Path,
    board_jsons: dict[str, str],
    commit_sha: str,
    repo: str,
    dry_run: bool = False,
) -> None:
    """Write JSON board files and a ``_sync_metadata.json`` to the output directory."""
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
