  -- T80 (Z80) in interrupt mode 2: as the simple adapter, plus the interrupt-
  -- acknowledge cycle (INTA = M1_n and IORQ_n both low) drives the controller's
  -- vector byte onto the CPU's data input, so the Z80 fetches its ISR address
  -- from the I:vector table.  IO is memory-mapped, so IORQ_n is asserted only
  -- during INTA -- there is no other IN/OUT traffic to confuse with it.
  cpu_core : block
    signal mreq_n, wr_n, m1_n, iorq_n, inta : std_logic;
    signal cpu_di : std_logic_vector(7 downto 0);
  begin
    cpu : entity work.T80s
      generic map (Mode => 0)   -- 0 = Z80
      port map (
        RESET_n => not cpu_reset,
        CLK     => clk,
        CEN     => '1',
        WAIT_n  => '1',
        INT_n   => not cpu_irq_req,
        NMI_n   => '1',
        BUSRQ_n => '1',
        M1_n    => m1_n,
        MREQ_n  => mreq_n,
        IORQ_n  => iorq_n,
        RD_n    => open,
        WR_n    => wr_n,
        RFSH_n  => open,
        HALT_n  => open,
        BUSAK_n => open,
        A       => cpu_addr,
        DI      => cpu_di,
        DO      => cpu_dout
      );
    inta   <= (not m1_n) and (not iorq_n);              -- interrupt-acknowledge cycle
    cpu_di <= io_irq_vec when inta = '1' else cpu_din;  -- vector during INTA, else the bus
    -- write strobe = memory request with WR asserted (refresh keeps WR_n high)
    cpu_we <= (not wr_n) and (not mreq_n);
  end block;
