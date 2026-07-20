  -- Duty integrator, FIX-NS-1P: same accumulator contract as FIX-NS-PC (see
  -- fpga_sim.sim_duty), but ONE process watching the whole vector instead of
  -- one per channel.  It therefore wakes once per *instant* at which any
  -- channel changes and rescans all of them, where FIX-NS-PC wakes once per
  -- *channel transition*.  Which is cheaper is a property of the design: the
  -- ratio between the two wake counts is exactly how correlated the channels
  -- are (a shared PWM compare drives every LED in lockstep, so one wake covers
  -- N channels; independently-timed channels give the two the same count and
  -- the rescan is pure loss).  The now->ns conversion is hoisted out of the
  -- scan, so it is paid once per instant rather than once per channel.
  {p}_meas : process ({p}_int)
    type u48_arr is array (natural range <>) of unsigned(47 downto 0);
    constant NS_PER_SEC : unsigned(29 downto 0) := to_unsigned(1000000000, 30);
    variable last_v : std_logic_vector({n} - 1 downto 0) := (others => 'U');
    variable on_ns  : u48_arr(0 to {n} - 1) := (others => (others => '0'));
    variable t_chg  : u48_arr(0 to {n} - 1) := (others => (others => '0'));
    variable sec_t  : time := 0 fs;                              -- cached second boundary
    variable sec_ns : unsigned(47 downto 0) := (others => '0');  --   and its value in ns
    variable nns    : unsigned(47 downto 0);
  begin
    -- See FIX-NS-PC for why the seconds->ns product is cached rather than
    -- recomputed: it is a numeric_std software multiply that only changes once
    -- per simulated second.
    if now - sec_t >= 1 sec then
      sec_t  := (now / 1 sec) * 1 sec;
      sec_ns := resize(to_unsigned(now / 1 sec, 31) * NS_PER_SEC, 48);
    end if;
    nns := sec_ns + to_unsigned((now - sec_t) / 1 ns, 48);
    for i in 0 to {n} - 1 loop
      if {p}_int(i) /= last_v(i) then
        if to_x01(last_v(i)) = '1' then
          on_ns(i) := on_ns(i) + (nns - t_chg(i));
          {p}_acc((i + 1) * 48 - 1 downto i * 48) <= std_logic_vector(on_ns(i));
        end if;
        t_chg(i) := nns;
        {p}_tch((i + 1) * 48 - 1 downto i * 48) <= std_logic_vector(nns);
        last_v(i) := {p}_int(i);
      end if;
    end loop;
  end process {p}_meas;
