"""Running a design through its own constraint file (U53).

Board-native mode (U21) recognizes a design by its **port names**: write
``CLOCK_50`` / ``LEDR`` / ``KEY`` and a Terasic board knows you.  That covers
designs written to a vendor's published naming, and covers nothing else -- and
the way a great deal of real work is actually done is to name ports whatever
the assignment says and let the *project's constraint file* bind them to pins.
Every Quartus and Vivado project has one; the course material in front of this
arc names its ports ``clock`` / ``led_r`` / ``hex`` and binds them in a ``.qsf``.

So this module maps by the one thing both sides agree on: **the pin**.  Take
the design's ports, look each bit up in the constraint file to get a pin, look
that pin up in the board to get a resource, and the design's own names stop
mattering.  It is the student's declared truth rather than a guess about their
naming.

Three rules earned from real files rather than from the design sketch:

* **A port with no assignment at all is normal.**  A lab's own top level
  declares ``button(2 downto 0)`` that its ``.qsf`` never binds -- Quartus
  places such a pin automatically, so the project builds and nobody notices.
  An unassigned input is tied off with a note, never rejected.
* **The constraint file is the vendor's whole pin file.**  The course's is 422
  assignments against a six-port design: SDRAM, VGA, audio, HPS, and both the
  golden-top names and the instructor's.  The map is therefore built *outward
  from the design's ports*; an assignment no declared port claims is not our
  business, and only a pin some declared port actually claims can be an error.
* **A design may drive part of a display.**  Four digits of a six-digit board is
  a normal thing to write, and the other two stay dark exactly as they do on the
  bench.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from fpga_sim.constraints import boardstore_xml, ccf, cst, lpf, pcf, qsf, ucf, xdc
from fpga_sim.constraints.types import PortTable

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef
    from fpga_sim.vhdl_interface import _IfaceDecl

#: Constraint-file suffix -> the dialect module that reads it.  The suffix is
#: how a project names its file; there is no content sniffing, because a
#: mis-detected dialect would produce a *wrong* map rather than no map.
_DIALECTS = {
    ".qsf": qsf,
    ".xdc": xdc,
    ".ucf": ucf,
    ".pcf": pcf,
    ".cst": cst,
    ".lpf": lpf,
    ".ccf": ccf,
    ".xml": boardstore_xml,
}

#: ``PIN_AF14`` and ``AF14`` are the same pad.  Quartus writes the prefix in its
#: assignment statements and the board data stores the bare pad name.
_PIN_PREFIX = re.compile(r"^pin_", re.IGNORECASE)

#: ``LED_R[3]`` -> ("led_r", 3).  A bare name has no index, which is how a
#: scalar port and bit 0 of a vector stay distinguishable.
_INDEXED = re.compile(r"^(.*?)\s*\[\s*(\d+)\s*\]$")


def normalize_pin(pin: str) -> str:
    """Canonical form of a pin name: no ``PIN_`` prefix, lowercased."""
    return _PIN_PREFIX.sub("", pin.strip()).lower()


def split_port(port: str) -> tuple[str, int | None]:
    """Split a constraint file's port token into (lowercased name, index)."""
    text = port.strip()
    m = _INDEXED.match(text)
    if m:
        return m.group(1).strip().lower(), int(m.group(2))
    return text.lower(), None


# ── What a pin is, on the board ──────────────────────────────────────────────


@dataclass(frozen=True)
class PinRole:
    """What one board pin drives, in the simulator's own boundary terms.

    *kind* is ``"clk"``, ``"led"``, ``"sw"``, ``"btn"``, ``"seg"``, ``"dp"`` or
    ``"digit_enable"``.  *index* means the boundary bit for led/sw/btn, the
    digit for dp and digit_enable, and is unused for clk.  *segment* is the
    a..g position for a segment pin, and *digit* its digit -- ``None`` on a
    scanned display, whose segment lines are shared across all of them.
    """

    kind: str
    index: int = 0
    digit: int | None = None
    segment: int | None = None
    active_low: bool = False


def board_pin_index(board: BoardDef) -> dict[str, PinRole]:
    """Map every pin the board data knows to what it drives.

    Built from the same fields the renderer draws from, so a pin map and the
    picture on screen cannot disagree.  A resource with no pin recorded is
    skipped rather than guessed at: the consequence is a design that cannot be
    mapped, which is reported, instead of one mapped to the wrong LED.
    """
    index: dict[str, PinRole] = {}

    for clock in board.clock_defs:
        if clock.pin:
            index.setdefault(normalize_pin(clock.pin), PinRole("clk"))

    # LED channels follow the boundary layout the wrapper and renderer already
    # use (U37): mono LEDs first in JSON order, then three channels per RGB
    # site.  An RGB component owns three consecutive channels and three pins, so
    # its pins are consumed in step with them.
    consumed: dict[int, int] = {}
    for channel, led_i in enumerate(board.led_channel_targets):
        led = board.leds[led_i]
        taken = consumed.get(led_i, 0)
        if taken >= len(led.pins):
            continue
        consumed[led_i] = taken + 1
        index.setdefault(
            normalize_pin(led.pins[taken]),
            PinRole("led", channel, active_low=led.inverted),
        )

    for i, sw in enumerate(board.switches):
        if sw.pins:
            index.setdefault(normalize_pin(sw.pins[0]), PinRole("sw", i, active_low=sw.inverted))

    for i, btn in enumerate(board.buttons):
        if btn.pins:
            index.setdefault(normalize_pin(btn.pins[0]), PinRole("btn", i, active_low=btn.inverted))

    seg = board.seven_seg
    if seg is not None and seg.has_pin_data:
        low = seg.inverted
        for digit_or_shared, row in enumerate(seg.segment_pins):
            digit = None if seg.is_scan else digit_or_shared
            for segment, pin in enumerate(row):
                index.setdefault(
                    normalize_pin(pin),
                    PinRole("seg", digit=digit, segment=segment, active_low=low),
                )
        for i, pin in enumerate(seg.dp_pins):
            digit = None if seg.is_scan else i
            index.setdefault(normalize_pin(pin), PinRole("dp", digit=digit, active_low=low))
        for i, pin in enumerate(seg.digit_enable_pins):
            index.setdefault(
                normalize_pin(pin),
                PinRole("digit_enable", index=i, active_low=seg.select_inverted),
            )
    return index


# ── Finding the file ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PinMapProblem:
    """Why a design could not be mapped through its constraint file."""

    message: str


def discover_pinmap(vhdl_path: str | Path) -> Path | PinMapProblem | None:
    """Find the constraint file beside a design.

    Exactly one is used.  Two or more is a question only the user can answer --
    a project with both a ``.qsf`` and an ``.xdc`` beside it is targeting two
    boards -- so it is reported rather than guessed, and ``--pinmap`` settles
    it.  None at all is not an error: the name-based paths still run.
    """
    design = Path(vhdl_path)
    folder = design.parent
    if not folder.is_dir():
        return None
    found = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _DIALECTS)
    if not found:
        return None
    if len(found) > 1:
        names = ", ".join(p.name for p in found)
        return PinMapProblem(
            f"{folder} holds more than one constraint file ({names}), so it is not clear "
            "which one describes this design.\n"
            "Pass the one you mean with --pinmap <file>."
        )
    return found[0]


def read_pinmap(path: str | Path) -> PortTable | PinMapProblem:
    """Parse a constraint file with the dialect its suffix names."""
    file = Path(path)
    module = _DIALECTS.get(file.suffix.lower())
    if module is None:
        known = " ".join(sorted(_DIALECTS))
        return PinMapProblem(f"{file.name}: not a constraint file this reads ({known}).")
    try:
        text = file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return PinMapProblem(f"Cannot read {file.name}: {e}")
    parsed: PortTable = module.parse(text)
    return parsed


# ── The map itself ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BitBinding:
    """One bit of one design port, and the board resource it lands on."""

    port: str
    bit: int | None  # None for a scalar port
    pin: str
    role: PinRole


@dataclass(frozen=True)
class PinMapMatch:
    """A design mapped onto the board through its constraint file.

    ``notes`` carry what the user should know but need not act on -- an input
    that no assignment binds, tied off so the design still runs.
    """

    source: str  # the constraint file's name, for the badge and the log
    board_name: str
    clock_port: str = ""
    inputs: tuple[BitBinding, ...] = ()
    outputs: tuple[BitBinding, ...] = ()
    open_outputs: tuple[str, ...] = ()
    tied_inputs: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)
    #: Declared width of each design port, or ``None`` where it is a scalar.
    #: The wrapper needs it to declare the signal it drives the port through,
    #: including for a port nothing binds -- which has no bindings to infer from.
    widths: tuple[tuple[str, int | None], ...] = ()

    @property
    def port_widths(self) -> dict[str, int | None]:
        """The declared widths as a mapping, for the wrapper's convenience."""
        return dict(self.widths)


def _port_bits(decl: _IfaceDecl, name: str) -> list[int | None]:
    """Return the bit positions one declared port occupies.

    A scalar is ``[None]``; a vector of literal width *n* is ``0..n-1``.  A
    vector whose width is an expression has no literal width, so its bits are
    discovered from the constraint file instead -- which is the right source
    anyway, since that file is what says how wide the design really is on this
    board.
    """
    if decl.literal_width is None:
        return [None]
    return list(range(decl.literal_width))


def build_pin_map(
    ports: list[_IfaceDecl],
    table: PortTable,
    board: BoardDef,
    *,
    source: str,
    device: str = "",
) -> PinMapMatch | PinMapProblem:
    """Map a design's declared ports onto *board* through its constraint file.

    Built **outward from the design's ports**: the constraint file is the
    vendor's entire pin file (422 assignments against a six-port design, in the
    material this was written for), so an assignment no declared port claims is
    simply not this design's business.  Only a pin a *declared* port claims can
    be an error.
    """
    assignments: dict[tuple[str, int | None], str] = {}
    for entry in table.pins:
        assignments[split_port(entry.port)] = entry.pin
    pin_roles = board_pin_index(board)

    inputs: list[BitBinding] = []
    outputs: list[BitBinding] = []
    open_outputs: list[str] = []
    tied_inputs: list[str] = []
    notes: list[str] = []
    clock_port = ""
    unknown: list[str] = []
    widths: list[tuple[str, int | None]] = []

    for decl in ports:
        for name in decl.names:
            bits = _port_bits(decl, name)
            widths.append((name, decl.literal_width))
            bound: list[BitBinding] = []
            for bit in bits:
                pin = assignments.get((name, bit))
                if pin is None and bit is None:
                    # A scalar may still be written indexed in the constraint
                    # file, and vice versa; try the other spelling before
                    # calling it unassigned.
                    pin = assignments.get((name, 0))
                if pin is None:
                    continue
                role = pin_roles.get(normalize_pin(pin))
                if role is None:
                    unknown.append(f"{name}{'' if bit is None else f'[{bit}]'} -> pin {pin}")
                    continue
                bound.append(BitBinding(name, bit, normalize_pin(pin), role))

            if not bound:
                if decl.mode == "out":
                    open_outputs.append(name)
                elif decl.has_default:
                    pass  # the design already says what it should read
                else:
                    # Gate A: a real lab top level declares `button(2 downto 0)`
                    # that its own .qsf never binds.  Quartus places such a pin
                    # automatically, so the project builds and nobody finds out.
                    # Tie it off and say so -- rejecting would refuse the first
                    # file of the first lab.
                    tied_inputs.append(name)
                    notes.append(
                        f"'{name}' has no pin assignment in {source}, so it reads as "
                        "0 here (on the board it would float or be placed automatically)."
                    )
                continue

            if any(b.role.kind == "clk" for b in bound):
                clock_port = name
            elif decl.mode == "out":
                outputs.extend(bound)
            else:
                inputs.extend(bound)

    if unknown:
        detail = "\n".join(f"  {u}" for u in unknown[:8])
        extra = f"\n  ... and {len(unknown) - 8} more" if len(unknown) > 8 else ""
        hint = ""
        if device and board.device and device.lower() not in board.device.lower():
            hint = (
                f"\n\n{source} targets {device}, but {board.name} is {board.device} — "
                "did you select the wrong board?"
            )
        return PinMapProblem(
            f"{source} assigns pins that {board.name} does not have:\n{detail}{extra}{hint}"
        )

    if not outputs:
        return PinMapProblem(
            f"{source} binds none of '{board.name}'s LEDs or display segments to this "
            "design's outputs, so there would be nothing to watch.\n"
            "Check that the constraint file and the board match."
        )

    return PinMapMatch(
        source=source,
        board_name=board.name,
        clock_port=clock_port,
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        open_outputs=tuple(open_outputs),
        tied_inputs=tuple(tied_inputs),
        notes=tuple(notes),
        widths=tuple(widths),
    )
