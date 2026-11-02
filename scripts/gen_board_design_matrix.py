"""Generate ``tests/fixtures/board_design_matrix.json``: every design on every board.

U56 rewrites every generated board file -- identity fields, parser fixes,
upstream version bumps -- and each phase that does has to show that no design's
outcome moved unless it was meant to.  This file is that evidence, committed:
a phase regenerates it, and its diff is the impact.  Nothing here is projected
or re-derived; every entry is what the product itself answers today.

Boards are keyed by file, ``<source>/<file stem>`` (``digilent-xdc/nexys_4_ddr``),
never by display name, which repeats across sources.  Nothing is read from a
board file's ``source`` block, so identity fields added there change nothing.
Three sections:

``boards``
    Every board file on disk, with the generics a run passes it --
    ``build_generics`` plus the two that ``start_simulation`` adds for a design
    that declares them (``NUM_SEGS`` on a board with a display, ``NUM_RGB_LEDS``)
    -- or ``"not loaded"`` for a file the loader skips: the line that shows a
    board dropping out of the fleet.
``designs``
    For every design in ``hdl/``, ``hdl/native/`` and ``tests/fixtures/pinmap/*/``,
    the boards ``check_vhdl_contract`` accepts it on, by the path that accepted
    it: the generic contract (``generic``, a board set), a board-native
    convention (``native``: the ``ConventionMatch`` minus ``board_name``), or the
    design's own constraint file (``pinmap``: the ``PinMapMatch`` minus
    ``board_name`` and its prose notes).  A board in none of the three rejects
    the design.  ``wrong_board_hint`` is the set of boards whose rejection
    carried the pin map's "did you select the wrong board?" hint.  A board set
    is spelled whichever way is shorter: ``{"only": [...]}`` or
    ``{"all_except": [...]}``.
``native_banks``
    The in-repo designs target few boards, so these rows freeze every native
    match a design could make: for each LED, switch and button bank of every
    convention block, a minimal design declaring it (see :func:`minimal_block`)
    is put to ``match_convention`` on the real board.  A row holds the maker
    that matched and the bank as matched -- names, width, polarity, whether its
    ports are scalars -- or the bank as declared when nothing matched.

Leaf records sit on one line each, so a change to one board shows as a small,
local diff.

Usage::

    uv run python scripts/gen_board_design_matrix.py            # write the file
    uv run python scripts/gen_board_design_matrix.py --check    # fail if it would change
"""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import json
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
# build_generics lives in the launcher's controller, which imports pygame.
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from native_synth import synth_interface  # noqa: E402

from fpga_sim.board_loader import BoardDef, discover_boards  # noqa: E402
from fpga_sim.controller import build_generics  # noqa: E402
from fpga_sim.conventions import (  # noqa: E402
    ContractResult,
    ConventionMatch,
    NativePort,
    match_convention,
)
from fpga_sim.paths import BOARDS_DIR, HDL_DIR  # noqa: E402
from fpga_sim.pinmap import PinMapMatch  # noqa: E402
from fpga_sim.vhdl_contract import check_vhdl_contract  # noqa: E402

MATRIX_PATH = REPO_ROOT / "tests" / "fixtures" / "board_design_matrix.json"
PINMAP_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "pinmap"
REGENERATE = "uv run python scripts/gen_board_design_matrix.py"

#: What ``build_pin_map`` appends to a rejection when the constraint file names
#: a different device than the board (``fpga_sim.pinmap``).  The product keeps
#: no flag for it, so the sentence is the signal; ``tests/test_board_design_matrix.py``
#: fails if the product stops saying it.
WRONG_BOARD_HINT = "did you select the wrong board?"

#: The value a board file the loader skips gets in the ``boards`` section.
NOT_LOADED = "not loaded"

#: The convention roles that hold one bank each, in the matcher's terms.
BANK_ROLES = ("leds", "leds_green", "leds_rgb", "switches", "buttons")
#: Either satisfies the matcher's floor: every native design drives LEDs (U38).
_LED_FLOOR = ("leds", "leds_rgb")
#: Required whenever the convention declares them (U31).
_INPUT_ROLES = ("switches", "buttons")


@dataclasses.dataclass(frozen=True)
class _Inline:
    """A value written on a single line of the output: one leaf record."""

    value: object


# ── Inputs ───────────────────────────────────────────────────────────────────


def board_files(boards_dir: Path) -> list[str]:
    """Return the key of every board file on disk, as the loader defines one.

    Every ``*.json`` in a source directory, except ``schema/`` and the
    ``_``-prefixed files the sync writes beside the boards.  Listed here rather
    than taken from the loader, so a file the loader stops reading still has a
    line in the matrix.
    """
    return sorted(
        f"{p.parent.name}/{p.stem}"
        for p in boards_dir.glob("*/*.json")
        if p.parent.name != "schema" and not p.name.startswith("_")
    )


def design_paths() -> list[Path]:
    """Return every design the matrix covers, sorted by path."""
    return sorted(
        [
            *HDL_DIR.glob("*.vhd"),
            *(HDL_DIR / "native").glob("*.vhd"),
            *PINMAP_FIXTURES.glob("*/*.vhd"),
        ]
    )


# ── One board ────────────────────────────────────────────────────────────────


def generics_row(board: BoardDef) -> dict[str, str]:
    """Return the generics a run passes *board*.

    ``build_generics`` (at its default simulator, as analysis uses it), plus the
    two ``start_simulation`` sets only for a design that declares them:
    ``NUM_SEGS`` when the board has a display, ``NUM_RGB_LEDS`` always.
    """
    generics = build_generics(board)
    if board.seven_seg is not None:
        generics["NUM_SEGS"] = str(board.seven_seg.num_digits)
    generics["NUM_RGB_LEDS"] = str(board.num_rgb_leds)
    return generics


def minimal_block(block: Mapping[str, Any], role: str) -> dict[str, Any]:
    """Return the smallest convention a design declaring *role*'s bank must meet.

    Its clock and that bank, plus only what the matcher demands besides: an LED
    bank when *role* is not one (every native design drives LEDs), and each
    input bank the block declares (a declared input role is required).  The
    design :func:`native_synth.synth_interface` builds from it is the minimal
    native design for that bank.
    """
    sub: dict[str, Any] = {"clk": block.get("clk"), role: block[role]}
    if role not in _LED_FLOOR and role != "led_banks":
        floor = next((r for r in _LED_FLOOR if isinstance(block.get(r), dict)), None)
        if floor is not None:
            sub[floor] = block[floor]
        elif block.get("led_banks"):  # only other LED banks (U56 Phase 6): the first
            sub["led_banks"] = block["led_banks"][:1]
    for name in _INPUT_ROLES:
        if block.get(name):
            sub[name] = block[name]
    return sub


def _role_port(match: ConventionMatch, role: str) -> NativePort | None:
    """Return the bank *match* bound for *role*."""
    ports = {
        "leds": match.leds,
        "leds_green": match.leds_green,
        "leds_rgb": match.leds_rgb,
        "switches": match.switches,
        "buttons": match.buttons,
    }
    return ports[role]


def bank_rows(board: BoardDef) -> dict[str, object]:
    """Return one row per bank of every convention block on *board*, keyed ``maker.role``.

    The row is the matched maker plus the bank as the matcher bound it, or the
    bank as declared (and ``"match": null``) when the minimal design for it
    does not match -- or matches through another block that has no such bank.
    """
    rows: dict[str, object] = {}
    for maker, block in board.port_conventions.items():
        if not isinstance(block, dict):
            continue
        for role in BANK_ROLES:
            bank = block.get(role)
            if not isinstance(bank, dict):
                continue
            design = synth_interface(minimal_block(block, role))
            match = match_convention(design, [], board)
            port = _role_port(match, role) if match is not None else None
            rows[f"{maker}.{role}"] = _bank_row(match, port, bank)
        # The other LED banks (U56 Phase 6), keyed by the names they declare: each
        # one alone, with the clock and the inputs a match requires.
        for bank in block.get("led_banks") or []:
            if not isinstance(bank, dict):
                continue
            label = "+".join(bank.get("names") or [str(bank.get("name"))])
            sub = minimal_block({**block, "led_banks": [bank]}, "led_banks")
            match = match_convention(synth_interface(sub), [], board)
            port = match.led_banks[0] if match is not None and match.led_banks else None
            rows[f"{maker}.led_banks.{label}"] = _bank_row(match, port, bank)
    return rows


def _bank_row(
    match: ConventionMatch | None, port: NativePort | None, bank: dict[str, Any]
) -> _Inline:
    """One per-bank row: the matched maker and the bank as bound, or as declared."""
    row: dict[str, object] = {"match": match.maker if match is not None else None}
    if port is not None:
        row.update(_without_defaults(dataclasses.asdict(port)))
    else:
        row["declared"] = bank
    return _Inline(row)


def _without_defaults(record: dict[str, Any]) -> dict[str, Any]:
    """Drop the fields U56 Phase 6 added while they hold nothing.

    A bank with no ``channels`` map and a match with no other LED banks read as
    they did before, so the matrix's diff shows where a map or a bank appears.
    """
    out = {}
    for key, value in record.items():
        if key == "channels" and value is None:
            continue
        if key == "led_banks" and not value:
            continue
        if isinstance(value, dict):
            value = _without_defaults(value)
        elif isinstance(value, (list, tuple)):
            value = [_without_defaults(v) if isinstance(v, dict) else v for v in value]
        out[key] = value
    return out


# ── One design ───────────────────────────────────────────────────────────────


def wrong_board_hint_fired(result: ContractResult) -> bool:
    """Report whether a rejection carried the pin map's wrong-board hint."""
    return not result.ok and WRONG_BOARD_HINT in result.message


def _convention_record(match: ConventionMatch) -> dict[str, object]:
    """Lay out a native match minus ``board_name``: one line per field."""
    fields = _without_defaults(dataclasses.asdict(match))
    del fields["board_name"]
    return {name: _Inline(value) for name, value in fields.items()}


def _pinmap_record(match: PinMapMatch) -> dict[str, object]:
    """Lay out a pin-map match minus ``board_name`` and its prose ``notes``.

    One line per field, and one per bound bit, so a moved pin shows as the one
    binding it moved.  The notes are left out because they restate the fields
    in words; the matrix records what was bound, not how it was explained.
    """
    fields = dataclasses.asdict(match)
    del fields["board_name"], fields["notes"]
    return {
        name: [_Inline(bit) for bit in value] if name in ("inputs", "outputs") else _Inline(value)
        for name, value in fields.items()
    }


def _board_set(members: set[str], universe: list[str]) -> object:
    """Spell a set of boards the shorter way: its members, or all but the rest."""
    inside = sorted(members)
    outside = [key for key in universe if key not in members]
    key, boards = ("all_except", outside) if len(outside) < len(inside) else ("only", inside)
    return {key: boards} if boards else _Inline({key: []})


def design_entry(design: Path, boards: list[BoardDef]) -> dict[str, object]:
    """Return what ``check_vhdl_contract`` says about *design* on each board."""
    generic: set[str] = set()
    native: dict[str, object] = {}
    pinmap: dict[str, object] = {}
    hinted: set[str] = set()
    for board in boards:
        key = board.qualified_name
        result = check_vhdl_contract(design, board_def=board)
        if wrong_board_hint_fired(result):
            hinted.add(key)
        if not result.ok:
            continue
        if result.match is not None:
            native[key] = _convention_record(result.match)
        elif result.pinmap is not None:
            pinmap[key] = _pinmap_record(result.pinmap)
        else:
            generic.add(key)
    universe = sorted(board.qualified_name for board in boards)
    entry: dict[str, object] = {}
    if generic:
        entry["generic"] = _board_set(generic, universe)
    if native:
        entry["native"] = native
    if pinmap:
        entry["pinmap"] = pinmap
    if hinted:
        entry["wrong_board_hint"] = _board_set(hinted, universe)
    return entry


# ── The matrix ───────────────────────────────────────────────────────────────


def collect(
    boards_dir: Path = BOARDS_DIR, designs: Iterable[Path] | None = None
) -> dict[str, object]:
    """Build the matrix for the boards in *boards_dir* and *designs* (default: all)."""
    loaded = sorted(discover_boards(boards_dir), key=lambda b: b.qualified_name)
    by_key = {board.qualified_name: board for board in loaded}
    files = board_files(boards_dir)
    chosen = design_paths() if designs is None else sorted(designs)

    banks = {board.qualified_name: bank_rows(board) for board in loaded}
    banks = {key: rows for key, rows in banks.items() if rows}
    return {
        "_about": (
            f"Generated by scripts/gen_board_design_matrix.py; do not edit. Regenerate with "
            f"`{REGENERATE}` whenever board data or matching changes: the diff is that "
            "change's impact evidence. Boards are keyed <source>/<file stem>; a board in none "
            "of a design's generic, native and pinmap entries rejects it."
        ),
        "boards": {
            key: _Inline(generics_row(by_key[key])) if key in by_key else NOT_LOADED
            for key in files
        },
        "counts": {
            "board_files": len(files),
            "boards_loaded": len(loaded),
            "designs": len(chosen),
            "contract_checks": len(chosen) * len(loaded),
            "native_banks": sum(len(rows) for rows in banks.values()),
        },
        "designs": {
            path.relative_to(REPO_ROOT).as_posix(): design_entry(path, loaded) for path in chosen
        },
        "native_banks": banks,
    }


def _encode(value: object, depth: int = 0) -> str:
    """Write *value* as JSON: containers one item per line, :class:`_Inline` on one."""
    if isinstance(value, _Inline):
        return json.dumps(value.value, sort_keys=True)
    pad = "  " * (depth + 1)
    if isinstance(value, dict) and value:
        items = [
            f"{pad}{json.dumps(key)}: {_encode(item, depth + 1)}"
            for key, item in sorted(value.items())
        ]
        return "{\n" + ",\n".join(items) + "\n" + "  " * depth + "}"
    if isinstance(value, list) and value:
        items = [f"{pad}{_encode(item, depth + 1)}" for item in value]
        return "[\n" + ",\n".join(items) + "\n" + "  " * depth + "]"
    return json.dumps(value)


def render(matrix: Mapping[str, object]) -> str:
    """Return the committed text of *matrix*."""
    return _encode(dict(matrix)) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write (or with ``--check``, verify) the matrix; return a process exit code."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else None)
    ap.add_argument("--check", action="store_true", help="fail if the file would change")
    args = ap.parse_args(argv)

    text = render(collect())
    rel = MATRIX_PATH.relative_to(REPO_ROOT).as_posix()
    if args.check:
        current = MATRIX_PATH.read_text(encoding="utf-8") if MATRIX_PATH.exists() else ""
        if current == text:
            print(f"{rel} is up to date")
            return 0
        print(f"{rel} is out of date: regenerate it with `{REGENERATE}`.")
        diff = list(
            difflib.unified_diff(
                current.splitlines(), text.splitlines(), "committed", "product", lineterm="", n=1
            )
        )
        print("\n".join(diff[:80]))
        if len(diff) > 80:
            print(f"... {len(diff) - 80} more diff lines")
        return 1
    MATRIX_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
