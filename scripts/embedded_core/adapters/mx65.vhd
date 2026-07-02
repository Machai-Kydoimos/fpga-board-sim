  -- mx65 (6502): active-high reset, rw (1=read/0=write), active-low irq.
  cpu_core : block
    signal cpu_rw : std_logic;
  begin
    cpu : entity work.mx65
      port map (
        clock    => clk,
        reset    => cpu_reset,
        ce       => '1',
        data_in  => cpu_din,
        data_out => cpu_dout,
        address  => cpu_addr,
        rw       => cpu_rw,
        sync     => open,
        nmi      => '0',
        irq      => not cpu_irq_req
      );
    cpu_we <= not cpu_rw;
  end block;
