-- rgb_rainbow.vhd - RGB LED color demo (U37).
--
-- Drives every RGB LED site through per-channel PWM, using the simulator's
-- channel layout: mono LEDs occupy led[MONO-1:0] and each RGB site i owns
-- led(MONO + 3*i + 0/1/2) = (r, g, b), where MONO = NUM_LEDS - 3*NUM_RGB_LEDS.
-- The simulator measures each channel's duty exactly and mixes the rendered
-- color, so smooth PWM sweeps read as smooth hue sweeps on screen.
--
-- Mode select on sw(1 downto 0):
--   00  rainbow rotate : every site sweeps the hue circle, sites offset from
--                        each other by 360/NUM_RGB_LEDS degrees
--   01  static hue     : hue set by sw(9 downto 2) (MSB-first; missing
--                        switches read as '0'), same hue on every site
--   10  RGB-cube scan  : r/g/b duties are three windows of one slow counter,
--                        so red sweeps quickly inside a slower green inside a
--                        glacial blue - every mixable color, eventually
--   11  white breathe  : r = g = b follows a triangle envelope (validates the
--                        white mix and the (1,1,1) -> white wash)
--
-- Any button held snaps every channel to full - instant white (and a quick
-- sanity check that all three channels of every site are wired).
--
-- Hue -> RGB uses three triangle waves 120 degrees apart (the classic
-- approximation): tri(x) folds an 8-bit phase into /\, and the r/g/b phases
-- are offset so red peaks at hue 0, green at 85, blue at 170.  Neighboring
-- channels overlap, so colors are near-saturated rather than laser-pure -
-- exactly how hobby RGB LED "rainbow" firmware looks on real hardware.
--
-- Rates are derived from mid-counter taps like blinky_pwm: at the simulator's
-- COUNTER_BITS = 17 floor, one full hue rotation is 2^(COUNTER_BITS+4) clocks
-- = 21 ms of simulated time (roughly 8 wall-seconds on GHDL-mcode, ~1 s on
-- NVC), and the PWM sawtooth is counter(7:0) - a 2.56 us period at 100 MHz,
-- far above the eye's fusion rate.  The cube scan's blue window is
-- deliberately the slow axis; it drifts over wall-minutes.  Real hardware
-- would tap higher and use the full COUNTER_BITS default.
--
-- Mono LEDs mirror their switch (led(i) <= sw(i mod NUM_SWITCHES)) so boards
-- with both kinds show the inputs are alive; on a board with no RGB LEDs the
-- site loop runs zero times and that mirror is the whole (contract-clean)
-- design.  All the site math loops inside one process, blinky_pwm-style.
--
-- Effect  : all RGB LEDs sweep the color wheel (or scan / breathe / hold).
-- Teaches : the RGB channel layout, NUM_RGB_LEDS, per-channel PWM color mixing.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity rgb_rainbow is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_RGB_LEDS : natural  := 0;
    COUNTER_BITS : positive := 24
  );
  port (
    clk  : in  std_logic;
    sw   : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn  : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led  : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity rgb_rainbow;

architecture rtl of rgb_rainbow is

  -- Mono LEDs fill the low bits; RGB channels sit above them (U37 layout).
  constant MONO : natural := NUM_LEDS - 3 * NUM_RGB_LEDS;

  -- Wide counter: bits [7:0] = PWM sawtooth; the hue and cube windows sit
  -- higher.  CUBE_LSB places the cube's fast (red) axis so its LSB flips
  -- every 2^(COUNTER_BITS-6) clocks; the counter is sized to fit the blue
  -- window's top bit, CUBE_LSB + 23.
  constant CUBE_LSB : natural := COUNTER_BITS - 6;
  signal counter : unsigned(CUBE_LSB + 23 downto 0) := (others => '0');

  -- 8-bit hue phase: one full rotation per 2^(COUNTER_BITS+4) clocks.
  signal hue : unsigned(7 downto 0);

  -- Triangle envelope for white breathe, identical construction to blinky_pwm.
  signal envelope : unsigned(7 downto 0);

  -- (r, g, b) duty bytes for one site.
  type duty_array is array (0 to 2) of unsigned(7 downto 0);

  -- Fold an 8-bit phase into a triangle: 0..127 ramps up, 128..255 mirrors.
  function tri (phase : unsigned(7 downto 0)) return unsigned is
    variable ramp : unsigned(7 downto 0);
  begin
    ramp := phase(6 downto 0) & '0';
    if phase(7) = '0' then
      return ramp;
    else
      return not ramp;
    end if;
  end function;

begin

  count_proc : process (clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  hue      <= counter(COUNTER_BITS + 3 downto COUNTER_BITS - 4);
  envelope <= tri(hue);

  -- One process drives the whole led vector: the mono mirrors, then every
  -- RGB site's mode-selected (r, g, b) duties through the PWM compare.
  -- (Loops inside one process, blinky_pwm-style, rather than per-site
  -- generate blocks: GHDL-mcode does not re-elaborate generic-dependent
  -- generate structure for ``-r``-time generic overrides.)
  led_proc : process (counter, hue, envelope, sw, btn)
    variable mode     : unsigned(1 downto 0);
    variable hue_sw   : unsigned(7 downto 0);
    variable phase    : unsigned(7 downto 0);
    variable site_hue : unsigned(7 downto 0);
    variable duty     : duty_array;
    variable pwm_cnt  : unsigned(7 downto 0);
    variable force_on : std_logic;
  begin
    -- Mono LEDs mirror their switch, so the low bank stays meaningful.
    for i in 0 to MONO - 1 loop
      led(i) <= sw(i mod NUM_SWITCHES);
    end loop;

    -- Inputs beyond the board's switch count read as '0' (mode 00, hue 0).
    mode := (others => '0');
    for k in 0 to 1 loop
      if k <= NUM_SWITCHES - 1 then
        mode(k) := sw(k);
      end if;
    end loop;
    hue_sw := (others => '0');
    for k in 0 to 7 loop
      if 2 + k <= NUM_SWITCHES - 1 then
        hue_sw(7 - k) := sw(2 + k);
      end if;
    end loop;

    force_on := '0';
    for k in 0 to NUM_BUTTONS - 1 loop
      force_on := force_on or btn(k);
    end loop;

    pwm_cnt := counter(7 downto 0);
    for i in 0 to NUM_RGB_LEDS - 1 loop
      -- Site phase offset for the rotate mode: 360/NUM_RGB_LEDS degrees apart.
      phase := to_unsigned((i * 256 / NUM_RGB_LEDS) mod 256, 8);

      case to_integer(mode) is
        when 0 =>  -- rainbow rotate
          site_hue := hue + phase;
          duty(0) := tri(site_hue + 128);
          duty(1) := tri(site_hue + 43);
          duty(2) := tri(site_hue + 214);
        when 1 =>  -- static hue from switches
          site_hue := hue_sw;
          duty(0) := tri(site_hue + 128);
          duty(1) := tri(site_hue + 43);
          duty(2) := tri(site_hue + 214);
        when 2 =>  -- RGB-cube scan: three windows of the slow counter
          duty(0) := counter(CUBE_LSB + 7 downto CUBE_LSB);
          duty(1) := counter(CUBE_LSB + 15 downto CUBE_LSB + 8);
          duty(2) := counter(CUBE_LSB + 23 downto CUBE_LSB + 16);
        when others =>  -- white breathe
          duty(0) := envelope;
          duty(1) := envelope;
          duty(2) := envelope;
      end case;

      if force_on = '1' then
        duty(0) := (others => '1');
        duty(1) := (others => '1');
        duty(2) := (others => '1');
      end if;

      for c in 0 to 2 loop
        if pwm_cnt < duty(c) then
          led(MONO + 3 * i + c) <= '1';
        else
          led(MONO + 3 * i + c) <= '0';
        end if;
      end loop;
    end loop;
  end process led_proc;

end architecture rtl;
