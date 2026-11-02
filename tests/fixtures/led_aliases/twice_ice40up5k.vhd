-- U56 Phase 6 fixture: one LED under two names in one design, LiteX iCE40UP5K EVN.
-- user_led_n and user_ledb_n are both the RGB LED's blue (pin 39), and a pin can
-- have only one driver, so the contract check refuses the design. It is never
-- simulated.
library ieee;
use ieee.std_logic_1164.all;

entity twice_ice40up5k is
  port (
    clk12       : in  std_logic;
    user_sw     : in  std_logic_vector(3 downto 0);
    user_led_n  : out std_logic;
    user_ledb_n : out std_logic
  );
end entity;

architecture rtl of twice_ice40up5k is
begin
  user_led_n  <= user_sw(0);
  user_ledb_n <= user_sw(1);
end architecture;
