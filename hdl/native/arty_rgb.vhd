-- arty_rgb.vhd
--
-- A board-native design for the Digilent Arty A7 written to its Master-XDC RGB
-- channel names (led0_r .. led3_b as twelve scalar ports) plus the mono
-- led/sw/btn vectors, with fixed widths and no simulator generics.  It
-- simulates unmodified under fpga-sim via the U38 `leds_rgb` convention bank:
-- boards/digilent-xdc/arty_a7-100.json maps each scalar onto one boundary RGB
-- channel, active-high per the RM (the channels drive inverting transistors, so
-- the FPGA pin lights its channel when driven high).
--
-- Behavior: the four RGB LEDs rotate through a color wheel, each site a
-- quarter-turn apart; sw XORs the mono LED pattern; btn(0) is a lamp test that
-- forces all twelve channels solid on.  Per-channel duty is capped at 50%
-- following the RM's advice ("Driving any of the inputs to a steady logic '1'
-- will result in the LED being illuminated at an uncomfortably bright level")
-- -- except for the deliberate lamp test.
--
-- Tap MID counter bits: board-native designs get no COUNTER_BITS override, so
-- the top of a full 100 MHz divider would be invisible at sim speed (the wheel
-- position lives in count(21 downto 14), a fast shimmer on real hardware but a
-- visible rotation in simulation -- same trade-off as arty_litex.vhd).
--
-- Like the other hdl/native examples it matches only via a board's convention
-- and is deliberately NOT surfaced in the file picker.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity arty_rgb is
  port (
    CLK100MHZ : in  std_logic;
    sw        : in  std_logic_vector(3 downto 0);
    btn       : in  std_logic_vector(3 downto 0);
    led       : out std_logic_vector(3 downto 0);
    led0_r, led0_g, led0_b : out std_logic;
    led1_r, led1_g, led1_b : out std_logic;
    led2_r, led2_g, led2_b : out std_logic;
    led3_r, led3_g, led3_b : out std_logic
  );
end entity;

architecture rtl of arty_rgb is
  signal count : unsigned(27 downto 0) := (others => '0');
  signal rgb   : std_logic_vector(11 downto 0) := (others => '0');

  -- Color-wheel offset per channel, (r,g,b) per site: sites sit a quarter-turn
  -- (64) apart and the three colors of a site a third-turn (85) apart.
  type phase_array is array (0 to 11) of natural;
  constant PHASE : phase_array :=
    (0, 85, 170, 64, 149, 234, 128, 213, 42, 192, 21, 106);

  -- Full-scale triangle over the 8-bit wheel (same shape as rgb_rainbow.vhd).
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

  wheel : process (CLK100MHZ)
    variable hue : unsigned(7 downto 0);
    variable pwm : unsigned(7 downto 0);
    variable lvl : unsigned(7 downto 0);
  begin
    if rising_edge(CLK100MHZ) then
      count <= count + 1;
      hue := count(21 downto 14);
      pwm := count(7 downto 0);
      for i in 0 to 11 loop
        lvl := tri(hue + to_unsigned(PHASE(i), 8));
        if btn(0) = '1' then                      -- lamp test (buttons active-high)
          rgb(i) <= '1';
        elsif pwm < ('0' & lvl(7 downto 1)) then  -- halved: <= 50% duty per the RM
          rgb(i) <= '1';
        else
          rgb(i) <= '0';
        end if;
      end loop;
    end if;
  end process;

  -- Mono LEDs: mid counter bits, XORed with the switches (as arty_litex.vhd).
  led <= std_logic_vector(count(21 downto 18)) xor sw;

  led0_r <= rgb(0);  led0_g <= rgb(1);  led0_b <= rgb(2);
  led1_r <= rgb(3);  led1_g <= rgb(4);  led1_b <= rgb(5);
  led2_r <= rgb(6);  led2_g <= rgb(7);  led2_b <= rgb(8);
  led3_r <= rgb(9);  led3_g <= rgb(10); led3_b <= rgb(11);

end architecture;
