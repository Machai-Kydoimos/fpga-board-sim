-- bad_ghdl_blinky.vhdl - Fails Stage 3 (GHDL analysis).
--
-- DELIBERATE FLAW: "use ieee.numeric_std.all;" is omitted, so the
-- "unsigned" type is undefined.  GHDL -a will report an error.
-- Encoding is clean ASCII and the entity name matches the filename.

library ieee;
use ieee.std_logic_1164.all;
-- use ieee.numeric_std.all;   <-- intentionally removed

entity bad_ghdl_blinky is
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
end entity bad_ghdl_blinky;

architecture rtl of bad_ghdl_blinky is
  -- "unsigned" is unknown without ieee.numeric_std
  signal counter : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
begin

  count_proc : process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  led_proc : process(sw, btn, counter)
    variable tmp : std_logic_vector(NUM_LEDS - 1 downto 0);
  begin
    tmp := (others => '0');
    for i in 0 to minimum(NUM_SWITCHES, NUM_LEDS) - 1 loop
      tmp(i) := sw(i) xor counter(COUNTER_BITS - 1 - (i mod COUNTER_BITS));
    end loop;
    for i in 0 to minimum(NUM_BUTTONS, NUM_LEDS) - 1 loop
      tmp(i) := tmp(i) or btn(i);
    end loop;
    led <= tmp;
  end process led_proc;

end architecture rtl;
