-- de10_standard.vhd
--
-- A board-native design for the Terasic DE10-Standard, written to the board's
-- own pin names (CLOCK_50, SW, KEY, LEDR, HEX0..HEX5) with fixed widths and no
-- simulator generics.  It simulates unmodified under fpga-sim (U21 board-native).
--
-- The DE10-Standard's LEDR are ACTIVE-HIGH (a '1' lights the LED) while its HEX
-- segments are ACTIVE-LOW -- a common Terasic mix this example exercises.
--
-- Behavior: a free-running counter (reset by KEY0, active-low) drives the ten
-- LEDs and a six-digit hexadecimal readout.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity de10_standard is
  port (
    CLOCK_50 : in  std_logic;
    SW       : in  std_logic_vector(9 downto 0);
    KEY      : in  std_logic_vector(3 downto 0);
    LEDR     : out std_logic_vector(9 downto 0);
    HEX0     : out std_logic_vector(6 downto 0);
    HEX1     : out std_logic_vector(6 downto 0);
    HEX2     : out std_logic_vector(6 downto 0);
    HEX3     : out std_logic_vector(6 downto 0);
    HEX4     : out std_logic_vector(6 downto 0);
    HEX5     : out std_logic_vector(6 downto 0)
  );
end entity;

architecture rtl of de10_standard is

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

  -- SW is part of the DE10-Standard interface; unused in this minimal demo.

  process (CLOCK_50)
  begin
    if rising_edge(CLOCK_50) then
      if KEY(0) = '0' then           -- KEY is active-low: pressed drives '0'
        count <= (others => '0');
      else
        count <= count + 1;
      end if;
    end if;
  end process;

  -- LEDR is active-high on the DE10-Standard: drive the counter bits directly.
  LEDR <= std_logic_vector(count(27 downto 18));

  -- Six-digit hex readout of the counter; HEX segments are active-low.
  HEX0 <= not seg7(std_logic_vector(count(19 downto 16)));
  HEX1 <= not seg7(std_logic_vector(count(23 downto 20)));
  HEX2 <= not seg7(std_logic_vector(count(27 downto 24)));
  HEX3 <= not seg7(std_logic_vector(count(31 downto 28)));
  HEX4 <= not seg7(std_logic_vector(count(25 downto 22)));
  HEX5 <= not seg7(std_logic_vector(count(29 downto 26)));

end architecture;
