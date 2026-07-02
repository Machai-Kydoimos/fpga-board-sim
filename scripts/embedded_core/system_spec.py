"""SystemSpec: the board-independent description of an embedded-core system.

Parsed from a TOML file (see ``systems/*.toml``).  Carries the system name,
banner description, firmware stem, CPU plugin key, generic defaults, and the
memory map.  The memory map drives the ROM/RAM widths and the address slice;
the generics drive the VHDL generic defaults.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib


@dataclass(frozen=True)
class MemoryRegion:
    """A power-of-two address region in the CPU's memory map."""

    name: str
    base: int
    size: int

    @property
    def addr_bits(self) -> int:
        """Address bits the region spans (``size`` must be a power of two)."""
        if self.size & (self.size - 1) or self.size == 0:
            raise ValueError(f"region '{self.name}' size {self.size:#x} is not a power of two")
        return self.size.bit_length() - 1

    @property
    def select_low(self) -> int:
        """Lowest CPU address bit that is constant across the region."""
        return self.addr_bits

    def select_literal(self, address_bits: int = 16) -> str:
        """VHDL literal for the region's constant high bits (hex if nibble-aligned)."""
        width = address_bits - self.select_low
        prefix = self.base >> self.select_low
        if width % 4 == 0:
            return f'x"{prefix:0{width // 4}X}"'
        return '"' + format(prefix, f"0{width}b") + '"'


# Interrupt-dispatch modes and IO transports the generator understands.  Values
# are validated on construction; some are declared here but implemented in a
# later stage (the emitter guards the not-yet-built ones):
#   irq_mode:     none = polled; simple = one fixed-vector handler (6502 IRQ /
#                 Z80 IM 1); vectored = Z80 IM 2 (per-source vector on the bus).
#   io_transport: memory = memory-mapped registers; port = Z80 IN/OUT via IORQ.
IRQ_MODES = ("none", "simple", "vectored")
IO_TRANSPORTS = ("memory", "port")


@dataclass(frozen=True)
class SystemSpec:
    """A parsed ``systems/*.toml`` system specification."""

    name: str
    firmware: str
    cpu: str
    description: str
    generics: dict[str, int]
    ram: MemoryRegion
    rom: MemoryRegion
    io: MemoryRegion
    irq_mode: str = "none"  # interrupt dispatch: none | simple | vectored (see IRQ_MODES)
    io_transport: str = "memory"  # register transport: memory | port (see IO_TRANSPORTS)

    def __post_init__(self) -> None:
        """Validate the interrupt-mode and IO-transport axes against their value sets."""
        if self.irq_mode not in IRQ_MODES:
            raise ValueError(f"irq_mode {self.irq_mode!r} not one of {IRQ_MODES}")
        if self.io_transport not in IO_TRANSPORTS:
            raise ValueError(f"io_transport {self.io_transport!r} not one of {IO_TRANSPORTS}")

    @property
    def irq_driven(self) -> bool:
        """True when an interrupt controller drives the CPU's IRQ line (any mode but 'none')."""
        return self.irq_mode != "none"

    @property
    def addr_high(self) -> int:
        """Top index of the ROM/RAM address slice the top wires to the CPU."""
        return max(self.rom.addr_bits, self.ram.addr_bits) - 1


def load(path: str | Path) -> SystemSpec:
    """Load and validate a SystemSpec from a TOML file."""
    data = tomllib.loads(Path(path).read_text())
    mem = data["memory"]

    def region(key: str) -> MemoryRegion:
        return MemoryRegion(name=key, base=int(mem[key]["base"]), size=int(mem[key]["size"]))

    return SystemSpec(
        name=str(data["name"]),
        firmware=str(data["firmware"]),
        cpu=str(data["cpu"]),
        description=str(data["description"]),
        generics={k: int(v) for k, v in data["generics"].items()},
        ram=region("ram"),
        rom=region("rom"),
        io=region("io"),
        irq_mode=str(data.get("irq_mode", "none")),
        io_transport=str(data.get("io_transport", "memory")),
    )
