library ieee;
use ieee.std_logic_1164.all;

entity bad_contract_7seg_missing_seg is
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
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0)
    -- seg intentionally absent
  );
end entity;

architecture rtl of bad_contract_7seg_missing_seg is
begin
  led <= (others => '0');
end architecture;
