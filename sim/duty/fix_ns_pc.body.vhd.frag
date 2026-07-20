  -- Duty integrator, FIX-NS-PC (fpga_sim.sim_duty has the full rationale).
  -- One process per channel, sensitive to that bit alone: it wakes once per
  -- transition of its own channel and sleeps while the channel is static.
  -- At any settled instant, channel i:
  --   {p}_tch(i) = ns of that channel's most recent change (0 if never)
  --   {p}_acc(i) = total on-time over [0, {p}_tch(i)]
  -- The in-progress interval past tch is folded in only when it ends; the host
  -- adds it back and differences two snapshots for an exact window duty.  With
  -- no state shared between channels, a fast-toggling sibling cannot perturb
  -- this one, and delta-cycle glitches integrate to zero (nns - t_chg = 0).
  {p}_meas : for i in 0 to {n} - 1 generate
    acc : process ({p}_int(i))
      constant NS_PER_SEC : unsigned(29 downto 0) := to_unsigned(1000000000, 30);
      variable last_v : std_logic := 'U';                          -- 'U': the first real
      variable on_ns  : unsigned(47 downto 0) := (others => '0');  --   value reads as a
      variable t_chg  : unsigned(47 downto 0) := (others => '0');  --   change, stamping tch
      variable sec_t  : time := 0 fs;                              -- cached second boundary
      variable sec_ns : unsigned(47 downto 0) := (others => '0');  --   and its value in ns
      variable nns    : unsigned(47 downto 0);
    begin
      if {p}_int(i) /= last_v then          -- this channel changed
        -- now, in ns.  VHDL INTEGER is 32 bits, so a plain `now / 1 ns`
        -- overflows past 2.147 s; whole seconds and the sub-second remainder
        -- are each well under 2**31.  The seconds->ns product is a numeric_std
        -- software multiply (~900 bit ops) but only changes once per simulated
        -- second, so it is cached behind a TIME compare and the hot path is a
        -- subtract, a divide and a 48-bit add.
        if now - sec_t >= 1 sec then
          sec_t  := (now / 1 sec) * 1 sec;
          sec_ns := resize(to_unsigned(now / 1 sec, 31) * NS_PER_SEC, 48);
        end if;
        nns := sec_ns + to_unsigned((now - sec_t) / 1 ns, 48);
        if to_x01(last_v) = '1' then        -- the interval that just ended was ON
          on_ns := on_ns + (nns - t_chg);   -- (metavalues count as off)
          -- Published only here: on_ns cannot have changed on a rising edge.
          {p}_acc((i + 1) * 48 - 1 downto i * 48) <= std_logic_vector(on_ns);
        end if;
        t_chg := nns;
        {p}_tch((i + 1) * 48 - 1 downto i * 48) <= std_logic_vector(nns);
        last_v := {p}_int(i);
      end if;
    end process acc;
  end generate {p}_meas;
