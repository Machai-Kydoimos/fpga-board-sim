-- Pin-map test fixture (U53): the other constraint dialect (.xdc) and the other
-- display shape -- a scanned display, whose segment lines are shared across all
-- four digits and selected one at a time.  Every port name here is invented;
-- only the pins in top.xdc relate this design to the board.
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity top is
  port (
    clk_i   : in  std_logic;
    dip     : in  std_logic_vector(1 downto 0);
    go      : in  std_logic;
    lamps   : out std_logic_vector(1 downto 0);
    cathode : out std_logic_vector(6 downto 0);
    sel     : out std_logic_vector(3 downto 0);
    point   : out std_logic
  );
end entity;

architecture rtl of top is
  -- Scan fast in *simulation* time: a digit slot every 16 clocks, so all four
  -- digits are visited inside a frame and Full duty measures the honest 1/4
  -- brightness rather than freezing on one digit.
  signal tick : unsigned(5 downto 0) := (others => '0');
  signal slot : integer range 0 to 3 := 0;
  signal digit : std_logic_vector(6 downto 0);
begin
  scan : process (clk_i)
  begin
    if rising_edge(clk_i) then
      tick <= tick + 1;
      if tick = 15 then
        tick <= (others => '0');
        slot <= 0 when slot = 3 else slot + 1;
      end if;
    end if;
  end process;

  -- Active-low segments, as the board wires them: '0' lights a segment.
  with dip select digit <=
    "1000000" when "00",   -- 0
    "1111001" when "01",   -- 1
    "0100100" when "10",   -- 2
    "0110000" when others; -- 3

  cathode <= digit when go = '0' else "0000000";  -- go lights every segment

  -- Active-low digit enables: exactly one low at a time.
  sel <= "1110" when slot = 0 else
         "1101" when slot = 1 else
         "1011" when slot = 2 else
         "0111";

  lamps <= dip;
  point <= '1';  -- decimal point off (active low)
end architecture;
