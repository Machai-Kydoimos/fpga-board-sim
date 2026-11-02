-- U56 Phase 6 end-to-end fixture: LiteX OrangeCrab, mono names on an RGB LED.
-- user_led 0-2 are the rgb_led's r, g, b (upstream: "# rgb_led.r/.g/.b").
-- Red off, green and blue on: the boundary's RGB site shows "110".
library ieee;
use ieee.std_logic_1164.all;

entity alias_orangecrab is
  port (
    clk48    : in  std_logic;
    usr_btn  : in  std_logic;
    user_led : out std_logic_vector(2 downto 0)
  );
end entity;

architecture rtl of alias_orangecrab is
begin
  user_led <= "110";
end architecture;
