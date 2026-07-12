"""Parser for legacy Xilinx ISE ``.ucf`` constraint files.

Matches ``NET "name" LOC = "pin" | ATTR | ATTR;`` (attributes are pipe-separated
and ignored here — the regex only needs the part up to the pin). Two real-world
gotchas confirmed by fetched boards:

- The pin value is sometimes quoted (``LOC = "H17"``) and sometimes bare
  (``LOC=F7``, no surrounding spaces even) in the same board family.
- Vector port names appear in at least three conventions: bracketed
  (``"MOSI[0]"``, common), parenthesized (``"TMDS(0)"``), and the classic
  XST/ISE-generated angle-bracket form (``"led<0>"``). None need special
  handling here since the whole quoted string becomes ``port`` verbatim;
  :mod:`classify` is what later strips whichever bracket style wraps the index.

A clock's frequency, when stated, comes from a ``TIMESPEC ... = PERIOD "name"
N MHz ...;`` line.
"""

from __future__ import annotations

import re

from port_convention_parsers.types import ClockConstraint, PinEntry, PortTable

_RE_NET_LOC = re.compile(r'NET\s+"([^"]+)"\s+LOC\s*=\s*"?(\w+)"?')
_RE_PERIOD = re.compile(r'PERIOD\s+"([^"]+)"\s+([\d.]+)\s*MHz', re.IGNORECASE)


def parse(text: str) -> PortTable:
    """Extract every ``NET ... LOC`` pin and any ``TIMESPEC``/``PERIOD`` clock."""
    pins: list[PinEntry] = []
    clocks: list[ClockConstraint] = []
    for line in text.splitlines():
        m = _RE_NET_LOC.search(line)
        if m:
            pins.append(PinEntry(port=m.group(1), pin=m.group(2)))
            continue
        period_m = _RE_PERIOD.search(line)
        if period_m:
            mhz = float(period_m.group(2))
            if mhz > 0:
                clocks.append(ClockConstraint(port=period_m.group(1), frequency_hz=mhz * 1e6))
    return PortTable(pins=tuple(pins), clocks=tuple(clocks))
