-- U56 Phase 6 end-to-end fixture: Amaranth iCEBreaker, mono + mono aliases.
-- led_r / led_g are upstream's "semantic aliases" of led 0 and 1 (active-low).
-- Red on, green off: the boundary shows led(0) lit, led(1) dark.
library ieee;
use ieee.std_logic_1164.all;

entity alias_icebreaker is
  port (
    clk12  : in  std_logic;
    button : in  std_logic;
    led_r  : out std_logic;
    led_g  : out std_logic
  );
end entity;

architecture rtl of alias_icebreaker is
begin
  led_r <= '0';
  led_g <= '1';
end architecture;
