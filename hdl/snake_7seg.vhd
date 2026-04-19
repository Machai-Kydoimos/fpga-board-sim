-- snake_7seg.vhd  --  7-segment display "snake" animation.
--
-- A single lit segment crawls around the outlines of all 7-segment digits in a
-- repeating figure-8 path:
--
--   top bar (left->right)  ->  upper-right of rightmost  ->  middle bar (right->left)
--   -> lower-left of leftmost  ->  bottom bar (left->right)  ->  lower-right of rightmost
--   -> middle bar (right->left)  ->  upper-left of leftmost  ->  (repeat)
--
-- Exactly one segment is lit at any time.  The middle (g) segments are visited
-- twice per cycle -- once in each direction -- forming the bridge between the
-- upper and lower loops of the figure-8.
--
-- For N digits, one full cycle = 4N + 4 steps.
-- Example, N=2 (12 steps): 1a,2a, 2b, 2g,1g, 1e, 1d,2d, 2c, 2g,1g, 1f
-- (digit numbers are 1-based here for readability; internally 0-based)
--
-- A bouncing decimal point and a bouncing LED run in parallel with the snake,
-- both driven by the same step clock.
--
-- sw     : each additional active switch doubles the step rate
-- btn(0) : each press reverses the snake direction (and LED/dp directions)
-- btn(1) : held -- all segments (a-g) and decimal points on simultaneously
--
-- Effect  : A snake of light winds through the 7-segment displays.
-- Teaches : Generic-parameterised combinational decode, segment encoding,
--           step counter with wraparound, direction reversal.
--
-- ── 7-SEGMENT PORT CONTRACT (see counter_7seg.vhd for full details) ───────────
--
-- seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
--
-- Digit i occupies bits [8*i+7 : 8*i].  Digit 0 = rightmost display.
-- Within each slot, bit positions are: dp=7, g=6, f=5, e=4, d=3, c=2, b=1, a=0
-- (all active-high).
--
-- COORDINATE NOTE: this design uses a logical digit coordinate where 0 = leftmost
-- and NUM_SEGS-1 = rightmost, because the snake path is easiest to express that
-- way.  The output assignments translate this to seg-slot indices with:
--
--   seg slot = NUM_SEGS - 1 - logical_digit
--
-- i.e. logical digit 0 (leftmost) maps to seg slot NUM_SEGS-1 (the highest
-- bits of seg), and logical digit NUM_SEGS-1 (rightmost) maps to seg slot 0
-- (bits [7:0]).  See the seg_proc output lines for where this reversal occurs.
--
-- ──────────────────────────────────────────────────────────────────────────────

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity snake_7seg is
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
end entity snake_7seg;

architecture rtl of snake_7seg is

  -- Total steps per full snake cycle.  Max boards: 8 digits -> 36 steps.
  constant TOTAL_STEPS : integer := 4 * NUM_SEGS + 4;

  signal counter   : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
  signal step      : integer range 0 to TOTAL_STEPS - 1 := 0;
  signal fwd       : std_logic := '1';     -- '1' = forward through the path
  signal prev_step : std_logic := '0';     -- previous value of counter(step_idx) for edge detection
  signal prev_btn0 : std_logic := '0';     -- previous btn(0) for rising-edge detection
  signal step_idx  : integer range 0 to COUNTER_BITS - 1 := COUNTER_BITS - 1;
  signal led_pos   : integer range 0 to 127 := 0;   -- current lit LED index
  signal led_fwd   : std_logic := '1';
  signal dp_pos    : integer range 0 to 7 := 0;     -- digit whose decimal point is lit
  signal dp_fwd    : std_logic := '1';

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
  -- (doubling the snake speed).  Clamped to [1, COUNTER_BITS-1].
  --
  -- The base speed is capped at bit 16 so the step rate matches blinky_walking
  -- regardless of COUNTER_BITS.  (COUNTER_BITS is set by the simulator to
  -- 4*NUM_SEGS for BCD designs, which would otherwise slow the snake on boards
  -- with many digits.)
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

  -- Step advance + direction control ------------------------------------------
  -- On each rising edge of counter(step_idx), advance the snake step by one.
  -- The LED and decimal-point bounce positions advance at the same rate.
  -- btn(0) rising edge toggles the direction of all three.
  walk_proc : process(clk) is
    variable fwd_v     : std_logic;
    variable step_v    : integer range 0 to TOTAL_STEPS - 1;
    variable led_fwd_v : std_logic;
    variable led_pos_v : integer range 0 to 127;
    variable dp_fwd_v  : std_logic;
    variable dp_pos_v  : integer range 0 to 7;
  begin
    if rising_edge(clk) then
      fwd_v     := fwd;
      step_v    := step;
      led_fwd_v := led_fwd;
      led_pos_v := led_pos;
      dp_fwd_v  := dp_fwd;
      dp_pos_v  := dp_pos;

      -- Latch previous trigger bit for rising-edge detection.
      prev_step <= counter(step_idx);

      if prev_step = '0' and counter(step_idx) = '1' then

        -- Advance snake step, wrapping at both ends.
        if fwd_v = '1' then
          if step_v = TOTAL_STEPS - 1 then
            step_v := 0;
          else
            step_v := step_v + 1;
          end if;
        else
          if step_v = 0 then
            step_v := TOTAL_STEPS - 1;
          else
            step_v := step_v - 1;
          end if;
        end if;

        -- Advance LED bounce: ping-pong between 0 and NUM_LEDS-1.
        -- Mirrors the blinky_walking.vhd logic exactly.
        if led_fwd_v = '1' then
          if led_pos_v = NUM_LEDS - 1 then
            led_fwd_v := '0';
            led_pos_v := led_pos_v - 1;
          else
            led_pos_v := led_pos_v + 1;
          end if;
        else
          if led_pos_v = 0 then
            led_fwd_v := '1';
            led_pos_v := led_pos_v + 1;
          else
            led_pos_v := led_pos_v - 1;
          end if;
        end if;

        -- Advance decimal-point bounce: same logic, bounded by NUM_SEGS.
        -- dp_pos is a logical digit index (0 = leftmost, NUM_SEGS-1 = rightmost).
        if dp_fwd_v = '1' then
          if dp_pos_v = NUM_SEGS - 1 then
            dp_fwd_v := '0';
            dp_pos_v := dp_pos_v - 1;
          else
            dp_pos_v := dp_pos_v + 1;
          end if;
        else
          if dp_pos_v = 0 then
            dp_fwd_v := '1';
            dp_pos_v := dp_pos_v + 1;
          else
            dp_pos_v := dp_pos_v - 1;
          end if;
        end if;

      end if;

      -- btn(0) rising edge: toggle direction of snake, LED, and decimal point.
      -- The double assignment (first '0', then btn(0)) ensures prev_btn0 stays
      -- '0' when NUM_BUTTONS = 0, preventing a spurious direction change.
      prev_btn0 <= '0';
      if NUM_BUTTONS >= 1 then
        prev_btn0 <= btn(0);
        if prev_btn0 = '0' and btn(0) = '1' then
          fwd_v     := not fwd_v;
          led_fwd_v := not led_fwd_v;
          dp_fwd_v  := not dp_fwd_v;
        end if;
      end if;

      fwd     <= fwd_v;
      step    <= step_v;
      led_fwd <= led_fwd_v;
      led_pos <= led_pos_v;
      dp_fwd  <= dp_fwd_v;
      dp_pos  <= dp_pos_v;
    end if;
  end process walk_proc;

  -- 7-segment output ----------------------------------------------------------
  -- Decodes the current step to a (logical digit, segment bit) pair and lights
  -- exactly one segment.  The decimal point of dp_pos is also lit.
  -- btn(1) overrides: all segments a-g and all decimal points on.
  --
  -- Snake path phases for N = NUM_SEGS (dig is the LOGICAL digit, 0 = leftmost):
  --
  --   steps  0   .. N-1    : a (bit 0),  dig  0 -> N-1   top bar,    left  -> right
  --   step   N             : b (bit 1),  dig  N-1         upper-right of rightmost
  --   steps  N+1 .. 2N     : g (bit 6),  dig  N-1 -> 0   middle bar, right -> left
  --   step   2N+1          : e (bit 4),  dig  0           lower-left  of leftmost
  --   steps  2N+2 .. 3N+1  : d (bit 3),  dig  0 -> N-1   bottom bar, left  -> right
  --   step   3N+2          : c (bit 2),  dig  N-1         lower-right of rightmost
  --   steps  3N+3 .. 4N+2  : g (bit 6),  dig  N-1 -> 0   middle bar, right -> left
  --   step   4N+3          : f (bit 5),  dig  0           upper-left  of leftmost
  --
  -- OUTPUT INDEX REVERSAL: the logical coordinate (dig=0 leftmost) is converted
  -- to a seg-slot index (slot 0 = rightmost) by:  slot = NUM_SEGS - 1 - dig.
  -- This keeps the snake path arithmetic simple while honouring the port
  -- convention that digit 0 is the rightmost display.
  seg_proc : process(step, btn, dp_pos) is
    variable s      : integer range 0 to 35;
    variable dig    : integer range 0 to 7;   -- logical digit: 0 = leftmost
    variable sg     : integer range 0 to 6;   -- segment bit index within the slot
    variable all_on : std_logic;
    variable v_seg  : std_logic_vector(8 * NUM_SEGS - 1 downto 0);
  begin
    s := step;

    -- Decode step -> (logical digit index, segment bit).
    if s < NUM_SEGS then
      dig := s;                            sg := 0;  -- a: top bar, left -> right
    elsif s = NUM_SEGS then
      dig := NUM_SEGS - 1;                 sg := 1;  -- b: upper-right of rightmost
    elsif s <= 2 * NUM_SEGS then
      dig := 2 * NUM_SEGS - s;             sg := 6;  -- g: middle bar, right -> left
    elsif s = 2 * NUM_SEGS + 1 then
      dig := 0;                            sg := 4;  -- e: lower-left of leftmost
    elsif s <= 3 * NUM_SEGS + 1 then
      dig := s - (2 * NUM_SEGS + 2);       sg := 3;  -- d: bottom bar, left -> right
    elsif s = 3 * NUM_SEGS + 2 then
      dig := NUM_SEGS - 1;                 sg := 2;  -- c: lower-right of rightmost
    elsif s <= 4 * NUM_SEGS + 2 then
      dig := (4 * NUM_SEGS + 2) - s;       sg := 6;  -- g: middle bar, right -> left
    else
      dig := 0;                            sg := 5;  -- f: upper-left of leftmost
    end if;

    all_on := '0';
    if NUM_BUTTONS >= 2 then
      all_on := btn(1);
    end if;

    v_seg := (others => '0');
    if all_on = '1' then
      -- Light every segment and decimal point on every digit.
      for d in 0 to NUM_SEGS - 1 loop
        v_seg(8 * d + 7 downto 8 * d) := "11111111";
      end loop;
    else
      -- Convert logical digit -> seg slot and set the snake segment bit.
      -- Also set the dp bit (bit 7) of the decimal-point bounce digit.
      v_seg(8 * (NUM_SEGS - 1 - dig) + sg)   := '1';
      v_seg(8 * (NUM_SEGS - 1 - dp_pos) + 7) := '1';
    end if;
    seg <= v_seg;
  end process seg_proc;

  -- LED output ----------------------------------------------------------------
  -- One lit LED bounces back and forth (same as blinky_walking); btn(1) all on.
  led_proc : process(led_pos, btn) is
    variable all_on : std_logic;
  begin
    all_on := '0';
    if NUM_BUTTONS >= 2 then
      all_on := btn(1);
    end if;
    for i in 0 to NUM_LEDS - 1 loop
      if all_on = '1' then
        led(i) <= '1';
      elsif i = led_pos then
        led(i) <= '1';
      else
        led(i) <= '0';
      end if;
    end loop;
  end process led_proc;

end architecture rtl;
