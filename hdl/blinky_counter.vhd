-- blinky_counter.vhd - Binary counter display blinky.
--
-- All LEDs display a sliding window of bits from a free-running counter,
-- showing the raw binary count.  With no switches active the window sits at
-- the upper (slow) bits; each additional active switch shifts the window two
-- bit positions toward the LSB, doubling the visible count rate.
-- Holding any button forces all LEDs on.
--
-- Effect  : LEDs count upward in binary with a right-to-left ripple.
-- Teaches : std_logic_vector slicing, dynamic bit-index selection.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity blinky_counter is
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
end entity blinky_counter;

architecture rtl of blinky_counter is
  signal counter : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
begin

  -- Free-running counter
  count_proc : process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  -- LED output: map a window of counter bits onto the LEDs.
  --
  -- Window base (no switches) = COUNTER_BITS - NUM_LEDS  (upper/slow bits).
  -- Each active switch shifts the base 2 positions toward the LSB, making
  -- the count run faster.  The base is clamped so the window always fits
  -- within the counter.
  --
  -- Any active button overrides and forces all LEDs on.
  led_proc : process(counter, sw, btn)
    variable n_sw     : integer range 0 to NUM_SWITCHES;
    variable max_off  : integer range 0 to COUNTER_BITS;
    variable offset   : integer range 0 to COUNTER_BITS;
    variable base     : integer range 0 to COUNTER_BITS - 1;
    variable bit_idx  : integer range 0 to COUNTER_BITS - 1;
    variable force_on : std_logic;
  begin
    -- Count active switches
    n_sw := 0;
    for i in 0 to NUM_SWITCHES - 1 loop
      if sw(i) = '1' then
        n_sw := n_sw + 1;
      end if;
    end loop;

    -- Maximum allowed offset keeps the top of the window at COUNTER_BITS-1
    if COUNTER_BITS > NUM_LEDS then
      max_off := COUNTER_BITS - NUM_LEDS;
    else
      max_off := 0;
    end if;

    offset := n_sw * 2;
    if offset > max_off then
      offset := max_off;
    end if;

    base := max_off - offset;   -- lowest bit index of the window

    -- Any button forces all LEDs on
    force_on := '0';
    for i in 0 to NUM_BUTTONS - 1 loop
      force_on := force_on or btn(i);
    end loop;

    -- Map counter bits to LEDs; LED 0 = base bit (slowest in window)
    for i in 0 to NUM_LEDS - 1 loop
      bit_idx := base + i;
      if bit_idx > COUNTER_BITS - 1 then
        bit_idx := COUNTER_BITS - 1;
      end if;
      if force_on = '1' then
        led(i) <= '1';
      else
        led(i) <= counter(bit_idx);
      end if;
    end loop;
  end process led_proc;

end architecture rtl;
