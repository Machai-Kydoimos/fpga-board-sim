# Embedded Core Systems — Implementation Plan

> **Companion:** [`embedded_core_system_guide.md`](embedded_core_system_guide.md) — the user-facing
> development guide for building these systems.
> **Status:** approved 2026-06-29. This plan and the guide were split from the approved planning
> doc and are intended to be executed without re-deriving anything.

## Context

Today the simulator runs **fixed-function example HDL** (`hdl/blinky*.vhd`, `hdl/counter_7seg.vhd`, `hdl/walking_counter_7seg.vhd`, `hdl/snake_7seg.vhd`): each design *is* the behavior, hand-written in VHDL. We want to go a level up — generate a **single self-contained `.vhd`** that embeds a **soft-core CPU + an IO subsystem (wired to the board's sw/btn/led/seg) + embedded RAM + embedded ROM**, where the ROM holds **machine code assembled from an assembly-language program** (including authentic cold-start init). The CPU then does the *sensing and output through its IO interface*, instead of the behavior being baked into RTL.

The first concrete target is a **6502** system (using the **mx65** core) running a program that reproduces **`walking_counter_7seg.vhd`** — chosen over the free-running `counter_7seg` because it has **constant on-screen action**: a bouncing LED, a ticking decimal odometer, button-driven direction reversal, a lamp-test, and switch-controlled speed. That exercises the *full* IO loop (read `sw`/`btn`, write `led`/`seg`). Once the slice works, we extract a **reusable generator** and write the **development guide**, to reuse later for other CPUs (T65/65C02) and other programs.

**Why staged this way:** all the technical risk lives in the concrete system (does mx65 elaborate under GHDL/NVC, does an internal power-on reset work against a clk-only wrapper, is sim throughput enough to drive visible motion, do the reset vectors land). Proving that first makes the generator + guide mostly refactoring + documentation of a thing that already runs. *(Confirmed direction with the user — we expect to learn from the slice and feed it into the generalization.)*

### Decisions locked (with the user)

| Topic | Decision |
|---|---|
| Sequencing | **6502 slice first**, then extract generator, then write guide |
| CPU core (v1) | **mx65** (MIT, single-file, `numeric_std`-clean). T65 = documented alternative + future multi-unit test case |
| Assembler | **Not a project dependency.** Generator boundary = **ROM image** (bytes + load addr + vectors). Assemble with an external tool, check in `.asm` + assembled bytes + the exact command |
| First firmware | Replicate **`walking_counter_7seg.vhd`** *behaviors and glyphs* (not cycle-exact timing): bouncing one-hot LED + BCD decimal odometer; `btn(0)` reverses LED walk **and** count direction; `btn(1)` lamp-test; each active switch **doubles** the step rate (a chosen approximation — see *Demo firmware*) |
| Cold-start | **Authentic** 6502 boot (reset vector, SP init, `CLD`, `SEI`, valid IRQ/NMI/BRK vectors + handlers); guide generalizes per-CPU requirements + shortcuts |
| Timing | Hardware **prescaler tick**, CPU **polls** (read-to-clear) for v1; **IRQ-driven** variant later for compare/contrast; guide covers both |
| VHDL params | **Generic-parameterized** (symbolic `NUM_*`) so one generated file runs on every board; firmware reads board sizes from **config registers** and renders accordingly |
| Audience | Students/end-users **and** maintainers → two-layer guide (concepts + mechanics) |

### Hard constraints (confirmed from the codebase)

1. **Single file only.** `src/fpga_sim/sim_bridge.py` analyzes exactly *one* user `.vhd` (`ghdl -a --std=08` / `nvc --std=2008 -a`) + the auto-generated wrapper. → the whole system (CPU + ROM + RAM + IO + top) must be **one file**, multiple entities/architectures.
2. **Contract is a lenient whole-file text scan** (`sim_bridge.py` ~330–378): requires one `entity <stem> is` matching the filename, and the tokens `clk/sw/btn/led` to appear *somewhere*. mx65's differently-named ports (`clock/reset/ce/...`) don't interfere.
3. **Top entity contract:** generics `NUM_SWITCHES, NUM_BUTTONS, NUM_LEDS, NUM_SEGS, COUNTER_BITS`; ports `clk, sw, btn, led, seg`. The auto-wrapper (`sim_wrapper_template.vhd`) passes **exactly those five** generics by name and nothing else — so an extra defaulted top generic like `PRESCALER_BITS` is legal but the wrapper never overrides it: it stays at its VHDL default, **fixed at generation time, not settable from the simulator UI.** `seg` digit i = bits `[8*i+7:8*i]`, `bit7=dp..bit0=a`, active-high, digit 0 = rightmost. Simulator handles board active-low inversion + mux.
4. **Wrapper drives `clk` only** (`sim/sim_wrapper_template.vhd`) — **no reset**. → synthesize an internal power-on reset from **signal initial values** (honored by GHDL/NVC in simulation).
5. **VHDL-2008**, `ieee.std_logic_1164` + `numeric_std`. `ghdl -a --std=08` runs **without `-fsynopsys`** → cores using `std_logic_unsigned`/`std_logic_arith` would fail (mx65 is clean).
6. **Throughput:** ceiling ≈ `_MAX_CYCLES_PER_STEP (9596) × 60fps ≈ 575k sim-clk/s` at top slider; ~1/170 of that at default. A 6502 burns ~2–7 clk/instruction → must decouple visible rate from instruction count (prescaler).

### mx65 facts (claimed upstream — confirm in Stage 0/1)

`entity mx65` (no generics): `clock:in`, `reset:in` *(active-high, async)*, `ce:in` *(clock-enable)*, `data_in:in(7:0)`, `data_out:out(7:0)`, `address:out(15:0)`, `rw:out` *(1=read, 0=write)*, `sync:out` *(opcode fetch)*, `nmi:in`, `irq:in` *(active-high, level)*. ~995 lines, one `rtl` arch, no sub-components, `numeric_std` only, GHDL `--std=08`-clean (Stage-0 confirmed under GHDL + NVC). Vectors: NMI `$FFFA/B`, RESET `$FFFC/D`, IRQ/BRK `$FFFE/F` (little-endian).

These are **unverified** until the core is vendored. Three details drive the bus design and are **not yet pinned** — resolve them empirically in Stage 1 (see the Stage-1 exit checklist): (a) **which clock edge/phase mx65 samples `data_in`** (decides whether memory reads may be registered or must be combinational), (b) **when `data_out`/`rw` are valid** for a write, and (c) the **minimum reset pulse width** before it fetches the reset vector. Also confirm it tolerates `ce='1'` tied permanently.

## Architecture — the single-file 6502 system

Output: **`hdl/mx65_walking_counter_7seg.vhd`** → top entity `mx65_walking_counter_7seg`. **Entity order matters** (leaf units before the top, so single-pass analysis resolves `entity work.<name>`):

1. `mx65` — verbatim vendored core (untouched MIT text).
2. `cpu_rom` — **combinational-read** ROM (address in → byte out same cycle; see *Bus read timing* below); generic `ROM_BITS`; constant byte array = assembled program + decimal LUT + vectors.
3. `cpu_ram` — RAM with **combinational read, registered (clocked) write** when `rw='0'`; generic `RAM_BITS`. **Initialize the array signal to all-zero** (`others => (others => '0')`) so a read-before-write returns `x"00"`, not `'U'` — see *Metavalue hygiene* below.
4. `cpu_io` — address decoder + IO registers; carries `NUM_*` generics + `PRESCALER_BITS`.
5. `mx65_walking_counter_7seg` (top) — mandatory contract (all five generics incl. unused `COUNTER_BITS`); instantiates the four blocks; synthesizes POR; ties `ce='1'`, `irq='0'`, `nmi='0'` (polling v1).

**Memory map (64 KB)**

| Range | Size | Block | Decode (A15..A0) |
|---|---|---|---|
| `$0000–$07FF` | 2 KB | RAM (ZP `$00–$FF`, stack `$0100–$01FF`, vars) | `A(15:11)="00000"` |
| `$E000–$E0FF` | 256 B | IO registers | `A(15:8)=x"E0"` |
| `$F800–$FFFF` | 2 KB | ROM (program, LUT, vectors `$FFFA–$FFFF`) | `A(15:11)="11111"` |
| else | — | open, reads `x"00"` | — |

Read mux drives `mx65.data_in` (select RAM/IO/ROM by decode; default `x"00"`). Writes go to RAM or IO; ROM ignores writes.

**Bus read timing (the #1 Stage-1 risk).** The 6502 is a *same-cycle-read* bus: it drives `address`/`rw` and expects the addressed byte back on `data_in` **within the same cycle**, before its next sampling edge. So the read path (ROM, RAM, IO registers, and the mux) is **combinational** — address/decode in, byte out, no output register. A *registered-output* ("synchronous") memory would return data one cycle late and the CPU would fetch the previous address's byte → garbage from the first instruction on. Stage 1 must confirm mx65's `data_in` sampling edge and keep the read path combinational (this is correct and simplest for sim-only use; real silicon would use registered block-RAM plus a wait state).

**Metavalue hygiene.** GHDL/NVC initialize `std_logic` to `'U'`. A single `'U'` reaching `data_in` (an uninitialized RAM read landing in an operand or the PC) propagates through the whole datapath and **never resolves** in simulation, unlike real hardware — the display just freezes or blanks. Baked-in defenses: initialize the RAM array to `x"00"`, drive the read mux's `else` branch to `x"00"`, and synthesize the POR from init values so the CPU starts from a defined state.

**IO register map (offset from `$E000`)**

| Addr | Dir | Function |
|---|---|---|
| `$E000` | R | `sw(7:0)` zero-extended (`$E001` = high bits if `NUM_SWITCHES>8`) |
| `$E002` | R | `btn(7:0)` (`$E003` = high bits if `NUM_BUTTONS>8`) |
| `$E004` | R | **config: NUM_LEDS** |
| `$E005` | R | **config: NUM_SEGS** |
| `$E006` | R | **config: NUM_SWITCHES** |
| `$E007` | R | **config: NUM_BUTTONS** |
| `$E010` | R | bit0 = **tick pending, read-to-clear** |
| `$E020` | W | `led(7:0)` (`$E021` = high byte → up to 16 LEDs) |
| `$E030+i` | W | raw 8-bit segment byte for digit i (`0..NUM_SEGS-1`); writes to i ≥ NUM_SEGS ignored |

The **config registers** ($E004–$E007) expose the board's resource counts (driven straight from `cpu_io`'s generics) so the firmware can bound its bounce range and digit-render loop at runtime — keeping one generated file board-independent (a strictly-static fallback could bake MAX values instead). `cpu_io` holds `seg_regs : array(0 to NUM_SEGS-1) of std_logic_vector(7 downto 0)`, packed to `seg` exactly as `walking_counter_7seg.vhd` does (`for i generate seg(8*i+7 downto 8*i) <= seg_regs(i)`, no index reversal: digit 0 = units = rightmost). LED out = one-hot/lamp-test bits masked to `NUM_LEDS`. **Raw segment bytes, not a hardware decimal decoder** — keeps the LUT in software (the point is "the CPU does the output"), keeps `cpu_io` reusable, and reuses `walking_counter_7seg`'s exact 0–9 `SEG_LUT` bytes as ROM data → identical glyphs.

**Power-on reset (clk-only wrapper)**

```vhdl
signal por_cnt   : unsigned(2 downto 0) := (others => '0');  -- init 0 at t=0
signal cpu_reset : std_logic := '1';                         -- asserted at t=0
-- process(clk): if por_cnt /= "111" then por_cnt <= por_cnt + 1; end if;
cpu_reset <= '1' when por_cnt /= "111" else '0';
```

mx65 sees reset high ~7 clocks, then low → loads PC from `$FFFC/D`. **The "7" is a starting guess, not a confirmed figure** — size `por_cnt` to whatever mx65's reset sequence actually needs and widen it in Stage 1 if the PC doesn't load from `$FFFC/D`. (Sim-only POR via init values = exactly the simulator's contract; the guide notes this.)

**Throughput / timing.** Prescaler ticks every `2^PRESCALER_BITS` clk; the firmware loop runs ≈ 200–800 clk (BCD ripple + render, scaling with `N_SEGS` — a 6-digit board sits at the high end). As long as the tick period comfortably exceeds the worst-case loop length, the visible step rate equals the tick rate (deterministic — the decoupling value); the default `PRESCALER_BITS=10` (1024 clk) leaves margin even for 6 digits.

| `PRESCALER_BITS` | period | steps/s @ top slider | feel |
|---|---|---|---|
| 8 | 256 | ~2250 (CPU-capped) | LED bounce blurs |
| **10 (default)** | 1024 | ~560 | lively but watchable |
| 12 | 4096 | ~140 | calm |

`PRESCALER_BITS` = a top-level generic (default 10), **fixed at generation time** — the wrapper never passes it, so it is *not* a runtime knob (the runtime knobs are the speed slider and the switches). The speed slider scales sim-time; **switches** further multiply the rate via software tick-division (each active switch doubles it, matching `walking_counter_7seg.vhd`'s `idx := base - n` — see *Demo firmware*. The RTL originally quadrupled per switch, `base - n*2`, contradicting its own "doubles" comment; fixed in #133, so firmware and RTL now agree). **Polling** (read-to-clear `$E010`) for v1; IRQ-driven is a later stage.

## Demo firmware (replicates `walking_counter_7seg`)

Zero-page state: `BCD[0..NUM_SEGS-1]` (one byte/digit, 0–9; index 0 = units = rightmost), `POS` (lit LED), `FWD` (LED walk dir), `CNT_UP` (count dir), `PREVBTN` (edge detect), `SKIP`/`SKIPCNT` (switch speed divider), plus cached `N_LEDS`/`N_SEGS`.

**Cold-start (authentic):** `SEI` → `CLD` → `LDX #$FF; TXS` → read config regs (`$E004`→N_LEDS, `$E005`→N_SEGS) → zero `BCD[]`, `POS=0`, `FWD=1`, `CNT_UP=1`. Vectors: `$FFFC/D→RESET`; `$FFFE/F→IRQ/BRK handler` (`RTI`); `$FFFA/B→NMI handler` (`RTI`). All three valid.

**Main loop (per tick):** (1) poll `$E010` bit0 until tick (read-to-clear); (2) read `$E002`, rising-edge on bit0 vs `PREVBTN` → `FWD^=1`, `CNT_UP^=1`; (3) read `$E000`, popcount `P` → step divider `SKIP = max(1, SKIP_BASE >> P)` (e.g. `SKIP_BASE=8`) so **each active switch halves `SKIP`, doubling the step rate** (the chosen approximation of the reference's switch behavior); advance only on every `SKIP`-th tick; (4) if `btn(1)` → lamp-test (all segs/LEDs `$FF`), `JMP MAIN`; (5) on a step: bounce `POS` within `[0,N_LEDS-1]`, advance `BCD[]` ±1 with ripple carry/borrow across `N_SEGS`; (6) render digits (`LDX BCD[i]; LDA DECLUT,X; STA $E030,Y`) + one-hot LED (`1<<POS` → `$E020`/`$E021`); (7) `JMP MAIN`. `DECLUT` = the ten glyph bytes `x"3F".. x"6F"`. Program + LUT comfortably < 1 KB ROM.

**Button latency:** buttons are sampled once per tick (not every clock like the reference RTL), so a press must be held ≥ 1 tick to register — irrelevant for a human, but automated tests must hold `btn` high for ≥ 1 tick period plus one poll of latency.

**Acceptance (Stage 2 "done"):** identical 0–9 glyphs to `walking_counter_7seg`; one-hot LED bounces within `[0, N_LEDS-1]`; odometer ripples up/down with wrap; `btn(0)` reverses both LED and count direction; `btn(1)` lamp-tests; more switches = visibly faster. Absolute clock-for-clock timing is **not** required to match.

## The generator tool (built after the slice works)

`scripts/gen_embedded_core.py` + package `scripts/embedded_core/` (pure-Python, `uv run python ...`, mirrors the `scripts/sync_*.py` + `sync_common.py` validate-then-write idiom). **Emits generic-parameterized VHDL** (board sizes at runtime), validating the result against `sim_bridge`'s contract checker before writing.

**Input boundary = ROM image, not source asm** (assembler stays external). Abstraction (minimal v1, structured for growth):

- `CpuPlugin` — `core_vhdl_text()` (returns vendored `cores/mx65.vhd`), `entity_name`, `address_bits=16`, `data_bits=8`, reset polarity/async, `has_ce`, vectors `{reset,irq,nmi,endian}`, bus-adapter mapping.
- `SystemSpec` — memory regions (RAM/ROM/IO ranges+sizes), IO register layout (incl. config regs), `prescaler_bits`. Drives both the decoder VHDL and the asm symbol constants.
- `IoTemplate` / `SubsystemPlugin` — emits `cpu_io`; v1 ships one combined IO entity, structured as composable subsystems (gpio_in, gpio_out, seg7, timer, config).
- `RomImage` loader — reads a flat `.bin` (+ load addr + vector values) → sparse VHDL ROM constant (`others => x"00"`).
- `Emitter` — concatenates header + verbatim core + ROM + RAM + IO + top, leaf-first.

Vendored core: `scripts/embedded_core/cores/mx65.vhd` (**pin the upstream commit**, keep MIT header). Firmware: `firmware/mx65_walking_counter_7seg.s` + assembled `.bin` + a README with the exact assemble command. System spec: a small file under `scripts/embedded_core/` or `systems/`.

**Assembler — explicitly out of scope as a project dependency** (user-aligned; an in-repo assembler is excluded — the image is the interface). The generator never shells out to an assembler. But the demo firmware still needs assembling by *something*, so **lock that choice now to unblock Stage 2: use `ca65` (cc65)** — the de-facto 6502 assembler — as an **external dev-time tool**. The assembled `.bin` is **checked in and is the source of truth**; the `.asm` and the exact `ca65`/`ld65` command are checked in as reproducible documentation, but reassembly is **not** part of CI (no toolchain dependency). The ROM unit test therefore asserts the *shape* of the checked-in bytes (vectors at the right offsets, `DECLUT == SEG_LUT(0..9)`), not that the `.asm` reassembles to them. (`customasm` remains the documented path for the multi-ISA future.)

## Testing & verification

Reuse existing patterns — prefer cloning over new infra.

- **Stage-0 smoke (earliest, cheapest):** analyze vendored `mx65.vhd` *alone* under `ghdl -a --std=08` *and* `nvc --std=2008 -a`; assert both succeed.
- **ROM/image unit test:** load the **checked-in** `.bin` (the source of truth) → expected ROM constant; assert reset/IRQ/NMI vector bytes at the right offsets; assert `DECLUT` == `walking_counter_7seg`'s `SEG_LUT(0..9)`. (Does not reassemble the `.asm` — see *Assembler*, above.)
- **Generator unit test:** generated `.vhd` has entity == stem, contains all five entities, passes `sim_bridge`'s contract checker.
- **Integration (NVC + GHDL):** clone `tests/test_nvc.py::test_7seg_nvc_simulation_passes` + the `tests/test_ghdl.py` path. **Resource sizes come from the hardcoded `generics` dict** the test passes at elaborate/run time (`NUM_LEDS`, `NUM_SEGS`, …) plus a matching `SevenSegDef(num_digits=…)` so the wrapper's `seg` width agrees — **not** from `_7seg_board()`'s resource lists (those are empty and the headless path never reads them). The existing fixture is already 4-digit and the cloned test already passes `NUM_LEDS=4`, so to exercise generic sizing just **parametrize the generics over 2/4/6 digits**. Flow: analyze `hdl/mx65_walking_counter_7seg.vhd` (`toplevel='mx65_walking_counter_7seg'`) → elaborate `sim_wrapper` → run `sim/test_7seg.py` with `btn=0` (every digit a valid glyph — BCD 0–9 ⊂ valid set; `seg` advances). Add `sim/test_cpu_walking.py` (drives `dut.btn.value`/`dut.sw.value` directly): LED is **one-hot and bounces**; **`btn(0)` reverses** direction (hold `btn` high ≥ 1 tick); **`btn(1)` → lamp-test** — assert the lamp-test bytes are `0xFF` **explicitly** (`0xFF` is *not* in `test_7seg`'s valid-glyph set, so don't reuse that helper while `btn(1)` is held). Size `--stop-time` from the tick period (≥ a few × `N_LEDS` ticks to observe a full bounce + reversal); the existing 7-seg fixture's `2000000ns` (~97 ticks at `PRESCALER_BITS=10`, ~20 ns clk) is a good default — "hundreds of µs" is too tight for wide boards.
- **Headless GIF:** `scripts/capture_demo.py --vhdl hdl/mx65_walking_counter_7seg.vhd --sim nvc` on 2-digit (Nandland-Go), 4-digit (DE0), 6-digit (DE10-Lite) boards to prove generic sizing (`SDL_VIDEODRIVER=dummy`, `FPGA_SIM_BOARD_JSON`; `reference_headless_sim_testing` recipe).

## Staging & risks

**Sequence (vertical slice first):**

> **Status (2026-07-02):** Stages 0–5 are complete and shipped (`feat/embedded-core-system`, #135;
> per-stage log in [`embedded_core_build_notes.md`](embedded_core_build_notes.md)) — the IRQ-driven
> variant, T80 (Z80) as a second core, both Z80 feature axes (IM 2 vectored interrupts, port-mapped
> IO), and the capstone design combining them are all done. Remaining Stage-5 ideas (a true third
> core; the `customasm` path) are parked as roadmap **P8**, tracked by the active follow-up arc
> [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md). The roadmap **P7 (VSG)**
> trigger has fired — the generator now emits VHDL.

- **Stage 0** ✅ — Vendor `mx65.vhd` (pin commit); smoke-test it analyzes under both simulators.
- **Stage 1** ✅ — Hand-write the single file (top + mx65 + tiny ROM/RAM + trivial IO + config regs + POR); program writes a *constant* digit pattern + lights one LED, then spins. Goal: **elaborate + run** under GHDL **and** NVC; `test_7seg` sees valid (static) glyphs. **Stage-1 exit checklist (pins the open mx65 unknowns):** (a) PC loads from `$FFFC/D` — confirm POR width is enough, widen `por_cnt` if not; (b) reads land same-cycle — confirm mx65's `data_in` sampling edge and that the combinational read path feeds it in time (no off-by-one fetch); (c) a write to an IO register lands (verify `data_out`/`rw` timing); (d) a config-register read returns the generic value; (e) no `'U'` on `address`/`data_in` after reset (RAM init + mux default working). Proves bus wiring, vectors, POR, IO-write + config-read paths.
- **Stage 2** ✅ — Add prescaler tick + bounce/BCD/reversal firmware; then switch-speed + `btn(1)` lamp-test for full fidelity; tune `PRESCALER_BITS`. **← working 6502 demo here.**
- **Stage 3** ✅ — Build the generator to *reproduce* the Stage-2 file from inputs; add generator/ROM unit tests.
- **Stage 4** ✅ — Generalize interfaces; write the development guide; add 2/4/6-digit captures; **update the surrounding docs** (CLAUDE.md file table + "VHDL Design Contract" to mention the CPU-system family and `PRESCALER_BITS`; mark the roadmap card done) per the repo's completion-checklist convention.
- **Stage 5** ✅ — IRQ-driven variant (mx65 polled / simple / vectored IRQ); Z80 (T80) as a second
  core, exercising both feature axes (interrupt mode, port-mapped IO) plus a capstone design
  combining them. *(Originally scoped as "T65 as a second core"; delivered as T80/Z80 instead — a
  broader core-agnosticism proof — see [`embedded_core_build_notes.md`](embedded_core_build_notes.md).)*
  A true third core and the `customasm` path remain parked — roadmap **P8** /
  [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md).

**Top risks → mitigations:**

| Risk | Mitigation |
|---|---|
| mx65 elaboration under GHDL/NVC (2008 quirks, NVC heap, unconstrained types) | Stage-0 smoke test alone under both; pin commit; NVC already gets `-H 512m` in `sim_bridge.py` |
| Throughput too slow/fast for visible motion | Hardware prescaler decouples rate; `PRESCALER_BITS` generic + formula; switch-speed + slider |
| Reset/vector correctness (wrong vectors → garbage) | POR via init values; vectors placed deterministically + unit-tested; Stage-1 static program proves the fetch path first |
| **Bus read timing** — registered ("synchronous") memory returns data a cycle late → CPU fetches garbage | Combinational read path (ROM/RAM/IO/mux); confirm mx65's `data_in` sampling edge in Stage 1 |
| `'U'` propagation in sim (one metavalue poisons the whole datapath, never resolves) | Initialize RAM array to `x"00"`; mux `else => x"00"`; POR from init values; zero vars in cold-start |
| ROM-constant size / unwieldy VHDL | Sparse named association `others => x"00"`; 2 KB ROM |
| Board-variable LED/digit counts | Firmware reads **config registers**; LED reg 16-bit masked to NUM_LEDS; render N_SEGS digits |
| Read-to-clear tick race → missed steps | Acceptable for a free-running display; upgrade to an 8-bit tick counter later if needed |
| Button press shorter than one tick missed (polled once/tick, unlike the reference's per-clock sampling) | Fine for humans; automated tests hold `btn` ≥ 1 tick; IRQ variant removes the latency |

## How to verify end-to-end (once built)

```bash
# Stage 0 — core compiles under both simulators
ghdl -a --std=08 --workdir=$(mktemp -d) scripts/embedded_core/cores/mx65.vhd
nvc --std=2008 -a scripts/embedded_core/cores/mx65.vhd

# Unit + integration tests (assembler/ROM, generator, NVC+GHDL walking-counter)
uv run pytest tests/test_embedded_core.py -v

# Interactive: pick a 7-seg board (e.g. DE10-Lite) then hdl/mx65_walking_counter_7seg.vhd
uv run fpga-sim

# Headless GIFs across digit counts (proves generic sizing) -- captured from a
# temporary --prescaler-bits 14 variant build so the CPU free-runs while the
# display steps at a viewable rate; distinct --out per board
uv run python scripts/gen_embedded_core.py --system systems/mx65_walking_counter_7seg.toml \
    --prescaler-bits 14 --out /tmp/variant.vhd
uv run python scripts/capture_demo.py --scenario plain --sim nvc --vhdl /tmp/variant.vhd \
    --vhdl-label hdl/mx65_walking_counter_7seg.vhd --step-ns 336000 --frames 144 \
    --board step_mxo2 --out docs/assets/mx65_walking_counter_2digit.gif
uv run python scripts/capture_demo.py --scenario plain --sim nvc --vhdl /tmp/variant.vhd \
    --vhdl-label hdl/mx65_walking_counter_7seg.vhd --step-ns 336000 --frames 144 \
    --board de0 --out docs/assets/mx65_walking_counter_4digit.gif
uv run python scripts/capture_demo.py --scenario plain --sim nvc --vhdl /tmp/variant.vhd \
    --vhdl-label hdl/mx65_walking_counter_7seg.vhd --step-ns 336000 --frames 144 \
    --board de10_lite --out docs/assets/mx65_walking_counter_6digit.gif

# (Re)generate the design from the vendored core + system spec + ROM image
uv run python scripts/gen_embedded_core.py --cpu mx65 --system systems/mx65_walking_counter_7seg.toml \
    --rom firmware/mx65_walking_counter_7seg.bin --out hdl/mx65_walking_counter_7seg.vhd
```

Pre-commit (per repo convention): `ruff check`, `ruff format --check`, `mypy .`, then `uv run pytest`.

## Out of scope (this iteration)

- IRQ-driven firmware variant (Stage 5; guide discusses it).
- A second CPU core / multi-unit inlining (T65) — Stage 5; only documented now.
- An in-repo assembler — deliberately excluded; image is the interface.
- `snake_7seg` replica, peripherals beyond gpio/seg/timer/config (UART, etc.).
