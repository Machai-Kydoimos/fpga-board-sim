-- A design in the pre-standard Synopsys dialect, written to the generic
-- contract so it exercises the whole pipeline (analyze -> elaborate -> run)
-- rather than only the detector.  Both packages GHDL gates behind -fsynopsys
-- are used for real: conv_integer from std_logic_arith, "+" on a
-- std_logic_vector from std_logic_unsigned.
library ieee;
use ieee.std_logic_1164.all;
use ieee.std_logic_arith.all;
use ieee.std_logic_unsigned.all;

entity synopsys_blinky is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS - 1 downto 0)
  );
end synopsys_blinky;

architecture rtl of synopsys_blinky is
  signal counter : std_logic_vector(COUNTER_BITS - 1 downto 0) := (others => '0');
  signal step    : integer range 0 to 15 := 0;
begin
  -- std_logic_unsigned supplies "+" directly on the vector.
  tick : process (clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process tick;

  -- std_logic_arith supplies conv_integer.
  step <= conv_integer(sw(1 downto 0)) when btn(0) = '0' else 0;

  led(0) <= counter(counter'high);
  drive_rest : for i in 1 to NUM_LEDS - 1 generate
    led(i) <= '1' when step = i else '0';
  end generate drive_rest;
end rtl;
