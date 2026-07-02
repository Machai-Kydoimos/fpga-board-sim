  -- T80 (Z80) with BOTH vectored interrupts (IM 2) and port-mapped IO.  M1_n
  -- separates the two IORQ uses cleanly: the interrupt-acknowledge cycle (INTA =
  -- M1_n and IORQ_n both low) muxes the controller's vector onto DI but is
  -- excluded from the IO select; ordinary IN/OUT (IORQ_n low, M1_n high) select
  -- the IO register file but never mux the vector.  ROM/RAM stay on MREQ.
  cpu_core : block
    signal mreq_n, iorq_n, wr_n, m1_n, inta : std_logic;
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
    inta     <= (not m1_n) and (not iorq_n);             -- interrupt-acknowledge cycle
    cpu_di   <= io_irq_vec when inta = '1' else cpu_din;  -- vector during INTA, else the bus
    cpu_mreq <= not mreq_n;                               -- memory request (qualifies ROM/RAM)
    cpu_iorq <= (not iorq_n) and m1_n;                   -- I/O cycle (IN/OUT), excluding INTA
    cpu_we   <= not wr_n;                                 -- write strobe; the selects route it
  end block;
