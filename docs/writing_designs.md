# Writing VHDL for the simulator

The VHDL author's reference: the port contract every design must satisfy, the
7-segment byte layout, the single-file embedded-CPU systems, and — the headline —
**board-native designs** written to a board's own port names. For installation see
[docs/install.md](install.md); for using the app see
[docs/user_guide.md](user_guide.md). Back to the [README](../README.md).

There are three ways to write a design:

1. the **generic contract** — `clk`/`sw`/`btn`/`led`[`/seg`] with `NUM_*` generics,
   which runs on *any* board (the examples in `hdl/` use it);
2. a **single-file embedded-CPU system** — a soft 6502/Z80 core running firmware,
   still satisfying the generic contract;
3. a **board-native design** — a board's *own* port names and fixed widths, no
   generics, which runs on the boards whose convention it matches.

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

**262 of the 283 boards** carry a convention today. When a board has both tiers, the
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
**clk + LEDs the minimum**:

- **Switches and buttons** are matched only when the convention declares them, so a
  switch-less or button-less board runs a design that omits those banks.
- **Extra outputs** the convention doesn't map are left `open` (e.g. a DE0 example's
  `HEXn_DP` decimal-point pins).
- **Extra inputs** must carry a default value, exactly as in the generic contract; a
  default-less unmapped input is a near-miss.
- A **one-LED board** accepts the natural scalar spelling `led : out std_logic` — you
  are not forced to write `std_logic_vector(0 downto 0)`.

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

Board-native designs get **no `COUNTER_BITS` override** (that generic belongs to the
generic contract). A design that derives its visible rate from the top bits of a full
50 MHz divider will look frozen at the simulator's sub-real-time speed — so tap a
**mid** counter bit, as the examples do (`count(27 downto 18)` above).

### 7-segment scope

Only the **per-digit (`individual`)** 7-seg style is adapted to native mode — a board
whose convention exposes one port per digit (`HEX0`…`HEXn`). Multiplexed scan, serial,
and per-segment-scalar displays stay on the generic contract for now.

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
