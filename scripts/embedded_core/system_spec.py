"""SystemSpec: the board-independent description of an embedded-core system.

Parsed from a TOML file (see ``systems/*.toml``).  Carries the system name,
banner description, firmware stem, CPU plugin key, generic defaults, and the
memory map.  The memory map drives the ROM/RAM widths and the address slice;
the generics drive the VHDL generic defaults.
"""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on Python 3.10
    import tomli as tomllib

# Top of the CPU's 16-bit address space; every region must fit under it.
ADDRESS_SPACE_SIZE = 0x10000


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
        """Validate the interrupt-mode/IO-transport axes and the memory map."""
        if self.irq_mode not in IRQ_MODES:
            raise ValueError(f"irq_mode {self.irq_mode!r} not one of {IRQ_MODES}")
        if self.io_transport not in IO_TRANSPORTS:
            raise ValueError(f"io_transport {self.io_transport!r} not one of {IO_TRANSPORTS}")
        self._validate_regions()

    def _validate_regions(self) -> None:
        """Validate the memory map: power-of-two size, aligned base, in range, non-overlapping.

        ROM and RAM are always checked. IO is checked too *unless*
        ``io_transport == "port"``, in which case it names a region of the
        CPU's separate I/O space rather than the 64 KB memory map -- the
        committed port-IO specs legitimately place it "under" ROM (see guide
        §6).
        """
        regions = (
            [self.ram, self.rom] if self.io_transport == "port" else [self.ram, self.rom, self.io]
        )
        for region in regions:
            _ = region.addr_bits  # forces the power-of-two check now, not on first use
            if region.base % region.size != 0:
                raise ValueError(
                    f"region {region.name!r} base {region.base:#x} is not aligned to its "
                    f"size {region.size:#x}"
                )
            if region.base + region.size > ADDRESS_SPACE_SIZE:
                raise ValueError(
                    f"region {region.name!r} ({region.base:#x}..{region.base + region.size:#x}) "
                    f"extends past the {ADDRESS_SPACE_SIZE:#x} address space"
                )
        for a, b in itertools.combinations(regions, 2):
            a_end, b_end = a.base + a.size, b.base + b.size
            if a.base < b_end and b.base < a_end:
                raise ValueError(
                    f"regions {a.name!r} ({a.base:#x}..{a_end:#x}) and {b.name!r} "
                    f"({b.base:#x}..{b_end:#x}) overlap"
                )

    @property
    def irq_driven(self) -> bool:
        """True when an interrupt controller drives the CPU's IRQ line (any mode but 'none')."""
        return self.irq_mode != "none"


# Keys the loader accepts; anything else in a systems/*.toml is a load-time error
# (a typo like `irq_moed` must fail loudly, not silently fall back to a default).
_TOP_LEVEL_KEYS = frozenset(
    {"name", "firmware", "cpu", "description", "generics", "memory", "irq_mode", "io_transport"}
)
_MEMORY_KEYS = frozenset({"ram", "rom", "io"})
_REGION_KEYS = frozenset({"base", "size"})
_GENERIC_KEYS = frozenset(
    {"num_switches", "num_buttons", "num_leds", "num_segs", "counter_bits", "prescaler_bits"}
)


def _check_keys(data: dict[str, object], allowed: frozenset[str], context: str) -> None:
    """Raise ValueError naming any keys in ``data`` outside ``allowed``, for ``context``."""
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(
            f"unknown key(s) {sorted(unknown)} in {context}; allowed keys: {sorted(allowed)}"
        )


def load(path: str | Path) -> SystemSpec:
    """Load and validate a SystemSpec from a TOML file."""
    data = tomllib.loads(Path(path).read_text())
    _check_keys(data, _TOP_LEVEL_KEYS, "top level")
    mem = data["memory"]
    _check_keys(mem, _MEMORY_KEYS, "the 'memory' table")
    _check_keys(data["generics"], _GENERIC_KEYS, "the 'generics' table")

    def region(key: str) -> MemoryRegion:
        _check_keys(mem[key], _REGION_KEYS, f"'memory.{key}'")
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
