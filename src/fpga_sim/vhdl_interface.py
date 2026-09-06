"""Reading a VHDL file's toplevel interface, without judging it (D17).

The half of contract checking that is pure text work: is the file readable as
the encoding a simulator will accept, and what does its entity actually
declare?  :func:`_parse_toplevel_interface` returns the ports and generics as
:class:`_IfaceDecl` records -- name, direction, type, width, default -- and
everything downstream is a policy question asked of that answer.

Keeping the parser separate from the policies is what lets three different
policies share it: the generic contract (:mod:`fpga_sim.vhdl_contract`), the
board-native convention matcher (:mod:`fpga_sim.conventions`), and the wrapper
generator, which needs the same declarations to write its instantiation.  The
parser is deliberately forgiving about layout -- comments stripped, nesting
respected, one declaration per name even when several share a line -- and
deliberately ignorant of what any of it *means*.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef

# ── VHDL validation (simulator-independent) ───────────────────────────────────


def _has_seg_port(vhdl_text: str) -> bool:
    """Return True if the VHDL text declares a 'seg' output port."""
    return bool(re.search(r"\bseg\s*:\s*out\b", vhdl_text, re.IGNORECASE))


def _has_rgb_generic(vhdl_text: str) -> bool:
    """Return True if the VHDL text mentions the ``NUM_RGB_LEDS`` generic (U37).

    Mirrors :func:`_has_seg_port`'s role: the wrapper declares + maps the
    generic, and ``_prepare_simulation`` passes the board's RGB count, only
    when the design opts in by declaring it.
    """
    return bool(re.search(r"\bNUM_RGB_LEDS\b", vhdl_text, re.IGNORECASE))


def check_vhdl_encoding(path: str | Path) -> tuple[bool, str]:
    """Stage 1: encoding check (no simulator needed).

    Returns (ok: bool, message: str).
    """
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as e:
        return False, f"Cannot read file: {e}"

    if raw[:3] == b"\xef\xbb\xbf":
        return False, (
            f"UTF-8 BOM detected in '{path.name}'.\n"
            "Save the file without BOM (UTF-8 without BOM / ASCII)."
        )

    for lineno, line in enumerate(raw.split(b"\n"), start=1):
        for byte in line:
            if byte > 127:
                return False, (
                    f"Non-ASCII byte (0x{byte:02X}) on line {lineno} of '{path.name}'.\n"
                    "VHDL source must be plain ASCII or UTF-8 without BOM."
                )

    return True, ""


# ── Toplevel-interface parsing (contract checks + contextual hints, U4) ──────

_REQUIRED_PORTS = ("clk", "sw", "btn", "led")
_CONTRACT_PORTS = ("clk", "sw", "btn", "led", "seg")
_REQUIRED_GENERICS = ("NUM_SWITCHES", "NUM_BUTTONS", "NUM_LEDS", "COUNTER_BITS")
_PORT_MODES = {"clk": "in", "sw": "in", "btn": "in", "led": "out", "seg": "out"}
_PORT_SNIPPETS = {
    "clk": "clk : in  std_logic",
    "sw": "sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0)",
    "btn": "btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0)",
    "led": "led : out std_logic_vector(NUM_LEDS - 1 downto 0)",
    "seg": "seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)",
}
_PORT_GENERIC = {"sw": "NUM_SWITCHES", "btn": "NUM_BUTTONS", "led": "NUM_LEDS"}
# Port widths produced by sim_wrapper_template.vhd's generic defaults (all 4;
# seg = 8 * 4).  A fixed-width port passes the early elaboration check only at
# exactly these widths, because that check runs with the VHDL defaults.
_WRAPPER_DEFAULT_WIDTHS = {"sw": 4, "btn": 4, "led": 4, "seg": 32}


@dataclass
class _IfaceDecl:
    """One `names : [mode] type [:= default]` declaration from a port/generic clause."""

    names: list[str]  # lowercased identifiers
    mode: str  # "in"/"out"/"inout"/"buffer"/"linkage"; "" for generics
    has_default: bool
    literal_width: int | None  # std_logic_vector with pure-literal bounds, else None
    type_text: str = ""  # lowercased declared type ("positive", "natural", ...)
    #: The default expression as written, case preserved ("24", "'1'", "x\"FF\"").
    #: Kept verbatim rather than evaluated: the generic override (U48) shows it
    #: to the user and hands it back to the simulator, and neither wants our
    #: interpretation of an expression VHDL is better at reading than we are.
    default_text: str = ""


def _strip_vhdl_comments(text: str) -> str:
    return re.sub(r"--[^\n]*", "", text)


def _entity_block(text: str, name: str) -> str | None:
    """Return the text between ``entity <name> is`` and its first ``end``."""
    m = re.search(rf"\bentity\s+{re.escape(name)}\s+is\b", text, re.IGNORECASE)
    if m is None:
        return None
    tail = text[m.end() :]
    e = re.search(r"\bend\b", tail, re.IGNORECASE)
    return tail[: e.start()] if e else None


def _clause_body(text: str, keyword: str) -> str | None:
    """Return the balanced parenthesized body of ``<keyword> ( ... )``, or None."""
    m = re.search(rf"\b{keyword}\s*\(", text, re.IGNORECASE)
    if m is None:
        return None
    depth, start = 1, m.end()
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i]
    return None  # unbalanced


def _split_top_level(text: str, sep: str) -> list[str]:
    """Split on *sep* occurrences that are outside any parentheses."""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for c in text:
        if c == "(":
            depth += 1
        elif c == ")":
            depth = max(0, depth - 1)
        if c == sep and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    parts.append("".join(cur))
    return parts


def _parse_decls(body: str, *, ports: bool) -> list[_IfaceDecl] | None:
    """Parse a port/generic clause body into declarations; None if unparseable."""
    decls: list[_IfaceDecl] = []
    for part in _split_top_level(body, ";"):
        part = part.strip()
        if not part:
            continue
        head, colon, rest = part.partition(":")
        if not colon:
            return None
        names = [n.strip().lower() for n in head.split(",")]
        if not names or not all(re.fullmatch(r"[a-z_]\w*", n) for n in names):
            return None
        rest = rest.strip()
        mode = ""
        if ports:
            m = re.match(r"(in|out|inout|buffer|linkage)\b", rest, re.IGNORECASE)
            mode = m.group(1).lower() if m else "in"  # implicit port mode is IN
            if m:
                rest = rest[m.end() :].strip()
        type_text = rest.split(":=")[0].strip()
        literal_width = None
        wm = re.fullmatch(
            r"std_logic_vector\s*\(\s*(\d+)\s+(downto|to)\s+(\d+)\s*\)",
            type_text,
            re.IGNORECASE,
        )
        if wm:
            a, kw, b = int(wm.group(1)), wm.group(2).lower(), int(wm.group(3))
            span = a - b if kw == "downto" else b - a
            if span >= 0:
                literal_width = span + 1
        _, _, default_text = rest.partition(":=")
        decls.append(
            _IfaceDecl(
                names,
                mode,
                ":=" in rest,
                literal_width,
                type_text.lower(),
                default_text.strip(),
            )
        )
    return decls


def _parse_toplevel_interface(
    text: str, entity_name: str
) -> tuple[list[_IfaceDecl], list[_IfaceDecl]] | None:
    """Parse the toplevel entity's (ports, generics); None if unparseable.

    Scoped to ``entity <entity_name> is … end`` so inner entities of
    multi-entity files (e.g. the embedded-core designs) are never inspected.
    """
    block = _entity_block(_strip_vhdl_comments(text), entity_name)
    if block is None:
        return None
    gbody = _clause_body(block, "generic")
    pbody = _clause_body(block, "port")
    if pbody is None:
        return None
    generics = _parse_decls(gbody, ports=False) if gbody is not None else []
    ports = _parse_decls(pbody, ports=True)
    if ports is None or generics is None:
        return None
    return ports, generics


def _board_port_widths(board_def: BoardDef | None) -> dict[str, int]:
    """Effective wrapper port widths for *board_def*.

    Mirrors ``controller.build_generics()``: resource counts are floored at 1
    (the wrapper's vectors cannot be empty) and ``seg`` is 8 bits per digit.
    """
    if board_def is None:
        return {}
    widths = {
        "sw": max(1, len(board_def.switches)),
        "btn": max(1, len(board_def.buttons)),
        # Channels, not components: an RGB LED is one component but three
        # boundary bits (U37), so the led vector is num_led_channels wide.
        "led": max(1, board_def.num_led_channels),
    }
    if board_def.seven_seg is not None:
        widths["seg"] = 8 * board_def.seven_seg.num_digits
    return widths


def _plural(n: int, noun: str) -> str:
    if noun.endswith("h"):  # switch → switches
        return f"{n} {noun}es" if n != 1 else f"{n} {noun}"
    return f"{n} {noun}s" if n != 1 else f"{n} {noun}"
