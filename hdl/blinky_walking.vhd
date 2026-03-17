-- blinky_walking.vhd – Walking LED (Knight Rider) blinky.
--
-- A single lit LED bounces back and forth across all available LEDs.
-- The step rate is derived from the free-running counter: with no switches,
-- the LED advances on every MSB transition (slowest).  Each additional active
-- switch doubles the step rate by moving the trigger two bit positions toward
-- the LSB.
--
-- btn(0) : each press reverses the walking direction
-- btn(1) : held — all LEDs on simultaneously
--
-- Effect  : Single lit LED ping-pongs across the board.
-- Teaches : Shift register emulation, direction control, boundary detection.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity blinky_walking is
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
end entity blinky_walking;

architecture rtl of blinky_walking is
  signal counter   : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
  signal position  : integer range 0 to NUM_LEDS - 1 := 0;
  signal fwd       : std_logic := '1';     -- '1' = toward higher index
  signal prev_step : std_logic := '0';     -- previous value of the trigger bit
  signal prev_btn0 : std_logic := '0';     -- for edge detection on btn(0)
  signal step_idx  : integer range 0 to COUNTER_BITS - 1 := COUNTER_BITS - 1;
begin

  -- Free-running counter
  count_proc : process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  -- Derive step_idx from switch popcount.
  -- Each active switch moves the trigger bit 2 positions toward the LSB,
  -- doubling the step rate.  Index is clamped to [1, COUNTER_BITS-1].
  idx_proc : process(sw)
    variable n   : integer range 0 to NUM_SWITCHES;
    variable idx : integer;
  begin
    n := 0;
    for i in 0 to NUM_SWITCHES - 1 loop
      if sw(i) = '1' then
        n := n + 1;
      end if;
    end loop;
    idx := COUNTER_BITS - 1 - n * 2;
    if idx < 1 then
      idx := 1;
    end if;
    step_idx <= idx;
  end process idx_proc;

  -- Walk logic: advance position on the rising edge of counter(step_idx).
  -- btn(0) edge → reverse direction.
  walk_proc : process(clk)
    variable fwd_v : std_logic;
    variable pos_v : integer range 0 to NUM_LEDS - 1;
  begin
    if rising_edge(clk) then
      fwd_v := fwd;
      pos_v := position;

      -- Latch previous step bit for edge detection
      prev_step <= counter(step_idx);

      -- Advance position on rising edge of trigger bit
      if prev_step = '0' and counter(step_idx) = '1' then
        if fwd_v = '1' then
          if pos_v = NUM_LEDS - 1 then
            fwd_v := '0';
            pos_v := pos_v - 1;   -- bounce: reverse and step immediately
          else
            pos_v := pos_v + 1;
          end if;
        else
          if pos_v = 0 then
            fwd_v := '1';
            pos_v := pos_v + 1;   -- bounce: reverse and step immediately
          else
            pos_v := pos_v - 1;
          end if;
        end if;
      end if;

      -- btn(0) rising edge reverses direction
      prev_btn0 <= '0';
      if NUM_BUTTONS >= 1 then
        prev_btn0 <= btn(0);
        if prev_btn0 = '0' and btn(0) = '1' then
          fwd_v := not fwd_v;
        end if;
      end if;

      fwd      <= fwd_v;
      position <= pos_v;
    end if;
  end process walk_proc;

  -- LED output: light only the current position; btn(1) overrides to all-on
  led_proc : process(position, btn)
    variable all_on : std_logic;
  begin
    all_on := '0';
    if NUM_BUTTONS >= 2 then
      all_on := btn(1);
    end if;

    for i in 0 to NUM_LEDS - 1 loop
      if all_on = '1' then
        led(i) <= '1';
      elsif i = position then
        led(i) <= '1';
      else
        led(i) <= '0';
      end if;
    end loop;
  end process led_proc;

end architecture rtl;
