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
| First firmware | Replicate **`walking_counter_7seg.vhd`**: bouncing one-hot LED + BCD decimal odometer; `btn(0)` reverses LED walk **and** count direction; `btn(1)` lamp-test; switches double the step rate |
| Cold-start | **Authentic** 6502 boot (reset vector, SP init, `CLD`, `SEI`, valid IRQ/NMI/BRK vectors + handlers); guide generalizes per-CPU requirements + shortcuts |
| Timing | Hardware **prescaler tick**, CPU **polls** (read-to-clear) for v1; **IRQ-driven** variant later for compare/contrast; guide covers both |
| VHDL params | **Generic-parameterized** (symbolic `NUM_*`) so one generated file runs on every board; firmware reads board sizes from **config registers** and renders accordingly |
| Audience | Students/end-users **and** maintainers → two-layer guide (concepts + mechanics) |

### Hard constraints (confirmed from the codebase)

1. **Single file only.** `src/fpga_sim/sim_bridge.py` analyzes exactly *one* user `.vhd` (`ghdl -a --std=08` / `nvc --std=2008 -a`) + the auto-generated wrapper. → the whole system (CPU + ROM + RAM + IO + top) must be **one file**, multiple entities/architectures.
2. **Contract is a lenient whole-file text scan** (`sim_bridge.py` ~330–378): requires one `entity <stem> is` matching the filename, and the tokens `clk/sw/btn/led` to appear *somewhere*. mx65's differently-named ports (`clock/reset/ce/...`) don't interfere.
3. **Top entity contract:** generics `NUM_SWITCHES, NUM_BUTTONS, NUM_LEDS, NUM_SEGS, COUNTER_BITS`; ports `clk, sw, btn, led, seg`. The auto-wrapper passes all five generics by name (extra defaulted top generics, e.g. a prescaler width, are fine). `seg` digit i = bits `[8*i+7:8*i]`, `bit7=dp..bit0=a`, active-high, digit 0 = rightmost. Simulator handles board active-low inversion + mux.
4. **Wrapper drives `clk` only** (`sim/sim_wrapper_template.vhd`) — **no reset**. → synthesize an internal power-on reset from **signal initial values** (honored by GHDL/NVC in simulation).
5. **VHDL-2008**, `ieee.std_logic_1164` + `numeric_std`. `ghdl -a --std=08` runs **without `-fsynopsys`** → cores using `std_logic_unsigned`/`std_logic_arith` would fail (mx65 is clean).
6. **Throughput:** ceiling ≈ `_MAX_CYCLES_PER_STEP (9596) × 60fps ≈ 575k sim-clk/s` at top slider; ~1/170 of that at default. A 6502 burns ~2–7 clk/instruction → must decouple visible rate from instruction count (prescaler).

### mx65 facts (confirmed)

`entity mx65` (no generics): `clock:in`, `reset:in` *(active-high, async)*, `ce:in` *(clock-enable)*, `data_in:in(7:0)`, `data_out:out(7:0)`, `address:out(15:0)`, `rw:out` *(1=read, 0=write)*, `sync:out` *(opcode fetch)*, `nmi:in`, `irq:in` *(active-high, level)*. ~650 lines, one `rtl` arch, no sub-components, `numeric_std` only, GHDL `--std=08`-clean. Vectors: NMI `$FFFA/B`, RESET `$FFFC/D`, IRQ/BRK `$FFFE/F` (little-endian).

## Architecture — the single-file 6502 system

Output: **`hdl/cpu_walking_counter_7seg.vhd`** → top entity `cpu_walking_counter_7seg`. **Entity order matters** (leaf units before the top, so single-pass analysis resolves `entity work.<name>`):

1. `mx65` — verbatim vendored core (untouched MIT text).
2. `cpu_rom` — synchronous ROM; generic `ROM_BITS`; constant byte array = assembled program + decimal LUT + vectors.
3. `cpu_ram` — synchronous RAM; generic `RAM_BITS`; array signal, write when `rw='0'`.
4. `cpu_io` — address decoder + IO registers; carries `NUM_*` generics + `PRESCALER_BITS`.
5. `cpu_walking_counter_7seg` (top) — mandatory contract (all five generics incl. unused `COUNTER_BITS`); instantiates the four blocks; synthesizes POR; ties `ce='1'`, `irq='0'`, `nmi='0'` (polling v1).

**Memory map (64 KB)**

| Range | Size | Block | Decode (A15..A0) |
|---|---|---|---|
| `$0000–$07FF` | 2 KB | RAM (ZP `$00–$FF`, stack `$0100–$01FF`, vars) | `A(15:11)="00000"` |
| `$E000–$E0FF` | 256 B | IO registers | `A(15:8)=x"E0"` |
| `$F800–$FFFF` | 2 KB | ROM (program, LUT, vectors `$FFFA–$FFFF`) | `A(15:11)="11111"` |
| else | — | open, reads `x"00"` | — |

Read mux drives `mx65.data_in` (select RAM/IO/ROM by decode; default `x"00"`). Writes go to RAM or IO; ROM ignores writes.

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

mx65 sees reset high ~7 clocks, then low → loads PC from `$FFFC/D`. (Sim-only POR via init values = exactly the simulator's contract; the guide notes this.)

**Throughput / timing.** Prescaler ticks every `2^PRESCALER_BITS` clk; firmware loop ≈ 200–400 clk (BCD ripple + render). As long as the tick period > loop length, the visible step rate equals the tick rate (deterministic — the decoupling value).

| `PRESCALER_BITS` | period | steps/s @ top slider | feel |
|---|---|---|---|
| 8 | 256 | ~2250 (CPU-capped) | LED bounce blurs |
| **10 (default)** | 1024 | ~560 | lively but watchable |
| 12 | 4096 | ~140 | calm |

`PRESCALER_BITS` = a top-level generic (default 10, tunable). The speed slider scales sim-time; **switches** further multiply the rate via software tick-division (each active switch doubles it, matching the VHDL). **Polling** (read-to-clear `$E010`) for v1; IRQ-driven is a later stage.

## Demo firmware (replicates `walking_counter_7seg`)

Zero-page state: `BCD[0..NUM_SEGS-1]` (one byte/digit, 0–9; index 0 = units = rightmost), `POS` (lit LED), `FWD` (LED walk dir), `CNT_UP` (count dir), `PREVBTN` (edge detect), `SKIP`/`SKIPCNT` (switch speed divider), plus cached `N_LEDS`/`N_SEGS`.

**Cold-start (authentic):** `SEI` → `CLD` → `LDX #$FF; TXS` → read config regs (`$E004`→N_LEDS, `$E005`→N_SEGS) → zero `BCD[]`, `POS=0`, `FWD=1`, `CNT_UP=1`. Vectors: `$FFFC/D→RESET`; `$FFFE/F→IRQ/BRK handler` (`RTI`); `$FFFA/B→NMI handler` (`RTI`). All three valid.

**Main loop (per tick):** (1) poll `$E010` bit0 until tick (read-to-clear); (2) read `$E002`, rising-edge on bit0 vs `PREVBTN` → `FWD^=1`, `CNT_UP^=1`; (3) read `$E000`, popcount → `SKIP`, step only every `SKIP`-th tick; (4) if `btn(1)` → lamp-test (all segs/LEDs `$FF`), `JMP MAIN`; (5) on a step: bounce `POS` within `[0,N_LEDS-1]`, advance `BCD[]` ±1 with ripple carry/borrow across `N_SEGS`; (6) render digits (`LDX BCD[i]; LDA DECLUT,X; STA $E030,Y`) + one-hot LED (`1<<POS` → `$E020`/`$E021`); (7) `JMP MAIN`. `DECLUT` = the ten glyph bytes `x"3F".. x"6F"`. Program + LUT comfortably < 1 KB ROM.

## The generator tool (built after the slice works)

`scripts/gen_embedded_core.py` + package `scripts/embedded_core/` (pure-Python, `uv run python ...`, mirrors the `scripts/sync_*.py` + `sync_common.py` validate-then-write idiom). **Emits generic-parameterized VHDL** (board sizes at runtime), validating the result against `sim_bridge`'s contract checker before writing.

**Input boundary = ROM image, not source asm** (assembler stays external). Abstraction (minimal v1, structured for growth):

- `CpuPlugin` — `core_vhdl_text()` (returns vendored `cores/mx65.vhd`), `entity_name`, `address_bits=16`, `data_bits=8`, reset polarity/async, `has_ce`, vectors `{reset,irq,nmi,endian}`, bus-adapter mapping.
- `SystemSpec` — memory regions (RAM/ROM/IO ranges+sizes), IO register layout (incl. config regs), `prescaler_bits`. Drives both the decoder VHDL and the asm symbol constants.
- `IoTemplate` / `SubsystemPlugin` — emits `cpu_io`; v1 ships one combined IO entity, structured as composable subsystems (gpio_in, gpio_out, seg7, timer, config).
- `RomImage` loader — reads a flat `.bin` (+ load addr + vector values) → sparse VHDL ROM constant (`others => x"00"`).
- `Emitter` — concatenates header + verbatim core + ROM + RAM + IO + top, leaf-first.

Vendored core: `scripts/embedded_core/cores/mx65.vhd` (**pin the upstream commit**, keep MIT header). Firmware: `firmware/cpu_walking_counter_7seg.asm` + assembled `.bin` + a README with the exact assemble command. System spec: a small file under `scripts/embedded_core/` or `systems/`.

**Assembler — explicitly out of scope as a dependency** (user-aligned). The generator never shells out to an assembler. We *evaluate* ca65 vs customasm vs a tiny Python assembler only to inform the guide; whichever we use for the demo, the bytes are checked in.

## Testing & verification

Reuse existing patterns — prefer cloning over new infra.

- **Stage-0 smoke (earliest, cheapest):** analyze vendored `mx65.vhd` *alone* under `ghdl -a --std=08` *and* `nvc --std=2008 -a`; assert both succeed.
- **ROM/image unit test:** assembled bytes → expected ROM; assert reset/IRQ/NMI vector bytes at the right offsets; assert `DECLUT` == `walking_counter_7seg`'s `SEG_LUT(0..9)`.
- **Generator unit test:** generated `.vhd` has entity == stem, contains all five entities, passes `sim_bridge`'s contract checker.
- **Integration (NVC + GHDL):** clone `tests/test_nvc.py::test_7seg_nvc_simulation_passes` + the `tests/test_ghdl.py` path. Use a 7-seg fixture with **≥2 digits and ≥4 LEDs** (extend `tests/conftest.py::_7seg_board()`): analyze `hdl/cpu_walking_counter_7seg.vhd` (`toplevel='cpu_walking_counter_7seg'`) → elaborate `sim_wrapper` → run `sim/test_7seg.py` (every digit a valid glyph — BCD 0–9 ⊂ valid set; `seg` advances). Add `sim/test_cpu_walking.py`: LED is **one-hot and bounces**; **`btn(0)` reverses** direction; **`btn(1)` → lamp-test**. Generous `--stop-time` (hundreds of µs at `PRESCALER_BITS=10`, ~20 ns period).
- **Headless GIF:** `scripts/capture_demo.py --vhdl hdl/cpu_walking_counter_7seg.vhd --sim nvc` on 2-digit (Nandland-Go), 4-digit (DE0), 6-digit (DE10-Lite) boards to prove generic sizing (`SDL_VIDEODRIVER=dummy`, `FPGA_SIM_BOARD_JSON`; `reference_headless_sim_testing` recipe).

## Staging & risks

**Sequence (vertical slice first):**

- **Stage 0** — Vendor `mx65.vhd` (pin commit); smoke-test it analyzes under both simulators.
- **Stage 1** — Hand-write the single file (top + mx65 + tiny ROM/RAM + trivial IO + config regs + POR); program writes a *constant* digit pattern + lights one LED, then spins. Goal: **elaborate + run** under GHDL **and** NVC; `test_7seg` sees valid (static) glyphs. Proves bus wiring, vectors, POR, IO-write + config-read paths.
- **Stage 2** — Add prescaler tick + bounce/BCD/reversal firmware; then switch-speed + `btn(1)` lamp-test for full fidelity; tune `PRESCALER_BITS`. **← working 6502 demo here.**
- **Stage 3** — Build the generator to *reproduce* the Stage-2 file from inputs; add generator/ROM unit tests.
- **Stage 4** — Generalize interfaces; write the development guide; add 2/4/6-digit captures.
- **Stage 5 (later)** — IRQ-driven variant; T65 as a second (multi-unit) core; customasm path.

**Top risks → mitigations:**

| Risk | Mitigation |
|---|---|
| mx65 elaboration under GHDL/NVC (2008 quirks, NVC heap, unconstrained types) | Stage-0 smoke test alone under both; pin commit; NVC already gets `-H 512m` in `sim_bridge.py` |
| Throughput too slow/fast for visible motion | Hardware prescaler decouples rate; `PRESCALER_BITS` generic + formula; switch-speed + slider |
| Reset/vector correctness (wrong vectors → garbage) | POR via init values; vectors placed deterministically + unit-tested; Stage-1 static program proves the fetch path first |
| ROM-constant size / unwieldy VHDL | Sparse named association `others => x"00"`; 2 KB ROM |
| Board-variable LED/digit counts | Firmware reads **config registers**; LED reg 16-bit masked to NUM_LEDS; render N_SEGS digits |
| Read-to-clear tick race → missed steps | Acceptable for a free-running display; upgrade to an 8-bit tick counter later if needed |

## How to verify end-to-end (once built)

```bash
# Stage 0 — core compiles under both simulators
ghdl -a --std=08 --workdir=$(mktemp -d) scripts/embedded_core/cores/mx65.vhd
nvc --std=2008 -a scripts/embedded_core/cores/mx65.vhd

# Unit + integration tests (assembler/ROM, generator, NVC+GHDL walking-counter)
uv run pytest tests/test_embedded_core.py -v

# Interactive: pick a 7-seg board (e.g. DE10-Lite) then hdl/cpu_walking_counter_7seg.vhd
uv run fpga-sim

# Headless GIFs across digit counts (proves generic sizing)
uv run python scripts/capture_demo.py --vhdl hdl/cpu_walking_counter_7seg.vhd --board nandland_go --sim nvc
uv run python scripts/capture_demo.py --vhdl hdl/cpu_walking_counter_7seg.vhd --board de10_lite  --sim nvc

# (Re)generate the design from the vendored core + system spec + ROM image
uv run python scripts/gen_embedded_core.py --cpu mx65 --system systems/walking_counter_7seg.toml \
    --rom firmware/cpu_walking_counter_7seg.bin --out hdl/cpu_walking_counter_7seg.vhd
```

Pre-commit (per repo convention): `ruff check`, `ruff format --check`, `mypy .`, then `uv run pytest`.

## Out of scope (this iteration)

- IRQ-driven firmware variant (Stage 5; guide discusses it).
- A second CPU core / multi-unit inlining (T65) — Stage 5; only documented now.
- An in-repo assembler — deliberately excluded; image is the interface.
- `snake_7seg` replica, peripherals beyond gpio/seg/timer/config (UART, etc.).
