# Writing VHDL for the simulator

The VHDL author's reference: the port contract every design must satisfy, the
7-segment byte layout, the single-file embedded-CPU systems, and — the headline —
**your own project's pin map** — the `.qsf` or `.xdc` you already wrote for your
real board. For installation see [docs/install.md](install.md); for using the app
see [docs/user_guide.md](user_guide.md). Back to the [README](../README.md).

There are four ways to write a design:

1. **your project's own pin map** — keep your own port names and let your
   `.qsf`/`.xdc` say which pin each one is on. This is the one to reach for if you
   already have a Quartus or Vivado project;
2. the **generic contract** — `clk`/`sw`/`btn`/`led`[`/seg`] with `NUM_*` generics,
   which runs on *any* board (the examples in `hdl/` use it);
3. a **single-file embedded-CPU system** — a soft 6502/Z80 core running firmware,
   still satisfying the generic contract;
4. a **board-native design** — a board's *own* port names and fixed widths, no
   generics, which runs on the boards whose convention it matches.

They are tried in that order. A constraint file beside your design wins, because it
is the only one of the four that is a statement of *your* intent rather than a guess
about your naming.

## Your project's own pin map

If you already have a Quartus or Vivado project, your design's ports are named
whatever the assignment called them and your constraint file says which pin each one
is on. The simulator reads that file and maps your design **by pin**, so your port
names stop mattering:

```vhdl
entity test_entity is                       -- no board's naming anywhere
  port (
    clock  : in  std_logic;
    reset  : in  std_logic;
    sw     : in  std_logic_vector(9 downto 0);
    led_r  : out std_logic_vector(9 downto 0);
    hex    : out std_logic_vector(27 downto 0)
  );
end entity;
```

```tcl
# test_entity.qsf -- your own project's file, unmodified
set_location_assignment PIN_AF14 -to clock
set_location_assignment PIN_AA14 -to reset      # KEY[3] on this board: active-low
set_location_assignment PIN_W17  -to hex[0]     # HEX0 segment a
...
```

`reset` lands on a button, `led_r` on the LEDs, and each `hex` bit on the digit and
segment its pin belongs to. **Polarity comes from the board, not from your file** —
if the pin you named is an active-low button, the simulator inverts it for you,
exactly as the hardware does.

### One folder is one project

**Put the design, everything it needs, and one constraint file in a single
directory.** That is the whole contract:

```text
lab1/
├── test_entity.vhd      ← the design you pick
├── counter.vhd          ← a sub-entity it instantiates
├── testbench.vhd        ← ignored; it does not have to compile
└── test_entity.qsf      ← the pin map
```

The simulator reads that directory and nothing else. It does **not** learn Quartus's
or Vivado's project layout, and that is deliberate rather than lazy: Vivado's is
user-configurable and version-dependent, so a tool that chased it would be right
today and wrong after the next release — and wrong here means a design silently
wired to the wrong pins.

So if your files live inside a tool's project tree, **copy them out**. A Vivado
project keeps sources and constraints in different places:

```text
counter/counter.srcs/sources_1/new/top.vhd          ← your design
counter/counter.srcs/constrs_1/new/Basys3.xdc       ← your pins, three directories away
```

Copy both into one folder and pick the design there. If you point the simulator at a
design inside a project like that, it will tell you where the constraint file is
rather than leaving you to guess.

To keep a constraint file somewhere else on purpose, name it:
`fpga-sim --pinmap path/to/board.xdc --vhdl lab1/test_entity.vhd`.

### Designs split across several files

Your design does not have to be one file. If it does not compile on its own, the
other VHDL files in its folder are analyzed into the same library and it is tried
again — so a top level can instantiate a sub-entity or use a package that lives
next door:

```vhdl
-- top.vhd
u_counter : entity work.counter          -- counter.vhd, beside this file
  generic map (WIDTH => 8)
  port map (clk => clk, q => q);
```

You do not have to say what depends on what, and the files can be named anything:
the order is worked out by trying, and retrying whatever did not compile yet, until
nothing more can be added. A file that needs a package compiles on the round after
the package does.

**A neighbor that does not compile is ignored, not fatal.** Testbenches shipped with
an assignment often do not build as given, and they sit right beside the design they
test — your design still runs. The one message you get is about *your* design: if it
turns out to need a file that failed, the design's own analysis fails next, and that
error is the one shown.

Two consequences worth knowing:

- **Only your picked file is simulated.** The others are compiled so that it can be;
  the picker still runs the top level you chose. To run a testbench instead, see the
  manual recipe in the troubleshooting guide.
- Keep the folder to one project. Sixty VHDL files in a directory is not a lab
  folder, and the sweep stops there.
- **A design that compiles on its own costs nothing.** The folder is only read
  when your design actually needs it, which matters on GHDL's compiled LLVM
  backend, where analyzing a file means compiling it.

### What it reads, and what it ignores

- **Formats:** `.qsf` (Quartus), `.xdc` (Vivado), `.ucf`, `.pcf`, `.cst`, `.lpf`,
  `.ccf`, and BoardStore `.xml`. The suffix picks the dialect — there is no content
  sniffing, because guessing wrong would produce a *wrong* map rather than no map.
- **One file.** Two constraint files in one folder is a question only you can answer
  (a project with both a `.qsf` and an `.xdc` is targeting two boards), so the
  simulator asks instead of guessing. `--pinmap` settles it.
- **The whole board file is fine.** A vendor pin file assigns hundreds of pins —
  SDRAM, VGA, audio, HPS. The map is built outward from *your design's ports*, so an
  assignment no declared port claims is simply not read.
- **A port with no assignment is normal**, not an error. Quartus places such a pin
  automatically and real projects are full of them: an unassigned input is tied off
  with a note, and an unassigned output is left open.
- **A design may drive part of a display.** Four digits of a six-digit board is a
  normal thing to write; the rest stay dark, exactly as on the bench.
- **Wrong board?** When the constraint file names a device (`.qsf` files do), a
  mismatch with the selected board is reported by name rather than silently mapped.

## The generic contract

### Standard boards (no 7-segment display)

```vhdl
entity my_design is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk  : in  std_logic;
    sw   : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn  : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led  : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity;
```

The simulator sets the generics to match the selected board's resource counts. The
entity name **must match the filename stem** (e.g. `my_design.vhd` → entity
`my_design`). Use [`hdl/blinky.vhd`](../hdl/blinky.vhd) as a working template.

### 7-segment boards

Any board whose definition declares a 7-segment display (most of the Terasic
DE-series, the Digilent Nexys/Basys boards, Nandland Go, and around two dozen others)
also carries a `seg` output:

```vhdl
entity my_design is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;   -- number of digits; set by simulator to board value
    COUNTER_BITS : positive := 32
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
    -- digit i occupies bits [8i+7 : 8i] = {dp, g, f, e, d, c, b, a}, active-high
  );
end entity;
```

Each digit is one byte of `seg`, **active-high**: bit `8i` is segment `a` of digit
`i`, up through bit `8i+6` = segment `g` and bit `8i+7` = the decimal point. The
simulator normalizes all segment polarity to active-high in VHDL regardless of the
board's real hardware polarity, so you always drive a `'1'` to light a segment.

A 7-segment board will happily run a standard (no-`seg`) design — the digits stay
dark. A 7-seg design loaded on a board *without* a display also passes analysis: the
wrapper leaves `seg` unconnected, so it compiles and runs but the digits are never
driven. Use [`hdl/counter_7seg.vhd`](../hdl/counter_7seg.vhd) as a working example.

### RGB LED boards

Boards with RGB LEDs (Arty A7/S7/Z7, Cmod A7/S7, Cora Z7, ECPIX-5, Fomu, …) expose
each RGB LED as **three channels** of the `led` vector. Mono LEDs occupy the low bits
exactly as on standard boards; RGB channels fill the top, three bits per LED in
`(r, g, b)` order. To aim at them, declare one extra generic — the simulator sets it
to the board's RGB LED count at launch:

```vhdl
generic (
  ...
  NUM_LEDS     : positive := 4;   -- total channels: mono + 3 per RGB LED
  NUM_RGB_LEDS : natural  := 0    -- RGB sites; keep the := 0 default
);
```

```text
MONO = NUM_LEDS - 3*NUM_RGB_LEDS          -- led[MONO-1:0] = mono LEDs
led(MONO + 3*i + 0/1/2)                   -- RGB LED i: red / green / blue
```

Drive a channel high for a primary, or PWM it for shades — the simulator measures
duty per channel and mixes the rendered color, so three phase-offset PWM compares
sweep the full palette (see `hdl/rgb_rainbow.vhd`). Iterate sites with
`for i in 0 to NUM_RGB_LEDS - 1 loop`: on a board without RGB LEDs the loop
runs zero times and your design behaves like a plain standard-contract design, so
one file still fits every board. Never assume `NUM_RGB_LEDS > 0` in bare index
arithmetic. A design that omits the generic keeps working everywhere — RGB channels
are then just anonymous `led` bits, which light white-ish when driven together.

Declare the generic as `natural`, not `positive` — most boards have no RGB LEDs and
the simulator passes `0` there (the contract checker rejects a `positive`
declaration with exactly this explanation). Hovering an RGB LED shows all three
channel duties.

### Contract details

- **`COUNTER_BITS` is overridden at runtime.** Although the entity declares
  `:= 24` (or `:= 32`), the simulator drives a **lower** value — a floor of **17**,
  widened for many-digit displays. At the simulator's sub-real-time throughput, a full
  24-bit counter's MSB would toggle too slowly to see; real hardware would use the full
  default. Size any *visible* rate off a counter bit that is comfortably below the top
  of your declared width so it still moves. (This override applies to the generic
  contract only — board-native designs do not get it; see below.)
- **PWM works — brightness is measured, not sampled.** LEDs (and 7-segment
  segments) may be driven at any PWM frequency: the simulator integrates each
  channel's duty cycle *exactly* and renders it as brightness, so there are no
  sampling artifacts and no minimum pulse width. PWM that is slow relative to the
  simulation rate renders as slow-motion blinking — the truthful sub-real-time
  view — and a faster backend or a higher speed setting fuses it into steady
  brightness. Hover an LED to read its exact duty. See `hdl/blinky_pwm.vhd`.
- **Clock.** `clk` runs at the board's actual frequency, read from its `Clock`
  resource (falling back to **12 MHz** when a board declares none). Change it live in
  the sim with the virtual-clock **[-]/[+]** buttons.
- **Entity name = filename stem**, as above.
- **Extra ports need a default.** A port the simulator doesn't drive is fine as long
  as it is an output (left open) or an input **with a default value** (e.g.
  `uart_rx : in std_logic := '1'`). A default-less unmapped input is rejected — it
  would elaborate to an unbound signal.

### Put your divider width in a generic

The single most useful thing you can do to make a design of your own pleasant to
simulate is to name its clock divider:

```vhdl
entity running_light is
  generic (
    CNTR_LEN : positive := 24        -- the hardware value; leave it alone
  );
  ...
  signal count : unsigned(CNTR_LEN - 1 downto 0);
```

On the board, `CNTR_LEN = 24` at 50 MHz steps about three times a second. Here, the
same design steps about once every minute and a half — indistinguishable, on screen,
from a design that does not work.

With the width in a generic you can turn it down for the simulator and leave the
hardware value in the file, where it belongs:

```bash
fpga-sim --vhdl running_light.vhd --generic CNTR_LEN=4
```

Hard-coding `24` in the architecture works exactly as well on the bench and leaves you
no lever here. See
[generic overrides](user_guide.md#when-the-board-looks-frozen-generic-overrides) for
which types can be overridden.

### The Synopsys packages are accepted

A great deal of teaching and vendor example code opens with

```vhdl
use ieee.std_logic_arith.all;
use ieee.std_logic_unsigned.all;
```

These predate `ieee.numeric_std` and are **not part of any VHDL standard** — they
are Synopsys extensions that IEEE never adopted. GHDL refuses them outright unless
told otherwise (*"use of synopsys package `std_logic_arith` needs the -fsynopsys
option"*); NVC accepts them silently.

**The simulator passes that flag for you**, on analysis, elaboration *and* the run
(GHDL's mcode backend elaborates inside `-r`, so all three need it). A design
written this way runs here exactly as it does in Quartus or Vivado, unmodified.
The preview shows one line naming the packages, and the session log records them —
a note, not a warning: nothing is blocked and nothing behaves differently.

For **new** designs prefer `ieee.numeric_std`, which is the standard and is what
every example in this repository uses:

| Synopsys | `numeric_std` equivalent |
|---|---|
| `conv_integer(v)` | `to_integer(unsigned(v))` |
| `conv_std_logic_vector(i, n)` | `std_logic_vector(to_unsigned(i, n))` |
| `v + 1` on a `std_logic_vector` | `std_logic_vector(unsigned(v) + 1)` |

Mixing `std_logic_unsigned` with `numeric_std` in one file is the one combination
to avoid: both define arithmetic on the same types, and the ambiguity is a
compile error rather than a silent wrong answer.

## Embedded CPU systems

A design can instead be a **single self-contained file that embeds a soft CPU core**
— a vendored 6502 (mx65) or Z80 (T80) — running an assembled firmware program instead
of hand-written RTL. The file still satisfies the 7-segment contract above; the
firmware reads the board's resource counts from IO config registers, so one generated
file fits any board.

![The 6502 soft-CPU walking-counter firmware running on a virtual DE10-Lite: BTN0 reverses the count and the bouncing LED, BTN1 lights every LED and segment (lamp test), and SW0 doubles the step rate — then all three are restored so the loop repeats seamlessly](assets/mx65_walking_counter_demo.gif)

These are **generated, not hand-written**:
`uv run python scripts/gen_embedded_core.py --system systems/<name>.toml` (re)builds
one from a vendored core + a `systems/*.toml` spec + an assembled firmware `.bin`, and
`uv run python scripts/regen_embedded_cores.py` regenerates every system in one
command. Ships today: `hdl/mx65_walking_counter_7seg.vhd`,
`hdl/mx65_irq_counter_7seg.vhd`, four `hdl/t80_*.vhd` Z80 variants, the ~20-line
on-ramp `hdl/mx65_hello_7seg.vhd`, and the peripheral-extension example
`hdl/mx65_dice_7seg.vhd`. **Regenerate them rather than hand-editing.** See
[`docs/embedded_core_system_guide.md`](embedded_core_system_guide.md) for the full
development guide.

## Board-native designs

Instead of the generic contract, a design can be written to a **board's own port
names and fixed widths, with no `NUM_*` generics** — for example a Terasic board's
`CLOCK_50`, `SW(9 downto 0)`, `KEY(3 downto 0)`, `LEDR(9 downto 0)`, and
`HEX0`–`HEX5`:

```vhdl
entity de10_standard is
  port (
    CLOCK_50 : in  std_logic;
    SW       : in  std_logic_vector(9 downto 0);
    KEY      : in  std_logic_vector(3 downto 0);   -- active-low
    LEDR     : out std_logic_vector(9 downto 0);   -- active-high on this board
    HEX0, HEX1, HEX2, HEX3, HEX4, HEX5 : out std_logic_vector(6 downto 0)  -- active-low
  );
end entity;

-- ... in the architecture, tap a MID counter bit so motion stays visible:
LEDR <= std_logic_vector(count(27 downto 18));
```

When you load such a file, the simulator matches its ports against the **selected**
board's port convention; on a full match it runs the design unmodified, adapting the
native ports to its internal `clk`/`sw`/`btn`/`led`/`seg` boundary behind the scenes.
The [architecture guide](architecture.md#how-board-native-works) covers the internals;
this section is what you need to write one.

### Where the port names come from

Each board can carry one or more **port conventions** — named sets of its real port
names. They come in two tiers:

- **Vendor-canonical** conventions, cited from a board's real constraint files
  (Terasic `CLOCK_50`/`SW`/`KEY`/`LEDR`/`HEX0…`, and other vendors' own names).
- **Framework-derived** conventions, auto-built for most litex and amaranth boards
  from the framework's own resource names — litex `clk100`/`user_led`/`user_sw`/
  `user_btn`, amaranth `clk100`/`led`/`switch`/`button`. A design hand-written to
  those names runs board-native on that board (see
  [`hdl/native/arty_litex.vhd`](../hdl/native/arty_litex.vhd)).

**266 of the 285 boards** carry a convention today. When a board has both tiers, the
**canonical names win** — the matcher tries authoritative conventions first, so
distinctive vendor names take precedence over the generic framework ones.

### Polarity is the board's, not yours

The board's convention supplies polarity. On a board whose LEDs or keys are
active-low, the simulator inverts at the boundary for you: **your ports are the pins**,
so you drive them exactly as the real hardware expects (a `'0'` on an active-low
`KEY` when it is pressed, a `'1'` on an active-high `LEDR` to light it) and the
simulator maps that to the on-screen component. The stats panel names which roles it
is inverting (`board-native · active-low: …`; see the
[user guide](user_guide.md#board-native-runs)).

### Partial interfaces

A board-native design need only declare the roles the board's convention names, with
**clk + LEDs the minimum** (either the mono LED bank *or* a native RGB bank — see the
next section — satisfies the LED floor):

- **Switches and buttons** are matched only when the convention declares them, so a
  switch-less or button-less board runs a design that omits those banks.
- **Extra outputs** the convention doesn't map are left `open` (e.g. a DE0 example's
  `HEXn_DP` decimal-point pins).
- **Extra inputs** must carry a default value, exactly as in the generic contract; a
  default-less unmapped input is a near-miss. This includes the Nexys-family
  **reset pushbutton**: it is active-low while the directional buttons are
  active-high, so the convention maps only `btnC`/`btnU`/`btnD`/`btnL`/`btnR` — a
  native design that also declares the reset gives it a default
  (`btnCpuReset : in std_logic := '1'`).
- A **one-LED board** accepts the natural scalar spelling `led : out std_logic` — you
  are not forced to write `std_logic_vector(0 downto 0)`.

### RGB LEDs by their real names (Digilent)

On Digilent boards with 3-pin RGB LEDs, the convention also carries the real XDC
channel scalars — Arty's `led0_r`/`led0_g`/`led0_b` … `led3_b`, the original
Nexys 4's `RGB1_Red` … `RGB2_Blue` — so a board-native design can drive the RGB
LEDs directly:

```vhdl
entity my_arty_glow is
  port (
    CLK100MHZ : in  std_logic;
    sw        : in  std_logic_vector(3 downto 0);
    btn       : in  std_logic_vector(3 downto 0);
    led       : out std_logic_vector(3 downto 0);
    led0_r, led0_g, led0_b : out std_logic;   -- one scalar per channel
    -- ... led1_* .. led3_* likewise (declare the whole bank)
  );
end entity;
```

The bank is all-or-nothing: declare **every** channel scalar the convention names,
or none of them (a partial set is simply left dark, like any unmapped output). As
everywhere in native mode, **polarity is the board's**: each bank's `active_low`
is cited from the board's reference manual, so you drive the pins exactly as the
real hardware expects — most Digilent boards buffer the channels through inverting
transistors (drive **high** to light, e.g. Arty, Nexys, Zybo Z7, Cora Z7), while
the Cmod A7/S7 tri-color LED is common-anode (drive **low** to light). On
RGB-only boards (Cora Z7, Eclypse Z7) the RGB bank *is* the LED floor, so those
boards are natively targetable even though they have no mono LEDs.

### Scan displays by their real names (Digilent)

On boards whose 7-segment display is physically multiplexed, the convention carries
the real scan interface (`style: "scan"`), so a board-native design drives exactly
what the hardware exposes — shared segment lines, a shared decimal point, and the
digit-enable anodes, **all active-low** per the reference manuals ("both the AN0..N
and the CA..G/DP signals are driven low when active"):

```vhdl
-- Nexys 4 DDR / A7 idiom: per-segment scalars       -- Basys 3 idiom: shared vector
CA, CB, CC, CD, CE, CF, CG : out std_logic;          seg : out std_logic_vector(6 downto 0);
DP : out std_logic;                                  dp  : out std_logic;
AN : out std_logic_vector(7 downto 0);               an  : out std_logic_vector(3 downto 0);
```

Your design time-multiplexes exactly as on hardware: drive one digit's anode low
while placing that digit's segment pattern on the shared lines. The simulator
demultiplexes the scan and renders each digit at its honest 1/N scan brightness
(see the [user guide](user_guide.md#scan-displays-basys-3-nexys-4--4-ddr--a7)).
Notes:

- **Scan fast.** Pick a digit slot of ~1–10 µs simulated time (e.g. 128 clocks at
  100 MHz), not the ~1 kHz a hardware-first design would use: at the simulator's
  sub-real-time speed a 1 kHz scan parades one digit at a time across the
  brightness window instead of averaging into steady digits. This is the scan-rate
  cousin of the mid-counter-bits rule above; `hdl/native/nexys4ddr_scan.vhd` and
  `hdl/native/basys3_scan.vhd` show both.
- **`dp` is optional** — omit the port and the decimal points stay dark.
- The display role is matched **when declared**: leave the whole scan interface out
  and the design still runs (digits dark); declare only part of it and the run is
  rejected naming the missing ports.

### Loading a file written for a different board

The simulator always models the *selected* board and never silently coerces a
mismatch. A file whose ports are close but not identical — say the clock is `CLOCK_50`
but the selected board's is `CLOCK0_50` — is a **near-miss**, rejected with a message
that names the mismatch rather than run incorrectly:

```text
'my_design.vhd' is close to DE10-Lite's board-native 'terasic' interface but does
not fully match it (missing/mismatched: clk 'CLOCK_50' not found).
Fix those ports to run it board-native, or use the generic clk/sw/btn/led contract
(see hdl/blinky.vhd).
```

Pick the board the design was written for, or rewrite it to that board's names.

### The reference examples

[`hdl/native/`](../hdl/native/) has one example per board, each matching **only** its
own board (they are deliberately not offered in the file picker):

| File | Board | Notes |
|------|-------|-------|
| `de10_standard.vhd` | Terasic DE10-Standard | active-high `LEDR`, active-low `HEX` |
| `de0.vhd` | Terasic DE0 | leaves the `HEXn_DP` decimal points open |
| `de25_standard.vhd` | Terasic DE25-Standard | active-low LEDs (inverted for you) |
| `arty_litex.vhd` | Digilent Arty (litex names) | framework-derived `clk100`/`user_led`/… |
| `arty_rgb.vhd` | Digilent Arty A7-100 | native RGB channels `led0_r`…`led3_b`, color wheel + lamp test |
| `nexys4ddr_scan.vhd` | Digilent Nexys 4 DDR | physical scan display (`CA..CG`/`DP`/`AN`), hex counter + lamp test |
| `basys3_scan.vhd` | Digilent Basys 3 | scan display, shared-vector idiom (`seg`/`dp`/`an`) |

Board-native designs get **no `COUNTER_BITS` override** (that generic belongs to the
generic contract). A design that derives its visible rate from the top bits of a full
50 MHz divider will look frozen at the simulator's sub-real-time speed — so tap a
**mid** counter bit, as the examples do (`count(27 downto 18)` above).

### 7-segment scope

Two 7-seg styles are adapted to native mode: **per-digit (`individual`)** — one port
per digit (`HEX0`…`HEXn`) — and the **multiplexed `scan`** interface described above
(U22). Serial (shift-register) and per-segment-scalar displays stay on the generic
contract.

## When the compiler rejects your file

The simulator shows the analyzer's **own** error text, unedited — that is the
wording a search engine and the person next to you both recognize — and appends a
`Hint:` under it when it recognizes the failure. The hint is advice; the error
above it is the evidence.

GHDL and NVC word the same defect differently, so both are listed. Every message
below was captured by running the failure, not copied from a manual.

| What the compiler says | What it means | What to do |
|---|---|---|
| `no declaration for "std_logic"` · `no visible declaration for STD_LOGIC` | The IEEE header is missing | Add `library ieee;` and `use ieee.std_logic_1164.all;` |
| `no declaration for "unsigned"` · `... for "to_unsigned"` · `no visible declaration for UNSIGNED` | `numeric_std` is missing — it declares `unsigned`/`signed` and the conversions (`to_unsigned`, `to_integer`, `resize`) | Add `use ieee.numeric_std.all;` under the header |
| `no declaration for "couner"` | A name nothing declares — usually a typo, sometimes a signal declared in the wrong place | Check the spelling; declare signals between `architecture ... is` and `begin` |
| `an identifier is expected instead of 'units'` · `unexpected units while parsing signal declaration, expecting identifier` | A **reserved word** used as a name. Neither engine says "reserved word" | Rename it. The ones that read like ordinary names: `units`, `range`, `next`, `open`, `select`, `signal`, `type`, `bus`, `register`, `severity`, `label`, `body` |
| `missing ";" at end of object declaration` · `unexpected signal while parsing signal declaration, expecting one of := or ;` | A syntax error, reported where the text stopped making sense — often the line **after** the mistake | Check the end of the previous line. Every declaration and statement ends with `;`; the last entry inside `port ( ... )` or `generic ( ... )` does not |
| `unit "counter" not found in library "work"` · `design unit COUNTER not found in library WORK` | Something the design instantiates is not in the folder | Copy the file that declares it into the same folder, named after its entity (`counter.vhd` holds `entity counter`). If it *is* the design and you picked its testbench, pick the design |
| `too many actuals for component instance "uut"` · `found at least 7 positional actuals but WORK.X has only 6 ports` | A **positional** port map with the wrong number of actuals | Name the ports: `port map (clk => clk, rst => rst, sw => sw)`. A positional map binds by order, so it changes meaning silently whenever the entity's ports do |

### The error dialog

The dialog word-wraps but never re-indents, so GHDL's `^` stays under the column
it marks — including when the source line above it is too long to fit and wraps,
in which case the caret follows the piece of the line it points at. **[Copy]**
(or the `C` key) puts the whole thing — title, compiler text and hints — on the
clipboard, which is what you want when you are pasting it into a message.

The panel grows to the window, so a hinted error is normally shown whole. When a
message is longer than that, the footer says so and **↑ ↓ / PgUp / PgDn / Home /
End** scroll it as well as the mouse wheel.

The same text is also written to the terminal you started `fpga-sim` in, so it is
already in your scrollback whether or not you scrolled the dialog.

### Picking a testbench by mistake

A file whose entity declares **no ports at all** is a testbench, and the
simulator says so rather than listing the contract ports it is missing. Pick the
design instead: the simulator *is* the stimulus — the board's switches and
buttons are the inputs, and it drives the clock. The testbench can stay in the
folder; [files beside the design](#designs-split-across-several-files) are
analyzed with it.

## Example designs (`hdl/`)

Ready-to-run starting points, all on the generic contract:

| File | What it does |
|------|--------------|
| `blinky.vhd` | Switches XOR a counter → LEDs; buttons OR → LEDs |
| `blinky_alt.vhd` | Independent per-LED counters |
| `blinky_counter.vhd` | Binary counter on the LEDs |
| `blinky_morse.vhd` | Morse-code blinker |
| `blinky_pwm.vhd` | PWM LED brightness — all LEDs breathe (a full breath ≈ 8 s on GHDL-mcode, ≈ 1 s on NVC) |
| `blinky_walking.vhd` | Walking-light / knight-rider pattern |
| `rgb_rainbow.vhd` | RGB LEDs sweep the color wheel; switch-selected modes (rotate / static hue / cube scan / white breathe) |
| `counter_7seg.vhd` | Hex digit counter for 7-segment boards |
| `snake_7seg.vhd` | A segment crawls figure-8 across the digits; bouncing LED |
| `walking_counter_7seg.vhd` | Bouncing LED + decimal BCD counter; switch speed, button direction |
| `stopwatch_7seg.vhd` | Interactive stopwatch: `btn(0)` start/stop, `btn(1)` reset |
| `mx65_*.vhd`, `t80_*.vhd` | Generated embedded-core systems (see above) |
