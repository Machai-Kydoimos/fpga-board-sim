"""Parser for Xilinx Vivado ``.xdc`` constraint files.

Matches both the combined ``-dict`` form and the separate-line form, e.g.::

    set_property -dict { PACKAGE_PIN W5 IOSTANDARD LVCMOS33 } [get_ports { clk }]
    set_property PACKAGE_PIN W5 [get_ports clk]

Two gotchas proven in the wild (see the fixtures in the test module):

- ``PACKAGE_PIN`` values are sometimes quoted (``PACKAGE_PIN "H4"``, seen on
  Numato's Mimas A7) and sometimes bare (``PACKAGE_PIN N3``) *in the same
  file* — the pin regex tolerates optional quotes on either side.
- Digilent's published "master" XDC files comment out every single line with
  a leading ``#`` (the user is expected to uncomment what they need). Every
  regex here is applied with :func:`re.search`, not an anchored match, so a
  leading ``#`` (or any other prefix) never prevents a line from matching.

``create_clock`` lines give a period in nanoseconds, converted to Hz.
"""

from __future__ import annotations

import re

from port_convention_parsers.types import ClockConstraint, PinEntry, PortTable

_PIN = r'"?(\S+?)"?'
_DICT_PREFIX = rf"set_property\s+-dict\s*\{{[^}}]*?PACKAGE_PIN\s+{_PIN}\s[^}}]*\}}\s*"
_SEPARATE_PREFIX = rf"set_property\s+PACKAGE_PIN\s+{_PIN}\s*"
_CLOCK_PREFIX = r"create_clock\s+.*?-period\s+([\d.]+).*?"
# Split braced/bare forms rather than making the brace optional in one pattern:
# an optional-brace version back-references ambiguously when the port name
# itself contains ``]`` (e.g. ``{sw[0]}``), since a non-greedy port capture
# can stop at the port's own bracket instead of the surrounding one.
_PORTS_BRACED = r"\[get_ports\s+\{([^}]+)\}\s*\]"
_PORTS_BARE = r"\[get_ports\s+([\w\[\]]+)\s*\]"

_RE_DICT_BRACED = re.compile(_DICT_PREFIX + _PORTS_BRACED)
_RE_DICT_BARE = re.compile(_DICT_PREFIX + _PORTS_BARE)
_RE_SEPARATE_BRACED = re.compile(_SEPARATE_PREFIX + _PORTS_BRACED)
_RE_SEPARATE_BARE = re.compile(_SEPARATE_PREFIX + _PORTS_BARE)
_RE_CLOCK_BRACED = re.compile(_CLOCK_PREFIX + _PORTS_BRACED)
_RE_CLOCK_BARE = re.compile(_CLOCK_PREFIX + _PORTS_BARE)


def parse(text: str) -> PortTable:
    """Extract every ``PACKAGE_PIN``/port pair and any ``create_clock`` period."""
    pins: list[PinEntry] = []
    clocks: list[ClockConstraint] = []
    for line in text.splitlines():
        m = (
            _RE_DICT_BRACED.search(line)
            or _RE_DICT_BARE.search(line)
            or _RE_SEPARATE_BRACED.search(line)
            or _RE_SEPARATE_BARE.search(line)
        )
        if m:
            pins.append(PinEntry(port=m.group(2).strip(), pin=m.group(1)))
            continue
        clk_m = _RE_CLOCK_BRACED.search(line) or _RE_CLOCK_BARE.search(line)
        if clk_m:
            period_ns = float(clk_m.group(1))
            if period_ns > 0:
                clocks.append(
                    ClockConstraint(port=clk_m.group(2).strip(), frequency_hz=1e9 / period_ns)
                )
    return PortTable(pins=tuple(pins), clocks=tuple(clocks))
