"""CPU core plugins for the embedded-core generator.

A :class:`CpuPlugin` bundles what the emitter needs about a vendored CPU core:
its VHDL source (one or more files, concatenated leaf-first) and a *bus adapter*
-- a self-contained VHDL ``block`` that plugs the core into the design's
normalized bus (``cpu_addr`` / ``cpu_din`` / ``cpu_dout`` / ``cpu_we`` /
``cpu_reset`` (active-high) / ``cpu_irq_req`` (active-high)), translating reset
polarity, the write strobe, and the interrupt line to the core's real pins.

Adding a new core = vendor its VHDL under ``cores/`` and write one adapter under
``adapters/``; nothing else in the generator changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_CORES = Path(__file__).resolve().parent / "cores"
_ADAPTERS = Path(__file__).resolve().parent / "adapters"


@dataclass(frozen=True)
class CpuPlugin:
    """A vendored CPU core plus its normalized-bus adapter."""

    name: str  # registry key and --cpu value
    entity_name: str  # the core entity the adapter instantiates
    core_files: tuple[Path, ...]  # vendored VHDL, leaf-first (emitted verbatim)
    adapter_file: Path  # normalized-bus adapter block
    vectored_adapter_file: Path | None = None  # variant for vectored interrupts (Z80 IM 2)
    port_adapter_file: Path | None = None  # variant for port-mapped IO (Z80 IN/OUT via IORQ)
    vectored_port_adapter_file: Path | None = None  # variant for IM 2 + port-mapped IO
    address_bits: int = 16
    data_bits: int = 8
    reset_active_high: bool = True  # mx65: high; T80: RESET_n is active-low
    irq_active_high: bool = False  # both mx65 and T80 interrupt on a low line
    boots_at_zero: bool = False  # Z80 boots at $0000; 6502 fetches a reset vector
    endian: str = "little"

    def core_vhdl_text(self) -> str:
        """Return the vendored core VHDL, files concatenated leaf-first."""
        return "\n".join(f.read_text() for f in self.core_files)

    def adapter_vhdl(self, vectored: bool = False, port: bool = False) -> str:
        """Return the normalized-bus adapter block for this core.

        ``vectored`` selects the interrupt-mode-2 adapter (drives a vector onto the
        data bus during INTA); ``port`` selects the port-mapped-IO adapter (exposes
        MREQ/IORQ so the decode can split memory and I/O space).  The core must
        provide the matching adapter file.
        """
        if vectored and port:
            if self.vectored_port_adapter_file is None:
                raise ValueError(f"core {self.name!r} has no vectored + port-IO adapter")
            return self.vectored_port_adapter_file.read_text()
        if vectored:
            if self.vectored_adapter_file is None:
                raise ValueError(f"core {self.name!r} has no vectored-interrupt adapter")
            return self.vectored_adapter_file.read_text()
        if port:
            if self.port_adapter_file is None:
                raise ValueError(f"core {self.name!r} has no port-mapped-IO adapter")
            return self.port_adapter_file.read_text()
        return self.adapter_file.read_text()


MX65 = CpuPlugin(
    name="mx65",
    entity_name="mx65",
    core_files=(_CORES / "mx65.vhd",),
    adapter_file=_ADAPTERS / "mx65.vhd",
)

_T80 = _CORES / "t80"
T80 = CpuPlugin(
    name="t80",
    entity_name="T80s",
    core_files=tuple(
        _T80 / f"{stem}.vhd"
        for stem in ("T80_Pack", "T80_ALU", "T80_MCode", "T80_Reg", "T80", "T80s")
    ),
    adapter_file=_ADAPTERS / "t80.vhd",
    vectored_adapter_file=_ADAPTERS / "t80_vectored.vhd",
    port_adapter_file=_ADAPTERS / "t80_port.vhd",
    vectored_port_adapter_file=_ADAPTERS / "t80_vectored_port.vhd",
    reset_active_high=False,
    boots_at_zero=True,
)

PLUGINS: dict[str, CpuPlugin] = {MX65.name: MX65, T80.name: T80}


def get_plugin(name: str) -> CpuPlugin:
    """Look up a CPU plugin by name, or exit with a clear error."""
    try:
        return PLUGINS[name]
    except KeyError:
        known = ", ".join(sorted(PLUGINS))
        raise SystemExit(f"unknown CPU plugin '{name}'; known plugins: {known}") from None
