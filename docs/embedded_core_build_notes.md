# Embedded Core Systems — Build Notes

> Working log captured while implementing [`embedded_core_system_plan.md`](embedded_core_system_plan.md).
> Purpose: record concrete facts, gotchas, and working commands as each stage lands, so the
> [development guide](embedded_core_system_guide.md) can be finalized against reality at Stage 4.
> Not user-facing — fold the durable parts into the guide, then trim.

## Stage 0 — Vendor mx65 + smoke-test (DONE 2026-06-29)

**Upstream.** `github.com/Steve-Teal/mx65`, file `mx65.vhd`, pinned commit
`d65d81d4f8031e194bd8410133b9036db7e58794`. License **MIT** (Copyright (c) 2022 Steve Teal) — full
text in the repo's `LICENSE`; the core's own inline header carries only the copyright line, so the
vendored copy prepends the full MIT permission notice for compliance.

**Vendored to** `scripts/embedded_core/cores/mx65.vhd` = ASCII provenance+MIT header (32 lines) +
the upstream file byte-for-byte (995 lines) = **1027 lines**.

**Facts confirmed (corrected the plan + guide where they differed):**

- Size is **~995 lines**, not the "~650" the plan/guide originally claimed. *(Fixed in both docs.)*
- Libraries: `ieee.std_logic_1164` + `ieee.numeric_std` **only** — no Synopsys packages, no vendor
  primitives. Single `entity mx65` + one `architecture rtl`, **zero sub-component instantiations**
  (truly self-contained → nothing else to inline under the single-file rule).
- Ports exactly as the plan stated: `clock, reset, ce, data_in(7:0), data_out(7:0),
  address(15:0), rw, sync, nmi, irq`. No generics.
- The upstream repo also ships `ram.vhd`, `rom.vhd`, `uart.vhd`, `apple1.vhd` (an Apple-1 example
  system) — **not** vendored; we write our own `cpu_ram`/`cpu_rom` with the combinational-read
  timing the plan specifies.

**Analyzes clean under both simulators** (toolchain here: GHDL 7.0.0-dev on a 6.0.0 base;
NVC 1.22-devel):

```bash
ghdl -a --std=08   --workdir=<wd>      scripts/embedded_core/cores/mx65.vhd   # exit 0, no warnings
nvc  --work=work:<wd> --std=2008 -a    scripts/embedded_core/cores/mx65.vhd   # exit 0
```

- Benign NVC message: `directory <wd> already exists and is not an NVC library` appears when `<wd>`
  is pre-created (e.g. by `mkdtemp`); NVC then creates its library inside. Harmless (exit 0); the
  existing suite tolerates the same.

**Guide-worthy:**

- **Vendoring recipe:** prepend an ASCII comment block (provenance: repo URL + pinned commit; full
  MIT notice) and keep the core bytes verbatim. Verify the result is ASCII / no-BOM (the
  simulator's encoding gate, `check_vhdl_encoding`) *before* trusting it — non-ASCII bytes in a core
  would fail file selection in the UI.
- A bare core is analyzed with the backend's `analyze_cmd` **directly**, not via `analyze_vhdl()`
  (which also generates + elaborates the `sim_wrapper` and assumes the `clk/sw/btn/led` top contract
  the core doesn't have).

**Tests:** `tests/test_embedded_core.py` — file integrity (present, ASCII, MIT notice, pinned
commit, standard-IEEE-only) + `@pytest.mark.slow` analyze-under-GHDL/NVC. 6 tests, green.

**Still open for Stage 1** (the bus-timing unknowns from the plan's mx65 box — read out of the
architecture and confirm via waveform):

- which clock edge/phase mx65 samples `data_in` (decides combinational vs registered read);
- when `data_out`/`rw` are valid for writes;
- minimum reset pulse width before the reset-vector fetch;
- whether `ce='1'` tied permanently is fine.

## Stage 1 — Static bring-up system (DONE 2026-06-29)

**Result:** the single-file system `hdl/cpu_walking_counter_7seg.vhd` (banner + verbatim mx65 +
`cpu_rom` + `cpu_ram` + `cpu_io` + top, leaf-first, 1335 lines) **elaborates and runs under both
GHDL and NVC**, executing a hand-assembled static program. Observed: `led=0x1`,
`seg=0x3F3F3F3F` (every digit '0'), `num_segs=4`. All five Stage-1 exit-checklist items met —
the plan's #1 risk (bus read timing) is cleared.

**mx65 bus protocol (read out of the source — the key fact for the guide's *Bus read timing*
section):** mx65 is a textbook *synchronous* 6502 —

- `address` is **registered** (driven inside the clocked FSM; stable for the whole cycle);
- `data_out` / `rw` / `sync` are **combinational** concurrent assignments;
- **`data_in` is sampled on `rising_edge(clock)`** when `enable='1'` (`ir <= data_in` at T0,
  `dl <= data_in`, …), so the memory must present the byte *before* that edge;
- `reset` is **async, active-high**; on release the core runs an internal BRK-style sequence that
  fetches the reset vector from `$FFFC/D` (`reset_reg` gates writes off and steers `brk_vect` to
  `$FFFC`), clearing at state `BRK6`;
- `enable <= ce`, so `ce='1'` advances the core every clock.

⇒ **the read path (ROM/RAM/IO/mux) must be combinational** (address in → byte out same cycle).
Registered ("synchronous") memory would feed data a cycle late and the core would execute garbage.
This is exactly the plan's combinational-read decision — now confirmed against the source *and* by a
working run.

**POR:** a 3-bit counter holding reset ~7 clocks is sufficient — PC loaded from `$FFFC/D` first try;
no widening needed for mx65.

**Hand-assembled static program (26 bytes @ `$F800` — this is the guide's "hello LED" example):**
`SEI / CLD / LDX #$FF / TXS` ; `LDA #$01 / STA $E020` (LED0) ; `LDA $E005 / TAX / LDA #$3F` ;
`STA $E02F,X / DEX / BNE` (write '0' to all `NUM_SEGS` digits) ; `JMP self` ; `RTI` handler. Vectors
at `$FFFA/B` (NMI), `$FFFC/D` (RESET=`$F800`), `$FFFE/F` (IRQ/BRK) — all valid. Reading `NUM_SEGS`
from config reg `$E005` and looping proves the config-read path.

**Test-harness notes (guide / maintainer):**

- A bare core is analyzed directly; a *system* is run through the generated `sim_wrapper` via
  `analyze_vhdl(..., board_def=_7seg_board())` → elaborate → run, exactly like `test_7seg`. cocotb
  smoke module: `sim/test_cpu_smoke.py`.
- **cocotb runs under GHDL too**, not only NVC: `_GHDLBackend.run_cmd(... --vpi=...)` + `--stop-time`
  works. The existing suite only exercised NVC runs; both pass here.
- Registering a new `sim/test_*.py` cocotb module for the linters: add it to ruff `per-file-ignores`
  (`["ANN"]`) and the mypy `disallow_untyped_defs = false` override (so `dut` stays implicit `Any`),
  and give each test an **imperative-mood** docstring (the `D` rules still apply; D401).

### Firmware via cc65 (adopted 2026-06-29)

`cc65` (ca65 V2.18 / ld65 / cl65, plus `da65` disassembler, `od65`, `sim65`) is installed locally,
so firmware is **assembled with ca65/ld65** and the `.s` is checked in as first-class documentation
— no hand-assembly.

Pipeline: `firmware/cpu_walking_counter_7seg.s` (+ `cpu_6502.cfg`, an ld65 config: 2 KB ROM at
`$F800-$FFFF`, `CODE` at the base, `VECTORS` at `$FFFA`) → `ca65`/`ld65` →
`cpu_walking_counter_7seg.bin` (2 KB, **source of truth**, committed) →
`scripts/embedded_core/rom_to_vhdl.py` (sparse aggregate: non-zero bytes + `others => x"00"`) →
embedded into the VHDL ROM constant.

- **Validation:** the ca65/ld65 output was **byte-identical** to the Stage-1 hand-assembly
  (program bytes, interrupt vectors, and the full 2 KB) — confirming both the toolchain config and
  the earlier hand work.
- **Tests:** `test_embedded_rom_matches_firmware_bin` (the generated aggregate must appear verbatim
  in the `.vhd` — a drift guard), `test_firmware_bin_shape` (size + vectors), and
  `test_firmware_reassembles_with_ca65` (reassembly == `.bin`; **skips if `ca65` absent**, so cc65
  stays a dev-time tool, not a CI dependency).
- **Guide-worthy:** `da65 <bin>` disassembles for a cross-check; `ca65 -l` emits a source+bytes
  listing (great documentation). `sim65` is a standalone 6502 sim but models cc65's runtime I/O, not
  our MMIO (`$E020` …), so it can't exercise the IO firmware — GHDL/NVC running the real hardware
  model is the test path. The RESET vector low byte is `$00`, so it's omitted from the sparse
  aggregate and covered by `others` — a tidy example of why the sparse form is safe.

**Next (Stage 2):** write the walking-counter program in `firmware/cpu_walking_counter_7seg.s`
(prescaler-tick polling, bounce, BCD odometer with carry/borrow, `btn(0)` reverse, `btn(1)`
lamp-test, switch speed), assemble, and regenerate the ROM with `rom_to_vhdl.py`. The VHDL skeleton
(`cpu_rom`/`cpu_ram`/`cpu_io`/top, POR, mux, prescaler) and the ca65 pipeline are already in place,
so Stage 2 is firmware-only.
