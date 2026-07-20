-- duty_probe.vhd - PWM duty-cycle measurement test fixture (U9 phase 0).
--
-- Not a demo and NOT surfaced in the file picker: it lives under sim/ (like
-- sim_wrapper_template.vhd), referenced by path from the duty-engine tests.
-- It presents channels with exactly-known duty cycles so a test can read the
-- wrapper's duty accumulators and assert the measured duty against ground
-- truth, including the cases that break a naive integrator:
--
--   led(0) : stuck '0'                      -> duty 0.0   (stuck-OFF)
--   led(1) : stuck '1'                      -> duty 1.0   (stuck-ON: the
--                                              free-running-accumulator case
--                                              a duty engine must get right)
--   led(2) : 25% at a 256-clk period        -> duty 0.25  (power-of-two period),
--            gated by sw(1) so a test can flip a PWM channel mid-run
--   led(3) : 50% at a 100-clk period        -> duty 0.50  (NON-power-of-two
--                                              period: a sampler would alias;
--                                              an exact integrator will not)
--   led(4) : follows sw(0) directly         -> combinational gate, used for
--                                              the mid-run flip, the partial-
--                                              tail double-count case, and the
--                                              >2.2 s static-gap overflow test
--   led(5..): '0'                           -> spare stuck-OFF channels
--
-- Requires NUM_LEDS >= 5 and NUM_SWITCHES >= 2 (always elaborated so by the
-- tests).  COUNTER_BITS is part of the generic contract but unused here.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity duty_probe is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 8;
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity duty_probe;

architecture rtl of duty_probe is
  -- 256-clk sawtooth (power-of-two period) for the 25% channel.
  signal cnt256 : unsigned(7 downto 0) := (others => '0');
  -- 100-clk sawtooth (non-power-of-two period) for the 50% channel.
  signal cnt100 : integer range 0 to 99 := 0;
begin

  counters : process(clk)
  begin
    if rising_edge(clk) then
      cnt256 <= cnt256 + 1;
      if cnt100 = 99 then
        cnt100 <= 0;
      else
        cnt100 <= cnt100 + 1;
      end if;
    end if;
  end process counters;

  led(0) <= '0';
  led(1) <= '1';
  led(2) <= '1' when (sw(1) = '1' and cnt256 < 64) else '0';
  led(3) <= '1' when (cnt100 < 50) else '0';
  led(4) <= sw(0);

  spare : for i in 5 to NUM_LEDS - 1 generate
    led(i) <= '0';
  end generate spare;

end architecture rtl;
