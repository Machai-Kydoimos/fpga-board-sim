-- de0.vhd
--
-- A board-native design for the Terasic DE0 (Cyclone III), written to the
-- board's own pin names with fixed widths and no simulator generics.  It
-- simulates unmodified under fpga-sim (U21 board-native).
--
-- The DE0 differs from the newer Terasic boards in several ways this example
-- exercises: its LEDs are GREEN (LEDG, active-high, no red LEDR bank), its
-- push-buttons are named BUTTON (not KEY, active-low), and each 7-seg digit is
-- a split port -- a 7-bit segment vector HEXn_D plus a separate decimal-point
-- scalar HEXn_DP -- with four digits (HEX0..HEX3).  Segments are active-low.
--
-- Behavior: a free-running counter (reset by BUTTON0) drives the green LEDs and
-- a four-digit hexadecimal readout; the decimal points stay off.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity de0 is
  port (
    CLOCK_50 : in  std_logic;
    SW       : in  std_logic_vector(9 downto 0);
    BUTTON   : in  std_logic_vector(2 downto 0);
    LEDG     : out std_logic_vector(9 downto 0);
    HEX0_D   : out std_logic_vector(6 downto 0);
    HEX1_D   : out std_logic_vector(6 downto 0);
    HEX2_D   : out std_logic_vector(6 downto 0);
    HEX3_D   : out std_logic_vector(6 downto 0);
    HEX0_DP  : out std_logic;
    HEX1_DP  : out std_logic;
    HEX2_DP  : out std_logic;
    HEX3_DP  : out std_logic
  );
end entity;

architecture rtl of de0 is

  -- Active-high 7-segment font, bit 0 = segment a .. bit 6 = segment g.
  function seg7(nibble : std_logic_vector(3 downto 0)) return std_logic_vector is
  begin
    case nibble is
      when x"0" => return "0111111";
      when x"1" => return "0000110";
      when x"2" => return "1011011";
      when x"3" => return "1001111";
      when x"4" => return "1100110";
      when x"5" => return "1101101";
      when x"6" => return "1111101";
      when x"7" => return "0000111";
      when x"8" => return "1111111";
      when x"9" => return "1101111";
      when x"a" => return "1110111";
      when x"b" => return "1111100";
      when x"c" => return "0111001";
      when x"d" => return "1011110";
      when x"e" => return "1111001";
      when others => return "1110001";  -- f
    end case;
  end function;

  signal count : unsigned(31 downto 0) := (others => '0');

begin

  -- SW is part of the DE0 interface; unused in this minimal demo.

  process (CLOCK_50)
  begin
    if rising_edge(CLOCK_50) then
      if BUTTON(0) = '0' then         -- BUTTON is active-low: pressed drives '0'
        count <= (others => '0');
      else
        count <= count + 1;
      end if;
    end if;
  end process;

  -- LEDG (green LEDs) are active-high: drive the counter bits directly.
  LEDG <= std_logic_vector(count(27 downto 18));

  -- Four-digit hex readout; the segment vectors are active-low.
  HEX0_D <= not seg7(std_logic_vector(count(19 downto 16)));
  HEX1_D <= not seg7(std_logic_vector(count(23 downto 20)));
  HEX2_D <= not seg7(std_logic_vector(count(27 downto 24)));
  HEX3_D <= not seg7(std_logic_vector(count(31 downto 28)));

  -- Decimal points off ('1' is off for an active-low segment).
  HEX0_DP <= '1';
  HEX1_DP <= '1';
  HEX2_DP <= '1';
  HEX3_DP <= '1';

end architecture;
