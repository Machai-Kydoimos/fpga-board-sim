-- counter_7seg.vhd  --  Free-running hexadecimal counter on 7-segment displays.
--
-- The free-running counter drives all 7-segment digits as a single base-16
-- (hexadecimal) counter.  Each digit displays 4 consecutive bits of the counter:
-- digit 0 (rightmost) shows bits [3:0], digit 1 shows bits [7:4], and so on.
-- The rightmost digit therefore changes fastest and the leftmost digit slowest,
-- giving a natural hex odometer effect.  The LEDs show the most-significant
-- NUM_LEDS bits of the same counter.
--
-- No buttons or switches affect the display; they are accepted in the port for
-- simulator contract compatibility but otherwise ignored.
--
-- Effect  : Hex odometer on the 7-segment displays.
-- Teaches : The seg port contract, segment LUT construction, VHDL generate.
--
-- ── 7-SEGMENT PORT CONTRACT ────────────────────────────────────────────────────
--
-- seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
--
-- The port packs NUM_SEGS independent 8-bit digit slots end-to-end.
-- Digit i occupies bits [8*i+7 : 8*i].
--
-- DIGIT NUMBERING:
--   Digit 0  = RIGHTMOST display (least-significant position on screen).
--   Digit N-1 = LEFTMOST  display (most-significant position on screen).
--   To drive digit i, write your 8-bit pattern to seg[8*i+7 : 8*i].
--
-- SEGMENT BIT POSITIONS within each 8-bit slot (active-high):
--
--   bit:  7   6   5   4   3   2   1   0
--         dp   g   f   e   d   c   b   a
--
-- PHYSICAL SEGMENT LAYOUT (standard 7-segment face):
--
--        aaaa
--       f    b
--       f    b
--        gggg
--       e    c
--       e    c
--        dddd    dp
--
-- HOW TO BUILD A SEGMENT PATTERN FOR A GIVEN GLYPH:
--   Set bit 0 (a) if the top  horizontal bar should be on.
--   Set bit 1 (b) if the upper-right vertical   bar should be on.
--   Set bit 2 (c) if the lower-right vertical   bar should be on.
--   Set bit 3 (d) if the bottom horizontal bar should be on.
--   Set bit 4 (e) if the lower-left  vertical   bar should be on.
--   Set bit 5 (f) if the upper-left  vertical   bar should be on.
--   Set bit 6 (g) if the middle horizontal bar should be on.
--   Set bit 7 (dp) if the decimal point should be on.
--
--   Example: digit '2' lights a, b, d, e, g  (bits 0, 1, 3, 4, 6)
--            => 0b_0101_1011 = 0x5B
--
-- ──────────────────────────────────────────────────────────────────────────────

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity counter_7seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 32   -- must be >= 4*NUM_SEGS so every digit has 4 counter bits
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

  -- Free-running binary counter.  Bits 4*i+3..4*i drive digit i's LUT index,
  -- so 32 bits accommodates up to 8 digits (max across all supported boards).
  signal counter : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');

  -- Segment LUT: maps a 4-bit hex nibble (0-F) to an 8-bit segment pattern.
  -- Each entry encodes which segments (dp,g,f,e,d,c,b,a) must be asserted to
  -- render that hex digit on a 7-segment display (active-high, dp always 0).
  type seg_lut_t is array(0 to 15) of std_logic_vector(7 downto 0);
  constant SEG_LUT : seg_lut_t := (
    x"3F",  -- 0: a b c d e f       segments on: top, upper-R, lower-R, bottom, lower-L, upper-L
    x"06",  -- 1:   b c             segments on: upper-R, lower-R
    x"5B",  -- 2: a b   d e   g     segments on: top, upper-R, middle, lower-L, bottom
    x"4F",  -- 3: a b c d     g     segments on: top, upper-R, lower-R, middle, bottom
    x"66",  -- 4:   b c     f g     segments on: upper-R, lower-R, upper-L, middle
    x"6D",  -- 5: a   c d   f g     segments on: top, upper-L, middle, lower-R, bottom
    x"7D",  -- 6: a   c d e f g     segments on: top, upper-L, middle, lower-L, lower-R, bottom
    x"07",  -- 7: a b c             segments on: top, upper-R, lower-R
    x"7F",  -- 8: a b c d e f g     all segments on
    x"6F",  -- 9: a b c d   f g     segments on: top, upper-R, lower-R, upper-L, middle, bottom
    x"77",  -- A: a b c   e f g     segments on: top, upper-R, lower-R, upper-L, lower-L, middle
    x"7C",  -- b:     c d e f g     segments on: upper-L, middle, lower-L, lower-R, bottom
    x"39",  -- C: a     d e f       segments on: top, upper-L, lower-L, bottom
    x"5E",  -- d:   b c d e   g     segments on: upper-R, lower-R, middle, lower-L, bottom
    x"79",  -- E: a     d e f g     segments on: top, upper-L, middle, lower-L, bottom
    x"71"   -- F: a       e f g     segments on: top, upper-L, middle, lower-L
  );

begin

  -- Free-running binary counter: increments every clock cycle.
  process(clk) is
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process;

  -- LEDs show the most-significant NUM_LEDS bits of the counter.
  -- Safe as long as NUM_LEDS <= COUNTER_BITS (guaranteed for all real boards).
  led <= std_logic_vector(counter(COUNTER_BITS - 1 downto COUNTER_BITS - NUM_LEDS));

  -- Drive each digit independently via the LUT.
  -- Digit i uses counter bits [4*i+3 : 4*i] as a 4-bit LUT index.
  -- Because digit 0 is the rightmost display and uses the lowest counter bits,
  -- the display reads as a left-to-right hex number with the LSDigit on the right.
  gen_segs : for i in 0 to NUM_SEGS - 1 generate
    seg(8*i + 7 downto 8*i) <= SEG_LUT(to_integer(counter(4*i + 3 downto 4*i)));
  end generate;

end architecture;
