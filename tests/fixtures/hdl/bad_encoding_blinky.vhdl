-- bad_encoding_blinky.vhdl - Fails Stage 1 (encoding check).
--
-- DELIBERATE FLAW: the file begins with a UTF-8 BOM (EF BB BF).
-- The encoding checker rejects BOM-prefixed files because GHDL and
-- many synthesis tools do not tolerate them.
-- The entity name, ports, generics, and VHDL syntax are all correct.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity bad_encoding_blinky is
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
end entity bad_encoding_blinky;

architecture rtl of bad_encoding_blinky is
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
