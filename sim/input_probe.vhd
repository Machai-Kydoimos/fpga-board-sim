-- input_probe.vhd - button-edge counting test fixture (U44 phase 2, issue #353).
--
-- Not a demo and NOT surfaced in the file picker: it lives under sim/ (like
-- duty_probe.vhd and sim_wrapper_template.vhd), referenced by path from the
-- input-queue tests.
--
-- The bug it exists to catch is invisible to a level-sensitive design.  The
-- child used to apply every drained input message with no await between them,
-- so cocotb collapsed a whole batch to the last value written: a press and its
-- release arriving in one drain became "btn = 0" and the press never existed
-- as far as the simulator was concerned.  A design that merely *mirrors* btn
-- onto led cannot tell that apart from a press that never happened -- both end
-- with the LED off.  So this probe latches instead:
--
--   led : count of RISING edges seen on btn(0), free-running, never cleared
--
-- A test can therefore assert on a *permanent* record of what the DUT actually
-- observed, rather than racing to sample a transient level.  With the queue in
-- place a press+release pair drained together applies across two iterations,
-- one await Timer apart, and the count reaches 1; without it the count stays 0
-- forever.
--
-- btn is registered twice before the edge test: the wrapper drives it from VPI
-- writes that land asynchronously to clk, so a single flop could sample it
-- mid-transition.  Two-stage synchronization is what real hardware does with an
-- external button for the same reason.
--
-- COUNTER_BITS and sw are part of the generic contract but unused here.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity input_probe is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity input_probe;

architecture rtl of input_probe is
  signal sync   : std_logic_vector(1 downto 0) := (others => '0');
  signal edges  : unsigned(NUM_LEDS - 1 downto 0) := (others => '0');
begin

  counter : process(clk)
  begin
    if rising_edge(clk) then
      sync <= sync(0) & btn(0);
      -- Saturate rather than wrap: a test asserting "at least one press was
      -- seen" must never be fooled by a count that rolled back to zero.
      if sync(0) = '1' and sync(1) = '0' and edges /= (edges'range => '1') then
        edges <= edges + 1;
      end if;
    end if;
  end process counter;

  led <= std_logic_vector(edges);

end architecture rtl;
