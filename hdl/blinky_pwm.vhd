-- blinky_pwm.vhd - Breathing (PWM fade) blinky.
--
-- All LEDs slowly fade in and out using pulse-width modulation.  Brightness
-- follows a triangle-wave envelope derived from the upper bits of a wide
-- free-running counter; the lower 8 bits form the PWM sawtooth.
--
-- Triangle wave construction:
--   When MSB of counter = 0 : brightness rises  0 -> 255  (ascending half)
--   When MSB of counter = 1 : brightness falls 255 -> 0   (descending half)
--   The falling half is the bitwise complement of the ascending ramp, which
--   equals (255 - ramp) for 8-bit values  -- a perfect mirror image.
--
-- Breathing period = 2^(COUNTER_BITS + 8) clocks.
-- At 100 MHz, COUNTER_BITS = 24 -> one full breath every ~43 seconds.
-- Reduce COUNTER_BITS (e.g. 16) for a faster breath (~167 ms).
--
-- sw(i)  : '1' enables LED i to breathe; '0' keeps it dark
-- btn(*) : any button held snaps all LEDs to full brightness
--
-- Effect  : LEDs slowly breathe in and out (sleeping-device glow).
-- Teaches : PWM, triangle-wave generation, duty-cycle arithmetic.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity blinky_pwm is
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
end entity blinky_pwm;

architecture rtl of blinky_pwm is

  -- Wide counter: bits [7:0] = PWM sawtooth; upper bits = envelope
  signal counter : unsigned(COUNTER_BITS + 7 downto 0) := (others => '0');

  -- 8-bit brightness from triangle-wave envelope
  signal envelope : unsigned(7 downto 0);

begin

  -- Free-running wide counter
  count_proc : process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  -- Triangle-wave envelope.
  -- The 8 envelope bits are counter[COUNTER_BITS+6 : COUNTER_BITS-1].
  -- The MSB of the full counter (bit COUNTER_BITS+7) selects ascending vs.
  -- descending: NOT of the ascending ramp gives the descending mirror.
  envelope <= counter(COUNTER_BITS + 6 downto COUNTER_BITS - 1)
              when counter(COUNTER_BITS + 7) = '0'
              else not counter(COUNTER_BITS + 6 downto COUNTER_BITS - 1);

  -- LED output: PWM comparison.
  -- LED(i) is on while the 8-bit PWM sawtooth (counter[7:0]) is less than
  -- the current brightness level.  sw(i)='0' disables that LED entirely.
  -- Any active button overrides brightness to maximum (255).
  led_proc : process(counter, envelope, sw, btn)
    variable pwm_cnt  : unsigned(7 downto 0);
    variable bright   : unsigned(7 downto 0);
    variable force_on : std_logic;
    variable enabled  : std_logic;
  begin
    pwm_cnt := counter(7 downto 0);

    force_on := '0';
    for i in 0 to NUM_BUTTONS - 1 loop
      force_on := force_on or btn(i);
    end loop;

    if force_on = '1' then
      bright := (others => '1');   -- full brightness
    else
      bright := envelope;
    end if;

    for i in 0 to NUM_LEDS - 1 loop
      -- Switches enable individual LEDs; unmatched LEDs default to enabled
      enabled := '1';
      if i < NUM_SWITCHES then
        enabled := sw(i);
      end if;

      if enabled = '0' then
        led(i) <= '0';
      elsif pwm_cnt < bright then
        led(i) <= '1';
      else
        led(i) <= '0';
      end if;
    end loop;
  end process led_proc;

end architecture rtl;
