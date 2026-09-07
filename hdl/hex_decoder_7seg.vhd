-- hex_decoder_7seg.vhd  --  A byte on the switches, in hex, on two digits.
--
-- Set sw(7 downto 0) and the two right-hand digits show that byte in
-- hexadecimal: digit 0 the low nibble, digit 1 the high one.  The LEDs mirror
-- the switches, so you can read the same byte in binary at the same time.
--
-- Nothing here is clocked.  The digits follow the switches immediately, which
-- makes this the easiest design in the folder to *check*: flip a switch, look
-- at the display, and the answer is either right or wrong with no timing to
-- reason about.
--
-- -- THE DECODER IS THE POINT -------------------------------------------------
--
-- `to_seg` below is the shape you will write over and over: one `case`, one
-- branch per input value, every branch returning the same width, and a `when
-- others` that makes the function total.  Writing it as a function rather than
-- a process means the two digits *share* one decoder description -- change the
-- font once and both digits change -- and it is why the same nine lines can
-- drive an eight-digit board without being written eight times.
--
-- The bit order inside a digit is the simulator's 7-segment contract:
--
--   bit:  7   6   5   4   3   2   1   0
--         dp   g   f   e   d   c   b   a
--
--        aaaa
--       f    b        Set bit 0 for the top bar, bit 1 for the upper right,
--       f    b        and so on round the face; bit 6 is the middle bar.
--        gggg         Active-high here: a '1' lights that segment, and the
--       e    c        simulator inverts it for you on a board whose display
--       e    c        is wired active-low.
--        dddd    dp
--
-- Effect  : Two digits show sw(7 downto 0) in hex; LEDs mirror the switches.
-- Teaches : A `case` decoder as a reusable function, nibble slicing, and the
--           seg port contract.

library ieee;
use ieee.std_logic_1164.all;

entity hex_decoder_7seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 24   -- unused; the contract supplies it
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
  );
end entity;

architecture rtl of hex_decoder_7seg is

  -- The decoder.  One branch per nibble value; `others` is unreachable for a
  -- 4-bit input but required, because std_logic carries 'U', 'X', 'Z' and the
  -- rest, and VHDL will not let a function fall off its end.
  function to_seg(nibble : std_logic_vector(3 downto 0)) return std_logic_vector is
  begin
    case nibble is                --  dp g f e d c b a
      when x"0" => return "00111111";
      when x"1" => return "00000110";
      when x"2" => return "01011011";
      when x"3" => return "01001111";
      when x"4" => return "01100110";
      when x"5" => return "01101101";
      when x"6" => return "01111101";
      when x"7" => return "00000111";
      when x"8" => return "01111111";
      when x"9" => return "01101111";
      when x"A" => return "01110111";
      when x"B" => return "01111100";
      when x"C" => return "00111001";
      when x"D" => return "01011110";
      when x"E" => return "01111001";
      when x"F" => return "01110001";
      when others => return "01000000";  -- a bare middle bar: "cannot read this"
    end case;
  end function;

  -- A board may have fewer than eight switches; a switch it does not have
  -- reads '0', so the design runs everywhere and simply shows a smaller number.
  function sw_or_zero(v : std_logic_vector; i : natural) return std_logic is
  begin
    if i < v'length then
      return v(v'low + i);
    end if;
    return '0';
  end function;

  signal value : std_logic_vector(7 downto 0);

begin

  gen_value : for i in 0 to 7 generate
    value(i) <= sw_or_zero(sw, i);
  end generate;

  -- Digit 0 is the rightmost display, so it gets the low nibble: the number
  -- then reads left to right the way it is written.
  seg(7 downto 0) <= to_seg(value(3 downto 0));

  gen_high : if NUM_SEGS >= 2 generate
    seg(15 downto 8) <= to_seg(value(7 downto 4));
  end generate;

  -- Any further digits stay dark rather than repeating the value.
  gen_blank : for d in 2 to NUM_SEGS - 1 generate
    seg(8*d + 7 downto 8*d) <= (others => '0');
  end generate;

  -- The same byte in binary, as far as the board's LEDs reach.
  gen_led : for i in 0 to NUM_LEDS - 1 generate
    gen_have : if i < 8 generate
      led(i) <= value(i);
    end generate;
    gen_lack : if i >= 8 generate
      led(i) <= '0';
    end generate;
  end generate;

end architecture;
