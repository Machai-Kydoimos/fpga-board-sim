-- blinky.vhd – Simple blinky design for FPGA simulator testing.
--
-- Directly wires switches to LEDs, with a clock-driven counter
-- that XORs the upper counter bits onto the LED outputs to create
-- a visible blinking effect.
--
-- Generics let the testbench size the design to match any board.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

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

architecture rtl of blinky is
  signal counter : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
begin

  -- Free-running counter
  count_proc : process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  -- LED output logic:
  --   Each LED = corresponding switch XOR a counter bit,
  --   so switches toggle LEDs and the counter makes them blink.
  --   Buttons directly OR into the LEDs (active while held).
  led_proc : process(sw, btn, counter)
    variable tmp : std_logic_vector(NUM_LEDS - 1 downto 0);
  begin
    tmp := (others => '0');

    -- Map switches: XOR with upper counter bits for blink effect
    for i in 0 to minimum(NUM_SWITCHES, NUM_LEDS) - 1 loop
      tmp(i) := sw(i) xor counter(COUNTER_BITS - 1 - (i mod COUNTER_BITS));
    end loop;

    -- Map buttons: OR directly (active-high while pressed)
    for i in 0 to minimum(NUM_BUTTONS, NUM_LEDS) - 1 loop
      tmp(i) := tmp(i) or btn(i);
    end loop;

    led <= tmp;
  end process led_proc;

end architecture rtl;
