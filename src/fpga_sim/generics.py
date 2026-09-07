"""Overriding a design's own generics, on purpose (U48, decision D-9).

A design whose visible rate comes from the top bits of a clock divider looks
frozen here.  ``CNTR_LEN = 24`` at 50 MHz steps about three times a second on
the bench and once every minute and a half in simulation, and the student
cannot tell that from a design that does not work.

The lever is **never automatic**.  Silently rewriting somebody's constant would
make the simulator disagree with their hardware without saying so, and the
whole value of this tool is that it agrees.  So the design's own defaults are
what run until the user asks for something else -- and then the change is
visible, per-file, and thrown away when they move on.

What this module owns is the *judgment*: which generics a person can sensibly
be offered, and whether what they typed is worth handing to a simulator.  It
holds no UI and no simulator knowledge.

**Editable is a deliberately small set.**  Integers, booleans, and single-bit
literals cover the dividers, widths and enables that people actually want to
change; everything else -- a vector, an enumeration, a physical type, an
unconstrained string -- is shown but not editable, because we would be guessing
at both the syntax and the intent.  A generic we cannot offer is listed
read-only rather than hidden: "you cannot change this here" is information, and
a blank space is not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from fpga_sim.vhdl_interface import _IfaceDecl, _parse_toplevel_interface

#: Generic names the simulator sets itself, from the board's resource counts.
#: They are the contract's, not the design's, and offering them for editing
#: would let a user promise a width the board cannot deliver.
RESERVED = frozenset(
    {
        "num_switches",
        "num_buttons",
        "num_leds",
        "num_segs",
        "num_rgb_leds",
        "clk_half_ns_init",
    }
)

#: ``COUNTER_BITS`` is the one contract generic that IS offered.  The simulator
#: already overrides it (to 17, not the design's 24) and, until now, said so
#: nowhere -- which made it exactly the mystery the dialog exists to dispel.
TUNABLE_CONTRACT = "counter_bits"

_INTEGER_TYPES = frozenset({"integer", "positive", "natural"})
_BOOLEAN_TYPES = frozenset({"boolean"})
_BIT_TYPES = frozenset({"std_logic", "std_ulogic", "bit"})

_INT_RE = re.compile(r"^[+-]?\d[\d_]*$")
_BIT_RE = re.compile(r"^'[01]'$")


class Kind:
    """What an editor may offer for a generic. Not an enum: these are labels."""

    INTEGER = "integer"
    BOOLEAN = "boolean"
    BIT = "bit"
    READ_ONLY = "read-only"


@dataclass(frozen=True)
class GenericDef:
    """One generic of the picked design, as the user will see it."""

    name: str  # lowercased, as declared
    type_text: str  # lowercased declared type
    default_text: str  # the design's own default, verbatim; "" if none
    kind: str  # one of Kind.*
    reserved: bool = False  # set by the simulator from the board

    @property
    def editable(self) -> bool:
        """Report whether a user may type a new value for this generic."""
        return self.kind != Kind.READ_ONLY and not self.reserved


def _kind_of(decl: _IfaceDecl) -> str:
    t = decl.type_text.strip().lower()
    if t in _INTEGER_TYPES:
        return Kind.INTEGER
    if t in _BOOLEAN_TYPES:
        return Kind.BOOLEAN
    if t in _BIT_TYPES:
        return Kind.BIT
    return Kind.READ_ONLY


def design_generics(vhdl_text: str, toplevel: str) -> list[GenericDef]:
    """List the top level's generics in declaration order.

    Declaration order, not alphabetical: it is the order the author chose and
    usually groups related knobs together.  Returns ``[]`` for a design with no
    generics and for one whose entity will not parse -- an unparseable design
    has a louder problem than its generics, and the contract check reports it.
    """
    parsed = _parse_toplevel_interface(vhdl_text, toplevel.lower())
    if parsed is None:
        return []
    out: list[GenericDef] = []
    for decl in parsed[1]:
        for name in decl.names:
            reserved = name in RESERVED and name != TUNABLE_CONTRACT
            out.append(
                GenericDef(
                    name=name,
                    type_text=decl.type_text,
                    default_text=decl.default_text,
                    kind=_kind_of(decl),
                    reserved=reserved,
                )
            )
    return out


def validate(defn: GenericDef, value: str) -> str | None:
    """Check *value* against *defn*; return an error message, or ``None`` if fine.

    Deliberately shallow.  It rejects what is certainly wrong -- a word where a
    number belongs, a negative where the type forbids it -- and leaves the rest
    to the simulator, whose error message about a range violation is better
    than anything invented here.  Guessing harder would mean re-implementing
    VHDL's static expression rules to no benefit.
    """
    text = value.strip()
    if not text:
        return "Enter a value, or leave the default."
    if defn.reserved:
        return f"{defn.name.upper()} is set by the simulator from the board."
    if defn.kind == Kind.INTEGER:
        if not _INT_RE.match(text):
            return f"{defn.name.upper()} takes a whole number."
        n = int(text.replace("_", ""))
        if defn.type_text == "positive" and n < 1:
            return "A positive generic must be 1 or more."
        if defn.type_text == "natural" and n < 0:
            return "A natural generic cannot be negative."
        return None
    if defn.kind == Kind.BOOLEAN:
        return None if text.lower() in ("true", "false") else "Enter true or false."
    if defn.kind == Kind.BIT:
        return None if _BIT_RE.match(text) else "Enter '0' or '1', with the quotes."
    return f"{defn.name.upper()} is a {defn.type_text}; change it in the file."


def parse_cli_override(text: str) -> tuple[str, str] | str:
    """Split one ``--generic NAME=VALUE``; return the pair or an error message."""
    name, sep, value = text.partition("=")
    name, value = name.strip(), value.strip()
    if not sep or not name or not value:
        return f"--generic wants NAME=VALUE, not {text!r}."
    if not re.fullmatch(r"[A-Za-z_]\w*", name):
        return f"{name!r} is not a VHDL identifier."
    return name.lower(), value


def resolve(
    defs: list[GenericDef],
    requested: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    """Keep the requested overrides this design can actually accept.

    Returns ``(accepted, problems)``.  A name the design does not declare is a
    problem worth reporting rather than ignoring: on the CLI it is almost
    always a typo, and silently running the design unchanged would look exactly
    like the flag not working.
    """
    by_name = {d.name: d for d in defs}
    accepted: dict[str, str] = {}
    problems: list[str] = []
    for name, value in requested.items():
        defn = by_name.get(name.lower())
        if defn is None:
            known = ", ".join(sorted(d.name.upper() for d in defs if d.editable))
            problems.append(
                f"{name.upper()} is not a generic of this design."
                + (f" It declares: {known}." if known else "")
            )
            continue
        err = validate(defn, value)
        if err:
            problems.append(err)
            continue
        accepted[defn.name] = value.strip()
    return accepted, problems
