-- de10_lite.vhd
--
-- A board-native design for the Terasic DE10-Lite, written to the board's own
-- pin names (MAX10_CLK1_50, SW, KEY, LEDR, HEX0..HEX5) with fixed widths and
-- no simulator generics.  It simulates unmodified under fpga-sim (U21).
--
-- POLARITY, WHICH IS THE WHOLE POINT OF WRITING IT THIS WAY:
--   LEDR  is ACTIVE-HIGH  -- a '1' lights the LED.
--   KEY   is ACTIVE-LOW   -- a pressed key reads '0'.
--   HEX0..HEX5 are ACTIVE-LOW -- a '0' lights the segment.
-- The file therefore drives the *physical* levels the real board wants, which
-- is why it can be moved to Quartus unchanged.  The simulator's wrapper undoes
-- each polarity on the way to its own active-high boundary, so what you see on
-- screen matches what you would see on the bench.
--
-- Behavior: a free-running counter drives the ten LEDs and a six-digit hex
-- readout.  KEY(0) held resets the counter; KEY(1) held freezes it.
--
-- A note on the counter taps.  Board-native designs get no COUNTER_BITS
-- override from the simulator -- that generic belongs to the generic contract,
-- and this file deliberately has no generics at all -- so a design that shows
-- the *top* bits of a 50 MHz divider would appear frozen here.  The taps below
-- are mid-counter for that reason: fast enough to watch in simulation, and
-- still a sensible rate on real hardware.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity de10_lite is
  port (
    MAX10_CLK1_50 : in  std_logic;
    SW            : in  std_logic_vector(9 downto 0);
    KEY           : in  std_logic_vector(1 downto 0);
    LEDR          : out std_logic_vector(9 downto 0);
    HEX0          : out std_logic_vector(6 downto 0);
    HEX1          : out std_logic_vector(6 downto 0);
    HEX2          : out std_logic_vector(6 downto 0);
    HEX3          : out std_logic_vector(6 downto 0);
    HEX4          : out std_logic_vector(6 downto 0);
    HEX5          : out std_logic_vector(6 downto 0)
  );
end entity;

architecture rtl of de10_lite is

  -- Active-high font, bit 0 = segment a .. bit 6 = segment g.  It is inverted
  -- once at each port below, because the DE10-Lite's HEX displays are wired
  -- active-low.  Keeping the font positive and inverting at the boundary is
  -- easier to read than a table of complemented constants.
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
      when x"A" => return "1110111";
      when x"B" => return "1111100";
      when x"C" => return "0111001";
      when x"D" => return "1011110";
      when x"E" => return "1111001";
      when others => return "1110001";  -- F
    end case;
  end function;

  signal count : unsigned(31 downto 0) := (others => '0');

begin

  process (MAX10_CLK1_50) is
  begin
    if rising_edge(MAX10_CLK1_50) then
      if KEY(0) = '0' then          -- active-low: pressed reads '0'
        count <= (others => '0');
      elsif KEY(1) = '0' then
        null;                        -- held: freeze
      else
        count <= count + 1;
      end if;
    end if;
  end process;

  -- LEDR is active-high, so the counter bits drive it directly.  SW(9 downto 0)
  -- XORs in, which makes the switches visibly yours without changing the rate.
  LEDR <= std_logic_vector(count(24 downto 15)) xor SW;

  -- Six-digit hex readout, inverted for the active-low displays.
  HEX0 <= not seg7(std_logic_vector(count(15 downto 12)));
  HEX1 <= not seg7(std_logic_vector(count(19 downto 16)));
  HEX2 <= not seg7(std_logic_vector(count(23 downto 20)));
  HEX3 <= not seg7(std_logic_vector(count(27 downto 24)));
  HEX4 <= not seg7(std_logic_vector(count(29 downto 26)));
  HEX5 <= not seg7(std_logic_vector(count(31 downto 28)));

end architecture;
