      when x"11"  => rdata <= "000000" & ier;
      when x"12"  => rdata <= "000000" & input_flag & timer_flag;
