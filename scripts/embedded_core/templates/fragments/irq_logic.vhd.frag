  -- Interrupt controller: two sources (timer + sw/btn change).  Each has an
  -- enable bit (IER $E011) and a flag bit (IFR $E012, write-1-to-clear); irq is
  -- the OR of enabled+pending flags, and the ISR reads IFR to see who fired.
  interrupts : process (clk) begin
    if rising_edge(clk) then
      prev_sw  <= sw;
      prev_btn <= btn;
      -- register writes first, so a same-cycle flag set (below) wins the race
      if cs = '1' and we = '1' then
        if addr = x"11" then
          ier <= wdata(1 downto 0);
        elsif addr = x"12" then
          if wdata(0) = '1' then timer_flag <= '0'; end if;
          if wdata(1) = '1' then input_flag <= '0'; end if;
        end if;
      end if;
      -- flag sources (set wins over a simultaneous ack)
      if prescaler = (prescaler'range => '1') then
        timer_flag <= '1';
      end if;
      if sw /= prev_sw or btn /= prev_btn then
        input_flag <= '1';
      end if;
    end if;
  end process;

  irq <= (timer_flag and ier(0)) or (input_flag and ier(1));
