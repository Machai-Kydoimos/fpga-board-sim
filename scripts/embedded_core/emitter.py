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
    "-- System blocks (generated).  The CPU core above is vendored verbatim.\n"
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


def _frag(name: str, *, prefix: str = "\n") -> str:
    """Load a template fragment, prefixed for splicing into a Python-string token.

    Fragments hold multi-line VHDL bodies as readable ``.vhd.frag`` files
    (not standalone-analyzable VHDL -- see the P7/VSG exclusion list) instead
    of Python string literals. ``prefix`` supplies the leading blank line(s)
    the splice site expects; the trailing newline from the file read is
    stripped so the caller controls what follows.
    """
    return prefix + (_TEMPLATES / "fragments" / name).read_text().rstrip("\n")


def _decode(spec: SystemSpec) -> str:
    """Generate the address-decode lines from the system memory map.

    Memory-mapped IO uses three address windows (RAM / IO / ROM).  Port-mapped IO
    qualifies the ROM/RAM windows with a memory request (MREQ) and takes the IO
    select straight from the I/O cycle (IORQ), which the adapter exposes.
    """
    if spec.io_transport == "port":
        mem = [
            f"  {sel} <= '1' when cpu_mreq = '1' and "
            f"cpu_addr(15 downto {region.select_low}) = {region.select_literal()} else '0';"
            for region, sel in ((spec.ram, "sel_ram"), (spec.rom, "sel_rom"))
        ]
        return "\n".join([*mem, "  sel_io  <= cpu_iorq;"])
    lines = [
        f"  {sel} <= '1' when cpu_addr(15 downto {region.select_low}) "
        f"= {region.select_literal()} else '0';"
        for region, sel in ((spec.ram, "sel_ram"), (spec.io, "sel_io"), (spec.rom, "sel_rom"))
    ]
    return "\n".join(lines)


def emit(spec: SystemSpec, plugin: CpuPlugin, rom_bytes: bytes) -> str:
    """Return the complete single-file VHDL design as text."""
    if len(rom_bytes) > spec.rom.size:
        rom_end = spec.rom.base + spec.rom.size
        raise ValueError(
            f"firmware image is {len(rom_bytes)} bytes, which does not fit in the "
            f"{spec.rom.size}-byte 'rom' region ({spec.rom.base:#x}..{rom_end:#x})"
        )
    if plugin.boots_at_zero:
        if spec.rom.base != 0:
            raise ValueError(
                f"core {plugin.name!r} boots at $0000, so its 'rom' region must start at 0x0 "
                f"(got {spec.rom.base:#x}) -- see guide §6, put ROM where the core boots"
            )
    else:
        rom_top = spec.rom.base + spec.rom.size
        if rom_top != 0x10000:
            raise ValueError(
                f"core {plugin.name!r} fetches its reset vector from the top of memory, so its "
                f"'rom' region must end at 0x10000 (got {rom_top:#x}) -- see guide §6, "
                "put ROM where the core boots"
            )

    vectored = spec.irq_mode == "vectored"
    port_io = spec.io_transport == "port"
    g = spec.generics
    tokens = {
        "NAME": spec.name,
        "FIRMWARE": spec.firmware,
        "DESCRIPTION": _banner_description(spec.description),
        "ASM_TOOLCHAIN": plugin.asm_toolchain,
        "ASM_EXT": plugin.asm_ext,
        "NUM_SWITCHES": str(g["num_switches"]),
        "NUM_BUTTONS": str(g["num_buttons"]),
        "NUM_LEDS": str(g["num_leds"]),
        "NUM_SEGS": str(g["num_segs"]),
        "COUNTER_BITS": str(g["counter_bits"]),
        "PRESCALER_BITS": str(g["prescaler_bits"]),
        "ROM_BITS": str(spec.rom.addr_bits),
        "RAM_BITS": str(spec.ram.addr_bits),
        "ROM_ADDR_HIGH": str(spec.rom.addr_bits - 1),
        "RAM_ADDR_HIGH": str(spec.ram.addr_bits - 1),
        "ROM_AGGREGATE": rom_aggregate(rom_bytes),
        "DECODE": _decode(spec),
        "CPU_ADAPTER": plugin.adapter_vhdl(vectored=vectored, port=port_io).rstrip("\n"),
        "BUS_CTRL_DECL": (
            "\n  signal cpu_mreq : std_logic;  -- memory request (Z80 MREQ)"
            "\n  signal cpu_iorq : std_logic;  -- I/O cycle (Z80 IORQ)"
            if port_io
            else ""
        ),
    }
    # IRQ wiring. Empty tokens keep the polled design byte-identical.  irq_driven
    # designs wire cpu_io's interrupt controller to the CPU; the vectored (Z80 IM 2)
    # variant also exports a per-source vector byte the adapter drives during INTA.
    if spec.irq_driven:
        tokens.update(
            INT_SIGNAL=_frag("irq_signals.vhd.frag"),
            INT_SENS=", ier, timer_flag, input_flag",
            INT_READ=_frag("irq_read.vhd.frag"),
            CPU_IRQ_REQ="io_irq",
        )
        irq_logic = _frag("irq_logic.vhd.frag", prefix="\n\n")
        if vectored:
            tokens.update(
                IRQ_PORT=(
                    ";\n    irq     : out std_logic;"
                    "\n    irq_vec : out std_logic_vector(7 downto 0)"
                ),
                IRQ_LOGIC=irq_logic + _frag("irq_vec.vhd.frag", prefix="\n\n"),
                IO_IRQ_DECL=(
                    "\n  signal io_irq     : std_logic;"
                    "\n  signal io_irq_vec : std_logic_vector(7 downto 0);"
                ),
                IO_IRQ_CONN=",\n      irq     => io_irq,\n      irq_vec => io_irq_vec",
            )
        else:
            tokens.update(
                IRQ_PORT=";\n    irq   : out std_logic  -- interrupt request (level)",
                IRQ_LOGIC=irq_logic,
                IO_IRQ_DECL="\n  signal io_irq   : std_logic;",
                IO_IRQ_CONN=",\n      irq   => io_irq",
            )
    else:
        tokens.update(
            IRQ_PORT="",
            INT_SIGNAL="",
            INT_SENS="",
            INT_READ="",
            IRQ_LOGIC="",
            IO_IRQ_DECL="",
            CPU_IRQ_REQ="'0'",
            IO_IRQ_CONN="",
        )

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
