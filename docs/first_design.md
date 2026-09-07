# Your first design

This is the walkthrough for someone who has a `.vhd` file they wrote for a real
lab board, and wants to check it before the session. No lab, no TA, no board on the
desk — just the file, the Quartus or Vivado folder around it, and half an hour.

It goes: install → check the machine → run one of ours → **run yours** → understand
why it looks slow → read an error → and finally what the simulator wrapped around
your file, so nothing here is magic.

Everything else is reference:
[install.md](install.md) for the per-OS install matrix,
[user_guide.md](user_guide.md) for every screen and control,
[writing_designs.md](writing_designs.md) for the design contract,
and [troubleshooting.md](troubleshooting.md) for the thing that just went wrong.

---

## 1. Install

Two pieces: a **VHDL simulator** (GHDL or NVC — the thing that actually compiles and
runs your design) and **uv** (which handles Python for you).

```bash
# Linux
sudo apt install ghdl        # or: sudo dnf install ghdl
curl -LsSf https://astral.sh/uv/install.sh | sh

# macOS
brew install nvc             # not `brew install ghdl` — that cask is disabled
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell, not Command Prompt)
winget install ghdl.ghdl.ucrt64.mcode
winget install --id=astral-sh.uv -e
```

Then the project itself:

```bash
git clone https://github.com/Machai-Kydoimos/fpga-board-sim.git
cd fpga-board-sim
uv sync
```

`uv sync` installs three packages and takes a few seconds. You do **not** need to
install Python first, and you do not need the test tooling to use the simulator.

The full matrix — from-source builds, MSYS2, AUR, FreeBSD, and what to do when
GHDL is not on `PATH` — is in [install.md](install.md).

## 2. Check the machine before you blame your file

```bash
uv run fpga-sim --doctor
```

This needs no display, so it works over SSH and in a script. It checks nine things
and finishes by actually compiling and elaborating a bundled design on **every**
simulator it found:

```text
fpga-sim doctor - Ubuntu 24.04.1 LTS - x86_64

  [ ok ] Python         3.12.3 (CPython), within >=3.10,<3.15
  [ ok ] uv             uv 0.12.10
  [ ok ] pygame-ce      2.5.8 (SDL 2.32.10)
  [ ok ] cocotb         2.1.0
  [ ok ] Boards         285 definitions in 4 sources
  [ ok ] Profile        writable: /home/you/.fpga_simulator
  [ ok ] Simulators     1 found
  [ ok ] cocotb plugin  ghdl -> libcocotbvpi_ghdl.so
  [ ok ] Analyze        blinky.vhd on DE10-Standard: compiled and elaborated

All 9 checks passed.
```

Every failing check prints, under **How to fix**, the command for *your* operating
system. Run this first whenever something is wrong: it separates "my machine is not
set up" from "my design is broken," and those two have completely different fixes.

## 3. Run one of ours first

Get a known-good design on screen before you introduce your own. It takes ten
seconds and it means that if the next step fails, you know the tool works.

```bash
uv run fpga-sim --board DE10-Standard --vhdl hdl/gates_mux.vhd
```

The board preview opens with the file already loaded and checked. Click
**[Start Simulation]**.

[`hdl/gates_mux.vhd`](../hdl/gates_mux.vhd) is two switches, four gates and one LED,
with **no clock anywhere** — deliberately, because it is the only kind of design
whose output you can predict by reading it. Flip `sw(1)` and `sw(0)` to set the two
inputs, `sw(3 downto 2)` to pick AND / OR / XOR / NOT, and `led(0)` answers
immediately. Nothing to wait for, nothing to time — and `led(1)` and `led(2)` echo
your two inputs back, so you can read the whole truth table off the board.

That is the whole loop: pick a board, pick a file, press Start, poke the board.
Four more designs, each adding exactly one idea, are listed in
[§11](#11-where-to-go-next).

## 4. Now run your own file

Your design was written for a real board, with a pin assignment file beside it. The
simulator reads that file — so your ports keep the names *you* gave them, and each
one lands on the board resource **your own constraint file** says it does. No
guessing from names.

### One folder is one project

```text
lab1/
├── test_entity.vhd      ← the design you pick
├── counter.vhd          ← a sub-entity it instantiates
├── testbench.vhd        ← ignored; it does not even have to compile
└── test_entity.qsf      ← your pin assignments, unmodified
```

Put the design, everything it needs, and **one** constraint file in one directory.
That is the entire contract. `.qsf` (Quartus), `.xdc` (Vivado), `.ucf`, `.pcf`,
`.cst`, `.lpf`, `.ccf` and BoardStore `.xml` are all read.

If your files live inside a Vivado project tree, the sources and the constraints sit
three directories apart — **copy both into one folder** and pick the design there.
The simulator deliberately does not learn Vivado's layout: that layout is
user-configurable and changes between versions, and being wrong about it would mean
silently wiring a design to the wrong pins. If you point it at a design inside a
project tree anyway, it tells you where it found the constraint file rather than
leaving you to guess.

### Open it

Any of these three, whichever suits you:

```bash
uv run fpga-sim --board DE10-Standard --vhdl ~/labs/lab1/test_entity.vhd
```

…or launch `uv run fpga-sim`, pick the board, then **[Load VHDL File]**…

…or just **drag the `.vhd` onto the window**. Your files never have to move into
this repo.

Whichever way it arrives, the file goes through the same three checks — encoding,
then the port contract, then a real compile — and the preview tells you which
mechanism matched:

```text
Pin map: test_entity.qsf -> DE10-Standard. 10 output bit(s) and 13 input bit(s)
bound by pin, so this design's own port names are not used.
```

That last clause is the thing to notice: your ports were bound **by pin**, from your
own file, so a port called `svetla` or `prepinace` lands exactly where your `.qsf`
sends it. Names had no say in it.

Press **[Start Simulation]**.

> **Which board?** Pick the one the design was written for. The simulator always
> models the board you selected, and when your `.qsf` names a device that is not
> that board's, it says so by name rather than mapping it anyway.

## 5. The two clocks

This is the one concept that makes everything else make sense, and it is where most
first sessions go wrong.

**Your board's clock is real. The simulator's is not.** A DE10-Standard runs at
50 MHz. This simulator computes every gate of your design in software, so it gets
through some hundreds of thousands of simulated clock cycles per second of your
life. On the machine every number in this document was measured on, running
`running_light.vhd` on a DE10-Standard:

| Engine | Simulated clock cycles per wall-clock second | Ratio to the real board |
|---|---|---|
| GHDL, mcode backend | 361,000 | 1 : 139 |
| NVC | 3,080,000 | 1 : 16 |

Measure your own — it takes twelve seconds and needs no display:

```bash
uv run fpga-sim --benchmark 12 --no-ui --board DE10-Standard --vhdl hdl/running_light.vhd
```

That gap is not a defect. It is what simulating logic costs, and every number the
tool shows you is measured on your machine rather than assumed, for exactly this
reason.

Press **S** during a run and the stats panel spells it out:

| Readout | Means |
|---|---|
| **Board clk** | the frequency the design is being clocked at — the board's real one |
| **Sim time** | how much time has passed **inside your design** |
| **Eff. rate** | how many of those clock cycles this machine is managing per wall-clock second |

So "Sim time: 4.2 ms" after a minute of sitting there is not a stall. It is your
design having experienced 4.2 milliseconds while you experienced 60 seconds.

### Which is why a correct design can look dead

Try this one, unchanged:

```bash
uv run fpga-sim --board DE10-Standard --vhdl hdl/running_light.vhd
```

One LED should walk along the row. Nothing happens.

[`hdl/running_light.vhd`](../hdl/running_light.vhd) divides the clock with
`DIVIDER_BITS`, defaulting to **24** — the value you would really synthesize, because
`2**24 / 50 MHz = 0.34 s` per step is a comfortable walking pace on the bench.

Do the same arithmetic with the rate above. 2²⁴ is 16.8 million cycles; at 361,000
cycles a second that is **46 seconds per step**, and on a slower laptop it is
minutes. The design is correct. Your board is correct. The environment is different,
and nothing on screen can tell you that apart from a design that simply does not
work.

So the simulator does. Wait a few seconds and a small circled **i** appears beside
**[Pause]**; click it and it explains, in numbers measured during the run that just
went quiet:

```text
No LED or digit has changed in 12 s of wall-clock time.
In that time this machine simulated 4.33 M clock cycles = 86.7 ms of the board's 50 MHz.
Your DIVIDER_BITS = 24 means 16.8 M cycles per step: about 46 s here, 336 ms on the real board.
To watch it here, set DIVIDER_BITS to about 17:
    [Stop], then [Generics…] on the preview  —  or relaunch with  --generic DIVIDER_BITS=17
That steps about every 363 ms instead. Your file is not touched: DIVIDER_BITS stays 24
for the real board.
NVC is also installed here and is usually faster than GHDL: [Stop], then the SIM:
toggle on the preview re-runs this design on it.
```

It never interrupts: it is an offer you can ignore, and clicking it does not pause,
reset or restart anything. The width it suggests is computed from what your machine
just managed, so it is a number that will actually work there — not a constant, and
not the same on two different laptops.

### Three ways out; the third one is a trap

```bash
uv run fpga-sim --vhdl hdl/running_light.vhd --generic DIVIDER_BITS=15
```

…or click **[Generics…]** on the preview and type a smaller number into the
`DIVIDER_BITS` row. Any small value works — the advisory suggests one computed from
what your machine just managed, which is why it said 17 above and this page says 15.

The third way is to edit the default in the file, and **that is the one to avoid.**
Your file is right for your hardware; it is the simulator that is slow. Override it
per run and the file on disk keeps the value the board needs — which is the version
you hand in, and the version that gets synthesized.

**Nothing of yours is ever overridden without your asking.** There is exactly one
exception, `COUNTER_BITS`, and it is the contract's own generic rather than one you
invented; [§8](#8-what-the-simulator-wrapped-around-your-file) explains why.

This is why `writing_designs.md` asks you to
[put your divider width in a generic](writing_designs.md#put-your-divider-width-in-a-generic):
a hard-coded `2**24` in the middle of a process cannot be turned down without
editing the file, and then the file is no longer the one you hand in.

### And if it is simply slow, change engines

Any installed simulator runs any design; they differ mainly in speed — look again at
the table above, where the same design and the same board differ by most of an order
of magnitude between engines. The `SIM:` toggle on the preview switches between
everything you have installed, per run. The full comparison, including what each one
costs at startup, is [choosing a simulator](install.md#choosing-a-simulator).

That toggle is the **only** place the engine is chosen, on purpose: switching engines
tears the simulation down and restarts simulated time, so a mid-run "go faster"
button would silently throw away the wait you had already done. If you only have
one engine installed and runs feel slow, installing a second is the cheapest
improvement available — see
[choosing a simulator](install.md#choosing-a-simulator).

## 6. Change a line, reload, repeat

You do not have to restart the app to pick up an edit. With the simulation running:

1. Edit the `.vhd` in your own editor and save.
2. **[Reload VHDL]** in the toolbar, bottom-left.

All three checks run again — encoding, contract, compile — because the file on disk
may have changed arbitrarily; that is the point of the button. On success the run
restarts with your edit.

If your edit does not compile you get the compiler's error in a dialog, and the run
does **not** continue: the analysis products describe the old file, so they are
dropped rather than kept. **[Try Another File]** puts you back on the preview with
the board still selected, so fix the file and press Reload again.

**[Change VHDL]** goes back to the picker — which re-opens **in your directory, on the
file you tried**, not back at the bundled examples.

## 7. Reading an error

Errors here are GHDL's or NVC's own text, unedited, with a `Hint:` appended when the
message is one of the ones that reliably means something other than what it says.
Two examples of the shape:

```text
test_entity.vhd:15:27:error: no declaration for "to_unsigned"
  led <= std_logic_vector(to_unsigned(5, NUM_LEDS));
                          ^

Hint: Add the numeric package under the IEEE library header:
  use ieee.numeric_std.all;
It declares unsigned and signed, and the conversions between them, integer and
std_logic_vector (to_unsigned, to_signed, to_integer, resize).
```

```text
/tmp/fpga_sim_uvmiqe7b/sim_wrapper.vhd:104:21:error: unit "test_entity" not found in library "work"
  uut : entity work.test_entity
                    ^

Hint: The file analyzed, but it does not declare an entity called test_entity.
The entity name must match the filename — a design in test_entity.vhd has to declare
entity test_entity is — so rename whichever of the two is wrong.
```

The second one is worth reading twice, because the file it names is one you never
wrote. `sim_wrapper.vhd` is the simulator's own wrapper
([§8](#8-what-the-simulator-wrapped-around-your-file)); it went looking for
`entity test_entity` because that is what `test_entity.vhd` is called, and your file
declares something else. Your design compiled perfectly well — it is the name that
does not line up.

The hint is always *added below* the compiler's text, never instead of it — you
should be able to read the real message and learn the tool you will use in the lab.

[troubleshooting.md](troubleshooting.md) has the full catalog, by symptom.

## 8. What the simulator wrapped around your file

Nothing here is hidden, and knowing it turns a class of confusing errors into
obvious ones.

Your design is never the top level of the simulation. The simulator generates a
small VHDL file called **`sim_wrapper.vhd`**, instantiates your entity inside it,
and simulates *that*. The wrapper is what:

- **drives the clock** at the board's real frequency;
- **connects your ports** to the board on screen — through your pin map when there
  is one, through the board's own port names for a board-native design, or through
  the `clk/sw/btn/led/seg` contract otherwise;
- **applies the board's polarity**, so an active-low `KEY` on a Terasic board reads
  the way it does on the bench and you write the design you would really write;
- **counts LED on-time**, which is what makes a PWM-dimmed LED render dim rather
  than flickering.

It lives in a temporary work directory (`/tmp/fpga_sim_…`, or the Windows
equivalent) together with the compiled library, and it is regenerated whenever the
board, the design or the pin map changes. When a diagnostic names `sim_wrapper.vhd`,
that is the boundary between your design and the simulator — usually meaning the
two disagree about a port or an entity name.

### Why `COUNTER_BITS` is not what your file says

If your design uses the generic contract and declares `COUNTER_BITS : positive := 24`,
the wrapper passes it **17** (20 under NVC, and more on many-digit 7-segment boards)
rather than your 24.

That is the two-clocks problem again, solved automatically for the one generic the
contract defines: at simulator speeds the MSB of a full 24-bit counter would toggle
far too slowly to see, so a design written to the documented contract blinks
visibly here without anyone touching the file. Your board still gets 24.

It applies to `COUNTER_BITS` **only** — the contract's own name for this. A generic
you invented, `CNTR_LEN` or `DIVIDER_BITS`, is yours and is left alone; that is what
[Generics…] and `--generic` are for. And a **board-native** design gets no override
at all, since that generic belongs to the generic contract.

You can see all of it: `--generic COUNTER_BITS=20` replaces the automatic value with
your own, and the preview then names what is overridden.

## 9. Running your own testbench, by hand

The simulator supplies its own stimulus — the switches and buttons you click — so it
runs your **design**, not your testbench. Picking a testbench file gets you a
message saying so.

To run the testbench your assignment came with, call the simulator directly. Put the
design and the testbench in one directory and:

```bash
# GHDL
ghdl -a -fsynopsys --std=08 *.vhd
ghdl -r --std=08 -fsynopsys testbench --fst=tb.fst

# NVC
nvc --std=2008 -a *.vhd
nvc --std=2008 -e testbench
nvc --std=2008 -r testbench --wave=tb.fst
```

`testbench` is the **entity name** of your testbench, not its filename. Then
`gtkwave tb.fst` (or [Surfer](https://surfer-project.org/)) to look at it.

Three things that surprise people here, all of them normal:

- **`-fsynopsys` is for GHDL only.** If your files use `ieee.std_logic_arith` or
  `ieee.std_logic_unsigned` — as most course material does — GHDL refuses without
  that flag and says so. NVC accepts them with no flag. (The app passes
  `-fsynopsys` for you; this is only for hand-running.)
- **A testbench that ends in `severity failure` exits non-zero and prints
  "simulation failed".** That is it working. Ending a self-checking testbench with
  a deliberate failure is the standard way to stop a simulation that has no other
  end, and courses use it constantly. Read the report line, not the exit code.
- **The waveform is still written** when that happens. Look at `tb.fst`.

A testbench runner inside the app is planned (roadmap U54); until then this recipe
is the whole of it, and it is worth knowing anyway — it is what you will type in
the lab.

## 10. Designs in more than one file

Your top level can instantiate sub-entities and use packages that live beside it.
There is nothing to configure: if the picked design does not compile on its own,
the other VHDL files in its folder are compiled into the same library and it is
tried again, working out the order by retrying until nothing more can be added.

Two consequences:

- **A neighbor that does not compile is ignored, not fatal.** Course testbenches
  frequently do not build as shipped, and they sit right beside the design they
  test. Your design still runs.
- **Only the file you picked is simulated.** The rest are compiled so that it can be.

## 11. Where to go next

Four more bundled designs, each adding exactly one idea to
[`gates_mux.vhd`](../hdl/gates_mux.vhd):

| Design | Adds |
|---|---|
| [`hex_decoder_7seg.vhd`](../hdl/hex_decoder_7seg.vhd) | the 7-segment display — still no clock, so the digits follow the switches instantly |
| [`code_lock_fsm.vhd`](../hdl/code_lock_fsm.vhd) | a state machine with named states, and edge detection on a button |
| [`countdown_7seg.vhd`](../hdl/countdown_7seg.vhd) | a clock divider, on the contract's own `COUNTER_BITS` |
| [`running_light.vhd`](../hdl/running_light.vhd) | a divider on a generic **you** name — the two-clocks lesson above |

And then:

- [troubleshooting.md](troubleshooting.md) — by symptom, when something is wrong
- [writing_designs.md](writing_designs.md) — the port contract, pin maps, board-native
  designs, and the RGB and scan-display idioms
- [user_guide.md](user_guide.md) — every screen, control, setting and environment
  variable
- [`hdl/blinky_survey.md`](../hdl/blinky_survey.md) — twelve ways to write a blinker,
  and what each one teaches

> **A design is a program.** The simulator compiles and **runs** your `.vhd` with
> your user privileges — VHDL can read and write files, and on the native-code
> backends it can call arbitrary native functions. Treat a design you did not write
> like a script you did not write.
