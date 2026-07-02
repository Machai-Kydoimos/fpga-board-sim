  lfsr : process (clk) begin
    if rising_edge(clk) then
      lfsr_reg <= lfsr_reg(6 downto 0) &
                  (lfsr_reg(7) xor lfsr_reg(5) xor lfsr_reg(4) xor lfsr_reg(3));
    end if;
  end process;
