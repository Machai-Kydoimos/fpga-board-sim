  -- T80 (Z80) with port-mapped IO: ROM/RAM live in the memory space and the IO
  -- registers in the separate I/O space (IN/OUT -> IORQ).  The adapter exposes
  -- both request lines: the decode qualifies the ROM/RAM selects with MREQ and
  -- takes the IO select from IORQ (M1_n high excludes the interrupt-acknowledge
  -- cycle).  The register file (cpu_io) is unchanged -- only how it is selected.
  cpu_core : block
    signal mreq_n, iorq_n, wr_n, m1_n : std_logic;
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
        DI      => cpu_din,
        DO      => cpu_dout
      );
    cpu_mreq <= not mreq_n;                -- memory request (qualifies ROM/RAM selects)
    cpu_iorq <= (not iorq_n) and m1_n;     -- I/O cycle (IN/OUT), excluding INTA
    cpu_we   <= not wr_n;                  -- write strobe; the selects route it
  end block;
