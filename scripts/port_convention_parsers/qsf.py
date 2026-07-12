"""Parser for Intel/Altera Quartus ``.qsf`` pin-assignment files.

Matches ``set_location_assignment PIN_x -to name[idx]``. Quartus project files
also carry ``set_global_assignment -name DEVICE ...`` / ``-name
DEVICE_FILTER_PACKAGE ...`` lines; neither uses ``set_location_assignment``, so
they never collide with port extraction here (device identification is a
board-metadata concern handled elsewhere, not this module's job). QSF files
have no clock-frequency statement (that lives in a separate ``.sdc``), so
:attr:`~port_convention_parsers.types.PortTable.clocks` is always empty.
"""

from __future__ import annotations

import re

from port_convention_parsers.types import PinEntry, PortTable

_RE_LOCATION = re.compile(r"set_location_assignment\s+PIN_(\S+)\s+-to\s+(\S+)")


def parse(text: str) -> PortTable:
    """Extract every ``PIN_x -to name`` pair from a QSF file's text."""
    pins: list[PinEntry] = []
    for line in text.splitlines():
        m = _RE_LOCATION.search(line)
        if m:
            pins.append(PinEntry(port=m.group(2), pin=m.group(1)))
    return PortTable(pins=tuple(pins))
