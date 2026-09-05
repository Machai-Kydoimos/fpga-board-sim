"""Matching a design's own port names against a board's conventions (U21, D17).

The board-native path: a design written to a board's real port names --
Terasic's ``CLOCK_50`` / ``KEY`` / ``LEDR`` / ``HEX0``-``HEX5``, with no
``NUM_*`` generics -- instead of to the simulator's generic contract.  Each
board's JSON may carry several convention blocks (a vendor-canonical one, a
framework-derived one from litex or amaranth), so matching is a *search*: try
them in precedence order, take the first full match, and otherwise keep the
closest near-miss so the failure can name what actually differed.

Two rules run through everything here and are worth stating once. **The
simulator always models the selected board**, so a design written for a
different one near-misses on a name rather than being silently coerced or
polarity-flipped.  And **a role is matched when the convention declares it**:
a board with no switches, or a design that drives no display, is not a failure
-- only a design that declares *part* of a bank it half-recognizes is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from fpga_sim.vhdl_interface import _IfaceDecl

if TYPE_CHECKING:
    from fpga_sim.board_loader import BoardDef

# ── Board-native port-convention matcher (U21) ───────────────────────────────
#
# A board-native VHDL file uses the *board's* port names and fixed widths (e.g.
# DE10-Standard's CLOCK_50 / SW / KEY / LEDR / HEX0..5) instead of the
# simulator's generic clk/sw/btn/led[/seg] contract with NUM_* generics.  These
# fail `_check_parsed_contract` (no `clk`/`btn`/`led`), so when that happens we
# try to recognize the design against the selected board's `port_conventions`.
#
# A full match returns `ok=True` with a `ConventionMatch` on the result, and the
# native wrapper (`_render_native_wrapper`) adapts the design's own port names --
# polarity inversion, zero-extend, per-digit 7-seg packing -- onto the
# simulator's sw/btn/led[/seg] boundary, so the cocotb testbench and run
# mechanics are unchanged.  A partial (near-miss) match is reported precisely
# and rejected, never silently coerced.  The badge and session log consume the
# match too.


@dataclass(frozen=True)
class NativePort:
    """A matched native LED/switch/button bank for one contract role.

    ``names`` holds the board-native port name(s) (original case, as spelled in
    the convention): a single entry for a shared vector (e.g. ``("LEDR",)``) or
    several for a bank of distinct scalar ports (e.g. Nandland Go's
    ``("o_LED_1", ...)``).  ``width`` is the vector width or the scalar count.

    ``scalar_ports`` marks a bank whose ``names`` are each an individual scalar
    port (``std_logic``) rather than one shared vector: either a ``names[]``
    cluster, or a width-1 vector bank the design spelled as a plain scalar (the
    natural ``led : out std_logic`` on a one-LED board).  It -- not
    ``len(names)`` -- drives the per-bit vs whole-vector choice in the wrapper
    port map and the ``.gtkw`` writer, so a single-member scalar cluster is
    handled correctly too.
    """

    names: tuple[str, ...]
    width: int
    active_low: bool = False
    scalar_ports: bool = False


@dataclass(frozen=True)
class NativeSeg:
    """A matched native 7-segment interface (``individual`` or ``scan`` style, U22).

    ``individual``: ``names`` are the per-digit port names (e.g. ``("HEX0", ...,
    "HEX5")``), each a ``width_per_digit``-bit vector; ``digit_enable``/``dp``
    are unused.

    ``scan``: ``names`` describe the *shared segment lines* -- either one
    ``width_per_digit``-bit vector (``("seg",)``, ``scalar_segments=False``) or
    per-segment scalars (``("CA", ..., "CG")``, ``scalar_segments=True``) --
    ``digit_enable`` is the digit-select bank (its width is the digit count),
    and ``dp`` is the shared decimal-point scalar when both the convention and
    the design declare one.  ``active_low`` covers the segment (and dp) drive;
    the enable's polarity rides on ``digit_enable.active_low``.
    """

    style: str
    names: tuple[str, ...]
    width_per_digit: int
    active_low: bool = False
    digit_enable: NativePort | None = None
    dp: str | None = None
    scalar_segments: bool = False

    @property
    def num_digits(self) -> int:
        """Digit count: the enable width for ``scan``, else one digit per name."""
        if self.style == "scan" and self.digit_enable is not None:
            return self.digit_enable.width
        return len(self.names)


@dataclass(frozen=True)
class ConventionMatch:
    """A design recognized as board-native, with everything B3 needs to wrap it.

    Names are the board-native identifiers from the convention (original case);
    VHDL is case-insensitive, so B3 can emit them verbatim.
    """

    maker: str  # convention slug, e.g. "terasic"
    board_name: str  # BoardDef.name, for messages/badge
    clk: str  # native clock port name, e.g. "CLOCK_50"
    # The mono LED bank.  None when the design drives the board through the RGB
    # channel bank alone (U38) -- at least one of leds/leds_rgb is always set.
    leds: NativePort | None
    # switches/buttons are optional (U31): a switch-less or button-less board's
    # convention simply omits the role, so the design need not declare it (clk +
    # LEDs are the minimum meaningful board-native demo).
    switches: NativePort | None = None
    buttons: NativePort | None = None
    seven_seg: NativeSeg | None = None
    leds_green: NativePort | None = None  # optional secondary LED bank (e.g. LEDG)
    # RGB channel scalar bank (U38): names in (r,g,b) order per site, packed
    # onto the boundary's RGB channel block `led(MONO + 3i + c)`.
    leds_rgb: NativePort | None = None


@dataclass(frozen=True)
class ContractResult:
    """Outcome of :func:`check_vhdl_contract`.

    ``ok``/``message`` mirror the former ``(bool, str)`` tuple; ``match`` is the
    board-native recognition (U21) when the design uses a board's native port
    convention — populated even while ``ok`` is False (native execution is B3).
    """

    ok: bool
    message: str = ""
    match: ConventionMatch | None = None


@dataclass(frozen=True)
class _ConventionAttempt:
    """Result of trying one convention block: a full match, or the near-miss detail."""

    maker: str
    board_name: str
    match: ConventionMatch | None  # a complete board-native match, else None
    matched_roles: tuple[str, ...]  # role tags that matched (near-miss scoring)
    problems: tuple[str, ...]  # human-readable missing/mismatched roles


_SIZING_GENERICS = {"num_switches", "num_buttons", "num_leds", "num_segs", "num_rgb_leds"}


def _match_native_port(
    mapping: dict[str, Any],
    port_by_name: dict[str, _IfaceDecl],
    mode: str,
) -> NativePort | None:
    """Match a leds/switches/buttons/leds_green convention mapping to native ports.

    Accepts a shared vector (``name`` + ``width``) or a bank of distinct scalars
    (``names``).  Returns None unless the design declares the native port(s) at
    the convention's fixed width, in the expected direction (*mode*).

    A width-1 vector bank also matches a plain scalar port (``std_logic``) -- the
    natural spelling for a one-LED / one-button board -- returning a
    ``scalar_ports`` bank the wrapper associates per element.  A
    ``std_logic_vector(0 downto 0)`` spelling still matches as a (non-scalar)
    vector, so both forms work.
    """
    active_low = bool(mapping.get("active_low", False))
    scalar_names = mapping.get("names")
    if isinstance(scalar_names, list) and scalar_names:
        for nm in scalar_names:
            decl = port_by_name.get(str(nm).lower())
            # names[] members are individual scalar ports by definition; a
            # vector-typed member (literal_width set) is a mismatch caught here,
            # not a cryptic association failure at elaboration.
            if decl is None or decl.mode != mode or decl.literal_width is not None:
                return None
        return NativePort(
            tuple(str(n) for n in scalar_names), len(scalar_names), active_low, scalar_ports=True
        )
    name = mapping.get("name")
    width = mapping.get("width")
    if not isinstance(name, str) or not isinstance(width, int):
        return None
    decl = port_by_name.get(name.lower())
    if decl is None or decl.mode != mode:
        return None  # absent or wrong direction
    if decl.literal_width == width:
        return NativePort((name,), width, active_low)  # exact fixed-width vector
    if width == 1 and decl.literal_width is None:
        # A one-bit bank declared as a plain scalar (`led : out std_logic`):
        # associate it per element in the wrapper (`led => led_uut(0)`).
        return NativePort((name,), 1, active_low, scalar_ports=True)
    return None  # width mismatch


def _seg_role_port_names(seg: dict[str, Any]) -> set[str]:
    """Every port name (lowercased) a convention's 7-seg block lays claim to.

    Drives the U22 partial-declaration guard in :func:`_attempt_convention`: a
    design declaring *any* of these is trying to drive the display, so a failed
    seg match must surface as a near-miss rather than the ports silently going
    dark as unmapped outputs.  Covers every style — including the unmatchable
    ones (``per_segment_scalars``/``serial``), whose declared ports also mean
    "this design drives the display" and deserve the same honest rejection.
    """
    names: set[str] = set()
    raw_names = seg.get("names")
    if isinstance(raw_names, list):
        names.update(str(n).lower() for n in raw_names)
    if isinstance(seg.get("name"), str):
        names.add(str(seg["name"]).lower())
    if isinstance(seg.get("dp"), str):
        names.add(str(seg["dp"]).lower())
    enable = seg.get("digit_enable")
    if isinstance(enable, dict):
        if isinstance(enable.get("name"), str):
            names.add(str(enable["name"]).lower())
        if isinstance(enable.get("names"), list):
            names.update(str(n).lower() for n in enable["names"])
    return names


def _match_native_seg(
    seg: dict[str, Any],
    port_by_name: dict[str, _IfaceDecl],
) -> NativeSeg | None:
    """Match an ``individual``- or ``scan``-style 7-seg convention (U22).

    ``individual``: one fixed-width vector per digit, e.g. HEX0..n.

    ``scan``: the physical multiplexed interface — the shared segment lines
    (one ``width_per_digit``-bit vector, or per-segment scalars via ``names``)
    plus the ``digit_enable`` bank, both design *outputs*; the shared ``dp``
    scalar is matched when both sides declare it and stays optional otherwise
    (a dp-less design's dp bits are simply dark, mirroring ``leds_green``'s
    leniency).

    Other styles (``packed_vector``/``per_segment_scalars``/``serial``) decline
    here and are left to the generic path (Icebox territory).
    """
    style = seg.get("style")
    wpd = seg.get("width_per_digit")
    if style == "individual":
        names = seg.get("names")
        if not isinstance(names, list) or not names or not isinstance(wpd, int):
            return None
        for nm in names:
            decl = port_by_name.get(str(nm).lower())
            if decl is None or decl.mode != "out" or decl.literal_width != wpd:
                return None
        return NativeSeg(
            "individual", tuple(str(n) for n in names), wpd, bool(seg.get("active_low"))
        )

    if style != "scan" or not isinstance(wpd, int):
        return None
    enable_decl = seg.get("digit_enable")
    if not isinstance(enable_decl, dict):
        return None
    enable = _match_native_port(enable_decl, port_by_name, "out")
    if enable is None:
        return None

    # Segment side: per-segment scalars (names[]) or one shared vector (name).
    raw_names = seg.get("names")
    if isinstance(raw_names, list) and raw_names:
        if len(raw_names) != wpd:
            return None  # inconsistent data; cross_check_widths refuses this too
        for nm in raw_names:
            decl = port_by_name.get(str(nm).lower())
            if decl is None or decl.mode != "out" or decl.literal_width is not None:
                return None
        seg_names = tuple(str(n) for n in raw_names)
        scalar_segments = True
    else:
        name = seg.get("name")
        if not isinstance(name, str):
            return None
        decl = port_by_name.get(name.lower())
        if decl is None or decl.mode != "out" or decl.literal_width != wpd:
            return None
        seg_names = (name,)
        scalar_segments = False

    # dp: matched only when both sides declare a scalar out of that name.
    dp: str | None = None
    dp_name = seg.get("dp")
    if isinstance(dp_name, str):
        decl = port_by_name.get(dp_name.lower())
        if decl is not None and decl.mode == "out" and decl.literal_width is None:
            dp = dp_name

    return NativeSeg(
        "scan",
        seg_names,
        wpd,
        bool(seg.get("active_low")),
        digit_enable=enable,
        dp=dp,
        scalar_segments=scalar_segments,
    )


def _attempt_convention(
    maker: str,
    block: dict[str, Any],
    board_def: BoardDef,
    port_by_name: dict[str, _IfaceDecl],
) -> _ConventionAttempt:
    """Try to match one maker's convention block against the parsed interface."""
    problems: list[str] = []
    matched: list[str] = []

    clk_port: str | None = None
    clk_name = block.get("clk")
    if isinstance(clk_name, str):
        decl = port_by_name.get(clk_name.lower())
        if decl is not None and decl.mode == "in":
            clk_port = clk_name
            matched.append("clk")
    if clk_port is None:
        problems.append(f"clock '{clk_name}'" if isinstance(clk_name, str) else "clock")

    # Primary LED-ish banks (U38): the mono `leds` vector and/or the `leds_rgb`
    # scalar channel bank.  Each is matched when the convention declares it, and
    # the floor is that at least ONE matches -- on an RGB-only board (Cora Z7,
    # Eclypse Z7) the channel bank IS the LEDs.  Like leds_green, an unmatched
    # bank never blocks a match by itself: ports the design declares toward it
    # fall under the ordinary unmapped-output rule (left open, dark).
    leds = _match_native_port(block.get("leds") or {}, port_by_name, "out")
    rgb_decl = block.get("leds_rgb")
    leds_rgb = (
        _match_native_port(rgb_decl, port_by_name, "out") if isinstance(rgb_decl, dict) else None
    )
    if leds is not None:
        matched.append("led")
    if leds_rgb is not None:
        matched.append("rgb-led")
    if leds is None and leds_rgb is None:
        problems.append("LEDs")

    # Switches / buttons are matched only when the convention declares the role
    # (U31): most FPGA boards have no switches, so a switch-less convention
    # neither requires nor adapts an `sw` bank -- exactly as `seg` is conditional
    # on the board having a display.  The requirement keys off the *convention*
    # (the native-name source of truth), not the board's physical resources, so a
    # board whose convention has not captured its switches yet simply cannot drive
    # them natively rather than never matching.  A declared-but-unmatched bank is
    # a near-miss.
    sw_declared = bool(block.get("switches"))
    btn_declared = bool(block.get("buttons"))
    switches = (
        _match_native_port(block.get("switches") or {}, port_by_name, "in") if sw_declared else None
    )
    buttons = (
        _match_native_port(block.get("buttons") or {}, port_by_name, "in") if btn_declared else None
    )
    if sw_declared:
        (matched if switches is not None else problems).append(
            "sw" if switches is not None else "switches"
        )
    if btn_declared:
        (matched if buttons is not None else problems).append(
            "btn" if buttons is not None else "buttons"
        )

    # 7-seg (U22 relax + guard): matched when the design *declares* any of the
    # convention's seg-role ports, like switches/buttons post-U31 -- a design
    # that leaves the display alone runs with dark digits (exactly how an
    # unused leds_green/leds_rgb bank behaves).  The guard: declaring a strict
    # subset (a typo'd or partial seg interface) is a near-miss naming the
    # missing ports -- seg ports are *outputs*, so without this they would
    # silently fall to the unmapped-open rule and the display would stay dark.
    # Only considered when the board physically has a display (a convention's
    # seg block without one -- Sword's serial lines -- stays ordinary outputs).
    seven_seg: NativeSeg | None = None
    seg_ok = True
    board_seg = board_def.seven_seg
    if board_seg is not None:
        seg_block = block.get("seven_seg") or {}
        seg_role = _seg_role_port_names(seg_block)
        seg_declared = {n for n in seg_role if n in port_by_name}
        if seg_declared:
            seven_seg = _match_native_seg(seg_block, port_by_name)
            seg_ok = seven_seg is not None
            if seven_seg is not None:
                matched.append("seg")
            else:
                missing = sorted(seg_role - seg_declared)
                detail = f" (missing/mismatched: {', '.join(missing)})" if missing else ""
                problems.append(f"7-segment display{detail}")

    # Secondary LED bank (e.g. LEDG): captured when the design declares it, but
    # never required -- like the generic wrapper leaving `seg` dark, an unused
    # second bank does not block a match.
    leds_green: NativePort | None = None
    green = block.get("leds_green")
    if isinstance(green, dict):
        leds_green = _match_native_port(green, port_by_name, "out")

    # U31: a *default-less* input the convention does not map would be left
    # unbound in the wrapper's uut port map (an elaboration error), so a native
    # design that declares one is a near-miss.  An extra input carrying a default
    # expression is legal unassociated in both GHDL and NVC -- exactly as the
    # generic path allows one (`_check_parsed_contract`) -- so it does not block a
    # match.  Unmapped *outputs* are fine too: the wrapper leaves them `open`
    # (dark), as the DE0 example leaves its split-DP HEXn_DP scalars open.
    # (Names in port_by_name are already lowercased.)
    consumed = {clk_port.lower()} if clk_port is not None else set()
    for port in (leds, switches, buttons, leds_green, leds_rgb):
        if port is not None:
            consumed.update(n.lower() for n in port.names)
    if seven_seg is not None:
        consumed.update(n.lower() for n in seven_seg.names)
        if seven_seg.digit_enable is not None:
            consumed.update(n.lower() for n in seven_seg.digit_enable.names)
        if seven_seg.dp is not None:
            consumed.add(seven_seg.dp.lower())
    extra = sorted(
        n
        for n, d in port_by_name.items()
        if n not in consumed and d.mode == "in" and not d.has_default
    )
    if extra:
        problems.append(f"unmapped input port(s): {', '.join(extra)}")

    match: ConventionMatch | None = None
    if (
        clk_port is not None
        and (leds is not None or leds_rgb is not None)
        and (not sw_declared or switches is not None)
        and (not btn_declared or buttons is not None)
        and seg_ok
        and not extra
    ):
        match = ConventionMatch(
            maker=maker,
            board_name=board_def.name,
            clk=clk_port,
            leds=leds,
            switches=switches,
            buttons=buttons,
            seven_seg=seven_seg,
            leds_green=leds_green,
            leds_rgb=leds_rgb,
        )
    return _ConventionAttempt(maker, board_def.name, match, tuple(matched), tuple(problems))


# Convention match precedence.  Authoritative blocks -- vendor-canonical or
# hand-authored (``naming`` absent or ``"canonical"``) -- are tried before a
# ``"framework-derived"`` guess (U32), so ground-truth data added for a board
# later wins even if a port name overlaps a derived block.  A stable sort keyed
# on this rank alone leaves same-rank blocks in their on-disk order.
_CONVENTION_NAMING_RANK = {"canonical": 0, "framework-derived": 1}


def _convention_precedence(item: tuple[str, Any]) -> int:
    """Sort key: authoritative conventions before framework-derived ones."""
    _maker, block = item
    naming = block.get("naming", "canonical") if isinstance(block, dict) else "canonical"
    return _CONVENTION_NAMING_RANK.get(naming, 0)


def _best_convention_attempt(
    ports: list[_IfaceDecl],
    generics: list[_IfaceDecl],
    board_def: BoardDef | None,
) -> _ConventionAttempt | None:
    """Best board-native match attempt across the board's canonical conventions.

    Returns the first *full* match, else the closest near-miss, else None (no
    board / no conventions / the design is structurally a generic-contract one).
    Conventions are tried authoritative-first (see ``_CONVENTION_NAMING_RANK``).
    """
    if board_def is None or not board_def.port_conventions:
        return None
    # A design that declares the simulator's own sizing generics is a generic
    # design that failed the contract for some other reason -- not board-native.
    generic_names = {n for d in generics for n in d.names}
    if generic_names & _SIZING_GENERICS:
        return None
    port_by_name = {n: d for d in ports for n in d.names}
    best: _ConventionAttempt | None = None
    ordered = sorted(board_def.port_conventions.items(), key=_convention_precedence)
    for maker, block in ordered:
        if not isinstance(block, dict):
            continue
        # Schema: absent `naming` means canonical; only skip explicitly renamed
        # ("project-derived") blocks, whose names aren't the board's native ones.
        if block.get("naming", "canonical") == "project-derived":
            continue
        attempt = _attempt_convention(maker, block, board_def, port_by_name)
        if attempt.match is not None:
            return attempt
        if best is None or len(attempt.matched_roles) > len(best.matched_roles):
            best = attempt
    return best


def match_convention(
    ports: list[_IfaceDecl],
    generics: list[_IfaceDecl],
    board_def: BoardDef | None,
) -> ConventionMatch | None:
    """Recognize a board-native VHDL interface against *board_def*'s conventions.

    Pure (no I/O).  Returns a :class:`ConventionMatch` when the parsed toplevel
    interface fully matches one of the board's canonical port conventions by name
    + fixed width + direction (native designs use fixed widths, not NUM_*
    generics), else None.  This is the detection half of U21's board-native VHDL
    support; the wrapper that runs such a design lands in B3.
    """
    attempt = _best_convention_attempt(ports, generics, board_def)
    return attempt.match if attempt is not None else None


def _role_span(port: NativePort) -> str:
    """Compact port label for a native role, e.g. 'LEDR' or 'o_LED_1..o_LED_4'."""
    if len(port.names) == 1:
        return port.names[0]
    return f"{port.names[0]}..{port.names[-1]}"


def _native_convention_message(match: ConventionMatch, filename: str) -> str:
    """Info message for a design recognized as board-native (U21 B3: runs).

    ``check_vhdl_contract`` returns this with ``ok=True``; the launcher does not
    show it as an error, but it is carried on the result for the analysis spinner
    and session log (B3b) and for tests.
    """
    parts = [match.clk]
    if match.switches is not None:
        parts.append(_role_span(match.switches))
    if match.buttons is not None:
        parts.append(_role_span(match.buttons))
    if match.leds is not None:
        parts.append(_role_span(match.leds))
    if match.leds_rgb is not None:
        parts.append(_role_span(match.leds_rgb))
    if match.seven_seg is not None:
        segs = match.seven_seg.names
        span = segs[0] if len(segs) == 1 else f"{segs[0]}..{segs[-1]}"
        if match.seven_seg.style == "scan" and match.seven_seg.digit_enable is not None:
            span += f"+{match.seven_seg.digit_enable.names[0]}"  # e.g. CA..CG+AN
        parts.append(span)
    seg = "/seg" if match.seven_seg is not None else ""
    return (
        f"'{filename}' matches {match.board_name}'s board-native '{match.maker}' port "
        f"convention ({', '.join(parts)}); running it board-native — the simulator adapts "
        f"these to its clk/sw/btn/led{seg} boundary."
    )


def _near_miss_convention_message(attempt: _ConventionAttempt, filename: str) -> str:
    """User-facing message for a design that partially matches a board convention."""
    return (
        f"'{filename}' is close to {attempt.board_name}'s board-native '{attempt.maker}' "
        f"interface but does not fully match it "
        f"(missing/mismatched: {', '.join(attempt.problems)}).\n"
        "Fix those ports to run it board-native, or use the generic clk/sw/btn/led "
        "contract (see hdl/blinky.vhd)."
    )
