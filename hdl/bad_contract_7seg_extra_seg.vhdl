-- bad_contract_7seg_extra_seg.vhdl - Fails Stage 3 (GHDL elaboration) on 7-seg boards.
--
-- DELIBERATE FLAW: the seg port is 9 bits wide per digit (9 * NUM_SEGS - 1 downto 0)
-- instead of the required 8 bits per digit (8 * NUM_SEGS - 1 downto 0).
-- The 7-seg wrapper maps its seg(8*NUM_SEGS-1:0) to this port, which produces a
-- vector-length mismatch that GHDL catches at elaboration.
-- On non-7-seg boards the standard wrapper is used (seg left open), so no error occurs.
-- Encoding is clean ASCII and the entity name matches the filename.

library ieee;
use ieee.std_logic_1164.all;

entity bad_contract_7seg_extra_seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 32
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(9 * NUM_SEGS - 1 downto 0)  -- WRONG: should be 8 * NUM_SEGS
  );
end entity;

architecture rtl of bad_contract_7seg_extra_seg is
begin
  led <= (others => '0');
  seg <= (others => '0');
end architecture;
