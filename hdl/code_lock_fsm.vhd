-- code_lock_fsm.vhd  --  A three-press combination lock, as a labeled-state FSM.
--
-- Press the buttons in the order  btn0, btn1, btn0  and the lock opens.  Any
-- other press sends you back to the start.  Press btn2 (or flip sw0 on a board
-- with fewer than three buttons) to lock it again.
--
--   led(0)  lit while UNLOCKED
--   led(1)  lit in state ONE_OK    -- how far into the code you are
--   led(2)  lit in state TWO_OK
--
-- -- WHY THE STATES HAVE NAMES ------------------------------------------------
--
-- The states are an enumerated type, not a std_logic_vector of "01", "10" and
-- so on.  Both synthesize to the same flip-flops, and the tool picks a nicer
-- encoding than you would; the difference is that a waveform viewer shows you
-- ONE_OK instead of "01", and an illegal state cannot be written by accident
-- because the compiler will not let you assign a value the type does not have.
-- This is the shape almost every sequential exercise takes, so it is worth
-- getting into your fingers.
--
-- -- WHY THE PRESSES ARE EDGES, NOT LEVELS ------------------------------------
--
-- A button held down is '1' for millions of clock cycles -- millions of state
-- transitions if you test the level.  What you mean by "a press" is the
-- *moment* it went down, so the design keeps the previous sample and acts only
-- where the two differ.  That one-cycle pulse is the whole trick, and forgetting
-- it is the classic first-FSM bug: the lock appears to skip straight to
-- UNLOCKED because one press was seen as thousands.
--
-- Effect  : led(0) lights after btn0, btn1, btn0.  led(1)/led(2) show progress.
-- Teaches : Enumerated states, a two-process FSM, and edge detection on a
--           human-speed input.

library ieee;
use ieee.std_logic_1164.all;

entity code_lock_fsm is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24   -- unused; the contract supplies it
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity;

architecture rtl of code_lock_fsm is

  -- Boards carry anywhere from 0 to 8 buttons and 0 to 18 switches.  Reading
  -- through this keeps the design elaborating everywhere: an input the board
  -- does not have reads '0', so the lock simply never opens on a board with no
  -- buttons, which is the honest outcome rather than a compile error.
  function bit_or_zero(v : std_logic_vector; i : natural) return std_logic is
  begin
    if i < v'length then
      return v(v'low + i);
    end if;
    return '0';
  end function;

  type state_t is (LOCKED, ONE_OK, TWO_OK, UNLOCKED);

  signal state    : state_t := LOCKED;
  signal btn_prev : std_logic_vector(2 downto 0) := (others => '0');
  signal btn_now  : std_logic_vector(2 downto 0);
  signal pressed  : std_logic_vector(2 downto 0);   -- one cycle per press
  signal relock   : std_logic;

begin

  btn_now <= bit_or_zero(btn, 2) & bit_or_zero(btn, 1) & bit_or_zero(btn, 0);

  -- A press is a rising edge: high now, low on the previous clock.
  pressed <= btn_now and not btn_prev;

  -- Third button if the board has one, otherwise the first switch.
  relock <= bit_or_zero(btn, 2) when NUM_BUTTONS >= 3 else bit_or_zero(sw, 0);

  edges : process (clk) is
  begin
    if rising_edge(clk) then
      btn_prev <= btn_now;
    end if;
  end process edges;

  -- The state register.  One `case` over the current state, one branch per
  -- state, and every branch either moves or stays -- so there is no way to fall
  -- out of the machine into an undefined state.
  fsm : process (clk) is
  begin
    if rising_edge(clk) then
      if relock = '1' then
        state <= LOCKED;
      else
        case state is

          when LOCKED =>
            if pressed(0) = '1' then
              state <= ONE_OK;
            elsif pressed(1) = '1' then
              state <= LOCKED;          -- wrong first press: stay put
            end if;

          when ONE_OK =>
            if pressed(1) = '1' then
              state <= TWO_OK;
            elsif pressed(0) = '1' then
              state <= LOCKED;          -- wrong: start over
            end if;

          when TWO_OK =>
            if pressed(0) = '1' then
              state <= UNLOCKED;
            elsif pressed(1) = '1' then
              state <= LOCKED;
            end if;

          when UNLOCKED =>
            null;                        -- stays open until relock

        end case;
      end if;
    end if;
  end process fsm;

  -- Output decode: a pure function of the state, computed outside the clocked
  -- process so the relationship between state and lamps is one readable line
  -- each rather than something you have to trace through the transitions.
  outputs : process (state) is
    variable out_v : std_logic_vector(NUM_LEDS - 1 downto 0);
  begin
    out_v := (others => '0');
    if state = UNLOCKED then
      out_v(0) := '1';
    end if;
    if NUM_LEDS > 1 and state = ONE_OK then
      out_v(1) := '1';
    end if;
    if NUM_LEDS > 2 and state = TWO_OK then
      out_v(2) := '1';
    end if;
    led <= out_v;
  end process outputs;

end architecture;
