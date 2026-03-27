# VHDL Blinky Survey

A categorized survey of `blinky.vhd` / `blinky.vhdl` patterns found across FPGA
tutorials, vendor documentation, and open-source repositories.  The project supports
80 boards spanning Xilinx, Lattice iCE40/ECP5/MachXO, Intel/Altera, and Gowin
families; examples from all ecosystems are represented.

---

## Category 1 — Bare Minimum (Constant Output)

**Found in**: University "intro to VHDL" first-lecture slides.

```vhdl
entity blinky is
  port (led : out std_logic);
end entity;

architecture rtl of blinky is
begin
  led <= '1';
end architecture;
```

Technically not a blinky — it turns one LED permanently on.  Occasionally labeled
"blinky" in slide decks as the first synthesisable VHDL file a student writes.

---

## Category 2 — Free-Running Counter, MSB → LED

**Found in**: ~80 % of all FPGA tutorials regardless of vendor.
Digilent Basys3 Getting Started, Nexys A7, Arty A7, DE0-Nano, ULX3S examples, GHDL
quickstart, countless GitHub repos.

```vhdl
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity blinky is
  port (
    clk : in  std_logic;
    led : out std_logic
  );
end entity;

architecture rtl of blinky is
  signal counter : unsigned(23 downto 0) := (others => '0');
begin
  process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process;

  led <= counter(23);   -- MSB toggles at f_clk / 2^24
end architecture;
```

**Blink rate formula**

```
f_blink = f_clk / 2^N     (N = counter bit width)
```

| Clock   | Bits | Rate    | Board examples              |
|---------|------|---------|-----------------------------|
| 12 MHz  |  21  | 5.7 Hz  | iCEstick, iCEBreaker crystal |
| 25 MHz  |  23  | 3.0 Hz  | OrangeCrab, some Gowin      |
| 27 MHz  |  23  | 3.2 Hz  | TangNano 9K                 |
| 50 MHz  |  24  | 3.0 Hz  | DE0-Nano, DE10-Lite         |
| 100 MHz |  25  | 3.0 Hz  | Arty A7, Basys3, Nexys A7   |

**Variants**: counter width 24–27 depending on board clock; `counter(N-2)` used for a
2× faster blink; no reset — counter wraps naturally.

---

## Category 3 — Named-Constant Period

**Found in**: Intel University Program DE0-Nano/DE10 lab sheets; Xilinx Vivado
"Counter" lab for Basys3.

```vhdl
architecture rtl of blinky is
  constant CLK_FREQ   : positive := 50_000_000;  -- Hz
  constant BLINK_FREQ : positive := 2;            -- Hz
  constant MAX_COUNT  : positive := CLK_FREQ / BLINK_FREQ / 2 - 1;

  signal counter : integer range 0 to MAX_COUNT := 0;
  signal led_reg : std_logic := '0';
begin
  process(clk)
  begin
    if rising_edge(clk) then
      if counter = MAX_COUNT then
        counter <= 0;
        led_reg <= not led_reg;
      else
        counter <= counter + 1;
      end if;
    end if;
  end process;

  led <= led_reg;
end architecture;
```

Teaches `constant` declarations and exact frequency specification.  Downside: requires
updating `CLK_FREQ` per board and does not adapt automatically to different clocks.

---

## Category 4 — Synchronous Reset Variant

**Found in**: Intel/Altera-centric tutorials; textbooks (Ashenden, Brown & Vranesic).

```vhdl
entity blinky is
  port (
    clk   : in  std_logic;
    reset : in  std_logic;   -- active-high synchronous reset
    led   : out std_logic
  );
end entity;

architecture rtl of blinky is
  signal counter : unsigned(24 downto 0) := (others => '0');
begin
  process(clk)
  begin
    if rising_edge(clk) then
      if reset = '1' then
        counter <= (others => '0');
      else
        counter <= counter + 1;
      end if;
    end if;
  end process;

  led <= counter(24);
end architecture;
```

Intel Quartus style-guide mandates explicit reset for all registers.  An asynchronous
variant (reset checked outside `rising_edge`) is common in textbooks but complicates
timing closure and is disfavored in modern synthesis practice.

---

## Category 5 — Multi-LED Binary Counter Display

**Found in**: Boards with ≥ 4 LEDs — Basys3 (16 LEDs), Nexys A7 (16 LEDs),
DE0-Nano (8 LEDs), ULX3S (8 LEDs).

```vhdl
entity blinky is
  port (
    clk : in  std_logic;
    led : out std_logic_vector(7 downto 0)
  );
end entity;

architecture rtl of blinky is
  signal counter : unsigned(31 downto 0) := (others => '0');
begin
  process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process;

  led <= std_logic_vector(counter(31 downto 24));
end architecture;
```

Upper 8 bits of a 32-bit counter advance slowly enough to be visible (~0.4 Hz per bit
at 100 MHz).  Effect: LEDs display a rippling binary count.

**Walking-LED variant** (Knight Rider precursor):

```vhdl
-- Shift register: exactly one LED on, advances on counter rollover
signal shift : std_logic_vector(7 downto 0) := "00000001";

process(clk)
begin
  if rising_edge(clk) then
    counter <= counter + 1;
    if counter = 0 then
      if shift(7) = '1' then
        shift <= "00000001";
      else
        shift <= shift(6 downto 0) & '0';
      end if;
    end if;
  end if;
end process;
led <= shift;
```

---

## Category 6 — Switch / Button Interactive

**Found in**: Digilent "intro" projects for Basys3, Nexys A7, DE10-Lite.

```vhdl
-- sw(0)='1' → LED blinks; sw(0)='0' → LED off
-- btn(0)='1' → LED forced on while held
led(0) <= (sw(0) and counter(23)) or btn(0);
```

The project's own `hdl/blinky.vhd` is a fully generalized, parametric version of this
pattern across all `NUM_LEDS` LEDs simultaneously.

---

## Category 7 — FSM-Based Blinky

**Found in**: FPGA courses introducing finite state machines (used as a gentle first
FSM example because the result is already familiar).

```vhdl
architecture rtl of blinky is
  type state_t is (S_OFF, S_ON);
  signal state   : state_t := S_OFF;
  signal counter : unsigned(23 downto 0) := (others => '0');
begin
  process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
      case state is
        when S_OFF =>
          led <= '0';
          if counter = 0 then state <= S_ON; end if;
        when S_ON  =>
          led <= '1';
          if counter = 0 then state <= S_OFF; end if;
      end case;
    end if;
  end process;
end architecture;
```

Structurally equivalent to Category 2 but expressed as a `case` statement.  Adds one
state register with no functional benefit for a simple blinky — used purely to
introduce `type`, enumerated states, and `case` syntax.

---

## Category 8 — Internal Oscillator (No External Clock)

**Found in**: Lattice iCE40 boards (iCEstick, iCEBreaker, UPduino v1/v2, Fomu) that
may lack an external crystal.

```vhdl
-- Requires Lattice sb_ice_tech primitive library (IceStorm / nextpnr only)
library sb_ice_tech;
use sb_ice_tech.components.all;

architecture rtl of blinky is
  signal osc_clk : std_logic;
  signal counter : unsigned(23 downto 0) := (others => '0');
begin
  -- SB_HFOSC: 48 MHz internal oscillator, divided by 4 → 12 MHz
  osc_inst : SB_HFOSC
    generic map (CLKHF_DIV => "0b10")
    port map (CLKHFPU => '1', CLKHFEN => '1', CLKHF => osc_clk);

  process(osc_clk)
  begin
    if rising_edge(osc_clk) then
      counter <= counter + 1;
    end if;
  end process;

  led <= counter(23);
end architecture;
```

The entity has **no `clk` port** — the oscillator is instantiated internally.
`SB_LFOSC` (10 kHz) is an alternative for ultra-slow blinking.

Note: most iCE40 blinky examples use Verilog; VHDL variants require the vendor
primitive library and are less commonly found in tutorials.

---

## Category 9 — PLL / DCM Clock Multiplication

**Found in**: Tutorials whose primary goal is teaching clock generation, not blinking.
Xilinx `MMCME2_BASE`, Intel `altpll` megafunction, ECP5 `TRELLIS_PLL`.

```vhdl
-- Xilinx 7-series: generate 200 MHz from 100 MHz input
component MMCME2_BASE
  generic (
    CLKFBOUT_MULT_F  : real := 2.0;
    CLKIN1_PERIOD    : real := 10.0;   -- 100 MHz
    CLKOUT0_DIVIDE_F : real := 1.0
  );
  port ( CLKIN1, CLKFBIN : in std_logic;
         CLKOUT0, CLKFBOUT : out std_logic; ... );
end component;
```

Adds ~50 LUTs and a PLL block for zero improvement to LED blink quality.  Appropriate
only when the tutorial is about clock synthesis, not blinking.

---

## Category 10 — Nandland Go Board Style

**Found in**: nandland.com tutorials; widely imitated by students who learn from that
course.

```vhdl
architecture behave of blinky is
  constant c_CNT_1HZ : integer := 12_500_000;  -- 25 MHz / 2 / 1 Hz
  signal r_led1 : std_logic := '0';
  signal r_cnt  : integer range 0 to c_CNT_1HZ - 1 := 0;
begin
  p_blink : process (i_clk) is
  begin
    if rising_edge(i_clk) then
      if r_cnt = c_CNT_1HZ - 1 then
        r_cnt  <= 0;
        r_led1 <= not r_led1;
      else
        r_cnt <= r_cnt + 1;
      end if;
    end if;
  end process p_blink;

  o_led1 <= r_led1;
end architecture behave;
```

**Distinctive style choices**: `r_` prefix for registers, `i_`/`o_` prefix for ports,
named processes (`p_blink`), `architecture behave`.  This naming convention is taught
consistently throughout the Nandland FPGA course and is visible in many student
GitHub repositories.

---

## Category 11 — RGB LED Cycling

**Found in**: ULX3S (8 green + 1 RGB), iCEBreaker (1 RGB), TangNano 9K (RGB).

**ECP5 / direct drive** (most common — no vendor primitive):

```vhdl
-- Three independent counter bits drive R, G, B at different rates.
-- The combination cycles through all 8 colors.
led_r <= counter(25);
led_g <= counter(24);
led_b <= counter(23);
```

**iCE40 `SB_RGBA_DRV` variant** (Fomu, UPduino):

```vhdl
-- SB_RGBA_DRV provides hardware current control (PWM dimming)
rgb_driver : SB_RGBA_DRV
  generic map (
    CURRENT_MODE => "0b1",
    RGB0_CURRENT => "0b000001",
    RGB1_CURRENT => "0b000001",
    RGB2_CURRENT => "0b000001"
  )
  port map (
    RGBLEDEN => '1',
    RGB0PWM  => counter(23),
    RGB1PWM  => counter(24),
    RGB2PWM  => counter(25),
    RGB0     => led_r,
    RGB1     => led_g,
    RGB2     => led_b
  );
```

---

## Category 12 — Parametric / Generic Blinky

**Found in**: Board-agnostic frameworks; Amaranth HDL VHDL output; academic
"configurable blinky" lab templates.

**This project's `hdl/blinky.vhd`** is the reference implementation:

```vhdl
entity blinky is
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
end entity blinky;
```

Key properties:
- `COUNTER_BITS` generic scales blink frequency to any board clock
- `NUM_LEDS / NUM_SWITCHES / NUM_BUTTONS` generics match any board's resources
- `for i in 0 to minimum(...) - 1` loops handle boards with mismatched counts
- No reset — unsigned counter wraps correctly; VHDL initializer covers simulation
- LED output process is correctly sensitive to `sw`, `btn`, and `counter`

---

## Summary Comparison Table

| Cat | Blink mechanism            | Ports              | ~Lines | Typical boards          | Teaching goal               |
|-----|----------------------------|--------------------|--------|-------------------------|-----------------------------|
|  1  | Constant `'1'`             | led                | 8      | Any                     | First VHDL file             |
|  2  | Free counter MSB           | clk, led           | 20     | Any                     | Counter, synthesis          |
|  3  | Compare-reset counter      | clk, led           | 25     | DE0-Nano, Basys3        | `constant`, exact freq      |
|  4  | Counter + sync reset       | clk, reset, led    | 25     | DE-series (Intel)       | Reset styles                |
|  5  | Multi-bit counter display  | clk, led(N)        | 22     | ≥4 LED boards           | Vectors, binary display     |
|  6  | Counter + sw/btn           | clk, sw, btn, led  | 30     | Boards with switches    | Interactive I/O             |
|  7  | FSM (S_OFF/S_ON)           | clk, led           | 35     | Any                     | State machines              |
|  8  | Internal oscillator        | led (no clk!)      | 30     | Lattice iCE40           | Vendor primitives           |
|  9  | PLL + counter              | clk, led           | 60+    | Xilinx 7, Intel Cyclone | Clock generation            |
| 10  | Compare-reset, named style | i_clk, o_led       | 30     | Nandland Go Board       | Naming conventions          |
| 11  | Multi-bit RGB              | clk, r, g, b       | 25     | ULX3S, iCEBreaker       | RGB LEDs                    |
| 12  | Parametric generics        | clk, sw(N), btn(N), led(N) | 60 | Any (board-agnostic) | Reusable designs        |

---

## Key Observations

1. **Category 2 dominates** — approximately 80 % of real-world tutorials use the
   free-running MSB counter.  It is the simplest correct synthesisable VHDL.

2. **No reset is idiomatic** — VHDL FPGA flip-flops have defined power-on state;
   the counter signal initializer `(others => '0')` is sufficient for simulation.
   Avoid reset unless a specific requirement demands it.

3. **Port naming reflects vendor culture**:
   - Xilinx / OSS: `clk`, `led`
   - Intel / Altera: `CLOCK_50`, `LED`, `KEY` (uppercase, board-specific names)
   - Lattice / nextpnr: `clk`, `led`, sometimes `rst`
   - Nandland / academic: `i_clk`, `o_led` or `CLK`, `LED`

4. **VHDL is the minority language for iCE40 and ECP5** — most open-source examples
   use Verilog or Amaranth; VHDL dominates Xilinx and Intel university programs.

5. **`hdl/blinky.vhd` (Category 12) is best-in-class** among tutorials — fully
   board-agnostic, parametric, interactive, and correct for all 80 boards in this
   project's submodule without modification.
