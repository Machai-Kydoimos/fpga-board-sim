# Embedded-core firmware

Assembly programs for the single-file embedded-core systems (`hdl/mx65_*.vhd`, `hdl/t80_*.vhd`):
6502 sources (`.s`) for the mx65 core, Z80 sources (`.asm`) for the T80 core. The source *is* the
documentation for what the CPU does on the board -- read it alongside `docs/embedded_core_system_guide.md`.

## Files

| File | Core | Role |
|------|------|------|
| `mx65_walking_counter_7seg.s` / `.bin` | 6502 | Walking counter: bouncing one-hot LED + BCD odometer; `btn(0)` reverses, `btn(1)` is a lamp test, switches speed it up |
| `mx65_irq_counter_7seg.s` / `.bin` | 6502 | Same behavior, but interrupt-driven -- the ISR acks the timer/input flags with a write-1-to-clear on IFR (`$E012`) |
| `mx65_hello_7seg.s` / `.bin` | 6502 | The newcomer on-ramp: light LED0, show "0" on digit 0, then hold forever (~20 lines) |
| `mx65_dice_7seg.s` / `.bin` | 6502 | Peripheral-extension worked example: `btn(0)` reads a free-running LFSR register and rolls a 1-6 die onto digit 0 + the LEDs. Also has an unequal ROM (2 KB) / RAM (1 KB) map |
| `t80_walking_counter_7seg.asm` / `.bin` | Z80 | The walking counter on the T80, memory-mapped IO |
| `t80_irq_counter_7seg.asm` / `.bin` | Z80 | IM 2 vectored interrupts -- timer and input dispatch to separate ISRs via the vector table |
| `t80_portio_counter_7seg.asm` / `.bin` | Z80 | Port-mapped IO -- registers reached with `IN`/`OUT` instead of loads/stores |
| `t80_irq_portio_counter_7seg.asm` / `.bin` | Z80 | Capstone: IM 2 vectored interrupts **and** port-mapped IO together |
| `mx65.cfg` | 6502 | Shared `ld65` linker config: a 2 KB ROM at `$F800-$FFFF` with CPU vectors at `$FFFA` |

Each `.bin` is the assembled ROM image and **is the source of truth** -- it is what actually gets
embedded into the committed `hdl/*.vhd`, not the `.s`/`.asm` alongside it. The reassembly tests
(`tests/test_embedded_core.py::test_firmware_reassembles_with_{ca65,z80asm}`) and the generator's
byte-for-byte golden tests are what guard against the two drifting apart.

## Assembling

Both toolchains are **dev-time only** -- the `.bin` is committed, so reassembly is only needed when
a `.s`/`.asm` changes, and CI never needs either (the reassembly tests skip when the tool is absent).

### 6502: ca65 + ld65 ([cc65](https://cc65.github.io/))

```bash
ca65 --cpu 6502 -o mx65_walking_counter_7seg.o mx65_walking_counter_7seg.s
ld65 -C mx65.cfg -o mx65_walking_counter_7seg.bin mx65_walking_counter_7seg.o
```

Substitute the stem for `mx65_irq_counter_7seg`, `mx65_hello_7seg`, or `mx65_dice_7seg` to build those. Add
`-l <stem>.lst` to the `ca65` line for a source+address+bytes listing, or run `da65 <stem>.bin` to
disassemble the image as a cross-check.

### Z80: z88dk's `z80asm`

```bash
z80asm -b -o t80_walking_counter_7seg.bin t80_walking_counter_7seg.asm
```

`-b` selects a raw binary image; z88dk's `z80asm` glues its value directly to `-o` (no space).
Substitute the stem for any of the other three `t80_*` sources. Run from inside `firmware/` (or copy
the `.asm` to a scratch directory first) -- z88dk's `z80asm` drops `.obj`/`.sym` byproducts next to
its input (gitignored, but keep the tree clean).

**Version note:** this project uses **z88dk's** Z80 Module Assembler (Fedora package `z88dk`, binary
`z80asm`; tested against 2.7.1o). A *different*, unrelated assembler from the z80pack project is also
commonly named `z80asm` -- if `z80asm -b -o<out> <file>` errors on unrecognized flags, you likely have
the wrong one installed.

## Workflow

1. Edit the `.s`/`.asm` source.
2. Assemble it (above) to refresh the `.bin`.
3. `uv run python scripts/regen_embedded_cores.py --write` -- regenerates every `hdl/*.vhd` whose
   `.bin` changed (`rom_to_vhdl.py` is an internal helper the generator calls; there is no manual
   paste-the-aggregate step).
4. `uv run pytest` -- the reassembly and golden tests confirm the new `.bin` and the regenerated
   `.vhd` agree.

## Notes

- The IO register addresses in a source's equates (`LED_LO`, `CFG_SEGS`, `SEG_BASE`, …) must match
  the `cpu_io` address decode in the VHDL -- see guide §6 for the register map.
- Starting your own firmware: copy `mx65_hello_7seg.s`, `systems/mx65_hello_7seg.toml`, and the
  assemble command above, then follow the guide's "Quickstart" box.
