"""Apply the cited LED color registry to board JSONs (U36).

Stamps ``leds[].color`` on every board named in ``docs/led_color_sources/*.toml``
from its cited entry, in place, with no network access -- the offline companion
to the color application that ``sync_common.write_outputs`` performs during a
full board re-sync. Run it after editing the registry, or to populate colors
without re-syncing a whole source.

Two on-disk layouts are preserved:

* **canonical** boards (the ``json.dumps(indent=2)`` the sync scripts emit) are
  re-serialized canonically, so the only diff is the added ``color`` lines;
* **hand-authored** ``boards/custom/*`` boards (one compact component object per
  line) are stamped by inserting ``"color"`` after the component's ``"name"``,
  preserving their bespoke formatting.

The stamped result is verified to parse back to the intended colors and is
schema-validated before anything is written, so a format this tool doesn't
recognize fails loudly rather than corrupting a board.

Self-contained CLI, no ``fpga_sim`` dependency (mirrors the other ``sync_*.py``).
"""

import argparse
import json
import sys
from pathlib import Path

from led_metadata import (  # noqa: E402
    ColorBank,
    apply_registry_colors,
    load_color_registry,
)
from sync_common import validate_board_jsons  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent
BOARDS_DIR = _ROOT / "boards"
SCHEMA_PATH = BOARDS_DIR / "schema" / "board.schema.json"


def _stamp_single_line(content: str, colors: dict[str, str]) -> str:
    """Insert ``"color"`` into the compact one-object-per-line ``custom`` layout.

    For each colored bank, finds the line carrying ``"name": "<match>",`` (unique
    to that bank -- ``"led",`` never matches ``"led_g",``) that has no ``color``
    yet and inserts ``"color": "<color>",`` right after the name.
    """
    lines = content.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if '"color"' in line:
            continue
        for match, color in colors.items():
            needle = f'"name": "{match}",'
            if needle in line:
                lines[i] = line.replace(needle, f'{needle} "color": "{color}",', 1)
                break
    return "".join(lines)


def stamp_board(
    content: str, board_file: str, registry: dict[str, list[ColorBank]]
) -> tuple[str, bool]:
    """Return ``(new_content, changed)`` with registry colors applied to ``content``.

    Chooses the canonical or the hand-authored layout automatically and verifies
    the result parses back to exactly the intended colors; raises ``ValueError``
    if it cannot stamp the file in a recognized layout.
    """
    target = json.loads(content)
    if not apply_registry_colors(target, board_file, registry):
        return content, False  # nothing to add (no entry, or already colored)

    canonical = json.dumps(json.loads(content), indent=2) + "\n"
    if content == canonical:
        return json.dumps(target, indent=2) + "\n", True

    colors = {bank.match: bank.color for bank in registry[board_file]}
    new_content = _stamp_single_line(content, colors)
    if json.loads(new_content) != target:
        raise ValueError(
            f"{board_file}: could not stamp cited colors while preserving the file's "
            f"layout (unrecognized format); update sync_led_colors._stamp_single_line"
        )
    return new_content, True


def apply_all(
    registry: dict[str, list[ColorBank]],
    boards_dir: Path = BOARDS_DIR,
    write: bool = True,
) -> list[str]:
    """Stamp every board in ``registry``; write in place unless ``write`` is False.

    Returns the sorted list of board files whose colors changed. Validates the
    stamped content against the schema before writing (all-or-nothing).
    """
    final: dict[str, str] = {}
    changed: list[str] = []
    for board_file in sorted(registry):
        path = boards_dir / board_file
        if not path.exists():
            raise FileNotFoundError(f"{board_file}: registry names a board that does not exist")
        content = path.read_text(encoding="utf-8")
        new_content, did_change = stamp_board(content, board_file, registry)
        final[board_file] = new_content
        if did_change:
            changed.append(board_file)

    validate_board_jsons(final, SCHEMA_PATH)

    if write:
        for board_file in changed:
            (boards_dir / board_file).write_text(final[board_file], encoding="utf-8")
    return changed


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report boards whose colors would change and exit non-zero; write nothing",
    )
    args = parser.parse_args()

    registry = load_color_registry()
    changed = apply_all(registry, write=not args.check)

    if not changed:
        print(f"LED colors up to date ({len(registry)} boards in registry).")
        return 0

    verb = "would change" if args.check else "updated"
    print(f"{len(changed)} board(s) {verb}:")
    for board_file in changed:
        print(f"  {board_file}")
    return 1 if args.check else 0


if __name__ == "__main__":
    sys.exit(main())
