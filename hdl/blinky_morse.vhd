-- blinky_morse.vhd – SOS Morse code blinky.
--
-- All LEDs continuously blink the international SOS distress signal:
--   S = · · ·   O = − − −   S = · · ·   (then a long word gap)
--
-- Timing follows standard Morse code proportions:
--   dot      = 1 unit    dash    = 3 units
--   intra-character gap = 1 unit
--   inter-character gap = 3 units   word gap = 7 units
--
-- One "unit" is 2^COUNTER_BITS clock cycles (one counter rollover).
-- At 100 MHz, COUNTER_BITS = 24 → unit ≈ 167 ms → full SOS ≈ 5.7 s.
--
-- sw(i)  : '0' mutes LED i from the pattern (keeps it dark)
-- btn(*) : any button held lights all LEDs at full brightness
--
-- Effect  : LEDs broadcast SOS in Morse code, repeating forever.
-- Teaches : ROM lookup tables, state sequencing, variable-length timing.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity blinky_morse is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk  : in  std_logic;
    sw   : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn  : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led  : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity blinky_morse;

architecture rtl of blinky_morse is

  -- SOS Morse sequence encoded as two parallel ROM arrays.
  -- Each entry is one element: a LED state ('1'=on, '0'=gap) and its
  -- duration in Morse units.
  constant ROM_LEN : positive := 18;

  type state_rom_t    is array (0 to ROM_LEN - 1) of std_logic;
  type duration_rom_t is array (0 to ROM_LEN - 1) of positive;

  -- S: dot gap dot gap dot char-gap
  -- O: dash gap dash gap dash char-gap
  -- S: dot gap dot gap dot word-gap
  constant SOS_STATE : state_rom_t := (
    '1','0','1','0','1','0',   -- S  (3 dots + 2 intra + 1 char-gap)
    '1','0','1','0','1','0',   -- O  (3 dashes + 2 intra + 1 char-gap)
    '1','0','1','0','1','0'    -- S  (3 dots + 2 intra + 1 word-gap)
  );

  constant SOS_DUR : duration_rom_t := (
    1, 1, 1, 1, 1, 3,          -- S
    3, 1, 3, 1, 3, 3,          -- O
    1, 1, 1, 1, 1, 7           -- S + word gap
  );

  -- Total duration = 8 + 14 + 12 = 34 units

  signal counter    : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
  signal sym_idx    : integer range 0 to ROM_LEN - 1 := 0;
  signal unit_cnt   : integer range 0 to 7 := 0;   -- counts down within a symbol
  signal led_state  : std_logic := '0';

begin

  -- Free-running counter; its rollover (back to zero) is the Morse "tick"
  count_proc : process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  -- Morse sequencer: advance on each counter rollover (tick).
  seq_proc : process(clk)
    variable next_idx : integer range 0 to ROM_LEN - 1;
  begin
    if rising_edge(clk) then
      -- Tick fires when counter wraps back to zero
      if counter = 0 then
        if unit_cnt = 0 then
          -- Finished this symbol; move to next
          if sym_idx = ROM_LEN - 1 then
            next_idx := 0;
          else
            next_idx := sym_idx + 1;
          end if;
          sym_idx   <= next_idx;
          led_state <= SOS_STATE(next_idx);
          unit_cnt  <= SOS_DUR(next_idx) - 1;
        else
          unit_cnt <= unit_cnt - 1;
        end if;
      end if;
    end if;
  end process seq_proc;

  -- LED output: apply Morse state to all LEDs, gated by switches.
  -- Any active button overrides to all-on (full brightness).
  led_proc : process(led_state, sw, btn)
    variable force_on : std_logic;
    variable enabled  : std_logic;
  begin
    force_on := '0';
    for i in 0 to NUM_BUTTONS - 1 loop
      force_on := force_on or btn(i);
    end loop;

    for i in 0 to NUM_LEDS - 1 loop
      -- sw(i)='0' mutes this LED; unmatched LEDs default to enabled
      enabled := '1';
      if i < NUM_SWITCHES then
        enabled := sw(i);
      end if;

      if force_on = '1' then
        led(i) <= '1';
      else
        led(i) <= led_state and enabled;
      end if;
    end loop;
  end process led_proc;

end architecture rtl;
