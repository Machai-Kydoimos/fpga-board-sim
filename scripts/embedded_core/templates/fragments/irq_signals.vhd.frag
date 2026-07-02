  signal ier        : std_logic_vector(1 downto 0) := "00";
  signal timer_flag : std_logic := '0';
  signal input_flag : std_logic := '0';
  signal prev_sw    : std_logic_vector(NUM_SWITCHES - 1 downto 0) := (others => '0');
  signal prev_btn   : std_logic_vector(NUM_BUTTONS - 1 downto 0) := (others => '0');
