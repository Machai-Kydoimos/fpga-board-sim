"""CPU core plugins for the embedded-core generator.

A :class:`CpuPlugin` bundles the facts the generator needs about a soft CPU
core: its vendored VHDL text, the entity to instantiate, bus geometry, reset
convention, and reset/IRQ/NMI vectors.  v1 ships one plugin (``mx65``); the
dataclass is the seam for adding more cores (e.g. T65) later.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_CORES = Path(__file__).resolve().parent / "cores"


@dataclass(frozen=True)
class CpuPlugin:
    """Everything the emitter needs to know about a vendored CPU core."""

    name: str  # registry key, e.g. "mx65"
    entity_name: str  # VHDL entity the top instantiates
    core_file: Path  # vendored, verbatim VHDL (emitted first)
    address_bits: int = 16
    data_bits: int = 8
    reset_active_high: bool = True
    reset_async: bool = True
    has_ce: bool = True
    endian: str = "little"
    reset_vector: int = 0xFFFC
    irq_vector: int = 0xFFFE
    nmi_vector: int = 0xFFFA

    def core_vhdl_text(self) -> str:
        """Return the vendored core VHDL verbatim (placed first in the output)."""
        return self.core_file.read_text()


MX65 = CpuPlugin(name="mx65", entity_name="mx65", core_file=_CORES / "mx65.vhd")

PLUGINS: dict[str, CpuPlugin] = {MX65.name: MX65}


def get_plugin(name: str) -> CpuPlugin:
    """Look up a CPU plugin by name, or exit with a clear error."""
    try:
        return PLUGINS[name]
    except KeyError:
        known = ", ".join(sorted(PLUGINS))
        raise SystemExit(f"unknown CPU plugin '{name}'; known plugins: {known}") from None
