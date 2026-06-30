"""Emitter: assemble a single-file embedded-core VHDL design.

Concatenates, leaf-first: a generated banner, the vendored CPU core (verbatim),
then the ROM / RAM / IO / top blocks rendered from the templates in
``templates/``.  The ROM block's constant is produced from the firmware ``.bin``
by :func:`embedded_core.rom_to_vhdl.rom_aggregate`.
"""

from __future__ import annotations

from pathlib import Path

from .cpu_plugin import CpuPlugin
from .rom_to_vhdl import rom_aggregate
from .system_spec import SystemSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"
_RULER = "-- " + "=" * 75

# Inserted between the vendored core and the first generated block.
_SYSTEM_HEADER = (
    "\n"
    f"{_RULER}\n"
    "-- System blocks (generated).  The mx65 core above is vendored verbatim.\n"
    f"{_RULER}\n"
    "\n"
)


def _banner_description(description: str) -> str:
    """Render the spec description as VHDL comment lines (a blank line -> '--')."""
    return "\n".join(f"-- {line}" if line else "--" for line in description.split("\n"))


def _fill(template: str, tokens: dict[str, str]) -> str:
    for key, value in tokens.items():
        template = template.replace(f"@@{key}@@", value)
    return template


def emit(spec: SystemSpec, plugin: CpuPlugin, rom_bytes: bytes) -> str:
    """Return the complete single-file VHDL design as text."""
    g = spec.generics
    tokens = {
        "NAME": spec.name,
        "FIRMWARE": spec.firmware,
        "CORE_ENTITY": plugin.entity_name,
        "DESCRIPTION": _banner_description(spec.description),
        "NUM_SWITCHES": str(g["num_switches"]),
        "NUM_BUTTONS": str(g["num_buttons"]),
        "NUM_LEDS": str(g["num_leds"]),
        "NUM_SEGS": str(g["num_segs"]),
        "COUNTER_BITS": str(g["counter_bits"]),
        "PRESCALER_BITS": str(g["prescaler_bits"]),
        "ROM_BITS": str(spec.rom.addr_bits),
        "RAM_BITS": str(spec.ram.addr_bits),
        "ADDR_HIGH": str(spec.addr_high),
        "ROM_AGGREGATE": rom_aggregate(rom_bytes),
    }

    def block(name: str) -> str:
        return _fill((_TEMPLATES / name).read_text(), tokens)

    result = "".join(
        [
            block("banner.vhd.tmpl"),
            "\n",
            plugin.core_vhdl_text(),
            _SYSTEM_HEADER,
            block("cpu_rom.vhd.tmpl"),
            block("cpu_ram.vhd.tmpl"),
            block("cpu_io.vhd.tmpl"),
            block("top.vhd.tmpl"),
        ]
    )
    if "@@" in result:
        raise ValueError("unfilled template token(s) remain in generated VHDL")
    return result
