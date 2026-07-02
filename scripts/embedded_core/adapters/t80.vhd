  -- T80 (Z80): active-low RESET_n/INT_n; memory access via MREQ_n + RD_n/WR_n.
  -- IO is memory-mapped (accessed with MREQ), so IORQ_n is left unconnected.
  cpu_core : block
    signal mreq_n, wr_n : std_logic;
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
        M1_n    => open,
        MREQ_n  => mreq_n,
        IORQ_n  => open,
        RD_n    => open,
        WR_n    => wr_n,
        RFSH_n  => open,
        HALT_n  => open,
        BUSAK_n => open,
        A       => cpu_addr,
        DI      => cpu_din,
        DO      => cpu_dout
      );
    -- write strobe = memory request with WR asserted (refresh keeps WR_n high)
    cpu_we <= (not wr_n) and (not mreq_n);
  end block;
