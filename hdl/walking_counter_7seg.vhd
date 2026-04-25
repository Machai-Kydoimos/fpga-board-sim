-- walking_counter_7seg.vhd  --  Walking LED with decimal BCD counter.
--
-- A single lit LED bounces back and forth across all available LEDs.
-- Every LED step advances a decimal counter displayed on the 7-segment digits.
-- The digits are treated as a single NUM_SEGS-digit decimal number.
--
-- sw     : each additional active switch doubles the step rate
-- btn(0) : each press reverses the LED walk direction AND toggles the counter
--          direction (increment <-> decrement)
-- btn(1) : held -- all LEDs on and all 7-seg segments on simultaneously
--
-- Counter wrap-around:
--   Incrementing past the maximum (all 9s) wraps to 0.
--   Decrementing past 0 wraps to the maximum (all 9s).
--   LED bounce at the ends does NOT affect counter direction -- only btn(0) does.
--
-- Effect  : Bouncing LED drives a decimal odometer on the 7-segment displays.
-- Teaches : BCD counter with carry/borrow ripple, direction control,
--           decoupled LED and counter state machines.
--
-- -- 7-SEGMENT PORT CONTRACT (see counter_7seg.vhd for full details) -----------
--
-- seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
--
-- Digit i occupies bits [8*i+7 : 8*i].  Digit 0 = rightmost display.
-- Within each slot, bit positions are: dp=7, g=6, f=5, e=4, d=3, c=2, b=1, a=0
-- (all active-high).
--
-- DIGIT-TO-BCD MAPPING in this design:
--   bcd_cnt(0)         holds the units digit  -> drives seg[7:0]   = rightmost.
--   bcd_cnt(NUM_SEGS-1) holds the most-significant digit -> drives the leftmost.
-- Because digit 0 is already the rightmost slot, no index reversal is needed
-- in seg_proc; the natural array index matches the seg-slot index directly.
--
-- ------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity walking_counter_7seg is
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
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
  );
end entity walking_counter_7seg;

architecture rtl of walking_counter_7seg is

  signal counter   : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
  signal position  : integer range 0 to NUM_LEDS - 1 := 0;  -- current lit LED
  signal fwd       : std_logic := '1';     -- LED walk direction: '1' = toward higher index
  signal prev_step : std_logic := '0';     -- previous counter(step_idx) for edge detection
  signal prev_btn0 : std_logic := '0';     -- previous btn(0) for rising-edge detection
  signal step_idx  : integer range 0 to COUNTER_BITS - 1 := COUNTER_BITS - 1;

  -- BCD counter: one integer per decimal digit, each constrained to 0-9.
  -- Index 0 = units (rightmost display); index NUM_SEGS-1 = most significant (leftmost).
  -- Storing digits individually makes carry/borrow ripple straightforward to
  -- implement without binary-to-decimal conversion.
  type bcd_arr_t is array(0 to NUM_SEGS - 1) of integer range 0 to 9;
  signal bcd_cnt : bcd_arr_t := (others => 0);

  -- Counter direction: '1' = increment each step, '0' = decrement each step.
  -- This is independent of the LED walk direction (fwd).  LED bounce at the
  -- display boundaries does NOT flip cnt_up; only btn(0) does.
  signal cnt_up : std_logic := '1';

  -- Segment LUT: maps a decimal digit (0-9) to an 8-bit segment pattern.
  -- Decimal point (bit 7) is always 0 -- this design leaves dp dark.
  -- See counter_7seg.vhd for the full segment bit layout and how to derive
  -- the hex values from the segment diagram.
  type seg_lut_t is array(0 to 9) of std_logic_vector(7 downto 0);
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
    x"6F"   -- 9
  );

begin

  -- Free-running counter ------------------------------------------------------
  count_proc : process(clk) is
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  -- Speed index from switch popcount ------------------------------------------
  -- Each active switch subtracts 2 from step_idx, halving the step period
  -- (doubling the rate).  Base is capped at bit 16 so the step rate is
  -- consistent across all boards regardless of the COUNTER_BITS value set
  -- by the simulator.
  idx_proc : process(sw) is
    variable n    : integer range 0 to NUM_SWITCHES;
    variable base : integer;
    variable idx  : integer;
  begin
    n := 0;
    for i in 0 to NUM_SWITCHES - 1 loop
      if sw(i) = '1' then
        n := n + 1;
      end if;
    end loop;
    base := COUNTER_BITS - 1;
    if base > 16 then
      base := 16;
    end if;
    idx := base - n * 2;
    if idx < 1 then
      idx := 1;
    end if;
    step_idx <= idx;
  end process idx_proc;

  -- LED walk + BCD counter update ---------------------------------------------
  -- On each rising edge of counter(step_idx):
  --   1. Advance the LED position one step, bouncing at the ends.
  --   2. Advance the BCD counter by one in the current cnt_up direction.
  -- btn(0) rising edge reverses the LED direction and toggles cnt_up.
  walk_proc : process(clk) is
    variable fwd_v    : std_logic;
    variable cnt_up_v : std_logic;
    variable pos_v    : integer range 0 to NUM_LEDS - 1;
    variable bcd_v    : bcd_arr_t;
    variable carry    : integer range 0 to 1;   -- carry out of each digit during increment
    variable borrow   : integer range 0 to 1;   -- borrow into each digit during decrement
    variable tmp      : integer range -1 to 10; -- temporary sum/difference before clamping
  begin
    if rising_edge(clk) then
      fwd_v    := fwd;
      cnt_up_v := cnt_up;
      pos_v    := position;
      bcd_v    := bcd_cnt;

      prev_step <= counter(step_idx);

      if prev_step = '0' and counter(step_idx) = '1' then

        -- Advance LED: bounce at both ends (Knight Rider / blinky_walking style).
        if fwd_v = '1' then
          if pos_v = NUM_LEDS - 1 then
            fwd_v := '0';             -- hit right end: reverse and step left
            pos_v := pos_v - 1;
          else
            pos_v := pos_v + 1;
          end if;
        else
          if pos_v = 0 then
            fwd_v := '1';             -- hit left end: reverse and step right
            pos_v := pos_v + 1;
          else
            pos_v := pos_v - 1;
          end if;
        end if;

        -- Advance BCD counter.
        -- Increment: add 1 to digit 0 (units).  If the digit overflows (reaches
        -- 10), reset it to 0 and carry 1 into the next digit.  Carry ripples
        -- upward through all digits.  If carry exits the most-significant digit
        -- the counter wraps to 0000...0 naturally (carry is discarded).
        if cnt_up_v = '1' then
          carry := 1;
          for i in 0 to NUM_SEGS - 1 loop
            tmp := bcd_v(i) + carry;
            if tmp >= 10 then
              bcd_v(i) := 0;
              carry     := 1;   -- propagate carry to next digit
            else
              bcd_v(i) := tmp;
              carry     := 0;   -- no carry: higher digits unchanged
            end if;
          end loop;

        -- Decrement: subtract 1 from digit 0.  If the digit underflows (goes
        -- below 0), set it to 9 and borrow 1 from the next digit.  Borrow
        -- ripples upward.  If borrow exits the most-significant digit the counter
        -- wraps to 9999...9 naturally (borrow is discarded).
        else
          borrow := 1;
          for i in 0 to NUM_SEGS - 1 loop
            tmp := bcd_v(i) - borrow;
            if tmp < 0 then
              bcd_v(i) := 9;
              borrow    := 1;   -- propagate borrow to next digit
            else
              bcd_v(i) := tmp;
              borrow    := 0;   -- no borrow: higher digits unchanged
            end if;
          end loop;
        end if;

      end if;

      -- btn(0) rising edge: reverse LED direction and toggle counter direction.
      -- The double assignment (first '0', then btn(0)) ensures prev_btn0 stays
      -- '0' when NUM_BUTTONS = 0, preventing a spurious direction change.
      prev_btn0 <= '0';
      if NUM_BUTTONS >= 1 then
        prev_btn0 <= btn(0);
        if prev_btn0 = '0' and btn(0) = '1' then
          fwd_v    := not fwd_v;
          cnt_up_v := not cnt_up_v;
        end if;
      end if;

      fwd      <= fwd_v;
      cnt_up   <= cnt_up_v;
      position <= pos_v;
      bcd_cnt  <= bcd_v;
    end if;
  end process walk_proc;

  -- LED output ----------------------------------------------------------------
  -- Light only the current position; btn(1) overrides to all-on.
  led_proc : process(position, btn) is
    variable all_on : std_logic;
  begin
    all_on := '0';
    if NUM_BUTTONS >= 2 then
      all_on := btn(1);
    end if;
    for i in 0 to NUM_LEDS - 1 loop
      if all_on = '1' then
        led(i) <= '1';
      elsif i = position then
        led(i) <= '1';
      else
        led(i) <= '0';
      end if;
    end loop;
  end process led_proc;

  -- 7-segment output ----------------------------------------------------------
  -- Each digit slot i is driven by bcd_cnt(i) through the decimal LUT.
  -- bcd_cnt(0) = units -> seg[7:0] = rightmost display, so the counter reads
  -- naturally left-to-right with the most-significant digit on the left.
  -- btn(1) overrides all digits to "all segments on" (shows 8 with dp lit).
  seg_proc : process(bcd_cnt, btn) is
    variable all_on : std_logic;
  begin
    all_on := '0';
    if NUM_BUTTONS >= 2 then
      all_on := btn(1);
    end if;
    for i in 0 to NUM_SEGS - 1 loop
      if all_on = '1' then
        seg(8 * i + 7 downto 8 * i) <= "11111111";
      else
        seg(8 * i + 7 downto 8 * i) <= SEG_LUT(bcd_cnt(i));
      end if;
    end loop;
  end process seg_proc;

end architecture rtl;
