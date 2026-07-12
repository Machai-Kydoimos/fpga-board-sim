"""Parser for Xilinx BoardStore ``part0_pins.xml`` files (KC705/KCU105/ZCU102/...).

This dialect is genuine, well-formed XML (Apache-2.0 licensed), so it is
parsed with :mod:`xml.etree.ElementTree` rather than regex — every other
dialect in this package is a line-oriented vendor-specific syntax with no
standard grammar, which is why those use regex, but XML already has a real
parser available. That choice also makes a superficial "gotcha" a non-issue:
some BoardStore files write ``name ="X"`` with a space before ``=``, which
looks unusual next to ``name="X"`` but is perfectly valid, standard XML (the
spec allows optional whitespace on either side of ``=`` in an attribute) — a
naive ``name="([^"]+)"`` regex would miss it, but ``Element.get("name")``
handles it transparently.

No clock-frequency data appears in this format (it is pure pin-location
data), so :attr:`~port_convention_parsers.types.PortTable.clocks` is always
empty.
"""

from __future__ import annotations

from xml.etree import ElementTree

from port_convention_parsers.types import PinEntry, PortTable


def parse(text: str) -> PortTable:
    """Extract every ``<pin name=... loc=.../>`` from a BoardStore XML file's text.

    Every other dialect module in this package degrades gracefully on
    unparsable input (a regex simply matches nothing); ``ElementTree`` does
    not share that behavior and raises on malformed XML, so that case is
    caught here to keep the contract the same across all eight modules --
    a truncated or non-XML fetch (e.g. a redirected error page) yields an
    empty table rather than propagating a parser-internal exception.
    """
    pins: list[PinEntry] = []
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return PortTable()
    for pin_el in root.iter("pin"):
        name = pin_el.get("name")
        loc = pin_el.get("loc")
        if name and loc:
            pins.append(PinEntry(port=name, pin=loc))
    return PortTable(pins=tuple(pins))
