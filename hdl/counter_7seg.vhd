library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity counter_7seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 32   -- 32 so bits 4*i+3..4*i are valid for all 9 boards (max 8 digits × 4 bits = 32)
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
  );
end entity;

architecture rtl of counter_7seg is
  signal counter : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');

  -- {dp=0, g, f, e, d, c, b, a}, active-high
  type seg_lut_t is array(0 to 15) of std_logic_vector(7 downto 0);
  constant SEG_LUT : seg_lut_t := (
    x"3F",  -- 0
    x"06",  -- 1
    x"5B",  -- 2
    x"4F",  -- 3
    x"66",  -- 4
    x"6D",  -- 5
    x"7D",  -- 6
    x"07",  -- 7
    x"7F",  -- 8
    x"6F",  -- 9
    x"77",  -- A
    x"7C",  -- b
    x"39",  -- C
    x"5E",  -- d
    x"79",  -- E
    x"71"   -- F
  );
begin
  process(clk) is
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process;

  -- Safe only when NUM_LEDS <= COUNTER_BITS (always true for real boards)
  led <= std_logic_vector(counter(COUNTER_BITS - 1 downto COUNTER_BITS - NUM_LEDS));

  gen_segs : for i in 0 to NUM_SEGS - 1 generate
    seg(8*i + 7 downto 8*i) <= SEG_LUT(to_integer(counter(4*i + 3 downto 4*i)));
  end generate;

end architecture;
