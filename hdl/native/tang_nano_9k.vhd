-- tang_nano_9k.vhd
--
-- A board-native design for the Sipeed Tang Nano 9K, written to the board's own
-- names from the official constraint file: a 27 MHz `sys_clk` and six LEDs.
--
-- WHAT MAKES THIS ONE DIFFERENT: the board has **no switches and no buttons**
-- in its convention, so this design declares no inputs beyond the clock.  That
-- is legal and supported -- the simulator ties off the input banks it cannot
-- connect and leaves them out of the way (U31 partial-interface support).  It
-- is the smallest complete board-native design in the repository, and a good
-- one to read first.
--
-- POLARITY: the Tang Nano 9K's LEDs are ACTIVE-LOW -- a '0' lights one.  The
-- file drives the physical levels the real board wants, so it moves to the
-- Gowin toolchain unchanged; the simulator's wrapper inverts on the way to its
-- own active-high boundary, and the screen shows what the bench would.
--
-- Behavior: a single lit LED walks along the row of six and back again.
--
-- The counter tap is mid-range on purpose.  A board-native design gets no
-- COUNTER_BITS override -- it has no generics for the simulator to override --
-- so taking the top bits of a 27 MHz divider would look frozen here.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity tang_nano_9k is
  port (
    sys_clk : in  std_logic;
    led     : out std_logic_vector(5 downto 0)
  );
end entity;

architecture rtl of tang_nano_9k is

  constant NUM_LED : natural := 6;

  signal count    : unsigned(23 downto 0) := (others => '0');
  signal position : natural range 0 to NUM_LED - 1 := 0;
  signal rising   : boolean := true;
  signal pattern  : std_logic_vector(NUM_LED - 1 downto 0);

begin

  walk : process (sys_clk) is
  begin
    if rising_edge(sys_clk) then
      count <= count + 1;

      if count = (count'range => '1') then
        if rising then
          if position = NUM_LED - 1 then
            rising   <= false;
            position <= position - 1;
          else
            position <= position + 1;
          end if;
        else
          if position = 0 then
            rising   <= true;
            position <= position + 1;
          else
            position <= position - 1;
          end if;
        end if;
      end if;
    end if;
  end process walk;

  -- One bit set, at the walking position ...
  gen : for i in 0 to NUM_LED - 1 generate
    pattern(i) <= '1' when i = position else '0';
  end generate;

  -- ... and inverted on the way out, because a '0' is what lights an LED on
  -- this board.  So the walking position drives '0' and lights up, while the
  -- five idle positions drive '1' and stay dark: one lit LED, walking.
  led <= not pattern;

end architecture;
