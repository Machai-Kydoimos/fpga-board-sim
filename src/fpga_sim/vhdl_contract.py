"""Deciding whether a design can run on a board, and saying why not (D17).

The policy layer over :mod:`fpga_sim.vhdl_interface`'s parse.  A file reaches
:func:`check_vhdl_contract` and leaves as a :class:`ContractResult` that either
runs -- through the generic contract, or through a board-native convention
match (:mod:`fpga_sim.conventions`) -- or carries the message the user will
read.

Those messages are the module's real output.  A rejected design is the normal
case for someone learning, so the failure paths get more care than the success
one: a near-miss names the port that differed rather than reprinting the whole
contract, a width mismatch quotes the board's own count, and
:func:`add_error_hints` annotates the simulator's raw stderr without ever
replacing it -- the compiler's exact words stay, because they are what a search
engine and a lab neighbor both recognize.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from fpga_sim.conventions import (
    ContractResult,
    _best_convention_attempt,
    _native_convention_message,
    _near_miss_convention_message,
)
from fpga_sim.pinmap import (
    PinMapMatch,
    PinMapProblem,
    build_pin_map,
    discover_pinmap,
    nearby_pinmaps,
    read_pinmap,
)
from fpga_sim.vhdl_interface import (
    _CONTRACT_PORTS,
    _PORT_GENERIC,
    _PORT_MODES,
    _PORT_SNIPPETS,
    _REQUIRED_GENERICS,
    _REQUIRED_PORTS,
    _WRAPPER_DEFAULT_WIDTHS,
    _board_port_widths,
    _has_seg_port,
    _IfaceDecl,
    _parse_toplevel_interface,
    _plural,
    _strip_vhdl_comments,
    declares_no_ports,
)

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef


def _check_parsed_contract(
    filename: str,
    ports: list[_IfaceDecl],
    generics: list[_IfaceDecl],
    board_def: BoardDef | None,
) -> tuple[bool, str]:
    """Contract rules over a parsed toplevel interface (helper of check_vhdl_contract)."""
    port_by_name = {n: d for d in ports for n in d.names}
    generic_names = {n for d in generics for n in d.names}
    has_seg = "seg" in port_by_name
    board_7seg = board_def is not None and board_def.seven_seg is not None

    # Required ports
    missing_ports = [p for p in _REQUIRED_PORTS if p not in port_by_name]
    if missing_ports:
        snippet = "\n".join(f"  {_PORT_SNIPPETS[p]};" for p in _REQUIRED_PORTS)
        return False, (
            f"Missing required port(s) in '{filename}': {', '.join(missing_ports)}.\n"
            "The top-level entity must declare:\n"
            f"{snippet}\n"
            "(plus  seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)  to drive a "
            "7-segment display)."
        )

    # Port directions.  Both GHDL and NVC silently accept a wrong-direction
    # contract port (the wrapper's output is simply never driven), so this
    # textual check is the only guard against e.g. `led : in ...`.
    for name in _CONTRACT_PORTS:
        decl = port_by_name.get(name)
        if decl is not None and decl.mode != _PORT_MODES[name]:
            return False, (
                f"Port '{name}' must be mode {_PORT_MODES[name].upper()} but is declared "
                f"{decl.mode.upper()} in '{filename}'.\n"
                f"Declare it as:  {_PORT_SNIPPETS[name]}\n"
                "The board drives clk/sw/btn into the design; led/seg are outputs it displays."
            )

    # NUM_SEGS without a seg port is a contract error: the generic is meaningless alone
    if "num_segs" in generic_names and not has_seg:
        return False, (
            f"'{filename}' declares NUM_SEGS generic but has no 'seg' output port.\n"
            "Add:  seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)"
        )

    # NUM_RGB_LEDS must be natural: most boards have no RGB LEDs, so the
    # simulator passes 0 — a `positive` declaration would fail elaboration
    # everywhere except the RGB boards it was presumably written on (U37).
    for decl in generics:
        if "num_rgb_leds" in decl.names and decl.type_text == "positive":
            return False, (
                f"Generic NUM_RGB_LEDS must be declared 'natural', not 'positive', in "
                f"'{filename}'.\n"
                "Boards without RGB LEDs pass NUM_RGB_LEDS=0, which a positive rejects. "
                "Declare it as:\n"
                "  NUM_RGB_LEDS : natural := 0"
            )

    # seg port without NUM_SEGS: fatal on 7-seg boards (the 7-seg wrapper maps it)
    if has_seg and board_7seg and "num_segs" not in generic_names:
        assert board_def is not None and board_def.seven_seg is not None
        digits = board_def.seven_seg.num_digits
        return False, (
            f"'{filename}' has a 'seg' port but no NUM_SEGS generic, which "
            f"{board_def.name}'s 7-segment display requires.\n"
            "Add to the generic clause:  NUM_SEGS : positive := 4\n"
            f"(the simulator sets NUM_SEGS={digits} for this board at launch)."
        )

    # Required generics.  The wrapper maps all four unconditionally, so a
    # missing one always fails analysis with a cryptic sim_wrapper.vhd error —
    # report it here with the fix instead.
    missing_generics = [g for g in _REQUIRED_GENERICS if g.lower() not in generic_names]
    if missing_generics:
        lines = [
            "  generic (",
            "    NUM_SWITCHES : positive := 4;",
            "    NUM_BUTTONS  : positive := 4;",
            "    NUM_LEDS     : positive := 4;",
        ]
        if has_seg:
            lines.append("    NUM_SEGS     : positive := 4;")
        lines += ["    COUNTER_BITS : positive := 24", "  );"]
        return False, (
            f"Missing required generic(s) in '{filename}': {', '.join(missing_generics)}.\n"
            "The simulator sizes the design to the board by overriding these at launch, "
            "so the entity must declare them all:\n" + "\n".join(lines)
        )

    # Extra inputs the simulator cannot drive, and generics it will not set:
    # both need a default value or the wrapper instantiation fails.
    for decl in ports:
        for name in decl.names:
            if name in _CONTRACT_PORTS or decl.mode not in ("in", "inout") or decl.has_default:
                continue
            return False, (
                f"Port '{name}' in '{filename}' is not part of the simulator contract "
                "(clk, sw, btn, led, seg), so nothing drives it.\n"
                f"Give it a default value — e.g.  {name} : in std_logic := '0'  — "
                "or remove it."
            )
    known_generics = {g.lower() for g in _REQUIRED_GENERICS} | {"num_segs", "num_rgb_leds"}
    for decl in generics:
        for name in decl.names:
            if name not in known_generics and not decl.has_default:
                return False, (
                    f"Generic '{name}' in '{filename}' is not set by the simulator "
                    "(it sets only NUM_SWITCHES, NUM_BUTTONS, NUM_LEDS, NUM_SEGS, "
                    "NUM_RGB_LEDS and COUNTER_BITS).\n"
                    f"Give it a default value, e.g.  {name} : positive := 1"
                )

    # Fixed-literal port widths, judged against this board's resources
    widths = _board_port_widths(board_def)
    for name in ("sw", "btn", "led", "seg"):
        decl = port_by_name.get(name)
        if decl is None or decl.literal_width is None or name not in widths:
            continue  # generic-sized, absent, no board, or seg on a board without 7-seg
        expected = widths[name]
        found = decl.literal_width
        assert board_def is not None
        if name == "seg":
            assert board_def.seven_seg is not None
            digits = board_def.seven_seg.num_digits
            have = f"a {digits}-digit 7-segment display (8 * {digits} = {expected} bits)"
            generic_ref = f"NUM_SEGS={digits}"
        elif name == "led" and board_def.num_rgb_leds:
            # Spell out the channel math: an RGB LED is three boundary bits.
            mono = len(board_def.leds) - board_def.num_rgb_leds
            have = (
                f"{expected} LED channels ({_plural(mono, 'mono LED')} + 3 x "
                f"{board_def.num_rgb_leds} RGB)"
            )
            generic_ref = f"NUM_LEDS={expected}"
        else:
            noun = {"sw": "switch", "btn": "button", "led": "LED"}[name]
            have = _plural(expected, noun)
            generic_ref = f"{_PORT_GENERIC[name]}={expected}"
        if found != expected:
            return False, (
                f"Port '{name}' is a fixed {found} bits wide, but {board_def.name} has "
                f"{have}.\n"
                f"The simulator sets {generic_ref} for this board — declare the port as\n"
                f"  {_PORT_SNIPPETS[name]}\n"
                "so the design fits any board."
            )
        if found != _WRAPPER_DEFAULT_WIDTHS[name]:
            # Matches this board, but the pre-launch elaboration check runs with
            # the generic defaults (4 / 4 / 4 / 8*4), so a fixed width ≠ default
            # still fails validation — and would break on any other board.
            return False, (
                f"Port '{name}' is a fixed {found} bits wide. That matches "
                f"{board_def.name} ({have}), but fixed-width ports fail the simulator's "
                "validation and break on other boards.\n"
                f"Declare the port as\n  {_PORT_SNIPPETS[name]}"
            )

    return True, ""


# >>> moved to fpga_sim.conventions <<<
#: The pre-standard Synopsys packages, lowercased.  ``std_logic_arith`` and
#: ``std_logic_unsigned`` are the pair the course material in front of this
#: project uses; ``std_logic_signed`` and ``std_logic_textio`` complete the set
#: GHDL gates behind ``-fsynopsys``.
_SYNOPSYS_PACKAGES = (
    "std_logic_arith",
    "std_logic_signed",
    "std_logic_textio",
    "std_logic_unsigned",
)

#: ``use ieee.std_logic_arith.all;`` -- the library qualifier is required, so a
#: design with its *own* package of that name is not mistaken for this one.
_SYNOPSYS_USE = re.compile(
    r"\buse\s+ieee\s*\.\s*(" + "|".join(_SYNOPSYS_PACKAGES) + r")\b",
    re.IGNORECASE,
)


def uses_synopsys_packages(text: str) -> tuple[str, ...]:
    """Name the pre-standard Synopsys packages *text* imports, in source order.

    These predate ``ieee.numeric_std`` and are not part of any VHDL standard;
    GHDL refuses them outright without ``-fsynopsys``, which the simulator now
    passes (see :data:`fpga_sim.sim_backends._SYNOPSYS`).  NVC accepts them
    unflagged.

    The point of naming them is a *message*, not a decision: a great deal of
    teaching material is written this way, so refusing would tell a student
    their instructor's own file is wrong, while saying nothing would leave them
    to discover on their own hardware that the dialect is non-standard.
    Comments are stripped first, so a package named only in a ``--`` note does
    not count.
    """
    found: list[str] = []
    for match in _SYNOPSYS_USE.finditer(_strip_vhdl_comments(text)):
        name = match.group(1).lower()
        if name not in found:
            found.append(name)
    return tuple(found)


def _try_pinmap(
    path: Path,
    board_def: BoardDef | None,
    explicit: str | Path | None,
) -> ContractResult | None:
    """Try to bind *path* to *board_def* through a constraint file (U53).

    Returns ``None`` when there is nothing to try -- no board, no constraint
    file beside the design and none named -- which is the ordinary case and
    leaves the name-based paths to run exactly as before.

    A constraint file that *is* present takes precedence over both the
    convention matcher and the generic contract, because it is the only one of
    the three that carries the user's own statement of intent.  When it is
    present and does not work, that is the answer: falling back would answer a
    question about pins with a message about names.
    """
    if board_def is None:
        return None
    source: Path
    if explicit is not None:
        source = Path(explicit)
        if not source.is_file():
            return ContractResult(False, f"--pinmap file not found: {source}")
    else:
        found = discover_pinmap(path)
        if found is None:
            return None
        if isinstance(found, PinMapProblem):
            return ContractResult(False, found.message)
        source = found

    table = read_pinmap(source)
    if isinstance(table, PinMapProblem):
        return ContractResult(False, table.message)

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ContractResult(False, f"Cannot read file: {e}")
    parsed = _parse_toplevel_interface(text, path.stem.lower())
    if parsed is None:
        return None  # unparseable interface: let the legacy scan explain it

    result = build_pin_map(
        parsed[0],
        table,
        board_def,
        source=source.name,
        device=_declared_device(source),
    )
    if isinstance(result, PinMapProblem):
        return ContractResult(False, result.message)
    return ContractResult(True, _pinmap_message(result), pinmap=result)


#: ``set_global_assignment -name DEVICE 5CSXFC6D6F31C6`` -- Quartus states the
#: part in the same file as the pins, which makes "wrong board" answerable.
_DEVICE = re.compile(r"-name\s+DEVICE\s+(\S+)", re.IGNORECASE)


def _declared_device(source: Path) -> str:
    """Return the device a constraint file names, when its dialect states one."""
    try:
        m = _DEVICE.search(source.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return ""
    return m.group(1) if m else ""


def _pinmap_message(match: PinMapMatch) -> str:
    """Build the one-line note the preview shows for a pin-mapped design."""
    lines = [
        f"Pin map: {match.source} -> {match.board_name}. "
        f"{len(match.outputs)} output bit(s) and {len(match.inputs)} input bit(s) "
        "bound by pin, so this design's own port names are not used."
    ]
    lines.extend(match.notes)
    return "\n".join(lines)


def _folder_contract_hint(path: Path) -> str:
    """Say that a constraint file exists in this project but not in this folder.

    The one message the folder contract owes a user.  Silence here is read as
    "this tool cannot do pin maps", when the truth is one copy away -- and the
    student least able to tell those apart is the one who opened a Vivado
    project and landed three directories from their own ``.xdc``.

    Returns ``""`` when there is nothing to say, which is the common case.
    """
    found = nearby_pinmaps(path)
    if not found:
        return ""
    lines = [
        f"There is no constraint file in {path.parent}, so this design was checked "
        "by port name instead of by pin.",
        "",
        "This project has one elsewhere:",
    ]
    lines.extend(f"    {p}" for p in found)
    lines.append("")
    lines.append(
        f"Copy the one that describes {path.name} into the same folder as the design "
        "and the simulator will map the design through it. One folder is one project: "
        "the simulator reads the design, its neighbors and its constraint file from a "
        "single directory, and never guesses at files outside it."
    )
    return "\n".join(lines)


def check_vhdl_contract(
    path: str | Path,
    board_def: BoardDef | None = None,
    pinmap: str | Path | None = None,
) -> ContractResult:
    """Stage 2: contract validation, plus the advisory that rides along with it.

    Thin wrapper over :func:`_check_contract`: it stamps every outcome with the
    Synopsys packages the file imports, so the launcher can mention them once
    without any caller having to re-read the file.  The advisory never changes
    the verdict -- a design that runs still runs, and one that does not is
    rejected for its own reason, not for its dialect.
    """
    path = Path(path)
    result = _try_pinmap(path, board_def, pinmap) or _check_contract(path, board_def)
    # Only on a rejection, and only when no constraint file was in play at all:
    # a design that ran needs no advice, and one the pin map already judged has
    # been told about the file it used.
    if not result.ok and result.pinmap is None and pinmap is None and discover_pinmap(path) is None:
        hint = _folder_contract_hint(path)
        if hint:
            result = replace(result, message=f"{result.message}\n\n{hint}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    packages = uses_synopsys_packages(text)
    return replace(result, synopsys=packages) if packages else result


def _check_contract(
    path: Path,
    board_def: BoardDef | None = None,
) -> ContractResult:
    """Stage 2: contract validation (text-based, no simulator needed).

    Parses the toplevel entity's port/generic clauses and checks them against
    the design contract — board-aware when *board_def* is given (fixed widths
    are compared to the board's resource counts).  Falls back to the legacy
    whole-text scan when the interface cannot be parsed, so exotic-but-valid
    formatting is never rejected on parser limitations alone.

    When the generic contract fails, the design is checked against the board's
    board-native port conventions (U21): a full native match returns ``ok=True``
    with a precise message and the :class:`ConventionMatch` on the result (the
    native wrapper adapts its ports onto the sw/btn/led[/seg] boundary at run
    time), while a partial match is rejected with a near-miss message naming the
    convention.

    Returns a :class:`ContractResult`.
    """
    path = Path(path)
    stem = path.stem.lower()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return ContractResult(False, f"Cannot read file: {e}")

    # Check entity name matches filename
    entities = re.findall(r"entity\s+(\w+)\s+is", text, re.IGNORECASE)
    if not entities:
        return ContractResult(
            False,
            f"No entity declaration found in '{path.name}'.\n"
            "The file must contain: entity <name> is ... end entity;",
        )
    entity_names_lower = [e.lower() for e in entities]
    if stem not in entity_names_lower:
        found = ", ".join(f"'{e}'" for e in entities)
        return ContractResult(
            False,
            f"Entity name mismatch: found {found} but filename is '{path.name}'.\n"
            f"Rename the file to '{entities[0]}{path.suffix}' or rename the entity to '{stem}'.",
        )

    # A port-less entity is a testbench, and saying so is worth more than the
    # contract-port list it is missing (U50/G4).  It has to be asked here
    # rather than after the parse: an entity with no port clause and one whose
    # ports simply did not parse both leave _parse_toplevel_interface at None.
    if declares_no_ports(text, stem):
        return ContractResult(
            False,
            f"'{path.name}' declares an entity with no ports, which is what a "
            "testbench looks like.\n"
            "Pick the design it tests instead — the file whose entity declares "
            "clk, sw, btn and led. The simulator supplies the stimulus itself: "
            "the board's switches and buttons are the inputs, and it drives the "
            "clock.\n"
            "The testbench can stay in the folder; files beside the design are "
            "analyzed with it.",
        )

    parsed = _parse_toplevel_interface(text, stem)
    if parsed is not None:
        ok, msg = _check_parsed_contract(path.name, parsed[0], parsed[1], board_def)
        if ok:
            return ContractResult(True)
        # Generic contract failed -- is this instead a board-native design?
        attempt = _best_convention_attempt(parsed[0], parsed[1], board_def)
        if attempt is not None and attempt.match is not None:
            # U21 B3: a full native match runs -- the native wrapper adapts the
            # board's own port names to the sw/btn/led/seg boundary.
            return ContractResult(
                True, _native_convention_message(attempt.match, path.name), attempt.match
            )
        if attempt is not None and len(attempt.matched_roles) >= 2:
            return ContractResult(False, _near_miss_convention_message(attempt, path.name))
        return ContractResult(False, msg)

    # ── Legacy whole-text fallback (interface not parseable) ──────────────

    # Check required ports
    missing_ports = [
        p for p in _REQUIRED_PORTS if not re.search(r"\b" + p + r"\b", text, re.IGNORECASE)
    ]
    if missing_ports:
        return ContractResult(
            False,
            f"Missing required port(s) in '{path.name}': {', '.join(missing_ports)}.\n"
            "The top-level entity must have ports: clk, sw, btn, led.",
        )

    # NUM_SEGS without a seg port is a contract error: the generic is meaningless alone
    if re.search(r"\bNUM_SEGS\b", text, re.IGNORECASE) and not _has_seg_port(text):
        return ContractResult(
            False,
            f"'{path.name}' declares NUM_SEGS generic but has no 'seg' output port.\n"
            "Add:  seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)",
        )

    # Warn (non-fatal) about missing generics
    missing_generics = [
        g for g in _REQUIRED_GENERICS if not re.search(r"\b" + g + r"\b", text, re.IGNORECASE)
    ]
    if missing_generics:
        print(f"[warn] Missing generics (will use VHDL defaults): {', '.join(missing_generics)}")

    return ContractResult(True)


# ── Reading a simulator's own diagnostics (U4, widened by U50) ───────────────
#
# Every pattern below was captured by running the failure it describes against
# GHDL and NVC, never read off a manual: the two engines word the same defect
# differently, only one of them prints a caret, and the wording a student
# actually meets is the one their file produces on the machine in front of
# them.  A hint is added; the compiler's own text is never replaced.

#: GHDL ``no declaration for "x"`` / NVC ``no visible declaration for X``.
#: One message, three different answers -- see :func:`_classify_undeclared`.
_UNDECLARED = re.compile(r"no (?:visible )?declaration for \"?([A-Za-z_]\w*)", re.IGNORECASE)

#: Undeclared names that mean ``ieee.std_logic_1164`` was never imported.
_STD_LOGIC_NAMES = frozenset(
    {"std_logic", "std_logic_vector", "std_ulogic", "std_ulogic_vector", "rising_edge"}
)

#: Undeclared names that mean ``ieee.numeric_std`` was never imported (U50).
#: The types come first because they are what a declaration names, but the
#: conversion functions are the more common miss: a design can be written
#: entirely in ``std_logic_vector`` and still need ``to_unsigned`` to count.
_NUMERIC_STD_NAMES = frozenset(
    {
        "unsigned",
        "signed",
        "to_unsigned",
        "to_signed",
        "to_integer",
        "resize",
        "shift_left",
        "shift_right",
        "rotate_left",
        "rotate_right",
    }
)

#: The VHDL-2008 reserved words (LRM 15.10).  Used only to recognize one that a
#: student has used as an identifier -- ``units`` for a countdown's ones digit
#: is the case that found this (U50/G7) -- because neither engine says
#: "reserved word", and nothing in a first course explains why ``units`` is one.
_VHDL_RESERVED = frozenset(
    """
    abs access after alias all and architecture array assert assume
    assume_guarantee attribute begin block body buffer bus case component
    configuration constant context cover default disconnect downto else elsif
    end entity exit fairness file for force function generate generic group
    guarded if impure in inertial inout is label library linkage literal loop
    map mod nand new next nor not null of on open or others out package
    parameter port postponed procedure process property protected pure range
    record register reject release rem report restrict restrict_guarantee
    return rol ror select sequence severity signal shared sla sll sra srl
    strong subtype then to transport type unaffected units until use variable
    vmode vprop vunit wait when while with xnor xor
    """.split()
)

#: GHDL: ``an identifier is expected instead of 'units'``.
_GHDL_WANTED_IDENTIFIER = re.compile(
    r"an identifier is expected instead of '([A-Za-z_]\w*)'", re.IGNORECASE
)

#: NVC: ``unexpected units while parsing signal declaration, expecting
#: identifier``.  The expectation set is the discriminator: NVC words a missing
#: semicolon the same way ("unexpected signal ... expecting one of := or ;"),
#: and *that* token is reserved too, so matching the token alone would blame a
#: reserved word for a defect on the previous line.
_NVC_WANTED_IDENTIFIER = re.compile(
    r"unexpected ([A-Za-z_]\w*) while parsing [^\n]*?expecting [^\n]*\bidentifier\b",
    re.IGNORECASE,
)

#: Syntax errors, both engines.  Deliberately broad: the hint it produces is
#: about *where to look*, which is the same advice for every one of them.
_SYNTAX_ERROR = re.compile(
    r"missing \";\" at end of|is expected instead of|unexpected token"
    r"|unexpected \S+ while parsing",
    re.IGNORECASE,
)

#: The generated wrapper.  Its name in a diagnostic says the failure is at the
#: simulator's own boundary rather than in a file the user wrote, which is the
#: difference between two opposite pieces of advice about a missing unit.
_WRAPPER_FILE = "sim_wrapper.vhd"

#: GHDL: ``unit "test_entity" not found in library "work"``
#: NVC:  ``design unit TEST_ENTITY not found in library WORK``
_UNIT_NOT_FOUND = re.compile(
    r"(?:design )?unit \"?([A-Za-z_]\w*)\"? not found in library \"?work\"?", re.IGNORECASE
)

#: GHDL: ``too many actuals for component instance "uut"``
#: NVC:  ``found at least 7 positional actuals but WORK.TEST_ENTITY has only 6 ports``
_TOO_MANY_ACTUALS = re.compile(
    r"too many actuals for|found at least (\d+) positional actuals but"
    r"[^\n]*?has only (\d+) ports",
    re.IGNORECASE,
)


def _classify_undeclared(message: str) -> tuple[bool, bool, list[str]]:
    """Sort every undeclared name in *message* into why it is undeclared.

    Returns ``(needs_1164, needs_numeric_std, unknown_names)``.  The same
    sentence carries all three cases -- a missing library header, a missing
    ``numeric_std``, and a plain typo -- and only the name inside it tells them
    apart, so they are classified together rather than by three regexes that
    would each have to avoid the other two.
    """
    needs_1164 = needs_numeric = False
    unknown: list[str] = []
    for m in _UNDECLARED.finditer(message):
        name = m.group(1).lower()
        if name in _STD_LOGIC_NAMES:
            needs_1164 = True
        elif name in _NUMERIC_STD_NAMES:
            needs_numeric = True
        elif name not in unknown:
            unknown.append(name)
    return needs_1164, needs_numeric, unknown


def _reserved_word_used_as_identifier(message: str) -> str | None:
    """Return the reserved word a design used as an identifier, if that is the fault."""
    for pattern in (_GHDL_WANTED_IDENTIFIER, _NVC_WANTED_IDENTIFIER):
        m = pattern.search(message)
        if m is not None and m.group(1).lower() in _VHDL_RESERVED:
            return m.group(1).lower()
    return None


def add_error_hints(message: str, board_def: BoardDef | None = None) -> str:
    """Append actionable "Hint:" lines to a simulator analysis/elaboration error.

    Recognizes the GHDL and NVC wordings of two kinds of failure and explains
    the fix for each.  **Contract violations** -- a missing IEEE header,
    unmapped generics, extra unconnected ports, vector-length mismatches --
    are explained in terms of the design contract, with the board's real
    resource counts when *board_def* is given.  **Defects in the source
    itself** (U50) -- a missing ``numeric_std``, an undeclared identifier, a
    reserved word used as a name, a syntax error, an entity missing from
    ``work``, a positional port map with too many actuals -- are explained in
    terms of VHDL, because that is what went wrong.

    Unrecognized messages pass through unchanged, and a recognized one is
    never edited: the hint is appended below the compiler's own text.
    """
    if not message.strip():
        return message
    hints: list[str] = []

    # An undeclared name is one sentence with three causes (U50): a missing
    # library header, a missing numeric package, or a typo.
    needs_1164, needs_numeric_std, unknown_names = _classify_undeclared(message)

    if needs_1164:
        hints.append(
            "Add the IEEE library header at the top of the file:\n"
            "  library ieee;\n"
            "  use ieee.std_logic_1164.all;"
        )

    if needs_numeric_std:
        hints.append(
            "Add the numeric package under the IEEE library header:\n"
            "  use ieee.numeric_std.all;\n"
            "It declares unsigned and signed, and the conversions between them, "
            "integer and std_logic_vector (to_unsigned, to_signed, to_integer, resize)."
        )

    # GHDL: generic "NUM_LEDS" is not an interface name
    # NVC:  NUM_LEDS is not a formal generic of WORK.FOO
    m = re.search(
        r"generic \"(\w+)\" is not an interface name|(\w+) is not a formal generic",
        message,
        re.IGNORECASE,
    )
    if m:
        name = (m.group(1) or m.group(2)).upper()
        hints.append(
            f"The simulator sets the generic {name} at launch, so the top-level entity "
            "must declare it (with a default value). The standard generics are "
            "NUM_SWITCHES, NUM_BUTTONS, NUM_LEDS and COUNTER_BITS, plus NUM_SEGS for "
            "designs that drive a 7-segment display and NUM_RGB_LEDS for designs that "
            "aim at RGB LED channels."
        )

    # GHDL: port "rst" of mode IN must be connected
    # NVC:  missing actual for port RST of mode IN without a default expression
    m = re.search(
        r"port \"(\w+)\" of mode IN must be connected"
        r"|missing actual for port (\w+) of mode IN",
        message,
        re.IGNORECASE,
    )
    if m:
        name = (m.group(1) or m.group(2)).lower()
        hints.append(
            f"The simulator drives only the contract ports (clk, sw, btn, led, seg), so "
            f"the extra input port '{name}' is left unconnected. Give it a default value "
            f"— e.g.  {name} : in std_logic := '0'  — or remove it."
        )

    # GHDL mcode: mismatching vector length; got 4, expect 10
    # NVC:        actual length 10 does not match formal length 4
    # GHDL llvm/gcc: bound check failure at sim_wrapper.vhd:NN (the U35 probe
    #   appends the offending "port => port" association so the port is named)
    if re.search(
        r"mismatching vector length|actual length \d+ does not match formal length"
        r"|bound check failure",
        message,
        re.IGNORECASE,
    ):
        # The simulator echoes the failing wrapper association (e.g. "led => led").
        pm = re.search(r"\b(sw|btn|led|seg)\s*=>", message)
        port = pm.group(1) if pm else None
        widths = _board_port_widths(board_def)
        lines = ["Port widths must come from the generics"]
        if port:
            lines[0] += f" — the mismatch is on port '{port}'"
        lines[0] += "."
        if board_def is not None and widths:
            parts = [f"{_PORT_GENERIC[p]}={widths[p]}" for p in ("sw", "btn", "led")]
            if "seg" in widths:
                assert board_def.seven_seg is not None
                digits = board_def.seven_seg.num_digits
                parts.append(f"NUM_SEGS={digits} (seg is 8 * {digits} = {widths['seg']} bits)")
            lines.append(f"{board_def.name} provides {', '.join(parts)}.")
        lines.append(f"Declare the port with its generic:  {_PORT_SNIPPETS[port or 'led']}")
        lines.append(
            "(This validation step elaborates with the generic defaults, so the lengths "
            "reported above can differ from the board's.)"
        )
        hints.append("\n".join(lines))

    # ── Source-level defects the compiler describes but does not explain ──

    # A reserved word used as an identifier, and a plain syntax error, are
    # mutually exclusive readings of the same diagnostic: "check the previous
    # line" is wrong advice for `signal units : integer`, whose previous line
    # is fine.  The reserved word is the more specific of the two, so it wins.
    reserved = _reserved_word_used_as_identifier(message)
    if reserved is not None:
        hints.append(
            f"'{reserved}' is one of VHDL's reserved words, so it cannot name a signal, "
            f"variable, port or constant. Rename it — '{reserved}_value' or 's_{reserved}' "
            "— everywhere it appears.\n"
            'Neither GHDL nor NVC says "reserved word": both report only that an '
            "identifier was expected here. The ones that read like ordinary names "
            "include units, range, next, open, select, signal, type, bus, register, "
            "severity, label and body."
        )
    elif _SYNTAX_ERROR.search(message):
        hints.append(
            "A syntax error is reported where the text stopped making sense, which is "
            "often the line *after* the mistake — check the end of the previous line "
            "for a missing ';'.\n"
            "Every declaration and statement ends with a semicolon; the last entry "
            "inside a port ( ... ) or generic ( ... ) clause does not."
        )

    if unknown_names:
        names = ", ".join(f"'{n}'" for n in unknown_names)
        hints.append(
            f"Nothing declares {names}. Check the spelling against the declaration, and "
            "declare every signal in the architecture's declarative part — between "
            "'architecture ... is' and 'begin'.\n"
            "A port of the entity is visible without redeclaring it; a signal is not."
        )

    m = _UNIT_NOT_FOUND.search(message)
    if m:
        unit = m.group(1)
        if _WRAPPER_FILE in message:
            # Only the generated wrapper instantiates the design, and it is
            # analyzed after the design succeeded -- so the design compiled
            # under some *other* name.  Sending this reader to look for a
            # missing file would be sending them after one they already have.
            hints.append(
                f"The file analyzed, but it does not declare an entity called {unit}.\n"
                "The entity name must match the filename — a design in "
                f"{unit.lower()}.vhd has to declare  entity {unit.lower()} is  — so "
                "rename whichever of the two is wrong."
            )
        else:
            hints.append(
                f"Nothing in the library declares {unit}. The simulator analyzes the other "
                "files in the folder you picked from (one folder is one project), so copy "
                f"the file that declares {unit} into that folder, named after the entity it "
                f"declares — {unit.lower()}.vhd holds entity {unit.lower()}.\n"
                f"If {unit} is the design and you picked its testbench, pick the design "
                "instead: the simulator supplies the stimulus itself."
            )

    m = _TOO_MANY_ACTUALS.search(message)
    if m:
        counts = ""
        if m.group(1) and m.group(2):
            counts = f" — {m.group(1)} actuals for {m.group(2)} ports"
        hints.append(
            f"The port map lists more actuals than the entity has ports{counts}.\n"
            "A positional port map — port map (clk, rst, sw) — binds by position, so it "
            "silently changes meaning whenever the entity's port list does. Name the "
            "ports instead:\n"
            "  port map (clk => clk, rst => rst, sw => sw);"
        )

    if not hints:
        return message
    return message + "".join(f"\n\nHint: {h}" for h in hints)
