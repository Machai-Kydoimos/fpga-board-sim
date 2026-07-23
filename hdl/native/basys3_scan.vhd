-- basys3_scan.vhd
--
-- A board-native design for the Digilent Basys 3 written to its Master-XDC
-- physical scan-display names: the shared 7-bit segment vector `seg`, the
-- `dp` scalar, and the an[3:0] digit-enable anodes, all active-low per the RM
-- ("both the AN0..3 and the CA..G/DP signals are driven low when active"),
-- with fixed widths and no simulator generics.  The vector-segment sibling of
-- nexys4ddr_scan.vhd (whose CA..CG are distinct scalars); together they cover
-- both Digilent scan idioms the U22 `scan` convention style adapts.
--
-- Behavior: a 4-digit hex counter (digit i shows nibble i of a mid-bit value),
-- dp marks digit 0, sw drives the mono LEDs, btnC is a lamp test.  Scan FAST
-- (128-clock digit slots) and tap MID counter bits -- see nexys4ddr_scan.vhd's
-- header for why both rules matter at the simulator's sub-real-time speed.
--
-- Like the other hdl/native examples it matches only via a board's convention
-- and is deliberately NOT surfaced in the file picker.

library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity basys3_scan is
  port (
    clk  : in  std_logic;
    sw   : in  std_logic_vector(15 downto 0);
    btnC : in  std_logic;
    btnU : in  std_logic;
    btnD : in  std_logic;
    btnL : in  std_logic;
    btnR : in  std_logic;
    led  : out std_logic_vector(15 downto 0);
    seg  : out std_logic_vector(6 downto 0);
    dp   : out std_logic;
    an   : out std_logic_vector(3 downto 0)
  );
end entity;

architecture rtl of basys3_scan is
  signal count : unsigned(33 downto 0) := (others => '0');

  signal scan_digit : unsigned(1 downto 0);
  signal value      : unsigned(15 downto 0);
  signal segs       : std_logic_vector(6 downto 0);
  signal nibble     : unsigned(3 downto 0);

  -- Hex glyphs, {g,f,e,d,c,b,a} active-high (same shapes as counter_7seg).
  type seg_lut_t is array (0 to 15) of std_logic_vector(6 downto 0);
  constant SEG_LUT : seg_lut_t := (
    "0111111", "0000110", "1011011", "1001111",  -- 0 1 2 3
    "1100110", "1101101", "1111101", "0000111",  -- 4 5 6 7
    "1111111", "1101111", "1110111", "1111100",  -- 8 9 A b
    "0111001", "1011110", "1111001", "1110001"   -- C d E F
  );
begin

  process (clk) is
  begin
    if rising_edge(clk) then
      count <= count + 1;
    end if;
  end process;

  scan_digit <= count(8 downto 7);
  value      <= count(33 downto 18);

  -- shift_right + resize (keeps the low bits): the active digit's nibble,
  -- without a signal-dependent slice range.
  nibble <= resize(shift_right(value, to_integer(scan_digit) * 4), 4);
  segs   <= SEG_LUT(to_integer(nibble));

  -- Active-low drive; btnC lamp test forces everything lit at once.
  seg <= (others => '0') when btnC = '1' else not segs;
  dp  <= '0' when btnC = '1' or scan_digit = 0 else '1';
  an  <= (others => '0') when btnC = '1'
         else not std_logic_vector(shift_left(to_unsigned(1, 4), to_integer(scan_digit)));

  led <= sw;

end architecture;
