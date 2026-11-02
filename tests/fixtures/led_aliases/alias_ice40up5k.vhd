-- U56 Phase 6 end-to-end fixture: LiteX iCE40UP5K EVN, three names on one RGB LED.
-- user_ledr_n / user_ledg_n / user_ledb_n are its r, g, b (active-low).  Only red
-- is on, so the boundary reads "001": a map by bank order would light blue.
library ieee;
use ieee.std_logic_1164.all;

entity alias_ice40up5k is
  port (
    clk12       : in  std_logic;
    user_sw     : in  std_logic_vector(3 downto 0);
    user_ledr_n : out std_logic;
    user_ledg_n : out std_logic;
    user_ledb_n : out std_logic
  );
end entity;

architecture rtl of alias_ice40up5k is
begin
  user_ledr_n <= '0';
  user_ledg_n <= '1';
  user_ledb_n <= '1';
end architecture;
