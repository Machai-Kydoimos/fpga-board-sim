  -- IM 2 vector: the enabled+pending source, timer over input.  The values
  -- index the CPU's I:vector table ($00 -> timer ISR, $02 -> input ISR).
  irq_vec <= x"00" when (timer_flag and ier(0)) = '1' else
             x"02" when (input_flag and ier(1)) = '1' else
             x"00";
