-- de25_standard.vhd
--
-- A board-native design for the Terasic DE25-Standard, written to the board's
-- own pin names (CLOCK0_50, SW, KEY, LEDR, HEX0..HEX5) with fixed widths and no
-- simulator generics.  It simulates unmodified under fpga-sim thanks to U21
-- board-native support: the simulator recognizes the DE25 port convention and
-- generates a wrapper that adapts these native ports (polarity + 7-seg packing)
-- to its clk/sw/btn/led/seg boundary.
--
-- The DE25-Standard is an Agilex board whose LEDR and HEX segments are
-- ACTIVE-LOW (driving a pin to '0' turns the LED/segment on), so this design
-- inverts its internal active-high values on the way out.
--
-- Behavior: a free-running counter (reset by KEY0, which is active-low) drives
-- the ten LEDs and a six-digit hexadecimal readout.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity de25_standard is
  port (
    CLOCK0_50 : in  std_logic;
    SW        : in  std_logic_vector(9 downto 0);
    KEY       : in  std_logic_vector(3 downto 0);
    LEDR      : out std_logic_vector(9 downto 0);
    HEX0      : out std_logic_vector(6 downto 0);
    HEX1      : out std_logic_vector(6 downto 0);
    HEX2      : out std_logic_vector(6 downto 0);
    HEX3      : out std_logic_vector(6 downto 0);
    HEX4      : out std_logic_vector(6 downto 0);
    HEX5      : out std_logic_vector(6 downto 0)
  );
end entity;

architecture rtl of de25_standard is

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

  -- SW is part of the DE25-Standard interface; unused in this minimal demo.

  process (CLOCK0_50)
  begin
    if rising_edge(CLOCK0_50) then
      if KEY(0) = '0' then           -- KEY is active-low: pressed drives '0'
        count <= (others => '0');
      else
        count <= count + 1;
      end if;
    end if;
  end process;

  -- LEDR is active-low: invert so a '1' bit lights its LED.
  LEDR <= not std_logic_vector(count(27 downto 18));

  -- Six-digit hex readout of the counter; HEX segments are active-low.
  HEX0 <= not seg7(std_logic_vector(count(19 downto 16)));
  HEX1 <= not seg7(std_logic_vector(count(23 downto 20)));
  HEX2 <= not seg7(std_logic_vector(count(27 downto 24)));
  HEX3 <= not seg7(std_logic_vector(count(31 downto 28)));
  HEX4 <= not seg7(std_logic_vector(count(25 downto 22)));
  HEX5 <= not seg7(std_logic_vector(count(29 downto 26)));

end architecture;
