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

**Result:** the single-file system `hdl/mx65_walking_counter_7seg.vhd` (banner + verbatim mx65 +
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

Pipeline: `firmware/mx65_walking_counter_7seg.s` (+ `mx65.cfg`, an ld65 config: 2 KB ROM at
`$F800-$FFFF`, `CODE` at the base, `VECTORS` at `$FFFA`) → `ca65`/`ld65` →
`mx65_walking_counter_7seg.bin` (2 KB, **source of truth**, committed) →
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

## Stage 2 — Walking-counter firmware (DONE 2026-06-29)

**Result:** `firmware/mx65_walking_counter_7seg.s` now holds the full walking counter — assembled to
~310 bytes of code + glyph table (`$F800-$F934`; `irq_handler` RTI at `$F92A`, `DECLUT` at `$F92B`)
— and the system reproduces `hdl/walking_counter_7seg.vhd` end to end. The new behavioral suite
`sim/test_cpu_walking.py` (4 cocotb tests) passes **`PASS=4` under both NVC and GHDL**: digits are
0-9 glyphs and the odometer advances, the LED is always one-hot and bounces, `btn(0)` reverses the
count direction, and `btn(1)` lights every lamp. **Firmware-only as planned** — it worked on the
first simulation attempt (only the harness `--stop-time` needed raising); Stage-1 bring-up had
de-risked the bus/IO/tick paths.

**6502 implementation (the readable `.s` is the documentation):** zero-page state (POS, FWD, CNT_UP,
PREVBTN, LAMP, SKIP_VAL/SKIPCNT, cached N_LEDS/N_SEGS, BCD[0..7] one digit/byte); subroutines
`bounce` / `bcd_inc` / `bcd_dec` / `onehot` / `calc_skip` (so JSR/RTS exercise the stack too). One-hot
LED = `1 << POS` built with `ASL ONEHOT_LO / ROL ONEHOT_HI`; BCD ripple via per-digit `CMP #10` /
borrow; switch speed = `SKIP = max(1, 8 >> popcount(SW))` (each switch doubles the rate, matching
the reference RTL now that #133 fixed its `base - n*2` quadrupling bug). Main loop = poll tick,
edge-detect `btn(0)`, sample `btn(1)`, recompute SKIP, step every SKIP-th tick, render (lamp-test
override else one-hot + glyphs).

**Tick path confirmed (first functional exercise of the prescaler):** the firmware's read-to-clear
poll of `$E010` works, including the "set wins over a simultaneous clear" rule in `cpu_io` — no
missed or doubled ticks across the run.

**Guide-worthy (test harness):**

- **`PRESCALER_BITS` is *not* forwarded by `sim_wrapper`** — the wrapper only passes the contract
  generics (NUM_*/COUNTER_BITS). So headless runs always use the design's default tick (1024 clocks
  ≈ 41 us at the 40 ns wrapper period); you can't speed ticks up via generics. Instead **drive all
  switches high** so `SKIP=1` and the firmware steps on *every* tick — that bounds sim time.
- **All `@cocotb.test()`s in a module share one simulation; sim time is cumulative.** `--stop-time`
  must exceed the *sum* of every test's awaits, or a later test is killed mid-`Timer` (the failure I
  hit first: 100 us stop-time truncated the very first 287 us wait → all four "failed"). Sized the
  suite to ~3.6 ms and set `--stop-time=6000000ns`.
- **Assert `PASS=N` (not just `PASS=`)** in the runner — `"FAIL=0" and "PASS="` is a false pass when
  *zero* tests run (the summary still reads `PASS=0 FAIL=0`). `PASS=4` pins the real count.
- **Measure the odometer, not the LED, to test `btn(0)` direction** — the LED bounces on its own at
  the ends, which confounds a direction probe. Read the decimal value and warm up well clear of zero
  so the post-reverse decrement window can't underflow/wrap.
- Metavalue `TO_INTEGER` warnings appear **only at `0ms+0`** (ROM/RAM address undriven before the
  CPU starts) — expected, benign (the plan's metavalue-hygiene note); the run is clean thereafter.
- The Stage-1 smoke (`sim/test_cpu_smoke.py`, static program) was **deleted** — superseded by the
  walking suite, which subsumes its checks (it would fail against the dynamic ROM anyway).

## Stage 3 — The generator (DONE 2026-06-30)

**Result:** `scripts/gen_embedded_core.py` + the `scripts/embedded_core/` package now **reproduce the
Stage-2 file byte-for-byte** from inputs. Running

```bash
uv run python scripts/gen_embedded_core.py --cpu mx65 \
    --system systems/mx65_walking_counter_7seg.toml \
    --rom firmware/mx65_walking_counter_7seg.bin --out hdl/mx65_walking_counter_7seg.vhd
```

emits a file that differs from the hand-written one **only** in the banner/separator (now marked
*generated*, "do not edit by hand"); everything else — the 1027-line vendored core, all four blocks,
the ROM aggregate — is identical. The committed `.vhd` is now the generator's output; regenerate on
any firmware/spec change.

**Pieces (mirror the `sim_wrapper_template.vhd` + validate-then-write idiom):**

- `cpu_plugin.py` — `CpuPlugin` dataclass (`mx65`): `core_vhdl_text()` returns the vendored core
  verbatim; carries entity name, bus geometry, reset convention, vectors (the seam for T65 later).
- `system_spec.py` — `SystemSpec` + `MemoryRegion` from a TOML file; the memory map's power-of-two
  sizes derive `ROM_BITS`/`RAM_BITS`/address slice and the decode literals (`select_literal()`).
- `emitter.py` — concatenates banner + verbatim core + `cpu_rom`/`cpu_ram`/`cpu_io`/`top` templates,
  substituting `@@TOKEN@@`s; injects the ROM aggregate from the `.bin` (the live input); rejects any
  unfilled token.
- `templates/*.vhd.tmpl` — the hand-written blocks, **sed-extracted as exact line ranges** then
  tokenized only where the spec/ROM drive a scalar (generics, bits, names, aggregate) → byte-exact.
- `systems/mx65_walking_counter_7seg.toml` — name, banner description, generics, and memory map.

**Tests added (`tests/test_embedded_core.py`, now 17):** `test_generator_cli_reproduces_committed_design`
(byte-for-byte golden via the real CLI — the drift guard), `..._passes_contract_and_lists_all_entities`
(five entities + `check_vhdl_contract`), `test_memory_map_drives_widths_and_decode` (spec derives the
ROM/RAM widths + decode literals, which then appear in the output).

**Guide-worthy:**

- **Templatize by extraction, not transcription.** `sed -n 'A,Bp'` the exact block ranges into
  `*.tmpl`, then tokenize *only* the spec/ROM-driven scalars. The diff oracle (`diff committed gen`)
  converges fast; the only intended diff is the "generated" banner. The vendored core is emitted via
  `CpuPlugin.core_vhdl_text()` (never templatized).
- **Don't generate aligned VHDL you can keep literal.** The three decode lines (`= x"E0"`,
  `= "00000"`, `= "11111"`) stay literal in `top.vhd.tmpl`; the spec's memory map *derives* them
  (`MemoryRegion.select_literal`, hex if nibble-aligned else binary) and a test asserts they match —
  so the spec is authoritative without the generator hand-rolling column alignment.
- **Validate before writing.** The CLI writes to a temp file **named `<spec.name>.vhd`** (so the
  entity==filename contract check passes) and runs `check_vhdl_encoding` + `check_vhdl_contract`
  before committing bytes to `--out`.
- **TOML on the 3.10 floor:** `tomllib` (3.11+) with a `tomli` fallback guard; the banner description
  is stored as prose and the emitter prefixes each line as a `--` comment (blank line -> bare `--`).
- **Deferred to growth (documented, not built):** generating the `cpu_io` register cases / IO layout
  from the spec (v1 keeps `cpu_io` a template; the spec carries the memory map, not per-register
  layout); `CpuPlugin.instantiation()` (the mx65 port map is literal in `top`); a second core (T65).

**Next (Stage 4):** finalize the dev guide, add 2/4/6-digit GIF captures, update `CLAUDE.md`.

## Stage 4 — Generic-sizing captures + docs (DONE 2026-06-30)

**Result:** the one generated design is captured running on **2/4/6-digit boards** (proving generic
sizing), and the surrounding docs are wired up. The three GIFs (`docs/assets/cpu_walk_{2,4,6}digit.gif`)
were produced with `scripts/capture_demo.py --scenario plain --vhdl hdl/mx65_walking_counter_7seg.vhd
--sim nvc --switches 0 --step-ns 336000 --every 1 --frames 48` on **StepMXO2 (2)**, **DE0 (4)**, and
**DE10-Lite (6)** — all 10-LED boards, so the trio differs *only* in digit count. The firmware reads
`CFG_LEDS`/`CFG_SEGS` at cold-start and drives exactly that many; verified by eye (a one-hot LED
bounce and an advancing odometer at each digit count).

**Bug found and fixed (`sim/capture_frames.py`):** the `plain` capture scenario drove `sw` but
**left `btn` undriven** → `'U'`. A button-reading design (the embedded CPU) latched that garbage and
rendered the all-on lamp-test state, frozen, on every frame. The `snake` scenario already drove
`btn=0`; `plain` didn't. Fix: `_run_plain` now sets `dut.btn.value = 0` (released) when the board has
buttons. *Guide-worthy:* a headless capture must drive **every** input to a defined level — an
undriven contract port is `'U'`, and metavalue-sensitive designs render garbage, not blank.

**Limitation found (worth a card if it bites again):** boards with **0 switches** (e.g. `nandland_go`,
the plan's intended 2-digit board) **cannot be elaborated headless** — the contract generics are
`positive` (min 1), so `NUM_SWITCHES=0` fails with *"value 0 outside of POSITIVE range"*. This is
true for *any* design, not just the embedded core. Swapped in `step_mxo2` (2-digit, 4 switches) for
the 2-digit capture. (Relaxing the generics to `natural` would allow null vectors but is a
contract-wide change; deferred.)

**Capture tuning:** `--switches 0` is the portable choice (works on switch-less *and* switch-ful
boards; firmware then uses `SKIP_BASE=8`, stepping every 8 ticks). At `PRESCALER_BITS=10` (≈41 µs/
tick, 40 ns clock) one step ≈ 8 ticks ≈ 328 µs, so `--step-ns 336000 --every 1` advances ≈ one step
per frame; 48 frames shows several bounces + the odometer climbing.

**Docs updated:** `CLAUDE.md` (Key Files rows for `gen_embedded_core.py` / `embedded_core/` /
`systems/` / `firmware/` / the generated `.vhd`; a new *Embedded CPU systems* subsection in the VHDL
Design Contract covering the single-file family + `PRESCALER_BITS`); the dev guide §12 (generic-sizing
GIF table; `.asm`→`.s` fixes; the checked-in `.s` is the annotated listing); the plan's stage list
marked 0–4 ✅.

**Stages 0–4 complete.** Remaining: **Stage 5** (IRQ-driven variant; a second core; customasm path)
and **VSG/P7** (now triggered — the generator emits VHDL).

## Stage 5 (part 1) — Interrupt-driven variant + two-source controller (DONE 2026-07-01)

**Result:** a second generated design, `hdl/mx65_irq_counter_7seg.vhd`, drives the *same* walking
counter from **interrupts** instead of a polling loop — and runs `PASS=4` under **both GHDL and NVC**
(the existing `sim/test_cpu_walking.py` suite, unchanged). Produced by the generator from a new
`irq_driven = true` spec flag (`systems/mx65_irq_counter_7seg.toml`) + `firmware/mx65_irq_counter_7seg.s`.

**Two-source interrupt controller (user-requested; the realistic version).** `cpu_io` gains a small
controller with **two sources** multiplexed onto the CPU's single IRQ line:

- **timer** (IFR bit0) — the prescaler tick; paces the animation.
- **input** (IFR bit1) — any `sw`/`btn` change, **edge-detected in hardware** (`prev_sw`/`prev_btn`
  registers); the user acted, so re-read the controls.

Registers: **IER** (`$E011`, enable per source) and **IFR** (`$E012`, flag per source, read = status,
**write-1-to-clear** = ack). `irq <= (timer_flag and ier(0)) or (input_flag and ier(1))`. The ISR
**reads IFR to see who fired** and dispatches — the genuine "which peripheral interrupted?" step.
Clean split of work: the *timer* ISR advances + renders; the *input* ISR re-samples controls
(btn0 edge → reverse, `LAMP` = btn1 level, recompute switch speed). Firmware: `SEI` during init,
clear IFR, write IER, `CLI`; ISR saves A/X/Y, dispatches, acks, `RTI`.

**Facts / guide-worthy:**

- **mx65's `irq` is active-low** (`irq_ready <= not (reset_reg or irq or i)`), so the top wires
  `irq => not io_irq`. (This is the first thing a different core changes — captured for the guide.)
- **Flag process orders "clear then set"** so a tick arriving on the same cycle as its ack is not
  lost (set wins) — the same race the polled `$E010` tick already handled.
- The generator stays **byte-for-byte on the polled design**: all IRQ wiring is conditional tokens
  (`IRQ_PORT` / `INT_SIGNAL` / `INT_SENS` / `INT_READ` / `IRQ_LOGIC` in `cpu_io`; `IO_IRQ_DECL` /
  `CPU_IRQ` / `IO_IRQ_CONN` in the top) that are empty for `irq_driven = false`. The polled golden
  test still passes unchanged.
- The **same** `test_cpu_walking` suite verifies both designs: the tests drive `sw`/`btn`, which now
  fire *input* interrupts (sampling the controls) while *timer* interrupts run the animation — so
  identical observable behavior, different plumbing.

**Tests added:** `test_cpu_irq_runs_nvc` / `_ghdl` (walking suite, `PASS=4`) and a byte-for-byte
golden (`test_generator_reproduces_irq_design`). Suite: 20 embedded-core tests green.

## Stage 5 (part 2) — Second core (Z80/T80) + normalized-bus refactor (DONE 2026-07-01)

**Result:** `hdl/t80_walking_counter_7seg.vhd` runs the *same* walking counter on a **Z80** —
`PASS=4` under GHDL + NVC via the unchanged `sim/test_cpu_walking.py`. The full how-to is folded into
the [guide](embedded_core_system_guide.md) (§3–§4); this is the terse log.

- **Refactor (the seam):** a **normalized bus** (`cpu_addr`/`cpu_din`/`cpu_dout`/`cpu_we`/`cpu_reset`/
  `cpu_irq_req`, all active-high) that ROM/RAM/IO/decode speak, plus a per-core **adapter** `block`
  (`adapters/<core>.vhd`) translating it to the core's pins. The **decode is generated from the spec
  memory map**. mx65 designs regenerated (bytes re-pinned, behavior identical); `CpuPlugin` gained
  multi-file cores + the adapter.
- **T80** (`cores/t80/`, BSD-3, pinned `f7f776b`, 6 files leaf-first): one patch to the vendored
  bytes — `std_logic_unsigned` → `numeric_std_unsigned` in T80.vhd/T80s.vhd — makes it analyze under
  both sims with **no `-fsynopsys`** (T80 uses no `std_logic_arith`-only helpers).
- **Z80 map/firmware:** boots at **`$0000`** → ROM low, RAM `$8000`, IO `$E000` (memory-mapped;
  `IORQ_n` open). `firmware/t80_walking_counter_7seg.asm` via z88dk `z80asm` (`-b -o<bin>`, `org 0`,
  `defc NAME = value`), same algorithm as the 6502 with `HL`/`DE` pointers + `DJNZ` loops. Adapter:
  `cpu_we <= not WR_n and not MREQ_n`, `RESET_n <= not cpu_reset`, `INT_n <= not cpu_irq_req`.
- **The bug — read-to-clear vs multi-cycle reads.** The Z80 rendered nothing; a debug LED marker
  before the poll loop proved it **executes from reset** — so the **POR is fine** for the T80. The
  `$E010` tick was **read-to-clear**: fine for the 6502's 1-cycle read, but the Z80's *multi-cycle*
  read clears it on the first clock, before the core samples it → the poll loop hangs. Fixed to
  **write-to-clear** (poll to check, write to ack); touched `cpu_io` + both polled firmwares (the
  mx65 `sta TICK` shifted the vectors → `bin_shape` test updated). Guide lesson §4.5.
- **Naming:** per-core designs are `<core>_*` (`mx65_*`, `t80_*`); shared infra keeps `cpu_`
  (`cpu_io`/`cpu_rom`/`cpu_ram`, `cpu_plugin`, `sim/test_cpu_walking.py`).
- **Tests:** T80 runs (nvc + ghdl) + a byte-for-byte golden + 6 T80 vendored-integrity tests;
  embedded-core suite now **29 green**.

**Stage 5 parts 1–2 done.** Continued below with the Z80 feature axes.

## Stage 5 (parts 3–5) — Z80 interrupt-mode + IO-transport axes (DONE 2026-07-02)

**Result:** two spec axes and three new committed Z80 designs, each running the shared
`test_cpu_walking` suite (`PASS=4`) under GHDL + NVC; full embedded-core suite **44 green**. The
durable how-to is folded into the [guide](embedded_core_system_guide.md) (§4.6, §6, §9); terse log:

- **Axes (byte-identical to prior designs).** `irq_mode` (none/simple/vectored) generalizes the old
  `irq_driven` bool (kept as a property); `io_transport` (memory/port) is new. Both validated in
  `SystemSpec.__post_init__`; the emitter guards unbuilt combos. The mx65 IRQ spec migrated
  `irq_driven = true` → `irq_mode = "simple"`; all prior goldens stay green.
- **IM 2 (vectored) — `t80_irq_counter_7seg`.** During INTA (`M1_n & IORQ_n` low) the `t80_vectored`
  adapter muxes a per-source vector onto `DI`; cpu_io priority-encodes it (timer `$00`, input `$02`).
  Firmware: `I=$01`, page-aligned table at `$0100`, `IM 2`, two ISRs (no IFR dispatch). The emitter's
  vectored branch adds the `irq_vec` port/encoder + `io_irq_vec` wiring.
- **Port IO — `t80_portio_counter_7seg`.** The IO register file moves to the Z80 I/O space; the
  `t80_port` adapter exposes MREQ/IORQ, and the decode qualifies ROM/RAM by MREQ + takes `sel_io` from
  IORQ (a `BUS_CTRL_DECL` token declares the two signals). `cpu_io` is unchanged — firmware swaps
  loads/stores for `IN`/`OUT` (C-indexed `OUT` for the segment ports).
- **Capstone — `t80_irq_portio_counter_7seg`.** IM 2 **and** port IO together (the original goal).
  `M1_n` separates the two IORQ uses, so it needed only the combined `t80_vectored_port` adapter and
  **no emitter change** — the vectored + port token sets already compose.
- **Repo hygiene:** untracked leaked z80asm byproducts (`.obj`/`.sym`) and ignored `.obj/.sym/.map`.

Interrupt (none/simple/vectored) × transport (memory/port) matrix complete for the T80; six committed
designs across two cores.

**Stages 0–5 fully done** (IRQ + second core + both Z80 axes + capstone). Parked: VSG/P7 and the rest
of Stage 5 (a third core, e.g. T65; customasm).
