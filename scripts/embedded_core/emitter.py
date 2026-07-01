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
    # IRQ wiring (mx65's irq is active-low). Empty tokens keep the polled design
    # byte-identical; the IRQ variant exposes cpu_io.irq (= tick) and routes it in.
    if spec.irq_driven:
        tokens.update(
            IRQ_PORT=";\n    irq   : out std_logic  -- interrupt request (level)",
            INT_SIGNAL=(
                '\n  signal ier        : std_logic_vector(1 downto 0) := "00";'
                "\n  signal timer_flag : std_logic := '0';"
                "\n  signal input_flag : std_logic := '0';"
                "\n  signal prev_sw    : std_logic_vector(NUM_SWITCHES - 1 downto 0)"
                " := (others => '0');"
                "\n  signal prev_btn   : std_logic_vector(NUM_BUTTONS - 1 downto 0)"
                " := (others => '0');"
            ),
            INT_SENS=", ier, timer_flag, input_flag",
            INT_READ=(
                '\n      when x"11"  => rdata <= "000000" & ier;'
                '\n      when x"12"  => rdata <= "000000" & input_flag & timer_flag;'
            ),
            IRQ_LOGIC=(
                "\n\n"
                "  -- Interrupt controller: two sources (timer + sw/btn change).  Each has an\n"
                "  -- enable bit (IER $E011) and a flag bit (IFR $E012, write-1-to-clear); irq is\n"
                "  -- the OR of enabled+pending flags, and the ISR reads IFR to see who fired.\n"
                "  interrupts : process (clk) begin\n"
                "    if rising_edge(clk) then\n"
                "      prev_sw  <= sw;\n"
                "      prev_btn <= btn;\n"
                "      -- register writes first, so a same-cycle flag set (below) wins the race\n"
                "      if cs = '1' and we = '1' then\n"
                '        if addr = x"11" then\n'
                "          ier <= wdata(1 downto 0);\n"
                '        elsif addr = x"12" then\n'
                "          if wdata(0) = '1' then timer_flag <= '0'; end if;\n"
                "          if wdata(1) = '1' then input_flag <= '0'; end if;\n"
                "        end if;\n"
                "      end if;\n"
                "      -- flag sources (set wins over a simultaneous ack)\n"
                "      if prescaler = (prescaler'range => '1') then\n"
                "        timer_flag <= '1';\n"
                "      end if;\n"
                "      if sw /= prev_sw or btn /= prev_btn then\n"
                "        input_flag <= '1';\n"
                "      end if;\n"
                "    end if;\n"
                "  end process;\n"
                "\n"
                "  irq <= (timer_flag and ier(0)) or (input_flag and ier(1));"
            ),
            IO_IRQ_DECL="\n  signal io_irq   : std_logic;",
            CPU_IRQ="not io_irq",
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
            CPU_IRQ="'0'",
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
