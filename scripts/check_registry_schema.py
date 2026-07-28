#!/usr/bin/env python3
"""Schema-validate the hand-authored registry TOMLs.

The board JSONs have been schema-validated since the sync pipeline was built
(``sync_common.validate_board_jsons``); the *registries* that feed it never
were.  That asymmetry is the gap this closes.

Why it matters: every registry field is read with ``.get()`` --
``sync_port_conventions._gate`` checks ``rank1.get("fetched")``, the overlay
applier checks ``bank.get("active_low")``, and nothing anywhere validates a key
*name*.  So ``fetchd = true`` does not raise; it reads as not-fetched and the
row is silently skipped, which is precisely the silent-skip failure mode #335
was written to close, reachable through a one-character typo.  Same for a
misspelled ``status = "verifed"`` (never verified, never generates) or
``format = "QFS"`` (no parser, skipped).  All three are invisible today: the
run stays green and simply does less.

Beyond the JSON Schemas this also enforces the cross-file and cross-field rules
they cannot express -- consecutive ranks, unique board names, ``files[]``
pointing at board JSONs that exist, and every ``waves.toml`` / ``overlay.toml``
entry naming a real registry row.  The consecutive-rank rule found a real defect
on its first run (two rows carried a duplicate rank 2 after a rank-1 source was
replaced above a surviving one).

Self-contained CLI, no ``fpga_sim`` dependency, no network.  Chained from
``sync_port_conventions.py --check`` so CI picks it up through the existing
board-data drift entry point.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
import tomllib

REPO = Path(__file__).parent.parent
BOARDS_DIR = REPO / "boards"
PCS_DIR = REPO / "docs" / "port_convention_sources"
LCS_DIR = REPO / "docs" / "led_color_sources"

#: Files in PCS_DIR that are not per-maker registries and have their own schema.
_SPECIAL = {"overlay.toml": "overlay.schema.json", "waves.toml": "waves.schema.json"}


def _load(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    return data


def _validate(data: dict[str, Any], schema_path: Path, label: str) -> list[str]:
    """Return one message per schema violation, deepest-path first."""
    validator = jsonschema.Draft202012Validator(json.loads(schema_path.read_text()))
    out = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{label}: {where}: {err.message}")
    return out


def maker_files() -> list[Path]:
    """Return the per-maker registry TOMLs (everything with its own schema excluded)."""
    return sorted(p for p in PCS_DIR.glob("*.toml") if p.name not in _SPECIAL)


def check_schemas() -> list[str]:
    """Validate every registry TOML against its JSON Schema."""
    errors: list[str] = []
    for path in maker_files():
        errors += _validate(_load(path), PCS_DIR / "registry.schema.json", path.name)
    for name, schema in _SPECIAL.items():
        path = PCS_DIR / name
        if path.exists():
            errors += _validate(_load(path), PCS_DIR / schema, name)
    for path in sorted(LCS_DIR.glob("*.toml")):
        errors += _validate(_load(path), LCS_DIR / "registry.schema.json", path.name)
    return errors


def check_cross_field() -> list[str]:
    """Rules spanning rows or files that a JSON Schema cannot express."""
    errors: list[str] = []
    row_file: dict[str, str] = {}

    for path in maker_files():
        for board in _load(path).get("board", []):
            name = board.get("name", "(unnamed)")
            if name in row_file:
                errors.append(
                    f"{path.name}: duplicate board row {name!r} (also in {row_file[name]}); "
                    "row names address boards across the whole registry and must be unique"
                )
            row_file[name] = path.name

            ranks = sorted(s.get("rank") for s in board.get("source", []))
            if ranks and ranks != list(range(1, len(ranks) + 1)):
                errors.append(
                    f"{path.name}: {name}: source ranks are {ranks}, expected "
                    f"{list(range(1, len(ranks) + 1))} -- ranks must be consecutive from 1 "
                    "(a duplicate usually means a new source was inserted above a surviving one)"
                )

            for rel in board.get("files", []):
                if not (BOARDS_DIR / rel).exists():
                    errors.append(f"{path.name}: {name}: files entry {rel!r} does not exist")

    overlay = PCS_DIR / "overlay.toml"
    if overlay.exists():
        for board in _load(overlay).get("board", []):
            if (name := board.get("name")) and name not in row_file:
                errors.append(
                    f"overlay.toml: {name!r} matches no registry row; an overlay keyed to a "
                    "name nothing else uses is silently never applied"
                )

    waves = PCS_DIR / "waves.toml"
    if waves.exists():
        for wave in _load(waves).get("wave", []):
            for name in wave.get("boards", []):
                if name not in row_file:
                    errors.append(
                        f"waves.toml: wave {wave.get('number')}: {name!r} matches no registry row"
                    )

    for path in sorted(LCS_DIR.glob("*.toml")):
        for board in _load(path).get("board", []):
            for rel in board.get("files", []):
                if not (BOARDS_DIR / rel).exists():
                    errors.append(
                        f"{path.name}: {board.get('name')}: files entry {rel!r} does not exist"
                    )
    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Takes no arguments -- it is always a full check."""
    if argv:
        print(f"usage: {Path(__file__).name}  (no arguments)", file=sys.stderr)
        return 2

    errors = check_schemas() + check_cross_field()
    if errors:
        print(f"Registry schema check FAILED ({len(errors)} issue(s)):", flush=True)
        for e in errors:
            print(f"  - {e}", flush=True)
        return 1

    n = len(maker_files()) + len(list(LCS_DIR.glob("*.toml"))) + len(_SPECIAL)
    print(f"Registry TOMLs valid ({n} files).", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
