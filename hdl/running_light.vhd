-- running_light.vhd  --  One lit LED walks along the row, at a hardware rate.
--
-- A single lit LED steps left, wraps, and repeats.  The interesting part is
-- not the walk: it is DIVIDER_BITS, and the fact that its default is wrong for
-- this simulator on purpose.
--
-- -- WHY THIS DESIGN LOOKS FROZEN AT FIRST -------------------------------------
--
-- On a real board the clock is tens of megahertz, so a design slows itself
-- down by counting: with a 50 MHz clock, waiting 2**24 cycles between steps is
--
--     2**24 / 50e6 = 0.34 s per step
--
-- which is a comfortable walking speed.  DIVIDER_BITS therefore defaults to 24,
-- the value you would actually synthesize.  A simulator does not run at 50 MHz.
-- It simulates a few tens of thousands of clock cycles per second, so the same
-- 2**24 cycles take **minutes**, and the board sits there looking broken.
--
-- That is not a bug in the design or in the simulator; it is the difference
-- between the two clocks, and it is the single most common surprise when a
-- design that works on the bench is brought here.  You have three ways out:
--
--   * `uv run fpga-sim --generic DIVIDER_BITS=15 --vhdl hdl/running_light.vhd`
--   * the [Generics...] button on the preview screen, before you press Start
--   * edit the default below -- but then the file no longer suits hardware
--
-- Leave the file alone and override it instead: that is the habit worth
-- forming, because the design is *correct* and only the environment differs.
-- If you run it unchanged, the simulator notices the board has gone quiet and
-- offers to explain, naming this generic and the value to try.
--
-- Effect  : One LED walks the row; the rest are dark.  Slow until you say so.
-- Teaches : Clock division, a shift-register walk, and generics as the knob
--           that separates a design from the machine it is running on.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity running_light is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24;  -- unused; the contract supplies it

    -- How many clock cycles between steps, as a power of two.  24 suits a
    -- 50 MHz board (~0.34 s per step).  In this simulator, try 15.
    DIVIDER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity;

architecture rtl of running_light is

  -- The prescaler.  It counts every clock cycle and wraps every 2**DIVIDER_BITS
  -- of them; the wrap is what advances the walk.
  signal divider  : unsigned(DIVIDER_BITS - 1 downto 0) := (others => '0');

  -- Which LED is lit, 0 .. NUM_LEDS-1.
  signal position : natural range 0 to NUM_LEDS - 1 := 0;

begin

  -- One process, two jobs kept clearly apart: the prescaler always counts, and
  -- the position moves only on the cycle the prescaler wraps.  Writing it this
  -- way -- rather than as two processes, or with the position in its own clock
  -- domain -- keeps everything on the single clock edge, which is what makes
  -- the design synthesizable without further thought.
  step : process (clk) is
  begin
    if rising_edge(clk) then
      divider <= divider + 1;

      if divider = (divider'range => '1') then     -- the wrap, once per 2**N
        if position = NUM_LEDS - 1 then
          position <= 0;
        else
          position <= position + 1;
        end if;
      end if;
    end if;
  end process step;

  -- Exactly one LED on: a one-hot decode of `position`.
  drive : process (position) is
    variable out_v : std_logic_vector(NUM_LEDS - 1 downto 0);
  begin
    out_v := (others => '0');
    out_v(position) := '1';
    led <= out_v;
  end process drive;

end architecture;
