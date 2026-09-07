# Troubleshooting

Indexed by **what you are seeing**, not by what is wrong — because if you knew what
was wrong you would not be here.

New to the tool? Start with [first_design.md](first_design.md); this page is for when
something has already gone sideways.

**Before anything else:**

```bash
uv run fpga-sim --doctor
```

Nine checks, no display needed, and each failure prints the fix for your operating
system. It separates "my machine is not set up" from "my design is broken."

---

## The board does nothing

### Every LED is dark and nothing moves

Wait for the advisory. After the outputs have been quiet a while, a circled **i**
appears beside **[Pause]**; click it. It reports what your machine actually managed
in the seconds that just passed and, when your design declares a plausible divider
generic, the arithmetic for *that* generic and the value to try:

```text
No LED or digit has changed in 12 s of wall-clock time.
In that time this machine simulated 4.33 M clock cycles = 86.7 ms of the board's 50 MHz.
Your DIVIDER_BITS = 24 means 16.8 M cycles per step: about 46 s here, 336 ms on the real board.
To watch it here, set DIVIDER_BITS to about 17:
    [Stop], then [Generics…] on the preview  —  or relaunch with  --generic DIVIDER_BITS=17
```

Usually the answer is **the divider**, and the design is fine — it is counting, and
at simulator speeds a divider sized for a 50 MHz board takes tens of seconds to
minutes per step. See [the two clocks](first_design.md#5-the-two-clocks) for the
arithmetic, then:

```bash
uv run fpga-sim --vhdl lab2/running_light.vhd --generic DIVIDER_BITS=15
```

or **[Generics…]** on the preview. Your file is not edited, and the value your board
needs stays in it.

**If your design has no divider generic** — the width is written as a literal
`2**24` in the middle of a process — the advisory can only say so generally, because
it will not guess a number it cannot see. Hoist the width into a generic:

```vhdl
generic (DIVIDER_BITS : positive := 24);   -- 24 for the board; override it here
...
if tick = 2**DIVIDER_BITS - 1 then
```

That is the habit worth forming; see
[put your divider width in a generic](writing_designs.md#put-your-divider-width-in-a-generic).

### It is waiting for you, not counting

If the board has switches and you have not touched one since the run began, the
advisory leads with that instead — a design that waits for input is right to show
nothing. Try a switch before you go looking for a bug.

### It really is slow

If nothing above applies, the run may simply be at the limit of what your machine
does. Install a second simulator — the engines differ by most of an order of
magnitude on the same design, and the `SIM:` toggle on the preview switches between
everything you have installed, per run. Which to install, and what each costs at
startup: [choosing a simulator](install.md#choosing-a-simulator).

Measure your own machine before deciding anything, which takes twelve seconds and
needs no display:

```bash
uv run fpga-sim --benchmark 12 --no-ui --sim nvc --vhdl hdl/running_light.vhd
```

An amber **(CPU-limited)** note in the stats panel means the requested rate is not
being achieved — dragging the speed slider right will not help.

## The file will not load

### `Missing required port(s) in 'x.vhd': clk, btn, led`

```text
Missing required port(s) in 'test_entity.vhd': clk, btn, led.
The top-level entity must have ports: clk, sw, btn, led.
```

Your design does not match the generic contract, and there was no pin map to fall
back on. **This is the one message that means "none of the three ways in worked",**
so it is also what you get for a testbench picked by mistake or a `.qsf` left in the
other folder — read it as "I could not tell what this file is", not as a demand that
you rename your ports. The three ways a design can be accepted, in the order they are tried:

1. **Your project's pin map** — a `.qsf`/`.xdc`/… beside the design. Best case: your
   ports keep your names. See [§4 of the tutorial](first_design.md#4-now-run-your-own-file).
2. **Board-native names** — the board's own `CLOCK_50` / `SW` / `KEY` / `LEDR` / `HEX0…`.
3. **The generic contract** — `clk` / `sw` / `btn` / `led` (+ `seg`), sized by generics.

If you meant the first, the constraint file is probably not in the same folder as the
design. **One folder is one project**: copy the `.vhd` and the `.qsf`/`.xdc` into one
directory and pick the design there, or name it with `--pinmap path/to/file.xdc`.

The contract itself is in [writing_designs.md](writing_designs.md#the-generic-contract).

### `unit "test_entity" not found in library "work"`

The entity name must match the filename stem: `test_entity.vhd` has to declare
`entity test_entity`. Rename whichever of the two is wrong.

When the error names `sim_wrapper.vhd`, that is the simulator's own generated
wrapper looking for your entity — meaning your file compiled fine but declares a
different name.

### `holds more than one constraint file … it is not clear which one`

```text
/home/you/lab1 holds more than one constraint file (lab1.qsf, Basys3.xdc), so it is
not clear which one describes this design.
Pass the one you mean with --pinmap <file>.
```

A folder with both a `.qsf` and an `.xdc` is targeting two boards, and only you know
which one you mean, so the simulator asks rather than guessing:

```bash
uv run fpga-sim --pinmap lab1/lab1.qsf --vhdl lab1/test_entity.vhd
```

### It says my project is for another board

```text
test_entity.qsf assigns pins that Basys 3 does not have:
  clock_50 -> pin AF14
  sw[0] -> pin AB30
  sw[1] -> pin Y27
  ... and 16 more

test_entity.qsf targets 5CSXFC6D6F31C6, but Basys 3 is xc7a35t — did you select the
wrong board?
```

Select the board the project was written for. Note that the pins are reported first
and the device only at the end: the pins are the real evidence — a `.qsf` that names
no device at all still produces the top half — and the device line is the
confirmation. Nothing is ever silently remapped, because a design wired to the wrong
pins that *runs* would be far worse than one that refuses.

A **board-native** design that names ports the selected board does not have (the
clock is `CLOCK_50` but this board's is `CLOCK0_50`) is reported the same way, by
naming the mismatch.

### I picked the testbench by mistake

The simulator supplies its own stimulus — the switches and buttons you click — so it
runs designs, not testbenches. Pick the design; to run the testbench itself, see
[the manual recipe](#running-a-testbench-by-hand) below.

## The compiler rejected it

Every message here is GHDL's or NVC's own text, unedited, with a `Hint:` appended
below it. The hint never replaces the compiler's words: that is the compiler you
will use in the lab, and it is worth learning to read.

### `no declaration for "std_logic"` / `"rising_edge"`

The IEEE library header is missing:

```vhdl
library ieee;
use ieee.std_logic_1164.all;
```

### `no declaration for "to_unsigned"` / `"unsigned"` / `"resize"`

`numeric_std` is missing. It goes under the library header:

```vhdl
use ieee.numeric_std.all;
```

It declares `unsigned` and `signed` and the conversions between them, `integer` and
`std_logic_vector`. A design written entirely in `std_logic_vector` still needs it
the moment it counts.

### `an identifier is expected instead of 'units'`

You used a **reserved word** as a name. Neither engine says "reserved word" — both
report only that an identifier was expected here — so this one is genuinely hard to
see. The ones that read like ordinary names: `units`, `range`, `next`, `open`,
`select`, `signal`, `type`, `bus`, `register`, `severity`, `label`, `body`.

Rename it everywhere: `units_value`, `s_units`.

### `missing ";" at end of …` and other syntax errors

A syntax error is reported where the text stopped making sense, which is often the
line **after** the mistake. Check the end of the previous line for a missing `;`.

Every declaration and statement ends with a semicolon; the last entry inside a
`port ( … )` or `generic ( … )` clause does not.

### `use of synopsys package "std_logic_unsigned" needs the -fsynopsys option`

You will not see this inside the app — it passes `-fsynopsys` to GHDL for you, and
NVC needs no flag — but you will see it the moment you run `ghdl` by hand. Add the
flag to every GHDL command:

```bash
ghdl -a -fsynopsys --std=08 *.vhd
```

`ieee.std_logic_arith` / `std_logic_unsigned` / `std_logic_signed` are Synopsys
packages, not IEEE standards, though they are near-universal in course material.
They work here and in Quartus; `ieee.numeric_std` is the standard alternative if you
are writing something new. The preview says so once, without blocking anything.

### `too many actuals for component instance "uut"`

A **positional** port map — `port map (clk, rst, sw)` — binds by position, so it
silently changes meaning whenever the entity's port list does. Name them:

```vhdl
port map (clk => clk, rst => rst, sw => sw);
```

### `mismatching vector length; got 4, expect 10`

A port's width came from somewhere other than its generic. Declare it with the
generic and let the simulator size it to the board:

```vhdl
led : out std_logic_vector(NUM_LEDS - 1 downto 0)
```

The message quotes the widths from a validation pass that elaborates with your
file's *default* generics, so the numbers in it can differ from the board's. The
hint names the board's real counts.

### `generic "NUM_LEDS" is not an interface name`

The simulator sets the sizing generics at launch, so the top level has to declare
them (with defaults): `NUM_SWITCHES`, `NUM_BUTTONS`, `NUM_LEDS`, `COUNTER_BITS`,
plus `NUM_SEGS` for 7-segment designs and `NUM_RGB_LEDS` for RGB ones.

### `port "rst" of mode IN must be connected`

The simulator drives only the contract ports, so an extra input is left
unconnected. Give it a default — `rst : in std_logic := '0'` — or remove it. An
extra *output* is fine as it is; it is left open.

### My file is in a folder with other files

That is supported and needs no configuration. If the design does not compile alone,
its folder's other VHDL files are compiled into the same library and it is retried
until nothing more can be added.

**A neighbor that does not compile is ignored, not fatal** — course testbenches
frequently do not build as shipped, and they sit right beside the design they test.
Only the file you picked is simulated.

The sweep is not free on GHDL's compiled LLVM backend, where analyzing means
compiling, so it only runs when your design actually needs it. Sixty files in one
directory is not a lab folder, and it stops there.

## The board behaves oddly

### The buttons are backwards

Terasic `KEY` buttons are **active-low**: pressing one drives `0`. Terasic `LEDR`
outputs are active-*high*, so the two are opposite on the same board; on other
boards the LEDs are the inverted ones, and several 7-segment displays are too. There
is no rule to memorize, which is the point of the next paragraph.

**Write the design you would write for the real board.** The polarity comes from the
board data — cited from the vendor's own documentation — and the wrapper applies it,
so a board-native or pin-mapped design behaves here exactly as on the bench. A
board-native run says so in the stats panel.

Under the **generic contract**, `btn` and `led` are always active-high regardless of
board, because the wrapper has already undone the board's polarity for you. That is
the difference between the two, and it is the usual cause of "it works on the board
but is inverted here" (or the reverse).

### Only some digits light up

Normal. A design that drives four digits of a six-digit board leaves the rest dark,
exactly as on the bench.

### An input port I never assigned

Also normal, and it is what your `.qsf` actually says. Quartus places an unassigned
pin automatically, so real projects are full of them: the simulator ties the input
off and says so in one non-blocking line. An unassigned output is left open.

### The LEDs look dim, or flicker

That is the point — LED brightness is measured from real on-time in the simulated
design, so a PWM-dimmed LED renders dim. Press **D** for the duty-bar debug view to
see the measured numbers. See [LED brightness](user_guide.md#led-brightness).

## Waveforms

### Where did it go?

`~/.fpga_simulator/waveforms/<design>_<timestamp>.<ext>`, unless
`$FPGA_SIM_WAVEFORM_DIR` says otherwise. Capture is **off by default**; turn it on
in **Settings** (the gear on the preview). The end-of-run line prints the full path,
the size, and the `gtkwave` command with the signals preselected.

### It is enormous

Capture writes every event in the design, and the simulator generates a great many
of them. Measured on one machine, one 10-second run of `blinky.vhd`:

| Format | Dump size | Per simulated millisecond |
|---|---|---|
| FST | 9 MB | 0.12 MB |
| VCD | 190 MB | 3.4 MB |

**Use FST.** Same waveform, an order of magnitude and then some smaller — 21× if you
compare the two files above, 29× per simulated millisecond, the difference being that
writing VCD is itself slow enough to cost the run simulated time. It is the first
choice the Settings row offers for that reason. Nothing sweeps the directory, so
captures accumulate until you delete them — the size is printed after every run so
it does not creep up on you.

### I enabled Memories and my arrays are still not there

You are on GHDL with **VCD** selected. GHDL's VCD writer omits memories entirely;
its FST writer includes them with no flag at all. Switch the format to FST.

(Under NVC the **Memories** toggle drives `--dump-arrays` and works with both
formats. This combination is the one silent dead end in the matrix, which is why FST
is now what one click reaches.)

## Running a testbench by hand

The app runs your **design** and supplies the stimulus itself. To run the testbench
your assignment came with, call the simulator directly — put the design and the
testbench in one directory:

```bash
# GHDL
ghdl -a -fsynopsys --std=08 *.vhd
ghdl -r --std=08 -fsynopsys testbench --fst=tb.fst

# NVC
nvc --std=2008 -a *.vhd
nvc --std=2008 -e testbench
nvc --std=2008 -r testbench --wave=tb.fst
```

`testbench` is the **entity name**, not the filename. Then `gtkwave tb.fst`.

**A testbench that ends in `severity failure` exits non-zero and prints "simulation
failed" — that is it working.** Ending a self-checking testbench with a deliberate
failure is the standard way to stop a simulation that has no other end, and course
material uses it constantly. Read the report line, not the exit code; the waveform
is written either way.

## Installing and starting

### `ghdl not found` / `nvc not found`

`uv run fpga-sim --doctor` says which are missing and prints the install command for
your OS. On Windows, GHDL not being on `PATH` after `winget install` is common and
has its own section: [Windows: GHDL not on PATH](install.md#windows-ghdl-not-on-path-after-winget-install).

### `brew install ghdl` does nothing

Homebrew's GHDL cask was **disabled on 2026-09-01** for failing the macOS Gatekeeper
check. Use `brew install nvc`, or install GHDL from its
[release tarball](install.md#ghdl) — fetched with `curl`, because a browser download
carries the quarantine attribute and Gatekeeper blocks it the same way.

### Windows: the launcher does nothing in Command Prompt

It needs **PowerShell**. See [Windows run notes](install.md#windows-run-notes).

### Windows: `python313.dll` not found

The Windows Store Python is sandboxed and cannot be embedded by the simulator
process. Use a standalone Python — `uv` installs one for you. Full detail:
[install.md](install.md#windows-python-dll-not-found-hon313dll--python313dll).

### `No board definitions found`

You are running from outside the repository, or the clone is incomplete. See
[install.md](install.md#no-board-definitions-found).

### pygame will not import at all

Then `fpga-sim` cannot start, so run the doctor as a module — it does not import
pygame:

```bash
uv run python -m fpga_sim.doctor
```

The usual cause is `pip install pygame` colliding with the `pygame-ce` this project
uses. See [pygame-ce](install.md#pygame-ce).

## Still stuck

Paste the output of `uv run fpga-sim --doctor` into an
[issue](https://github.com/Machai-Kydoimos/fpga-board-sim/issues) — it carries the
versions, the simulators, and whether a real compile works, which is most of a bug
report already.
