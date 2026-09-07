-- gates_mux.vhd  --  Two data inputs, four functions, one LED.
--
-- The smallest useful design in the folder, and the only one with no clock in
-- its logic: switches go straight to a LED through combinational gates.  If
-- you have never written VHDL before, start here -- you can predict every
-- output by reading the truth table, with no counters or edges in the way.
--
--   sw(1 downto 0)  the two data inputs, A and B
--   sw(3 downto 2)  which function to show
--   led(0)          the result
--   led(1)/led(2)   A and B echoed back, so you can see what you selected
--
--   sw(3 downto 2)   led(0)
--   --------------   ----------------
--        00          A and B
--        01          A or  B
--        10          A xor B
--        11          not A          (B ignored)
--
-- Effect  : LED 0 follows a function of two switches; LEDs 1-2 echo the inputs.
-- Teaches : Combinational logic, a selected assignment as a multiplexer, and
--           why a design can be correct with no process and no clock at all.
--
-- Note that `clk` is declared and never used.  The simulator's contract asks
-- for it on every design, and a purely combinational design is entitled to
-- ignore it; a synthesis tool would simply optimize the unused input away.

library ieee;
use ieee.std_logic_1164.all;

entity gates_mux is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24   -- unused; the contract supplies it
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity;

architecture rtl of gates_mux is

  -- Boards in this simulator carry anywhere from 1 to 18 switches, so a design
  -- that indexes sw(3) unconditionally would fail to elaborate on a small one.
  -- Reading through this function makes the design run everywhere: a switch the
  -- board does not have reads as '0', which is exactly what an unconnected
  -- input pin would do on hardware with a pull-down.
  function sw_or_zero(v : std_logic_vector; i : natural) return std_logic is
  begin
    if i < v'length then
      return v(v'low + i);
    end if;
    return '0';
  end function;

  signal a, b   : std_logic;
  signal sel    : std_logic_vector(1 downto 0);
  signal result : std_logic;

begin

  a   <= sw_or_zero(sw, 0);
  b   <= sw_or_zero(sw, 1);
  sel <= sw_or_zero(sw, 3) & sw_or_zero(sw, 2);

  -- The multiplexer.  A selected signal assignment reads as a table, which is
  -- why it is the idiomatic way to write one: the four cases are exhaustive
  -- because `sel` is two bits, and `others` covers the metavalues ('U', 'X',
  -- 'Z' ...) that std_logic can carry but hardware cannot.
  with sel select result <=
    a and b       when "00",
    a or  b       when "01",
    a xor b       when "10",
    not a         when "11",
    '0'           when others;

  -- Drive every LED the board has: the result on LED 0, the inputs echoed on
  -- LEDs 1 and 2 so the switch positions are visible without looking down.
  drive : process (result, a, b) is
    variable out_v : std_logic_vector(NUM_LEDS - 1 downto 0);
  begin
    out_v := (others => '0');
    out_v(0) := result;
    if NUM_LEDS > 1 then
      out_v(1) := a;
    end if;
    if NUM_LEDS > 2 then
      out_v(2) := b;
    end if;
    led <= out_v;
  end process drive;

end architecture;
