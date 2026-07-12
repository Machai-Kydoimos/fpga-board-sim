r"""Parser for Gowin IDE ``.cst`` constraint files (Sipeed Tang Nano/Primer/Mega).

Matches ``IO_LOC "name" pin;``. Gowin pins are bare numbers (package-relative
pin IDs, not ball/site letters), which the generic ``\w+`` capture handles
the same as any other dialect's pin token. The companion ``IO_PORT "name"
PULL_MODE=... DRIVE=...;`` lines carry no location and are simply not
matched. CST has no clock-frequency statement, so
:attr:`~port_convention_parsers.types.PortTable.clocks` is always empty.
"""

from __future__ import annotations

import re

from port_convention_parsers.types import PinEntry, PortTable

_RE_IO_LOC = re.compile(r'IO_LOC\s+"([^"]+)"\s+(\w+)')


def parse(text: str) -> PortTable:
    """Extract every ``IO_LOC name pin`` pair from a CST file's text."""
    pins: list[PinEntry] = []
    for line in text.splitlines():
        m = _RE_IO_LOC.search(line)
        if m:
            pins.append(PinEntry(port=m.group(1), pin=m.group(2)))
    return PortTable(pins=tuple(pins))
