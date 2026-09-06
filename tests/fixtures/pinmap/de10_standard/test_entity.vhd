-- Pin-map test fixture (U53), not a teaching example and not anyone's lab work.
--
-- Its shape is what matters: instructor-style port names that match no board
-- convention (`clock` / `sw` / `led_r` / `hex`), the Synopsys dialect, and a
-- flat `hex` vector packing several digits -- bound to a real DE10-Standard by
-- the .qsf beside it.  The logic is deliberately trivial; the point is that
-- nothing here names a Terasic port and it runs anyway.
library ieee;
use ieee.std_logic_1164.all;
use ieee.std_logic_arith.all;
use ieee.std_logic_unsigned.all;

-- Task-3b shape: a byte on the switches shown as two hexadecimal digits.
entity test_entity is
  port (
    clock  : in std_logic;
    reset  : in std_logic;
    -- Declared, used, and bound to no pin at all by the .qsf beside this file.
    -- That is not a mistake in the fixture: it is what the real lab top level
    -- does, and Quartus places such a pin automatically so nobody finds out.
    button : in std_logic_vector(2 downto 0);
    sw     : in std_logic_vector(9 downto 0);
    led_r  : out std_logic_vector(9 downto 0);
    hex    : out std_logic_vector(27 downto 0));
end test_entity;

architecture behav of test_entity is
  function seg7 (nibble : std_logic_vector(3 downto 0))
    return std_logic_vector is
  begin
    case nibble is
      when "0000" => return "1000000";
      when "0001" => return "1111001";
      when "0010" => return "0100100";
      when "0011" => return "0110000";
      when "0100" => return "0011001";
      when "0101" => return "0010010";
      when "0110" => return "0000010";
      when "0111" => return "1111000";
      when "1000" => return "0000000";
      when "1001" => return "0010000";
      when "1010" => return "0001000";
      when "1011" => return "0000011";
      when "1100" => return "1000110";
      when "1101" => return "0100001";
      when "1110" => return "0000110";
      when others => return "0001110";
    end case;
  end function seg7;
begin
  hex(6 downto 0)   <= seg7(sw(3 downto 0));
  hex(13 downto 7)  <= seg7(sw(7 downto 4));
  hex(20 downto 14) <= (others => '1');
  hex(27 downto 21) <= (others => '1');

  led_r <= button(1 downto 0) & sw(7 downto 0);
end behav;
