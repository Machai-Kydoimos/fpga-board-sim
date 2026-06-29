# Embedded Core System Development Guide

> **Companion:** [`embedded_core_system_plan.md`](embedded_core_system_plan.md) — the implementation
> plan, staging, and risk register for the first system this guide describes.
>
> *A guide to building a single-file VHDL design that runs an assembled program on a soft-core
> CPU, driving a virtual FPGA board's switches, buttons, LEDs, and 7-segment displays through a
> memory-mapped IO subsystem. Two layers: **concepts** (for students/end-users) and **mechanics**
> (for maintainers extending the simulator). The running worked example is a 6502 (mx65) system
> that reproduces `hdl/walking_counter_7seg.vhd`.*
>
> **Note:** until the first system is built (plan Stages 0–4), the file paths and exact register
> details below are the *intended* design; finalize them against the real code as it lands.

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

- **Filename = top entity name.** `cpu_walking_counter_7seg.vhd` ⇒ `entity cpu_walking_counter_7seg`.
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

```text
        +------------------- cpu_walking_counter_7seg (top entity = filename) -------------------+
clk --->| clk        +-------+ cpu_reset  +-----------------+   address[15:0]                     |
        |            |  POR  |----------->|                 |-----------------+                   |
        |            +-------+   ce='1'   |      mx65        |  data_out[7:0]  |  rw               |
        | irq='0' -------------> ------->|  (6502 CPU core)  |---------+       |                   |
        | nmi='0' ------------->         +-----------------+          |       |                   |
        |                                   data_in[7:0] ^            v       v                   |
        |                                                |   +--- system bus -----------------+   |
        |   sw  ----------------------------------------|-->|  ROM  |  RAM  |  IO + config     |   |
        |   btn ----------------------------------------|-->|       |       |  (decoder+regs)  |   |
        |                                                +---|  read mux -> data_in            |   |
        |   led <--------------------------------------------|  led regs   seg regs --> seg ------> seg
        +----------------------------------------------------------------------------------------+
```

- **CPU core** (mx65): drives `address`, `data_out`, `rw`; reads `data_in`. `ce='1'` (full speed),
  `irq`/`nmi` tied off for the polling version.
- **ROM**: read-only bytes (program + LUT + reset/IRQ/NMI vectors).
- **RAM**: zero page, stack, variables.
- **IO + config**: address decoder + registers; reads `sw`/`btn`/config/tick, writes `led`/`seg`;
  contains the prescaler that generates the tick.
- **POR**: a small counter that holds the CPU in reset for the first few clocks (synthesized from
  signal initial values; see §5).
- **Read mux**: selects ROM/RAM/IO onto `data_in` by address decode — **combinational** (same-cycle
  read; see §4 *Bus read timing*), with the default branch driving `x"00"` so the bus is never `'U'`.

## 4. Choosing or adding a CPU core

**Requirements for a core to drop into this simulator:**

1. **VHDL** (GHDL/NVC are VHDL simulators; Verilog cores like Arlet's 6502 don't apply).
2. **Self-contained in standard IEEE libraries** — `std_logic_1164` + `numeric_std` only. **No
   Synopsys packages** (would need `-fsynopsys`, which the flow doesn't pass) and **no vendor
   primitives** (Lattice/Xilinx macros, `altsyncram`, etc.).
3. **Analyzes under `--std=08`** with no external dependencies.
4. **Simple, documented bus**: address out, data in/out, a read/write strobe, reset, ideally a
   clock-enable; level-sensitive `irq`/`nmi` if you want interrupts.
5. **Permissive license** (MIT/BSD) so it can be vendored into the repo, with its header kept.

**`CpuPlugin` fields** the generator needs (see the plan): verbatim core text, entity name, address
& data widths, reset polarity/sync, clock-enable presence, vector addresses + endianness, and the
bus-adapter mapping (which core port maps to which bus signal).

**6502 cores evaluated:**

| Core | License | Self-containment | Libraries | Fit |
|---|---|---|---|---|
| **mx65** (Steve-Teal) | MIT | **1 file, 1 arch, 0 sub-components** (~995 lines) | `std_logic_1164`+`numeric_std` | **Best** — drop-in; cycle-accurate; passes Klaus Dormann tests |
| T65 (mist-devel / CoPro6502) | BSD | 4 units (`T65`+`T65_Pack`+`T65_ALU`+`T65_MCode`); instantiates components | `std_logic_1164`+`numeric_std` (clean) | Good alternative; must **inline 4 units**; configurable 6502/65C02/65C816; very battle-tested |
| cpu6502_tc (OpenCores) | LGPL/OpenCores | multi-file, HDL-Designer-generated | possibly Synopsys | Weaker license/portability |

We use **mx65** for the first system. **T65** is the recommended next step to prove the generator
can inline a multi-unit core and to reach 65C02/65C816.

**mx65 interface:** `clock`, `reset` (active-high, async), `ce` (clock-enable), `data_in[7:0]`,
`data_out[7:0]`, `address[15:0]`, `rw` (1=read, 0=write), `sync` (opcode fetch), `nmi`, `irq`
(active-high, level). No generics.

**Bus read timing — the deepest pothole.** The 6502 (and most simple cores) use a *same-cycle*
read bus: the core drives `address`/`rw` and expects the byte back on `data_in` **within the same
clock cycle**. So your ROM, RAM, IO registers, and read mux must be **combinational** on the read
path (address/decode in → byte out, no output register). A registered ("synchronous") memory
returns data one cycle late, so the core latches the *previous* address's byte and executes garbage
from the first fetch. When adding a core, find the exact edge/phase it samples `data_in` and match
the read path to it; combinational read is the safe default for sim-only use. (Real hardware uses
registered block-RAM plus a wait state — not needed here.)

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

**Metavalue (`'U'`) hygiene — a simulation-only hazard.** GHDL/NVC start every `std_logic` at
`'U'` (uninitialized), which has no hardware analog. If a `'U'` reaches the CPU's `data_in` — an
uninitialized RAM read used as an operand or jammed into the PC — it propagates through the entire
datapath and **never resolves**, so the display simply freezes or goes blank. Defend against it:
initialize the RAM array to `x"00"`, drive the read mux's default branch to `x"00"`, synthesize the
POR so the CPU starts defined, and have cold-start zero the variables it reads. When a CPU design
"does nothing," suspect a `'U'` on the bus first (§14, and *Debugging with waveforms*).

## 6. Memory & IO map design

Decode the address bus into regions. Keep ROM where the reset/IRQ/NMI vectors must live (top of
memory for the 6502). Example map used by the worked example:

- **RAM `$0000–$07FF`** — zero page (`$00–$FF`), stack (`$0100–$01FF`), variables.
- **IO `$E000–$E0FF`** — registers below.
- **ROM `$F800–$FFFF`** — program, LUTs, and the vectors at `$FFFA–$FFFF`.

**IO registers** (offset from `$E000`):

| Addr | Dir | Function |
|---|---|---|
| `$E000`/`$E001` | R | switches (low/high byte) |
| `$E002`/`$E003` | R | buttons (low/high byte) |
| `$E004..$E007` | R | **config**: NUM_LEDS, NUM_SEGS, NUM_SWITCHES, NUM_BUTTONS |
| `$E010` | R | tick pending in bit0, **read-to-clear** |
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
`firmware/cpu_walking_counter_7seg.asm`; the sketches below are the algorithm, not final opcodes.

- **Poll the tick** (decouples visible rate from instruction speed):

  ```asm
  WAIT: LDA $E010      ; bit0 = tick pending (read clears it)
        AND #$01
        BEQ WAIT
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
clocks; the firmware polls it (read-to-clear). The visible step rate then equals the tick rate and
is independent of how long your loop is:

| `PRESCALER_BITS` | clocks/tick | steps/s @ top slider |
|---|---|---|
| 8 | 256 | ~2250 (CPU-capped) |
| **10 (default)** | 1024 | ~560 |
| 12 | 4096 | ~140 |

Expose `PRESCALER_BITS` as a generic (default 10). The speed slider scales sim-time; switch-based
software division multiplies the rate further.

**Polling vs. interrupts.** Start with **polling** — no ISR, no reentrancy, only a valid IRQ
vector needed. Polling samples inputs only once per loop iteration (here, once per tick), so very
short input pulses can be missed; an **IRQ-driven** version (wire the prescaler strobe to `irq`,
point `$FFFE/F` at an ISR that steps + acknowledges) reacts per-event, is more faithful to real
embedded code, and is worth building as a compare/contrast variant once polling works.

## 10. Generating the file

```bash
uv run python scripts/gen_embedded_core.py \
    --cpu mx65 \
    --system systems/walking_counter_7seg.toml \
    --rom    firmware/cpu_walking_counter_7seg.bin \
    --out    hdl/cpu_walking_counter_7seg.vhd
```

Inputs: a **CPU plugin** (verbatim core + bus/reset/vector conventions), a **system spec**
(memory + IO map, `prescaler_bits`), and a **ROM image**. Output: the single
generic-parameterized `.vhd`, validated against the contract checker before writing.

## 11. Running & verifying

- **Interactive:** `uv run fpga-sim` → pick a 7-seg board → select your `.vhd`.
- **Headless GIF:** `uv run python scripts/capture_demo.py --vhdl hdl/cpu_walking_counter_7seg.vhd
  --board de10_lite --sim nvc` (`SDL_VIDEODRIVER=dummy`; board JSON via `FPGA_SIM_BOARD_JSON`).
- **Tests:** an integration test analogous to `tests/test_nvc.py::test_7seg_nvc_simulation_passes`
  (reuse `sim/test_7seg.py` glyph/advance assertions) plus a walking-specific cocotb module
  (one-hot bounce, `btn(0)` reversal, `btn(1)` lamp-test), and unit tests for the ROM image and
  generator output.

## 12. End-to-end worked example (the 6502 walking counter)

1. **Vendor** `mx65.vhd` (pin a commit) at `scripts/embedded_core/cores/mx65.vhd`; smoke-test it
   analyzes under GHDL and NVC.
2. **Map** memory/IO as in §6; pick RAM/ROM sizes (2 KB each).
3. **Write** `firmware/cpu_walking_counter_7seg.asm` (§5 cold-start + §7 main loop).
4. **Assemble** to `firmware/cpu_walking_counter_7seg.bin`; record the command.
5. **Generate** `hdl/cpu_walking_counter_7seg.vhd` (§10).
6. **Verify** (§11): glyphs valid, odometer advances, LED bounces, `btn(0)` reverses, `btn(1)`
   lamp-test; compare side-by-side with `hdl/walking_counter_7seg.vhd`.

> Once `firmware/cpu_walking_counter_7seg.asm` exists, link or inline its **complete** annotated
> listing here (byte offsets + the three vector bytes) — a single end-to-end working program is the
> most useful artifact for a learner; the sketches in §5/§7 are deliberately partial.

## 13. Extending

- **New subsystems:** add composable IO blocks (UART, timer with compare, GPIO banks) behind the
  `SubsystemPlugin` interface; allocate fresh IO addresses.
- **New CPUs:** add a `CpuPlugin`. Multi-unit cores (T65) are inlined as several entities in the
  one file (validates the generator's inlining). Different ISAs use a different assembler
  (customasm shines here).
- **Hex vs BCD; IRQ-driven timing;** alternative programs — all just firmware + system-spec
  changes; the VHDL skeleton is unchanged.

## 14. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Analysis fails on the core | Synopsys package / vendor primitive / `--std` mismatch | Use a `numeric_std`-only core; confirm `--std=08`/`2008` |
| Elaborates but display blank | reset never released, or wrong reset vector | Check POR counter; verify `$FFFC/D` bytes point at `RESET` |
| Garbage on the display | bad vectors or uninitialized RAM read as code | Unit-test vector bytes; zero RAM in cold-start |
| Nothing moves | tick never fires, or busy-wait too long | Check prescaler + read-to-clear; lower `PRESCALER_BITS` |
| Too fast / blurred | prescaler too short / slider too high | Raise `PRESCALER_BITS`; lower the speed slider |
| LED stuck at one end | `POS` bound wrong / didn't read `N_LEDS` | Read config reg `$E004`; check bounce limits |
| Works in GHDL, fails in NVC | heap / elaboration differences | NVC already gets `-H 512m`; keep ROM/RAM modest |
| Display dead from the very first frame | Registered (sync) memory → off-by-one read; CPU fetched garbage | Make ROM/RAM/mux read path **combinational** (§4) |
| Display frozen/blank; `data_in` shows `U`/`X` | Metavalue propagation from uninitialized RAM/bus | Init RAM to `x"00"`, mux `else => x"00"`, zero vars in cold-start (§5) |
| `btn(0)` reversal sometimes ignored | Button pulse shorter than one tick (polled once/tick) | Hold ≥ 1 tick; or use the IRQ variant (§9) |

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
