"""Parser for Lattice/Trellis ``.lpf`` constraint files (ECP5 boards).

Matches ``LOCATE COMP "name" SITE "pin";``. The companion ``IOBUF PORT "name"
IO_TYPE=...;`` lines carry no site/pin and are simply not matched (nothing to
extract). A clock's frequency, when stated, comes from ``FREQUENCY PORT
"name" N MHZ;``.
"""

from __future__ import annotations

import re

from port_convention_parsers.types import ClockConstraint, PinEntry, PortTable

_RE_LOCATE = re.compile(r'LOCATE\s+COMP\s+"([^"]+)"\s+SITE\s+"(\w+)"')
_RE_FREQUENCY = re.compile(r'FREQUENCY\s+PORT\s+"([^"]+)"\s+([\d.]+)\s*MHZ', re.IGNORECASE)


def parse(text: str) -> PortTable:
    """Extract every ``LOCATE COMP ... SITE`` pin and any ``FREQUENCY PORT`` clock."""
    pins: list[PinEntry] = []
    clocks: list[ClockConstraint] = []
    for line in text.splitlines():
        m = _RE_LOCATE.search(line)
        if m:
            pins.append(PinEntry(port=m.group(1), pin=m.group(2)))
            continue
        freq_m = _RE_FREQUENCY.search(line)
        if freq_m:
            mhz = float(freq_m.group(2))
            if mhz > 0:
                clocks.append(ClockConstraint(port=freq_m.group(1), frequency_hz=mhz * 1e6))
    return PortTable(pins=tuple(pins), clocks=tuple(clocks))
