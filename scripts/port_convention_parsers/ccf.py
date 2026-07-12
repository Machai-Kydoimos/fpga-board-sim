"""Parser for Cologne Chip GateMate ``.ccf`` constraint files.

Matches ``Net "name" Loc = "pin";`` and the directional forms ``Pin_in``/
``Pin_out``/``Pin_inout "name" Loc = "pin" | ATTR;`` (GateMate's own format
comment documents pipe-separated attributes such as ``SCHMITT_TRIGGER``,
``PULLUP``, ``PULLDOWN`` after the location — ignored here the same way UCF's
pipe-separated attributes are). No clock-frequency statement was found in any
fetched GateMate file, so :attr:`~port_convention_parsers.types.PortTable.clocks`
is always empty.
"""

from __future__ import annotations

import re

from port_convention_parsers.types import PinEntry, PortTable

_RE_PIN = re.compile(
    r'(?:Net|Pin_in|Pin_out|Pin_inout)\s+"([^"]+)"\s+Loc\s*=\s*"([^"]+)"', re.IGNORECASE
)


def parse(text: str) -> PortTable:
    """Extract every ``Net``/``Pin_in``/``Pin_out``/``Pin_inout`` pin from a CCF file's text."""
    pins: list[PinEntry] = []
    for line in text.splitlines():
        m = _RE_PIN.search(line)
        if m:
            pins.append(PinEntry(port=m.group(1), pin=m.group(2)))
    return PortTable(pins=tuple(pins))
