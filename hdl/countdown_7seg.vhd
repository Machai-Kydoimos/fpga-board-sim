-- countdown_7seg.vhd  --  99 down to 00, one step per tick, then round again.
--
-- Two digits count 99, 98, 97 ... 00 and wrap.  btn(0) restarts at 99; hold
-- sw(0) to freeze it wherever it is.  The LEDs show the ones digit in binary,
-- so you can watch the same number in two notations at once.
--
-- -- WHICH GENERIC SIZES THE TICK, AND WHY IT MATTERS -------------------------
--
-- This design divides the clock with COUNTER_BITS, and `running_light.vhd` --
-- the same idea, one row over -- divides it with DIVIDER_BITS.  That is not an
-- inconsistency; it is the distinction worth learning:
--
--   COUNTER_BITS  is part of the simulator's contract.  It is declared with a
--                 hardware-sized default, and the simulator **overrides it at
--                 launch** with something you can actually watch.  Nothing to
--                 do: the countdown ticks about once a second here.
--
--   DIVIDER_BITS  is a name of your own.  The simulator has never heard of it,
--                 so your default stands -- and a hardware-sized default means
--                 minutes per step.  You override it yourself, with
--                 `--generic DIVIDER_BITS=15` or the [Generics...] button.
--
-- So: a generic the tool knows about is adjusted for you, and one it does not
-- is yours to set.  Run this file and `running_light.vhd` back to back and the
-- difference is immediate.
--
-- -- COUNTING IN DECIMAL ON A BINARY MACHINE ----------------------------------
--
-- The count is kept as two separate 0-9 digits rather than as one number that
-- is divided by ten for display.  Hardware has no cheap divider, so this is
-- what real designs do: decrement the ones digit, and when it rolls under from
-- 0 to 9, borrow from the tens.  It is the same borrow you learned on paper.
--
-- Effect  : A two-digit countdown, ~1 step/second, wrapping 00 -> 99.
-- Teaches : BCD counting with a borrow, a clock-divider tick, and the
--           difference between a contract generic and one of your own.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity countdown_7seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 26   -- see TICK_BITS below; the simulator resets this
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
  );
end entity;

architecture rtl of countdown_7seg is

  function bit_or_zero(v : std_logic_vector; i : natural) return std_logic is
  begin
    if i < v'length then
      return v(v'low + i);
    end if;
    return '0';
  end function;

  -- Decimal-only font: this design never shows A-F, so ten entries is honest
  -- about what it can display.  (`hex_decoder_7seg.vhd` has all sixteen.)
  type digit_font_t is array(0 to 9) of std_logic_vector(7 downto 0);
  constant FONT : digit_font_t := (
    "00111111",  -- 0        dp g f e d c b a
    "00000110",  -- 1
    "01011011",  -- 2
    "01001111",  -- 3
    "01100110",  -- 4
    "01101101",  -- 5
    "01111101",  -- 6
    "00000111",  -- 7
    "01111111",  -- 8
    "01101111"   -- 9
  );

  -- Take what this design needs from COUNTER_BITS rather than all of it.  The
  -- simulator lowers that generic so a design is watchable, but it also
  -- *widens* it on a board with many digits, because a hex-odometer design
  -- needs four counter bits per digit -- on a six-digit board it arrives as 24.
  -- Used whole, this countdown would then tick once every 2**24 cycles, which
  -- is about a minute of waiting per digit.  Capping the prescaler keeps the
  -- rate the same on every board, and is the honest way to share a generic
  -- whose width was chosen for somebody else.
  constant TICK_BITS : positive := minimum(COUNTER_BITS, 18);

  signal tick_div : unsigned(TICK_BITS - 1 downto 0) := (others => '0');
  signal ones     : natural range 0 to 9 := 9;
  signal tens     : natural range 0 to 9 := 9;

  signal reset_n  : std_logic;
  signal hold     : std_logic;

begin

  reset_n <= bit_or_zero(btn, 0);
  hold    <= bit_or_zero(sw, 0);

  count : process (clk) is
  begin
    if rising_edge(clk) then
      if reset_n = '1' then
        tens     <= 9;
        ones     <= 9;
        tick_div <= (others => '0');
      elsif hold = '1' then
        null;                                   -- frozen, divider included
      else
        tick_div <= tick_div + 1;

        if tick_div = (tick_div'range => '1') then
          -- The borrow.  Ones always steps; tens only when ones rolls under.
          if ones = 0 then
            ones <= 9;
            if tens = 0 then
              tens <= 9;                        -- 00 -> 99, round again
            else
              tens <= tens - 1;
            end if;
          else
            ones <= ones - 1;
          end if;
        end if;
      end if;
    end if;
  end process count;

  -- Digit 0 is the rightmost, so it carries the ones.
  seg(7 downto 0) <= FONT(ones);

  gen_tens : if NUM_SEGS >= 2 generate
    seg(15 downto 8) <= FONT(tens);
  end generate;

  gen_blank : for d in 2 to NUM_SEGS - 1 generate
    seg(8*d + 7 downto 8*d) <= (others => '0');
  end generate;

  -- The ones digit in binary, as far as the board's LEDs reach.
  leds : process (ones) is
    variable out_v : std_logic_vector(NUM_LEDS - 1 downto 0);
    variable bits  : std_logic_vector(3 downto 0);
  begin
    out_v := (others => '0');
    bits  := std_logic_vector(to_unsigned(ones, 4));
    for i in 0 to NUM_LEDS - 1 loop
      if i < 4 then
        out_v(i) := bits(i);
      end if;
    end loop;
    led <= out_v;
  end process leds;

end architecture;
