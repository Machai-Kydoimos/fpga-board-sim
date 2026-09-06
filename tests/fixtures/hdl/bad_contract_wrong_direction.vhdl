-- bad_contract_wrong_direction.vhdl - Fails Stage 2 (contract check).
--
-- DELIBERATE FLAW: the led port is declared with mode IN instead of OUT.
-- Both GHDL and NVC accept this silently (the wrapper's led output is simply
-- never driven), so the simulation would "run" with permanently-undefined
-- LEDs.  The textual contract check is the only guard, and rejects it with
-- the expected declaration.
-- Everything else (encoding, entity name, generics, other ports) is correct.

library ieee;
use ieee.std_logic_1164.all;

entity bad_contract_wrong_direction is
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
    led : in  std_logic_vector(NUM_LEDS     - 1 downto 0)  -- WRONG: must be out
  );
end entity;

architecture rtl of bad_contract_wrong_direction is
begin
end architecture;
