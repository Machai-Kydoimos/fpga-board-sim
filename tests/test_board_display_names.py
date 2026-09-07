"""Guard: no board reaches the selector under a mangled display name (U49).

The two sync parsers build a display name by splitting an upstream class name on
case and digit boundaries. That heuristic is right for most of the fleet and
produced fourteen wrecks, among them ``DE1SoCPlatform`` -> **"DE1 So C"** and
``ULX3S_45F_Platform`` -> **"ULX3 S-45 F-"**. (The arc plan predicted sixteen; two
of those turned out to be the vendor's own spelling -- see the note at the end.)

``board_loader._DISPLAY_NAME_OVERRIDES`` repairs them at load time; this module is
what stops the next one arriving unnoticed, because the *next* mangled name will
come from a re-sync nobody is reading the diff of.

Four things are checked, and they fail on different mistakes:

1. **The shape rule** — over every board's final name. Two mechanical tells, both
   taken from the real damage: a standalone single capital as its own word, and
   a leading or trailing separator. This is the half that fires on a *new* board.
2. **The table is honest** — every key names a board that exists and every value
   actually changes something. A stale key is dead weight, and an entry that
   renames nothing is a claim the tree does not support.
3. **The rename cannot cost anyone their board** — ``find_board`` must still
   resolve every renamed board by its *old* name, its new one, and its class
   name. This is the one that would hurt: a student pasting a name out of an
   older screenshot, or a saved session, must not stop working.
4. **No new ambiguity** — the override may not make two boards answer to one
   ``find_board`` key that did not already share one.

**Two names look mangled and are not**, so they are registered here with the
evidence rather than "fixed": Digilent's own constraint files are named
``Genesys-ZU-3EG-D-Master.xdc``, so the trailing ``-D`` is the vendor's, and
renaming it would be this guard corrupting real data to satisfy its own rule.
Registering them as line entries (rather than skipping the Genesys family) keeps
every other Genesys board covered -- the lesson ``test_us_spelling`` records.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from fpga_sim.board_loader import (
    _DISPLAY_NAME_OVERRIDES,
    discover_boards,
    find_board,
    get_default_boards_path,
)

#: A single capital standing alone as a word: the "So C" / "-45 F-" tell.
_LONE_CAPITAL = re.compile(r"(?:^|[\s-])[A-Z](?:$|[\s-])")

#: A name that opens or closes on a separator: the dangling "ULX3S_45F_" hyphen.
_EDGE_SEPARATOR = re.compile(r"^[\s-]|[\s-]$")

#: Names that trip a rule above and are nonetheless correct, each with the
#: source that says so. Kept as exact names, so a *different* Genesys board
#: arriving mangled still fails.
_VENDOR_SPELLINGS: dict[str, str] = {
    "Genesys ZU-3EG-D": "Digilent ships Genesys-ZU-3EG-D-Master.xdc; the -D is theirs",
    "Genesys ZU-5EV-D": "Digilent ships Genesys-ZU-5EV-D-Master.xdc; the -D is theirs",
}


def _board_key(text: str) -> str:
    """``find_board``'s comparison key: case- and separator-insensitive."""
    return "".join(ch for ch in text.lower() if ch.isalnum())


@pytest.fixture(scope="module")
def boards() -> list[Any]:
    found = discover_boards(get_default_boards_path())
    assert found, "no boards discovered; the guard would pass vacuously"
    return found


@pytest.fixture(scope="module")
def raw_names() -> dict[str, str]:
    """Every board's *pre-override* name, straight from its JSON."""
    out: dict[str, str] = {}
    for path in sorted(get_default_boards_path().glob("*/*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out[data["class_name"]] = data["name"]
        except (json.JSONDecodeError, KeyError):
            continue  # not a board file
    return out


# ── 1. The shape rule ─────────────────────────────────────────────────────────


def test_no_board_name_is_mangled(boards: list[Any]) -> None:
    """No display name carries a lone capital or a dangling separator."""
    offenders = []
    for board in boards:
        if board.name in _VENDOR_SPELLINGS:
            continue
        if _LONE_CAPITAL.search(board.name) or _EDGE_SEPARATOR.search(board.name):
            offenders.append(f"{board.name!r} ({board.class_name})")
    assert not offenders, (
        "mangled board display name(s): "
        + ", ".join(sorted(offenders))
        + ". Add a corrected entry to board_loader._DISPLAY_NAME_OVERRIDES, keyed "
        "by class_name — or, if the vendor really spells it that way, register it "
        "in _VENDOR_SPELLINGS here with the source that says so."
    )


def test_the_two_target_names_from_the_plan_read_correctly(boards: list[Any]) -> None:
    """The arc's own acceptance criterion, asserted rather than assumed."""
    names = {b.class_name: b.name for b in boards}
    assert names["DE1SoCPlatform"] == "DE1-SoC"
    assert names["ULX3S_45F_Platform"] == "ULX3S-45F"


def test_the_shape_rule_would_catch_the_names_it_was_written_for() -> None:
    """A guard that matches nothing is not a guard: prove it fires."""
    for wreck in ("DE1 So C", "ULX3 S-45 F-", "Cmod S7-", "AX7325 B"):
        assert _LONE_CAPITAL.search(wreck) or _EDGE_SEPARATOR.search(wreck), wreck
    for fine in ("DE10-Standard", "Basys 3", "Nexys 4 DDR", "Tang Nano 9K", "iCEstick"):
        assert not _LONE_CAPITAL.search(fine) and not _EDGE_SEPARATOR.search(fine), fine


# ── 2. The table is honest ────────────────────────────────────────────────────


def test_every_override_names_a_board_that_exists(raw_names: dict[str, str]) -> None:
    """A key for a board that is gone is dead weight nobody will notice."""
    stale = sorted(set(_DISPLAY_NAME_OVERRIDES) - set(raw_names))
    assert not stale, (
        f"_DISPLAY_NAME_OVERRIDES keys no board carries: {stale}. "
        "Board renamed or dropped upstream — remove the entry."
    )


def test_every_override_actually_changes_the_name(raw_names: dict[str, str]) -> None:
    """An entry that renames nothing says the data is wrong when it is not."""
    inert = sorted(cls for cls, new in _DISPLAY_NAME_OVERRIDES.items() if raw_names[cls] == new)
    assert not inert, (
        f"_DISPLAY_NAME_OVERRIDES entries that change nothing: {inert}. "
        "The parser now emits this name on its own — drop the override."
    )


def test_no_two_overrides_collide() -> None:
    """Two boards must not be renamed to one name."""
    seen: dict[str, str] = {}
    clashes = []
    for cls, name in _DISPLAY_NAME_OVERRIDES.items():
        if name in seen:
            clashes.append(f"{name!r} <- {seen[name]} and {cls}")
        seen[name] = cls
    assert not clashes, f"override collisions: {clashes}"


# ── 3. The rename cannot cost anyone their board ──────────────────────────────


def test_a_renamed_board_still_answers_to_its_old_name(
    boards: list[Any], raw_names: dict[str, str]
) -> None:
    """Old name, new name and class name must all still resolve.

    ``find_board`` strips separators and case, which is *why* this rename is
    safe — but "is safe" is a property of that implementation, not a law, so it
    is asserted here rather than reasoned about in a comment.
    """
    for cls, new_name in _DISPLAY_NAME_OVERRIDES.items():
        for spelling in (raw_names[cls], new_name, cls):
            found = find_board(boards, spelling)
            assert found is not None, f"{spelling!r} no longer resolves to any board"
            assert found.class_name == cls or _board_key(found.name) == _board_key(spelling), (
                f"{spelling!r} resolved to {found.class_name}, expected {cls}"
            )


# ── 4. No new ambiguity ───────────────────────────────────────────────────────


def test_the_override_makes_no_new_name_ambiguous(raw_names: dict[str, str]) -> None:
    """Renaming may not merge two boards' identities under one lookup key.

    Some keys are ambiguous already — the same board reaches us from two
    sources, so ``Arty A7-35`` is two entries — and that is pre-existing. What
    this forbids is the override *creating* such a pair.
    """

    def ambiguous(names: list[str]) -> set[str]:
        keys = [_board_key(n) for n in names]
        return {k for k in keys if keys.count(k) > 1}

    before = ambiguous(list(raw_names.values()))
    after = ambiguous([_DISPLAY_NAME_OVERRIDES.get(c, n) for c, n in raw_names.items()])
    assert not (after - before), (
        f"the override newly merges these lookup keys: {sorted(after - before)}. "
        "Two boards would answer to one --board argument that did not before."
    )


def test_a_shared_display_name_always_means_the_same_device(boards: list[Any]) -> None:
    """Two boards may share a name only when they *are* the same board.

    ``Cora Z7-07S`` is the case that motivated this: the amaranth and Digilent
    copies of one board disagreed on spelling, and the override makes them
    agree. That is the good kind of duplicate. The bad kind — two different
    devices under one name — is what this forbids. Boards whose JSON records no
    device, or records it at different precision, are outside what this can
    judge and are skipped rather than guessed at.
    """
    by_name: dict[str, set[str]] = {}
    for board in boards:
        by_name.setdefault(board.name, set()).add(board.device.lower())
    for name, devices in sorted(by_name.items()):
        known = {d for d in devices if d}
        if len(known) < 2:
            continue
        assert any(a.startswith(b) or b.startswith(a) for a in known for b in known if a != b), (
            f"{name!r} is used by unrelated devices {sorted(known)} — "
            "two different boards must not share one display name."
        )
