# Embedded Core System Development Guide

> **Companion:** [`embedded_core_system_plan.md`](embedded_core_system_plan.md) — the implementation
> plan, staging, and risk register.
>
> *A guide to building a single-file VHDL design that runs an assembled program on a soft-core CPU,
> driving a virtual FPGA board's switches, buttons, LEDs, and 7-segment displays through a
> memory-mapped IO subsystem. The generator (`scripts/gen_embedded_core.py`) is built; the worked
> examples are a **6502 (mx65)** and a **Z80 (T80)** running the same walking counter from a shared,
> core-agnostic skeleton. Wherever the two cores differ, the guide calls out what a **third** core
> would change — the goal is that you can drop in any VHDL CPU by vendoring it and writing one small
> bus adapter.*

## 1. Overview & goals

A normal design in this simulator is a hand-written VHDL behavior (see `hdl/blinky.vhd`). An
**embedded core system** instead puts a **CPU** on the board and lets **software** (machine code
in an embedded ROM) produce the behavior, sensing inputs and driving outputs through an **IO
subsystem**. The whole thing — CPU core, ROM, RAM, IO, and a top wrapper — is emitted as **one
`.vhd` file** you select in the simulator like any other design.

You will learn to: choose a CPU core that fits the simulator; design a memory + IO map; write a
power-on reset and cold-start; write firmware that senses `sw`/`btn` and drives `led`/`seg`;
assemble it; embed the bytes as a ROM; generate the single file; and verify it.

**The single-file rule is the dominant constraint.** `sim_bridge.py` analyzes exactly one user
`.vhd`. VHDL lets one file hold many entities/architectures, so the CPU core, ROM, RAM, IO, and
top all live in that one file.

## 2. Prerequisites — the simulator contract

A design the simulator accepts must satisfy (see `CLAUDE.md` and `hdl/counter_7seg.vhd`):

- **Filename = top entity name.** `mx65_walking_counter_7seg.vhd` ⇒ `entity mx65_walking_counter_7seg`.
- **Top generics:** `NUM_SWITCHES, NUM_BUTTONS, NUM_LEDS, NUM_SEGS, COUNTER_BITS` (all `positive`).
  The simulator computes these from the selected board and passes them by name. You may ignore
  `COUNTER_BITS`. Extra top generics are fine if they have defaults — but the wrapper passes
  *only* the five above, so an extra generic like `PRESCALER_BITS` keeps its VHDL default and is
  effectively **fixed at generation time, not adjustable from the UI**.
- **Top ports:** `clk : in std_logic`; `sw : in std_logic_vector(NUM_SWITCHES-1 downto 0)`;
  `btn : in ...(NUM_BUTTONS-1 ...)`; `led : out ...(NUM_LEDS-1 ...)`;
  `seg : out std_logic_vector(8*NUM_SEGS-1 downto 0)` (7-seg boards only).
- **`seg` packing:** digit *i* occupies bits `[8*i+7 : 8*i]`; within a digit `bit7=dp,
  6=g,5=f,4=e,3=d,2=c,1=b,0=a`, **active-high**; **digit 0 = rightmost**. The simulator applies any
  board-level active-low inversion and multiplexing for you — always drive active-high per-digit
  bytes.
- **Clock only.** The auto-generated wrapper (`sim/sim_wrapper_template.vhd`) drives `clk`
  (period from the board's default clock, adjustable by the speed slider). There is **no reset
  input** — you synthesize one (§5).
- **VHDL-2008**, `ieee.std_logic_1164` + `ieee.numeric_std`. Analysis runs `ghdl -a --std=08` /
  `nvc --std=2008 -a` **without `-fsynopsys`** — so the Synopsys packages
  `std_logic_unsigned`/`std_logic_arith`/`std_logic_signed` are **not available**.

The contract check is a lenient whole-file text scan: it only needs one `entity <stem> is`
matching the filename and the tokens `clk/sw/btn/led` to appear somewhere. A CPU core with
different port names (mx65 uses `clock/reset/ce/...`) coexists fine.

## 3. Anatomy of a generated system

The generator concatenates into one file: a banner, the **vendored CPU core** (verbatim), then four
generated blocks — `cpu_rom`, `cpu_ram`, `cpu_io`, and the **top**. The trick that lets one skeleton
host different CPUs: the ROM/RAM/IO and address decode all speak a **normalized internal bus**, and a
small per-core **adapter** translates that bus to the specific core's pins.

```text
   +------------------------- top (entity = filename) --------------------------+
   |  clk --> [ POR ] --> cpu_reset (active-high, normalized)                    |
   |                                                                            |
   |    +----------------------+     normalized bus     +--- decode + read mux -+|
   |    |  per-core ADAPTER     |  cpu_addr / cpu_din /  |  cpu_rom | cpu_ram |  ||
   |    |  (a VHDL `block`)     |<-cpu_dout / cpu_we  -->|  cpu_io (regs+timer) |||
   |    |   instantiates mx65   |  cpu_reset/cpu_irq_req |          |           ||
   |    |         or T80        |                       +----------|-----------+|
   |    +----------------------+                                   v            |
   |  sw/btn ---------------------------------------------> cpu_io ---> led/seg  |
   +----------------------------------------------------------------------------+
```

- **Normalized bus.** `cpu_addr(15:0)`, `cpu_din(7:0)` (to CPU), `cpu_dout(7:0)` (from CPU), `cpu_we`
  (active-high write strobe), `cpu_reset` (active-high), `cpu_irq_req` (active-high). Every generated
  block uses these names, so they are **core-independent**.
- **Per-core adapter** (`scripts/embedded_core/adapters/<core>.vhd`): a self-contained VHDL `block`
  that instantiates the core and wires it to the normalized bus, converting reset polarity, the write
  strobe, the interrupt polarity, and the bus protocol (§4). This is the *only* core-specific VHDL —
  the whole "port to a new CPU" job.
- **`cpu_rom`** — combinational read (§4 *Bus read timing*); program + LUTs, embedded from the
  firmware `.bin`. **`cpu_ram`** — combinational read, registered write, zero-initialized. **`cpu_io`**
  — address-decoded registers (sw/btn/config/tick reads, led/seg writes) + the prescaler + (optionally)
  a small interrupt controller (§9).
- **POR** — a counter that holds `cpu_reset` asserted for the first few clocks (§5).
- **Decode + read mux** — **generated from the system memory map** (so the 6502's and Z80's different
  maps both work); combinational, default `x"00"` so the bus is never `'U'`.

## 4. Adding a CPU core (the core-agnostic part)

Porting to a new CPU is **two files**: vendor the core under `cores/`, and write a bus adapter under
`adapters/`. The ROM/RAM/IO, address decode, and firmware toolchain don't change. mx65 (6502) and
T80 (Z80) are the two worked examples; a third core follows the same recipe.

### 4.1 Requirements for a core

1. **VHDL** (GHDL/NVC are VHDL simulators; Verilog cores don't apply).
2. **Analyzes under `--std=08` / `--std=2008` with no `-fsynopsys`** and no vendor primitives
   (`altsyncram`, Lattice/Xilinx macros). Standard `std_logic_1164` + `numeric_std` is ideal; a core
   that pulls in Synopsys `std_logic_unsigned`/`std_logic_arith` can usually be **standardized**
   (§4.2).
3. **A documented synchronous bus**: address out, data in/out, a read/write strobe, reset, and a
   level-sensitive interrupt line if you want interrupts.
4. **A redistributable license** (MIT/BSD) so the core can be vendored with its notice kept.

### 4.2 Vendoring the core

Copy the core VHDL under `scripts/embedded_core/cores/<core>/` (or a single file), **keeping its
license header** — it travels into every generated design. Then:

- **Pin the upstream commit** and record it (mx65's header; T80's `cores/t80/PROVENANCE.md`) so a
  test can guard against silent re-vendoring.
- **ASCII only, no BOM** — the simulator's gate (`check_vhdl_encoding`) rejects non-ASCII; sanitize a
  core with accented bytes and note it as a patch.
- **Multi-file cores are fine** — list the files **leaf-first**; the generator concatenates them
  (T80 = `T80_Pack`, `T80_ALU`, `T80_MCode`, `T80_Reg`, `T80`, `T80s`).
- **Synopsys → standard patch.** If the core uses `IEEE.STD_LOGIC_UNSIGNED`, swap it for the
  VHDL-2008 standard `IEEE.NUMERIC_STD_UNSIGNED` (same `std_logic_vector` unsigned arithmetic, no
  `-fsynopsys`). This worked verbatim for T80 because it uses no `std_logic_arith`-only helpers
  (`conv_integer`, …); if a core does, translate those to `to_integer`/`to_unsigned` too. **Document
  every change to the vendored bytes**; the integrity test checks the pinned commit *and* that the
  core still analyzes under both simulators.

### 4.3 The `CpuPlugin`

`scripts/embedded_core/cpu_plugin.py` describes each core — its files, its adapter, and the facts the
generator documents (reset polarity, boot behavior):

```python
MX65 = CpuPlugin(name="mx65", entity_name="mx65",
                 core_files=(_CORES / "mx65.vhd",),
                 adapter_file=_ADAPTERS / "mx65.vhd")            # reset active-high, boots at $FFFC

T80  = CpuPlugin(name="t80", entity_name="T80s",
                 core_files=(_T80/"T80_Pack.vhd", ..., _T80/"T80s.vhd"),
                 adapter_file=_ADAPTERS / "t80.vhd",
                 reset_active_high=False, boots_at_zero=True)    # RESET_n low, boots at $0000
```

`--cpu <name>` on the generator selects it.

### 4.4 The bus adapter — the heart of "any core"

The adapter is a self-contained VHDL `block` (it may declare local signals, so the whole port is one
block) that plugs the core into the **normalized bus** (§3). It must: drive `cpu_addr`, read
`cpu_din`, drive `cpu_dout`; produce **`cpu_we`** (active-high write strobe); consume **`cpu_reset`**
(active-high POR) and **`cpu_irq_req`** (active-high) at the core's polarities. The two cores show how
different a bus can be:

| Normalized | mx65 (6502) | T80 (Z80) |
|---|---|---|
| reset | `reset => cpu_reset` (active-high) | `RESET_n => not cpu_reset` (active-low) |
| write strobe | `cpu_we <= not rw` (rw: 1=read) | `cpu_we <= (not WR_n) and (not MREQ_n)` |
| read | combinational `data_in <= cpu_din` | combinational `DI <= cpu_din` |
| irq | `irq => not cpu_irq_req` (active-low) | `INT_n => not cpu_irq_req` (active-low) |
| boot | fetches PC from `$FFFC/D` | starts executing at `$0000` |

```vhdl
-- adapters/mx65.vhd
cpu_core : block
  signal cpu_rw : std_logic;
begin
  cpu : entity work.mx65 port map (
    clock => clk, reset => cpu_reset, ce => '1',
    data_in => cpu_din, data_out => cpu_dout, address => cpu_addr,
    rw => cpu_rw, sync => open, nmi => '0', irq => not cpu_irq_req );
  cpu_we <= not cpu_rw;
end block;
```

A Z80 can access IO via `IN`/`OUT` (the `IORQ_n` space) *or*, as here, memory-mapped loads/stores; we
memory-map IO so both cores share `cpu_io` and leave `IORQ_n` open.

### 4.5 Bus read timing — the deepest pothole

Simple cores use a *same-cycle* read bus: the core drives `address` and expects the byte on `data_in`
**within the same clock cycle**, so ROM/RAM/IO and the read mux must be **combinational** (address in
→ byte out, no output register). A registered ("synchronous") memory returns data a cycle late and
the core executes garbage from the first fetch. Combinational read is the safe default for both cores;
real hardware uses registered block-RAM + a wait state, not needed in sim.

> **Multi-cycle reads bite read-to-clear registers.** The 6502's read is one clock; the Z80's is
> several. A **read-to-clear** status bit clears on the *first* clock of the Z80's multi-cycle read —
> before the core samples it — so a poll loop hangs forever. Use **write-to-clear** for status/ack
> registers (poll to check, write to acknowledge): correct for any core, and what `cpu_io`'s tick and
> interrupt-flag registers do (§6, §9). This one bug cost the Z80 bring-up a debugging session.

## 5. Reset & cold-start (generalized)

**Every CPU has a boot convention.** Identify, for your core: where it fetches the initial PC
(the **reset vector**), how the **stack pointer** initializes, which **mode flags** need setting,
and how **interrupts** are enabled/disabled. Then make the hardware assert reset at power-on and
make the firmware satisfy the rest.

**Synthesizing reset from a clk-only wrapper.** The simulator gives you no reset line, but
GHDL/NVC honor **signal initial values** in simulation. A tiny power-on-reset counter:

```vhdl
signal por_cnt   : unsigned(2 downto 0) := (others => '0');  -- 0 at t=0
signal cpu_reset : std_logic := '1';                         -- asserted at t=0
process(clk) begin
  if rising_edge(clk) then
    if por_cnt /= "111" then por_cnt <= por_cnt + 1; end if;
  end if;
end process;
cpu_reset <= '1' when por_cnt /= "111" else '0';
```

This holds reset high ~7 clocks, then releases it. **Size the counter to your core's actual reset
requirement** — "7" is a starting guess; widen it if the PC never loads from the reset vector.
(This is **sim-only** — it relies on init values rather than an external reset pin. That is exactly
the simulator's model; on real hardware you'd wire a reset controller.)

The POR is **core-agnostic**: it drives the normalized active-high `cpu_reset`, and the adapter
(§4.4) converts polarity — mx65 takes it directly, T80 inverts it to `RESET_n`. Seven clocks proved
enough for both cores; widen `por_cnt` if a core needs a longer reset.

**6502 reset vector & cold-start.** On reset the 6502 loads PC from **`$FFFC/$FFFD`**
(little-endian). Your ROM must place a valid address there pointing at your cold-start routine.
Cold-start should:

```asm
RESET:  SEI            ; mask IRQ (polling model)
        CLD            ; clear decimal mode (defined state)
        LDX #$FF
        TXS            ; stack pointer -> $01FF
        ; ... read config regs, zero variables, set initial direction ...
        JMP MAIN
```

**Shortcuts (when authenticity isn't required):** skip `CLD` if you never use decimal mode; leave
IRQ/NMI vectors pointing at a single `RTI` if you don't use interrupts (but they must still be
*valid* bytes, or a stray interrupt/BRK runs garbage). For learning, prefer the full sequence and
real handlers.

**Z80 cold-start (the second core, for contrast).** The Z80 has **no reset vector** — it just starts
executing at **`$0000`**, so ROM sits at the bottom of the map (§6) and the program's first byte *is*
its reset code. Cold-start: `DI` (we poll), `LD SP, <top-of-RAM>` (the Z80 leaves SP undefined on
reset), then read config and init variables. No `$FFFC`-style vector to place, and interrupt entry
points ($0038 for IM 1, $0066 for NMI) matter only if you enable interrupts.

**Metavalue (`'U'`) hygiene — a simulation-only hazard.** GHDL/NVC start every `std_logic` at
`'U'` (uninitialized), which has no hardware analog. If a `'U'` reaches the CPU's `data_in` — an
uninitialized RAM read used as an operand or jammed into the PC — it propagates through the entire
datapath and **never resolves**, so the display simply freezes or goes blank. Defend against it:
initialize the RAM array to `x"00"`, drive the read mux's default branch to `x"00"`, synthesize the
POR so the CPU starts defined, and have cold-start zero the variables it reads. When a CPU design
"does nothing," suspect a `'U'` on the bus first (§14, and *Debugging with waveforms*).

## 6. Memory & IO map design

Decode the address bus into regions, and put ROM **where the core boots**: top of memory for the
6502 (so its `$FFFA–$FFFF` vectors live in ROM), or **`$0000`** for the Z80 (which boots there, with
RAM/IO moved up). The decode lines are **generated from the spec's memory map**, so a different core's
map is just different base addresses. Example 6502 map:

- **RAM `$0000–$07FF`** — zero page (`$00–$FF`), stack (`$0100–$01FF`), variables.
- **IO `$E000–$E0FF`** — registers below.
- **ROM `$F800–$FFFF`** — program, LUTs, and the vectors at `$FFFA–$FFFF`.

**IO registers** (offset from `$E000`):

| Addr | Dir | Function |
|---|---|---|
| `$E000`/`$E001` | R | switches (low/high byte) |
| `$E002`/`$E003` | R | buttons (low/high byte) |
| `$E004..$E007` | R | **config**: NUM_LEDS, NUM_SEGS, NUM_SWITCHES, NUM_BUTTONS |
| `$E010` | R/W | tick pending in bit0; **write any value to clear** (§4.5) |
| `$E020`/`$E021` | W | LED bits (low/high byte), masked to NUM_LEDS |
| `$E030+i` | W | segment byte for digit *i* (active-high, `dp g f e d c b a`) |

**Config registers** make one generated file work on any board: firmware reads NUM_LEDS/NUM_SEGS
at boot and adapts (essential for the walking LED, which must know how many LEDs to traverse).
**Generic sizing:** `cpu_io` carries `NUM_*`; it zero-extends narrow `sw`/`btn` inputs to a byte,
masks `led` to `NUM_LEDS`, and exposes `seg_regs(0..NUM_SEGS-1)` packed to `seg` (digit 0 =
rightmost, no reversal). **Vector placement:** the assembler must emit the reset/IRQ/NMI addresses
at `$FFFC/D`, `$FFFE/F`, `$FFFA/B`.

## 7. Writing firmware

**Start with the smallest thing that proves the IO path** — the firmware equivalent of `blinky`
(this is also plan Stage 1). Light one LED and write one fixed digit, then spin:

```asm
RESET:  SEI
        CLD
        LDX #$FF
        TXS               ; init stack
        LDA #$01
        STA $E020         ; LED0 on
        LDA #$3F          ; glyph for "0"
        STA $E030         ; digit 0
SPIN:   JMP SPIN          ; mx65 keeps fetching; display holds
```

If that shows one steady LED and a "0", your reset vector, POR, read path, and IO writes all work —
everything else is incremental. Now the full walking-counter patterns (6502, but the shapes
generalize). The canonical assembled source lives in
`firmware/mx65_walking_counter_7seg.asm`; the sketches below are the algorithm, not final opcodes.

- **Poll the tick** (decouples visible rate from instruction speed):

  ```asm
  WAIT: LDA $E010      ; bit0 = tick pending
        AND #$01
        BEQ WAIT
        STA $E010      ; ack: a write clears it (§4.5 — safe for multi-cycle-read CPUs)
  ```

- **Query config for board-independence:** `LDA $E004 → N_LEDS`, `LDA $E005 → N_SEGS` at boot.
- **Button edge-detection** (software rising edge): read `$E002`, compare bit0 against the stored
  `PREVBTN`; on a 0→1 transition toggle `FWD` and `CNT_UP`; then store the new value in `PREVBTN`.
  Buttons are sampled **once per tick** (not every clock like the reference RTL), so a press must be
  held ≥ 1 tick to register — fine for a human, but automated tests must hold `btn` across a tick.
- **Bounce state machine:** advance `POS`; at `0` or `N_LEDS-1` flip `FWD`.
- **BCD ripple** (decimal odometer): increment digit 0; on `>9` set 0 and carry into the next
  digit across `N_SEGS`; decrement mirrors with borrow (`<0` → 9). Wrap is natural.
- **Render digits via ROM LUT:** `LDX BCD[i]; LDA DECLUT,X; STA $E030,Y` (`DECLUT` = the ten
  glyph bytes from `walking_counter_7seg.vhd`). **One-hot LED:** compute `1<<POS` → `$E020`
  (+`$E021` if `N_LEDS>8`).
- **Lamp-test:** if `btn(1)` set, write `$FF` to all digit regs and all LED bits.
- **Switch speed:** popcount `sw` (= `P`), set `SKIP = max(1, SKIP_BASE >> P)` (e.g. `SKIP_BASE=8`)
  and treat only every `SKIP`-th tick as a step, so **each active switch halves `SKIP` and doubles
  the rate**. (A *chosen* approximation of the reference's feel — `walking_counter_7seg.vhd` varies
  a clock-divider bit and, despite its "doubles" comment, actually quadruples per switch; we match
  the documented intent, not that bug.)

## 8. Assembler & ROM embedding

**The project consumes a ROM *image*, not assembly source.** Pick any assembler that emits bytes;
the generator just needs `{bytes, load address, vector values}`.

| Option | Pros | Cons |
|---|---|---|
| **Vendored pure-Python** | self-contained, in-repo, unit-testable, CI-clean | ~300–500 lines to maintain; one ISA |
| **ca65 (cc65)** | industry standard, macros, linker | external toolchain in dev + CI |
| **customasm** | single binary, **ISA described in a ruledef** — great for many CPUs | non-Python binary per OS; author rulesets |
| **hand-assembled** | zero tooling | error-prone; not general |

**Recommendation:** the worked example uses **`ca65` (cc65)** as an external dev-time tool (the
plan keeps an assembler out of the project's dependencies, so reassembly is not in CI — the
checked-in `.bin` is the source of truth). For the long-term multi-CPU vision, `customasm` is
attractive (one ruledef per ISA). Whatever you use, **check in the `.asm`, the assembled bytes,
and the exact command** so the image is reproducible.

**The assembler is per-ISA, and that's fine** — the generator only ever sees the `.bin`. The 6502
uses `ca65`/`ld65` (cc65); the Z80 uses z88dk's `z80asm` (`z80asm -b -o<bin> file.asm`, with `org 0`
and `defc NAME = value` for constants). Both are external dev-time tools; the checked-in `.bin` is
the source of truth, so CI never needs the assembler.

**Embedding as a VHDL ROM** — sparse named association keeps it small regardless of ROM size:

```vhdl
type rom_t is array(0 to 2**ROM_BITS-1) of std_logic_vector(7 downto 0);
constant ROM : rom_t := (
  16#000# => x"78",  -- SEI ...
  -- vectors (ROM base $F800; offset = addr-$F800):
  16#7FC# => x"00", 16#7FD# => x"F8",   -- RESET -> $F800
  16#7FE# => x"40", 16#7FF# => x"F8",   -- IRQ/BRK -> handler
  16#7FA# => x"40", 16#7FB# => x"F8",   -- NMI -> handler
  others => x"00");
```

Unit-test the bytes: assert the vectors land at the right offsets and that `DECLUT` equals
`walking_counter_7seg`'s `SEG_LUT(0..9)`.

## 9. Timing & throughput

The simulator runs sub-real-time: a per-frame cap of ~9596 clocks at ~60 fps gives a ceiling
≈ **575k simulated clocks/second** at the top slider position (far less at default). A 6502 uses
several clocks per instruction, so **don't busy-wait** millions of cycles for visible motion.

**Use a hardware prescaler tick.** A free-running divider raises a tick every `2^PRESCALER_BITS`
clocks; the firmware polls it (write-to-clear). The visible step rate then equals the tick rate and
is independent of how long your loop is:

| `PRESCALER_BITS` | clocks/tick | steps/s @ top slider |
|---|---|---|
| 8 | 256 | ~2250 (CPU-capped) |
| **10 (default)** | 1024 | ~560 |
| 12 | 4096 | ~140 |

Expose `PRESCALER_BITS` as a generic (default 10). The speed slider scales sim-time; switch-based
software division multiplies the rate further.

**Polling vs. interrupts.** Start with **polling** — no ISR, no reentrancy. The interrupt-driven
variant (`mx65_irq_counter_7seg`) instead builds a small **interrupt controller** in `cpu_io` with
**two sources** on the one IRQ line: a **timer** (the prescaler tick) and an **input-change**
detector (any `sw`/`btn` edge, caught in hardware — the "additional circuitry" a real peripheral
needs). Each source has an enable bit (**IER**, `$E011`) and a flag bit (**IFR**, `$E012`,
write-1-to-clear); `irq` is the OR of enabled+pending flags, and the ISR **reads IFR to learn which
source fired** and dispatches — the real "which peripheral interrupted?" pattern (like a disk
controller signalling "data ready"). The adapter routes the normalized active-high `cpu_irq_req` to
the core's line (`not cpu_irq_req` for both the 6502's and the Z80's active-low inputs). Firmware:
enable the source in the peripheral (IER) *and* enable the CPU (`CLI` / `EI`), then ack in the ISR.

## 10. Generating the file

```bash
uv run python scripts/gen_embedded_core.py \
    --cpu mx65 \
    --system systems/mx65_walking_counter_7seg.toml \
    --rom    firmware/mx65_walking_counter_7seg.bin \
    --out    hdl/mx65_walking_counter_7seg.vhd
```

Inputs: a **CPU plugin** (`--cpu`: vendored core files + adapter), a **system spec** (memory + IO
map, `prescaler_bits`, `irq_driven`), and a **ROM image**. Output: the single generic-parameterized
`.vhd`, validated against the contract checker before writing. Swap `--cpu mx65` for `--cpu t80`
(with the matching Z80 spec + `.bin`) to generate the Z80 build; `irq_driven = true` in the spec
generates the interrupt-driven variant instead of the polled one.

## 11. Running & verifying

- **Interactive:** `uv run fpga-sim` → pick a 7-seg board → select your `.vhd`.
- **Headless GIF:** `uv run python scripts/capture_demo.py --vhdl hdl/mx65_walking_counter_7seg.vhd
  --board de10_lite --sim nvc` (`SDL_VIDEODRIVER=dummy`; board JSON via `FPGA_SIM_BOARD_JSON`).
- **Tests:** `sim/test_cpu_walking.py` (glyphs + advance, one-hot bounce, `btn(0)` reversal,
  `btn(1)` lamp-test) is the **shared** behavioral suite — every design (6502 polled, 6502 IRQ,
  Z80) runs it (`PASS=4`) under both simulators. `tests/test_embedded_core.py` also byte-for-byte
  golden-tests each generated `.vhd` and checks the vendored cores' integrity + standardization.

## 12. End-to-end worked example (the 6502 walking counter)

1. **Vendor** `mx65.vhd` (pin a commit) at `scripts/embedded_core/cores/mx65.vhd`; smoke-test it
   analyzes under GHDL and NVC.
2. **Map** memory/IO as in §6; pick RAM/ROM sizes (2 KB each).
3. **Write** `firmware/mx65_walking_counter_7seg.s` (§5 cold-start + §7 main loop).
4. **Assemble** with `ca65`/`ld65` to `firmware/mx65_walking_counter_7seg.bin` (the source of truth).
5. **Generate** `hdl/mx65_walking_counter_7seg.vhd` (§10).
6. **Verify** (§11): glyphs valid, odometer advances, LED bounces, `btn(0)` reverses, `btn(1)`
   lamp-test; compare side-by-side with `hdl/walking_counter_7seg.vhd`.

The complete, annotated program is the checked-in `firmware/mx65_walking_counter_7seg.s` (the §5/§7
sketches are deliberately partial); `ca65`/`ld65` assemble it to the `.bin` that
`scripts/embedded_core/rom_to_vhdl.py` embeds verbatim as the ROM constant.

### Generic sizing — one design, every board

The same generated `hdl/mx65_walking_counter_7seg.vhd` runs unchanged on boards with different
resource counts: at cold-start the firmware reads `NUM_LEDS`/`NUM_SEGS` from the IO config registers
(§6) and drives exactly that many. Captured headless with `scripts/capture_demo.py` on three boards
that differ only in digit count:

| 2 digits (StepMXO2) | 4 digits (DE0) | 6 digits (DE10-Lite) |
|---|---|---|
| ![2-digit walking counter](assets/cpu_walk_2digit.gif) | ![4-digit walking counter](assets/cpu_walk_4digit.gif) | ![6-digit walking counter](assets/cpu_walk_6digit.gif) |

The bouncing one-hot LED and the decimal odometer are the same firmware, sized at runtime — nothing
in the VHDL or the program is board-specific.

### The same counter on a Z80 (the second core)

Adding a genuinely different core exercised the whole abstraction. The Z80 version is
`systems/t80_walking_counter_7seg.toml` (ROM at `$0000`, RAM `$8000`, IO `$E000`) +
`firmware/t80_walking_counter_7seg.asm` (the same algorithm and subroutines in Z80 assembly, built
with `z80asm`) + the vendored T80 core + `adapters/t80.vhd`. Generate it with `--cpu t80`; it runs
the **same** `sim/test_cpu_walking.py` behavioral suite (`PASS=4`) under GHDL and NVC — identical
on-board behavior, a completely different CPU. Two lessons surfaced only on the Z80: the tick had to
become **write-to-clear** (§4.5), and the memory map flips (**ROM at `$0000`** because the Z80 boots
there). The POR needed no change.

## 13. Extending

- **New CPUs:** vendor the core (§4.2) + write one adapter (§4.4). Multi-file cores inline
  automatically (T80 = 6 files); a Synopsys-dependent core is standardized with
  `numeric_std_unsigned` (§4.2). The 6502 and Z80 prove the seam holds across very different buses.
- **New subsystems:** extend `cpu_io` with more registers/peripherals (UART, timer-compare, GPIO
  banks) at fresh IO addresses; the two-source interrupt controller (§9) is the template for adding
  an interrupt source (enable bit + flag bit + OR into `cpu_irq_req`).
- **IRQ-driven vs polled:** a spec flag (`irq_driven = true`) turns on the interrupt controller and
  the `cpu_io.irq` wiring; the firmware supplies the ISR. Same design, different plumbing.
- **Alternative programs / hex vs BCD:** just firmware + system-spec changes; the VHDL skeleton and
  the adapter are unchanged.

## 14. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Analysis fails on the core | Synopsys package / vendor primitive / `--std` mismatch | Use a `numeric_std`-only core; confirm `--std=08`/`2008` |
| Elaborates but display blank | reset never released, or wrong reset vector | Check POR counter; verify `$FFFC/D` bytes point at `RESET` |
| Garbage on the display | bad vectors or uninitialized RAM read as code | Unit-test vector bytes; zero RAM in cold-start |
| Nothing moves | tick never fires, or busy-wait too long | Check prescaler + the write-to-clear ack; lower `PRESCALER_BITS` |
| Too fast / blurred | prescaler too short / slider too high | Raise `PRESCALER_BITS`; lower the speed slider |
| LED stuck at one end | `POS` bound wrong / didn't read `N_LEDS` | Read config reg `$E004`; check bounce limits |
| Works in GHDL, fails in NVC | heap / elaboration differences | NVC already gets `-H 512m`; keep ROM/RAM modest |
| Display dead from the very first frame | Registered (sync) memory → off-by-one read; CPU fetched garbage | Make ROM/RAM/mux read path **combinational** (§4) |
| Display frozen/blank; `data_in` shows `U`/`X` | Metavalue propagation from uninitialized RAM/bus | Init RAM to `x"00"`, mux `else => x"00"`, zero vars in cold-start (§5) |
| `btn(0)` reversal sometimes ignored | Button pulse shorter than one tick (polled once/tick) | Hold ≥ 1 tick; or use the IRQ variant (§9) |
| Poll loop hangs on a multi-cycle CPU (e.g. Z80) | **read-to-clear** status bit clears mid-read, before the core samples it | Make it **write-to-clear**: poll to check, write to ack (§4.5) |
| New core: garbage or writes don't land | bus adapter maps a strobe or polarity wrong | Recheck `adapters/<core>.vhd`: `cpu_we`, reset polarity, irq polarity, address width (§4.4) |
| Core analysis fails on `std_logic_unsigned` | vendored core uses a Synopsys package | Swap to `numeric_std_unsigned` (§4.2); translate any `conv_*` helpers |

## 15. Debugging with waveforms

When a CPU design misbehaves, dump a waveform and watch the bus — the fastest way to see the reset
fetch and the main loop (flags are version-dependent; check each simulator's `-r --help`):

```bash
# GHDL: write a VCD while running headless
ghdl -r --std=08 --workdir=<wd> sim_wrapper --vcd=cpu.vcd --stop-time=50us
# NVC: write an FST wave
nvc --std=2008 -H 512m -r --wave=cpu.fst --stop-time=50us sim_wrapper
```

Open the trace (GTKWave, Surfer) and watch the core's pins:

- **Reset fetch:** after `cpu_reset` falls, `address` should show `$FFFC` then `$FFFD`, then jump to
  your RESET routine. If not, the POR is too short or the reset-vector bytes are wrong.
- **`sync`** marks opcode fetches — count them to confirm the main loop is looping.
- **`rw`** high = read, low = write — watch a write actually drive `$E020`/`$E030`.
- **`data_in`** showing `U`/`X` is the tell-tale of metavalue propagation (§5) or an off-by-one
  registered read (§4); the design looks "dead" on screen.

A 20–50 µs window at `PRESCALER_BITS=10` captures reset plus several ticks — enough to diagnose most
bring-up failures.
