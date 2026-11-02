-- U56 Phase 6 fixture: one LED under two names in one design, Amaranth iCEBreaker.
-- led(0) and led_r are both pin 11, and a pin can have only one driver, so the
-- contract check refuses the design. It is never simulated.
library ieee;
use ieee.std_logic_1164.all;

entity twice_icebreaker is
  port (
    clk12  : in  std_logic;
    button : in  std_logic;
    led    : out std_logic_vector(1 downto 0);
    led_r  : out std_logic
  );
end entity;

architecture rtl of twice_icebreaker is
begin
  led   <= "10";
  led_r <= '1';
end architecture;
