-- stopwatch_7seg.vhd  --  Interactive stopwatch: start/stop/reset under button control.
--
-- A decimal stopwatch counts up across the 7-segment digits.  btn(0) starts
-- and stops it; btn(1) resets the displayed digits to all-zero (without
-- changing whether it is running).  Each active switch doubles the count
-- rate.
--
-- Inputs are clean in this simulator (no debounce/metastability needed), so
-- btn(0)/btn(1) are sampled synchronously with a simple previous-value
-- register for edge detection -- same idiom as walking_counter_7seg.vhd.
--
-- Effect  : Same "start/stop/reset under user control" interaction as the
--           embedded-core firmware demos, but in hand-written RTL -- the
--           hardware side of this repo's "same behavior, hardware vs
--           software" teaching pair (see docs/embedded_core_system_guide.md).
-- Teaches : A free-running divider sized from a contract generic, BCD
--           ripple-increment (count-up only), synchronous edge detection on
--           two independent buttons, and decoupling "what changes"
--           (running) from "how it's rendered" (the digits).
--
-- -- 7-SEGMENT PORT CONTRACT (see counter_7seg.vhd for full details) -----------
--
-- seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
--
-- Digit i occupies bits [8*i+7 : 8*i].  Digit 0 = rightmost display.
-- Within each slot, bit positions are: dp=7, g=6, f=5, e=4, d=3, c=2, b=1, a=0
-- (all active-high).
--
-- ------------------------------------------------------------------------------

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity stopwatch_7seg is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;
    COUNTER_BITS : positive := 32   -- sizes the time-base divider; the simulator overrides this at runtime
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
  );
end entity stopwatch_7seg;

architecture rtl of stopwatch_7seg is

  signal divider   : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
  signal step_idx  : integer range 0 to COUNTER_BITS - 1 := COUNTER_BITS - 1;
  signal prev_step : std_logic := '0';   -- previous divider(step_idx), for edge detection

  signal running   : std_logic := '0';   -- '1' while the stopwatch is counting
  signal prev_btn0 : std_logic := '0';   -- previous btn(0), for rising-edge detection
  signal prev_btn1 : std_logic := '0';   -- previous btn(1), for rising-edge detection

  -- BCD counter: one integer per decimal digit, each constrained to 0-9.
  -- Index 0 = units (rightmost display); index NUM_SEGS-1 = most significant (leftmost).
  type bcd_arr_t is array(0 to NUM_SEGS - 1) of integer range 0 to 9;
  signal bcd_cnt : bcd_arr_t := (others => 0);

  -- Segment LUT: maps a decimal digit (0-9) to an 8-bit segment pattern.
  -- See counter_7seg.vhd for the full segment bit layout and derivation.
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

  -- Free-running time-base divider ---------------------------------------------
  div_proc : process(clk) is
  begin
    if rising_edge(clk) then
      divider <= divider + 1;
    end if;
  end process div_proc;

  -- Speed index from switch popcount --------------------------------------------
  -- Each active switch subtracts 1 from step_idx, halving the step period
  -- (doubling the rate).  Base is capped at bit 16 so the step rate is
  -- consistent across all boards regardless of the COUNTER_BITS value set by
  -- the simulator.  Same idiom as walking_counter_7seg.vhd.
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
    idx := base - n;
    if idx < 1 then
      idx := 1;
    end if;
    step_idx <= idx;
  end process idx_proc;

  -- Start/stop/reset + BCD ripple ------------------------------------------------
  -- btn(0) rising edge toggles `running`.  btn(1) rising edge zeroes the
  -- digits without changing `running` (checked and applied after any
  -- same-cycle ripple, so a reset always wins).  While running, each rising
  -- edge of divider(step_idx) ripple-increments the BCD digits, wrapping at
  -- all-9s -- same carry idiom as walking_counter_7seg.vhd, count-up only.
  main_proc : process(clk) is
    variable bcd_v : bcd_arr_t;
    variable carry : integer range 0 to 1;
    variable tmp   : integer range 0 to 10;
  begin
    if rising_edge(clk) then
      bcd_v := bcd_cnt;

      prev_step <= divider(step_idx);
      if running = '1' and prev_step = '0' and divider(step_idx) = '1' then
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
      end if;

      prev_btn0 <= '0';
      if NUM_BUTTONS >= 1 then
        prev_btn0 <= btn(0);
        if prev_btn0 = '0' and btn(0) = '1' then
          running <= not running;
        end if;
      end if;

      prev_btn1 <= '0';
      if NUM_BUTTONS >= 2 then
        prev_btn1 <= btn(1);
        if prev_btn1 = '0' and btn(1) = '1' then
          bcd_v := (others => 0);
        end if;
      end if;

      bcd_cnt <= bcd_v;
    end if;
  end process main_proc;

  -- LED output: led(0) shows whether the stopwatch is running; the rest stay dark.
  led_proc : process(running) is
  begin
    for i in 0 to NUM_LEDS - 1 loop
      if i = 0 then
        led(i) <= running;
      else
        led(i) <= '0';
      end if;
    end loop;
  end process led_proc;

  -- 7-segment output: each digit slot i is driven by bcd_cnt(i) through the LUT.
  seg_proc : process(bcd_cnt) is
  begin
    for i in 0 to NUM_SEGS - 1 loop
      seg(8 * i + 7 downto 8 * i) <= SEG_LUT(bcd_cnt(i));
    end loop;
  end process seg_proc;

end architecture rtl;
