# Embedded-core firmware

6502 assembly programs for the single-file embedded-core systems (`hdl/cpu_*.vhd`), assembled with
[cc65](https://cc65.github.io/)'s `ca65` assembler and `ld65` linker. The 6502 source *is* the
documentation for what the CPU does on the board.

## Files

| File | Role |
|------|------|
| `cpu_walking_counter_7seg.s` | 6502 source: the walking counter (bouncing one-hot LED + BCD odometer; `btn(0)` reverse, `btn(1)` lamp test, switch speed) |
| `cpu_6502.cfg` | ld65 config: a 2 KB ROM at `$F800-$FFFF` with CPU vectors at `$FFFA` |
| `cpu_walking_counter_7seg.bin` | assembled 2 KB ROM image — **the source of truth**, embedded into the VHDL |

## Assemble

```bash
ca65 --cpu 6502 -o cpu_walking_counter_7seg.o cpu_walking_counter_7seg.s
ld65 -C cpu_6502.cfg -o cpu_walking_counter_7seg.bin cpu_walking_counter_7seg.o
```

Add `-l cpu_walking_counter_7seg.lst` to the `ca65` line for a source+address+bytes listing, or run
`da65 cpu_walking_counter_7seg.bin` to disassemble the image as a cross-check.

## Embed into the VHDL

The single-file rule means the bytes live inside the VHDL ROM constant. Regenerate that aggregate
from the `.bin` and paste it into `constant ROM : rom_t := ( ... );` in
`hdl/cpu_walking_counter_7seg.vhd`:

```bash
uv run python scripts/embedded_core/rom_to_vhdl.py firmware/cpu_walking_counter_7seg.bin
```

## Notes

- `cc65` is a **dev-time** tool, not a CI dependency: the `.bin` is committed, so reassembly is only
  needed when the `.s` changes (the reassembly test skips when `ca65` is absent).
- The IO register addresses in the `.s` equates (`LED_LO`, `CFG_SEGS`, `SEG_BASE`, …) must match the
  `cpu_io` address decode in the VHDL.
