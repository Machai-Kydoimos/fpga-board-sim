-- bad_contract_fixed_width.vhdl - Fails Stage 2 (contract check) when a board is selected.
--
-- DELIBERATE FLAW: the led port is a fixed 16 bits wide instead of being
-- sized by the NUM_LEDS generic.  With a board selected, the contract checker
-- rejects it with a board-aware message (e.g. "DE0 has 1 LED ... set
-- NUM_LEDS").  Without a board the fixed width cannot be judged at Stage 2;
-- GHDL/NVC then reject it during Stage 3 elaboration (16 vs the default 4)
-- and the error gains a contextual hint.
-- Everything else (encoding, entity name, generics, other ports) is correct.

library ieee;
use ieee.std_logic_1164.all;

entity bad_contract_fixed_width is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(15 downto 0)  -- WRONG: should be NUM_LEDS - 1 downto 0
  );
end entity;

architecture rtl of bad_contract_fixed_width is
begin
  led <= (others => '0');
end architecture;
