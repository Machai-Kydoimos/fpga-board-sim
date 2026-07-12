"""Parser for IceStorm/nextpnr ``.pcf`` physical-constraint files (iCE40 boards).

Matches ``set_io [-nowarn] name pin``, tab- or space-separated, with an
optional trailing ``# comment`` (ignored — matching stops at the pin token).
PCF has no clock-frequency statement, so
:attr:`~port_convention_parsers.types.PortTable.clocks` is always empty.

No polarity keyword exists in the format itself, but some boards encode it in
the port name: ICEBreaker's ``.pcf`` names active-low pins with a trailing
``_N`` (``BTN_N``, ``LEDR_N``) — :mod:`classify` picks this convention up
generically (any dialect's port name may carry it), not this module.
"""

from __future__ import annotations

import re

from port_convention_parsers.types import PinEntry, PortTable

_RE_SET_IO = re.compile(r"set_io\s+(?:-nowarn\s+)?(\S+)\s+(\S+)")


def parse(text: str) -> PortTable:
    """Extract every ``set_io name pin`` pair from a PCF file's text."""
    pins: list[PinEntry] = []
    for line in text.splitlines():
        m = _RE_SET_IO.search(line)
        if m:
            pins.append(PinEntry(port=m.group(1), pin=m.group(2)))
    return PortTable(pins=tuple(pins))
