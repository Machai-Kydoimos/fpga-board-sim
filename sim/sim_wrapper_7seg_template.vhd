-- sim_wrapper_7seg_template.vhd
-- Like sim_wrapper_template.vhd but adds NUM_SEGS and the seg port for
-- designs that target boards with 7-segment displays.
-- The {toplevel} placeholder is replaced with the user's entity name.

library ieee;
use ieee.std_logic_1164.all;

entity sim_wrapper is
  generic (
    NUM_SWITCHES     : positive := 4;
    NUM_BUTTONS      : positive := 4;
    NUM_LEDS         : positive := 4;
    NUM_SEGS         : positive := 4;
    COUNTER_BITS     : positive := 24;
    CLK_HALF_NS_INIT : positive := 20
  );
  port (
    sw          : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn         : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led         : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg         : out std_logic_vector(8 * NUM_SEGS - 1 downto 0);
    clk_half_ns : in  natural := CLK_HALF_NS_INIT
  );
end entity;

architecture rtl of sim_wrapper is
  signal clk : std_logic := '0';
begin

  clk_proc : process
  begin
    clk <= '0';
    wait for clk_half_ns * 1 ns;
    clk <= '1';
    wait for clk_half_ns * 1 ns;
  end process;

  uut : entity work.{toplevel}
    generic map (
      NUM_SWITCHES => NUM_SWITCHES,
      NUM_BUTTONS  => NUM_BUTTONS,
      NUM_LEDS     => NUM_LEDS,
      NUM_SEGS     => NUM_SEGS,
      COUNTER_BITS => COUNTER_BITS
    )
    port map (
      clk => clk,
      sw  => sw,
      btn => btn,
      led => led,
      seg => seg
    );

end architecture;
