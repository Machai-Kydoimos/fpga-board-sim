-- nexys4ddr_scan.vhd
--
-- A board-native design for the Digilent Nexys 4 DDR written to its Master-XDC
-- physical scan-display names: the shared segment cathodes CA..CG and DP as
-- scalar ports plus the AN[7:0] digit-enable anodes, all active-low per the RM
-- ("both the AN0..7 and the CA..G/DP signals are driven low when active"),
-- with fixed widths and no simulator generics.  It simulates unmodified under
-- fpga-sim via the U22 `scan` convention style: the native wrapper
-- demultiplexes the scan combinationally, and Full duty mode renders each
-- digit at its honest 1/8 scan brightness.
--
-- Behavior: an 8-digit hex counter (digit i shows nibble i of a free-running
-- value; the top digits move glacially, exactly as a real counter's would);
-- the decimal point marks digit 0; SW drives the mono LEDs; BTNC is a lamp
-- test forcing every segment + dp lit on every digit simultaneously.
--
-- Scan FAST in simulation: this design's digit slot is 128 clocks (1.28 us at
-- 100 MHz -- a ~98 kHz refresh a real display would also accept), NOT the
-- ~1 kHz a hardware-first design would pick.  At the simulator's sub-real-time
-- throughput the duty window spans only tens of microseconds of simulated
-- time, so a 1 kHz scan would parade one digit at a time across the window
-- instead of averaging into steady 1/8-brightness digits.  This is the
-- scan-rate cousin of the mid-counter-bits rule below.
--
-- Tap MID counter bits for content: board-native designs get no COUNTER_BITS
-- override, so the displayed value starts at bit 18 (visible movement at sim
-- speed; a fast shimmer on real hardware).
--
-- Like the other hdl/native examples it matches only via a board's convention
-- and is deliberately NOT surfaced in the file picker.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity nexys4ddr_scan is
  port (
    CLK100MHZ : in  std_logic;
    SW        : in  std_logic_vector(15 downto 0);
    BTNC      : in  std_logic;
    BTNU      : in  std_logic;
    BTND      : in  std_logic;
    BTNL      : in  std_logic;
    BTNR      : in  std_logic;
    LED       : out std_logic_vector(15 downto 0);
    CA        : out std_logic;
    CB        : out std_logic;
    CC        : out std_logic;
    CD        : out std_logic;
    CE        : out std_logic;
    CF        : out std_logic;
    CG        : out std_logic;
    DP        : out std_logic;
    AN        : out std_logic_vector(7 downto 0)
  );
end entity;

architecture rtl of nexys4ddr_scan is
  signal count : unsigned(49 downto 0) := (others => '0');

  -- Scan machinery: which digit's slot is active (128 clocks per digit).
  signal scan_digit : unsigned(2 downto 0);
  -- The displayed 32-bit value (mid counter bits; see header).
  signal value : unsigned(31 downto 0);
  -- Active-high internal segment pattern {g,f,e,d,c,b,a} for the active digit.
  signal segs   : std_logic_vector(6 downto 0);
  signal nibble : unsigned(3 downto 0);

  -- Hex glyphs, {g,f,e,d,c,b,a} active-high (same shapes as counter_7seg).
  type seg_lut_t is array (0 to 15) of std_logic_vector(6 downto 0);
  constant SEG_LUT : seg_lut_t := (
    "0111111", "0000110", "1011011", "1001111",  -- 0 1 2 3
    "1100110", "1101101", "1111101", "0000111",  -- 4 5 6 7
    "1111111", "1101111", "1110111", "1111100",  -- 8 9 A b
    "0111001", "1011110", "1111001", "1110001"   -- C d E F
  );
begin

  process (CLK100MHZ) is
  begin
    if rising_edge(CLK100MHZ) then
      count <= count + 1;
    end if;
  end process;

  scan_digit <= count(9 downto 7);
  value      <= count(49 downto 18);

  -- Multiplex: the active digit's nibble drives the shared segment lines.
  -- shift_right + resize (keeps the low bits): the active digit's nibble,
  -- without a signal-dependent slice range.
  nibble <= resize(shift_right(value, to_integer(scan_digit) * 4), 4);
  segs   <= SEG_LUT(to_integer(nibble));

  -- Active-low drive; BTNC lamp test forces everything lit at once.
  CA <= '0' when BTNC = '1' else not segs(0);
  CB <= '0' when BTNC = '1' else not segs(1);
  CC <= '0' when BTNC = '1' else not segs(2);
  CD <= '0' when BTNC = '1' else not segs(3);
  CE <= '0' when BTNC = '1' else not segs(4);
  CF <= '0' when BTNC = '1' else not segs(5);
  CG <= '0' when BTNC = '1' else not segs(6);

  -- Decimal point marks digit 0 (lit only during digit 0's slot).
  DP <= '0' when BTNC = '1' or scan_digit = 0 else '1';

  -- One-hot active-low anode for the scanned digit; lamp test enables all.
  AN <= (others => '0') when BTNC = '1'
        else not std_logic_vector(shift_left(to_unsigned(1, 8), to_integer(scan_digit)));

  LED <= SW;

end architecture;
