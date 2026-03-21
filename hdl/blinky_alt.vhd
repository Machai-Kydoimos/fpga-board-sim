-- blinky_alt.vhd - Alternating-phase blinky.
--
-- Even-indexed LEDs and odd-indexed LEDs blink in opposite phase: when the
-- even group is on the odd group is off, and vice versa.  The blink rate is
-- set by COUNTER_BITS (MSB of the free-running counter).
--
-- sw(i)  : '1' enables LED i; '0' keeps it dark regardless of phase
--          (unmatched LEDs  -- where i >= NUM_SWITCHES  -- are always enabled)
-- btn(0) : held  -- inverts the current phase of both groups simultaneously
-- btn(1) : held  -- forces all LEDs on regardless of phase or switches
--
-- Effect  : Two groups of LEDs flash in opposition (like a crossing signal).
-- Teaches : XOR phase patterns, combinational gating, minimal logic.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity blinky_alt is
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
end entity blinky_alt;

architecture rtl of blinky_alt is
  signal counter : unsigned(COUNTER_BITS - 1 downto 0) := (others => '0');
begin

  -- Free-running counter
  count_proc : process(clk)
  begin
    if rising_edge(clk) then
      counter <= counter + 1;
    end if;
  end process count_proc;

  -- LED output: purely combinational.
  --
  -- base_phase = counter MSB  (the blink signal)
  -- btn(0) held XORs a '1' into the phase, inverting both groups.
  -- Even LEDs follow base_phase; odd LEDs follow its complement.
  -- sw(i) gates LED i; btn(1) overrides to full-on.
  led_proc : process(counter, sw, btn)
    variable base_phase : std_logic;
    variable phase_inv  : std_logic;
    variable all_on     : std_logic;
    variable blink_val  : std_logic;
    variable enabled    : std_logic;
  begin
    base_phase := counter(COUNTER_BITS - 1);

    phase_inv := '0';
    if NUM_BUTTONS >= 1 then
      phase_inv := btn(0);   -- held = inverted phase
    end if;

    all_on := '0';
    if NUM_BUTTONS >= 2 then
      all_on := btn(1);
    end if;

    for i in 0 to NUM_LEDS - 1 loop
      -- Even LEDs: in-phase; odd LEDs: out-of-phase
      if i mod 2 = 0 then
        blink_val := base_phase xor phase_inv;
      else
        blink_val := (not base_phase) xor phase_inv;
      end if;

      -- Switch enables this LED; unmatched LEDs are always enabled
      enabled := '1';
      if i < NUM_SWITCHES then
        enabled := sw(i);
      end if;

      if all_on = '1' then
        led(i) <= '1';
      else
        led(i) <= blink_val and enabled;
      end if;
    end loop;
  end process led_proc;

end architecture rtl;
