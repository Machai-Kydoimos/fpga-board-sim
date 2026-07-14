-- arty_litex.vhd
--
-- A board-native design for the Digilent Arty written to its LiteX platform port
-- names (CLOCK is clk100; user_led / user_sw / user_btn) with fixed widths and no
-- simulator generics.  It simulates unmodified under fpga-sim via the U32
-- framework-derived convention: boards/litex-boards/digilent_arty.json carries an
-- auto-derived `port_conventions.litex` block, matched here.
--
-- Unlike the Terasic examples, the LiteX names are *generic* (many litex boards
-- share user_led / user_sw / user_btn), so this file is representative rather than
-- Arty-specific.  The Arty's user_led / user_sw / user_btn are active-high in the
-- LiteX _io file; the board also has four rgb_led, so its LED count (8) exceeds the
-- user_led bank (4) -- the wrapper drives the bank and leaves the rest dark.
--
-- Like the other hdl/native examples it matches only via a board's convention and
-- is deliberately NOT surfaced in the file picker.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity arty_litex is
  port (
    clk100   : in  std_logic;
    user_sw  : in  std_logic_vector(3 downto 0);
    user_btn : in  std_logic_vector(3 downto 0);
    user_led : out std_logic_vector(3 downto 0)
  );
end entity;

architecture rtl of arty_litex is
  signal count : unsigned(27 downto 0) := (others => '0');
begin

  process (clk100)
  begin
    if rising_edge(clk100) then
      if user_btn(0) = '1' then          -- LiteX buttons active-high: pressed = '1'
        count <= (others => '0');
      else
        count <= count + 1;
      end if;
    end if;
  end process;

  -- Tap MID counter bits: board-native designs get no COUNTER_BITS override, so
  -- the top of a full 100 MHz divider would be invisible at sim speed.  user_sw
  -- XORs the pattern so the switches visibly affect the LEDs.
  user_led <= std_logic_vector(count(21 downto 18)) xor user_sw;

end architecture;
