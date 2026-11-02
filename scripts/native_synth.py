"""The interface a board-native design written to one convention block declares.

``fpga_sim.conventions.match_convention`` asks whether a design's parsed
interface matches one of a board's port conventions.  This is the inverse:
given one convention block, build the interface -- the ``_IfaceDecl`` records
``_parse_toplevel_interface`` would return -- of a design written to it, so a
test or a generator can put every convention on disk to the matcher without a
VHDL file per board.

Shared by ``tests/test_native_convention.py`` (every canonical board matches
its own interface; no cross-board match flips polarity) and
``scripts/gen_board_design_matrix.py`` (one minimal design per native bank).
Pure: no I/O and no board loading.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fpga_sim.vhdl_interface import _IfaceDecl


def synth_interface(block: Mapping[str, Any]) -> list[_IfaceDecl]:
    """Return the ports a native design for *block* declares.

    Banks are declared the way the matcher reads them: a ``names`` cluster as
    one scalar port per name, a ``name`` + ``width`` bank as one vector of that
    literal width.  A role the block omits is left out, so a partial convention
    (buttons only, from an XDC sync) yields an interface that never fully
    matches.  To ask about a subset of the roles, pass a block holding only
    those keys.
    """
    ports: list[_IfaceDecl] = []
    if isinstance(block.get("clk"), str):
        ports.append(_IfaceDecl([block["clk"].lower()], "in", False, None))

    def add(role: str, mode: str) -> None:
        m = block.get(role)
        if not isinstance(m, dict):
            return
        if m.get("names"):
            ports.extend(_IfaceDecl([str(n).lower()], mode, False, None) for n in m["names"])
        elif "name" in m and "width" in m:
            ports.append(_IfaceDecl([str(m["name"]).lower()], mode, False, int(m["width"])))

    add("leds", "out")
    add("switches", "in")
    add("buttons", "in")
    add("leds_green", "out")
    # The RGB channel bank (U38): scalar outputs in (r, g, b) order per site.
    add("leds_rgb", "out")
    # The other LED banks (U56 Phase 6) are alternatives: aliases of the LEDs the
    # primary bank already drives, which together would drive an LED twice.  A
    # block with no primary bank declares its first one, for the LED floor; to ask
    # about any one of them, pass a block holding only that bank.
    banks = block.get("led_banks")
    if not isinstance(block.get("leds"), dict) and isinstance(banks, list) and banks:
        first = banks[0]
        if first.get("names"):
            ports.extend(_IfaceDecl([str(n).lower()], "out", False, None) for n in first["names"])
        elif "name" in first and "width" in first:
            ports.append(
                _IfaceDecl([str(first["name"]).lower()], "out", False, int(first["width"]))
            )
    ss = block.get("seven_seg")
    if isinstance(ss, dict):
        style = ss.get("style")
        if style == "individual" and ss.get("names"):
            # One width_per_digit-bit vector port per digit (HEX0..n).
            wpd = int(ss["width_per_digit"])
            ports.extend(_IfaceDecl([str(n).lower()], "out", False, wpd) for n in ss["names"])
        elif style == "scan":
            # U22 physical scan interface: shared segment lines (one vector or
            # per-segment scalars) + digit_enable vector + optional dp scalar.
            if ss.get("names"):
                ports.extend(_IfaceDecl([str(n).lower()], "out", False, None) for n in ss["names"])
            elif "name" in ss:
                ports.append(
                    _IfaceDecl([str(ss["name"]).lower()], "out", False, int(ss["width_per_digit"]))
                )
            if isinstance(ss.get("dp"), str):
                ports.append(_IfaceDecl([ss["dp"].lower()], "out", False, None))
            en = ss.get("digit_enable")
            if isinstance(en, dict) and "name" in en and "width" in en:
                ports.append(_IfaceDecl([str(en["name"]).lower()], "out", False, int(en["width"])))
        elif style == "serial" and ss.get("names"):
            # Shift-register lines (Sword's sseg_clk/sseg_en/sseg_sdo): scalar
            # outputs; the style carries no width_per_digit.
            ports.extend(_IfaceDecl([str(n).lower()], "out", False, None) for n in ss["names"])
    return ports
