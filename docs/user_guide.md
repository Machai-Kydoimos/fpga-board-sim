# User guide

Everything the simulator does once it is installed: the four launcher screens, the
in-simulation controls and stats panel, board-native runs, and how your
preferences, waveforms, and session logs are stored. For installation see
[docs/install.md](install.md); for writing your own designs see
[docs/writing_designs.md](writing_designs.md). Back to the [README](../README.md).

## Starting from the command line

`fpga-sim` with no arguments opens at the board selector, which is the tour. Once you
know what you want, two flags skip straight to it:

```bash
fpga-sim --board DE10-Standard --vhdl lab1/test_entity.vhd
```

That opens the preview with the board selected and the file already loaded, validated
and analyzed — the same state you would reach by walking the first three screens. It
is worth a desktop shortcut on a machine you use for one board, and it saves a lot of
clicking while you iterate on a design.

| Flag | What it does |
|---|---|
| `--board BOARD` | Open on this board. Either spelling works — the name on screen (`DE10-Standard`) or the class name (`DE10StandardPlatform`) — and case and punctuation are ignored, so `de10 standard` finds it too. |
| `--vhdl PATH` | Load this design. Relative paths are resolved against the directory you ran the command from, so your files stay wherever you keep them. |
| `--pinmap PATH` | Bind the design through this constraint file instead of the one beside it (see [one folder is one project](#bring-your-own-project-one-folder-is-one-project)). |
| `--generic NAME=VALUE` | Override a generic on the design's top level; repeatable — the same thing [Generics…] does, at launch. See [below](#changing-a-generic-without-leaving-the-simulator). |
| `--sim NAME` | Use a particular simulator for this run (see [Simulator](#2-preview-the-board)). |
| `--list-sims` · `--add-sim PATH` | List the simulators found, or register one that is not on `PATH`. |
| `--benchmark N` | Run headless for N seconds and print a performance report instead of opening the launcher. |

Neither flag can strand you. An unknown board name opens the selector, and a file that
is missing or fails validation opens the preview with nothing loaded — with the reason
both on the terminal and in a dialog, since a shortcut may have no terminal attached.
`--vhdl` on its own (no `--board`) simply preloads the path: the design cannot be
checked until there is a board to check it against.

### "It looks frozen"

The simulator watches for this — but it does not interrupt you. If no LED or digit
changes for ten seconds **while simulated time is still advancing**, a small
control appears next to **[Pause]**:

```text
ⓘ Why is nothing happening?
```

That is all that happens until you click it. Nothing covers the board, no warning
appears, and if your design is a button that lights an LED and you simply were not
pressing it, you can ignore the whole thing entirely. Touching a control does not
withdraw the offer — poking at the board must not silence the thing that was about
to explain it — but it does change what the offer says, because once you have used
a switch "you may just not have pressed anything" is no longer the likeliest
reading.

**The simulation keeps running while you read it.** The panel is an overlay, not
a modal — the board stays live behind it, and the step you are waiting for may
well arrive while you are reading about it. Only **[Pause]** stops the simulator
(and the **F1** help, which has to: it takes over the window, and a simulator
nobody is listening to stalls anyway). **[Stop]**, **ESC** and closing the window
end the run.

**Pausing changes nothing about it.** Wall-clock time spent paused is not evidence
of a stall — no simulated time passes either — so a pause never raises the offer,
and it never takes one away: stopping the run to read the numbers carefully is the
obvious thing to do with a board that will not move, and it works. Time already
spent waiting is kept, not discarded, so a board that was eight seconds into a
silence when you paused is two seconds away from the offer when you resume.

**One step does not make it go away.** A design that toggles an LED once every
thirty seconds is exactly what this is for, so a single blink after a long silence
leaves the offer where it is: that blink is evidence the design *is* just slow, not
evidence that it isn't. The offer withdraws once the board has been genuinely
active for a while — and if you have the panel open, nothing the design does closes
it. Only **[ Close ]** does that.

The simulator cannot tell those apart, and that is the honest reason for the light
touch: a design waiting for input and a divider quietly counting look *identical*
from outside — still inputs, still outputs, simulated time running. Guessing which
one you have and announcing it would be wrong often enough to be worth nothing.

Click it and you get the arithmetic, measured at that moment — watch for a minute
before asking and you are told about the minute, not about the first ten seconds
of it:

```text
This design may just be slow, not broken
No LED or digit has changed in 10 s of wall-clock time.
In that time this machine simulated 819 k clock cycles = 16.4 ms of the board's 50 MHz.
Your CNTR_LEN = 24 means 16.8 M cycles per step: about 3 min here, 336 ms on the real board.
To watch it here, set CNTR_LEN to about 15:
    [Stop], then [Generics…] on the preview  —  or relaunch with  --generic CNTR_LEN=15
That steps about every 400 ms instead. Your file is not touched: CNTR_LEN stays 24 for the
  real board.
NVC is also installed here and is usually faster than GHDL: [Stop], then the SIM: toggle on
  the preview re-runs this design on it.
```

**If a faster simulator is already installed, it says so** — naming the engine and
pointing at the preview's `SIM:` toggle, which is the *only* place the simulator is
chosen. It is deliberately not a button on the panel: switching engines mid-run
restarts simulated time rather than continuing it, so a second control that looked
like "go faster" would quietly throw away the wait you had already done. Saying
"[Stop], then the toggle" keeps one control and is honest that a re-run is a re-run.
It gives no ratio — the ordering never varies, but the factor depends on your design
and your machine, and this panel does not print numbers it has not measured. See
[choosing a simulator](install.md#choosing-a-simulator) for the figures.

**The width it quotes is the one your design is actually running with**, which is
not always the one in your file. The simulator floors `COUNTER_BITS` so a contract
design blinks visibly here — to 17, or 20 on NVC, or `4 × digits` on a many-digit
7-segment board — and you may have set something else yourself through
[Generics…]. When the run and the file differ the advisory says so and names which
is which:

```text
COUNTER_BITS is running at 17, not the 24 in your file (the simulator lowers it so
  a design blinks visibly here) — that is 131 k cycles per step: about 804 ms here,
  1 ms on the real board.
```

The promise below it still quotes your file — *"COUNTER_BITS stays 24 for the real
board"* — because that is the number you can see in your editor and the one your
hardware will use.

**The width it suggests is computed from the rate it just measured**, not picked in
advance — a faster backend is told it can afford a wider divider, a slower one a
narrower, and each suggestion is sized to step about twice a second on the machine
in front of you. If your divider is already small enough to be quick here, it says
so and suggests nothing, because the cause is then somewhere else.

If your design has no divider generic — the width is a constant in the
architecture — it says how to make one, since that is the change that gives you the
lever without touching what the board runs.

Every number is measured on **your** machine during the quiet spell that just
happened. The cycle count is the simulated time your simulator actually reported
over those ten seconds, counted at the clock **you** have selected — change the
clock preset and the measurement restarts rather than mixing two rates. The "here"
figure is that window's own throughput (cycles ÷ seconds), not a running average,
so it describes this laptop, this OS and this backend at that moment: the figure
for GHDL's mcode and the figure for NVC are different, and both are right.

The only number that is *not* measured is the real board's — that one is your
board's own clock, which is the point of the comparison.

#### If you have not touched the controls, it says that instead

When the board has switches or buttons and none has been touched since the run
began, the panel leads with the likelier reading and keeps the arithmetic as the
alternative:

```text
Nothing has changed on the board
No LED or digit has changed in 10 s, and no switch or button has been touched.
If your design follows the switches or buttons, try one: a design that is waiting for input
  is right to show nothing.
If instead it counts, it may just be slow here: in that time this machine simulated 819 k
  clock cycles = 16.4 ms of the board's 50 MHz.
Your CNTR_LEN = 24 means 16.8 M cycles per step: about 3 min here, 336 ms on the real board.
To watch it here, set CNTR_LEN to about 15:
    [Stop], then [Generics…] on the preview  —  or relaunch with  --generic CNTR_LEN=15
That steps about every 400 ms instead. Your file is not touched: CNTR_LEN stays 24 for the
  real board.
NVC is also installed here and is usually faster than GHDL: [Stop], then the SIM: toggle on
  the preview re-runs this design on it.
```

Use a control — even once, even putting it straight back — and the simulator stops
offering that explanation for the rest of the run.

**[ Close ]** puts the panel away and leaves the small control where it was, so you
can look again without waiting another ten seconds.

Three things it deliberately does **not** do:

- **It never fires when simulated time has stopped.** A design that is merely slow
  and a simulator that has died look identical on screen, and blaming your divider
  for our crash would be worse than silence. Both conditions must hold.
- **It never interrupts.** The detection is not confident enough to earn a
  banner, so it earns an offer instead — one small control you may click or
  ignore. A first design that works is never talked over.
- **It ignores your switches and buttons *for the timer*.** Flipping a switch to
  see whether anything is alive changes the picture without telling the simulator
  anything about your design — so only LEDs and digits reset the timer, and poking
  at the board while you wonder will not silence the thing that was about to
  explain it. Your inputs are noted only to decide which explanation leads.

The offer goes away by itself after fifteen seconds of the board genuinely
animating. One blink is not enough — a design that steps once every thirty seconds
is exactly the case this exists for, so a single step is evidence *for* the
explanation rather than against it. If the board goes quiet again, the offer comes
back: that second silence is worth a word too.

Read it together with [generic overrides](#when-the-board-looks-frozen-generic-overrides),
which is what to do about it.

### Changing a generic without leaving the simulator

Once a design is loaded, the preview shows a **[Generics…]** button beside the
gear (only when the design actually has something you can change). It lists the
top level's generics with the values your file declares:

```text
Generics — running_light.vhd
─────────────────────────────────────────────
 NUM_SWITCHES  positive   set by the board
 NUM_LEDS      positive   set by the board
 COUNTER_BITS  positive  [ 24 ]
 CNTR_LEN      positive  [ 15 ]  design says 24
 INVERTED      boolean   [ false ]
 PATTERN       std_logi… "1010"
─────────────────────────────────────────────
 [ Defaults ]                [ Cancel ]  [ Apply ]
```

Click a value to type in it, **Tab** moves between fields, **Enter** applies and
**Esc** leaves the field (or closes the dialog). Values are checked when you apply
— a `positive` set to 0 is refused there, with the reason, rather than becoming a
confusing analysis error a minute later. **[Apply]** re-analyzes the design; the
preview then carries a line naming what is overridden, so an hour later you can
still see why the board is behaving as it is.

**Your file is never edited.** The values belong to this run and last as long as
the file is loaded; the design on disk keeps whatever the real board needs. The
board's own sizing generics (`NUM_LEDS` and friends) are shown but not editable —
they are the board's to set — and anything whose type we cannot offer safely (a
vector, an enumeration) is listed read-only rather than hidden, so you can see it
exists.

`--generic NAME=VALUE` on the command line does the same thing at launch, and is
still the right tool for a shortcut or a script.

### When the board looks frozen: generic overrides

A design that gets its visible rate from the top bits of a clock divider is fine on
hardware and looks dead here. `CNTR_LEN = 24` at 50 MHz steps about three times a
second on the bench; in simulation the same design steps about once every minute and
a half, and there is nothing on screen to tell you that from a design that does not
work.

Turn the divider down for the simulator without touching the file:

```bash
fpga-sim --board DE10-Standard --vhdl lab2/running_light.vhd --generic CNTR_LEN=4
```

Repeat the flag for more than one. Values are checked before anything runs, and a
name your design does not declare is reported with the list of names it does — a
typo should not look like the flag being ignored.

**Nothing is ever overridden for you.** Your file's own defaults run unless you ask,
because the point of this tool is that it agrees with your hardware. The override is
per-run and changes nothing on disk.

What you can change: whole-number generics (`integer`, `positive`, `natural`),
`boolean` ones (`true` / `false`), and single-bit ones (`'0'` / `'1'`). Anything else
— a vector, an enumeration — has to be changed in the file, where the syntax is
unambiguous. `NUM_LEDS`, `NUM_SWITCHES` and the rest of the sizing generics are the
board's to set and are not yours to override.

`COUNTER_BITS` **is** overridable, and worth knowing about: the simulator already
lowers it (to 17, not your file's 24) so that a contract design blinks visibly, and
until now it did that silently. `--generic COUNTER_BITS=20` replaces that with your
own number.

## Launcher screens

The launcher walks through four screens in order: board selector → board preview →
VHDL file picker → simulation.

Need a refresher at any launcher screen? Press **F1** or **?**, or click the **(?)**
button (top-right of the selector header and the preview corner) to open an in-app
help overlay covering the workflow, keyboard shortcuts, and the VHDL design contract.

### 1. Select a board

A list of 285 FPGA boards appears, **sorted by name**. Type to filter, click or
press **Enter** to select — the cursor starts on the first row, so the keyboard
alone works from the first frame.

**What the filter searches**, per board: its name, its class name, its silicon
vendor (Intel, Xilinx, Lattice, Gowin, …) and its **manufacturer**. That last one
is worth knowing about — the board data has no maker field, so it is taken from
the board's canonical port-convention name. Typing `terasic` finds the DE-series
boards even though their vendor field says "Intel", and `digilent` finds the
Arty/Basys/Nexys fleet. (`litex` and `amaranth` are toolchains rather than
manufacturers, so they do not match this way.)

The **Sort** dropdown and the component / vendor chips narrow the list further;
both, and the filter text, persist across sessions.

### 2. Preview the board

The board renders with LEDs, buttons, switches, and — on supported boards — a
7-segment display, all matching the real hardware. Each component is labeled with
its resource name; **hover** any LED, switch, or button for a moment to reveal its
net name, pin, and direction.

LEDs lay out **bank by bank**, labeled with the board's own bank names where the
data provides them (a DE2-115 shows an 18-LED `LEDR` row above a 9-LED `LEDG`
row), and render in their **documented colors** — every non-default color in the
board data cites a vendor source (reference-manual figure or prose). A 3-pin
**RGB LED** draws as a single puck (`RGB0`, `RGB1`, …) that mixes its three
channels into one color.

- **Click switches** to toggle them, or **press and sweep across a row** to set
  a whole bank in one gesture. The sweep *paints* rather than toggles: the
  switch you press on decides the value, and every switch the drag crosses is
  set to that value. Start on an **off** switch to drive the bank on, on an
  **on** switch to drive it off — so it is predictable from any starting
  pattern, unlike toggling, which would just hand you the complement. Wide
  banks wrap to two rows at smaller window sizes, in which case a full bank is
  one sweep per row
- **Click and hold buttons** to press them
- **Hold `0`-`9`, then `A` `B` `C`** to press buttons by index — key `0` is the
  **first** button (`btn(0)` in your VHDL), matching the labels the board draws.
  Hold as many as you like and release them in any order; two keys pressed in
  the same frame reach the design in one atomic update, which the mouse cannot
  do with its single cursor. The **numpad** digits work too, so a numeric keypad
  becomes a button pad. Each bound button shows its key on its face, and the
  hover tooltip names it as well. Hex covers the whole fleet: the largest board
  has 13 buttons, and only 6 of 285 have more than 10
- **Right-click a button** to **latch** it down hands-free; right-click again to
  release it. A latched button draws in its own color with a small padlock in
  its top-right corner, and combines freely with a live hold — hold it with the mouse *as well*, let the
  mouse go, and it stays down because the latch is a separate hold
- **Hover a component** → tooltip with its net name, pin, direction, and the
  vector bit it drives (`btn(3)` / `sw(11)`). The bit is worth knowing: on a few
  boards the *drawn label* is not the index — the Sword renders three different
  buttons all labeled `BTN0` — so the tooltip is where the on-screen widget and
  your VHDL index line up
- **`SIM: …`** toggle → cycle between installed simulators, each shown by a
  short label (`SIM: GHDL`, `SIM: NVC`, and the GHDL code generators
  `SIM: GHDL-LLVM` / `SIM: GHDL-JIT`); the choice is remembered per session.
  Run `fpga-sim --list-sims` to see them all, or `--add-sim PATH` to register
  one in a non-standard location — see
  [Choosing a simulator](install.md#choosing-a-simulator)
- **"Start Simulation"** button → opens the VHDL file picker
- **R** → reset all switches off and release every held button, latches included
- **F1 / ? / (?)** → open the help overlay
- Whatever you set here **carries into the run**: the switches you flip and the
  buttons you latch are exactly what the design sees on its very first clock
  edge, so you can stage a reset or a mode select before pressing Start rather
  than racing to click it afterwards. Live mouse and keyboard holds are not
  carried — those end with the gesture. The state follows you back out of the
  simulation too, and survives a trip through the file picker; **choosing a
  different board** resets it, since switch and button indices mean nothing
  across boards
- **Gear button** (next to the `(?)`) → open the [Settings dialog](#settings-dialog):
  switch the UI theme, reset the remembered sim speed, toggle waveform capture,
  auto-open the waveform viewer, or clear the recent-files list
- **ESC** → back to board list

### 3. Select a VHDL file

**Three ways in**, and they all end at the same three checks (encoding → contract
→ analysis), so a design behaves identically however it arrived:

- **Drop it on the window.** A `.vhd` or `.vhdl` dropped on the picker *or* on the
  board preview is loaded straight away — your files can stay in the Quartus or
  Vivado folder you already have open. Dropping a **directory** on the picker
  browses there instead.
- **Browse to it.** The picker opens where you last were, and after a file fails
  to load it re-opens **in your directory on the file you tried**, not back at the
  bundled examples.
- **Name it on the command line** — `fpga-sim --vhdl lab1/top.vhd`, see
  [above](#starting-from-the-command-line).

Until you pick something, the preview offers the **board's own example** —
`counter_7seg.vhd` on a 7-segment board, `blinky.vhd` otherwise — so there is
always something to run. It is only a suggestion: changing the board changes the
example, and the moment you load a file of your own it is never replaced.

The `hdl/` directory holds those examples — LED blinkers, 7-segment counters, and
the generated 6502/Z80 embedded-core systems. See
[docs/writing_designs.md](writing_designs.md) for the full catalog and the design
contract.

> **⚠ Simulating a design executes it.** Analysis, elaboration, and the run itself
> all happen with your user privileges: any design can read and write files through
> `std.textio`, and on the native-code backends (NVC and GHDL's LLVM/JIT/GCC
> variants) a `VHPIDIRECT` foreign declaration can call arbitrary native code. Treat
> a downloaded `.vhd` like a downloaded script — read it before you run it. A
> sandboxed run mode is planned ([roadmap D16](improvement_roadmap.md)).

When you pick a file, the simulator analyzes and elaborates it (a few seconds on a
large design); a spinner overlay keeps the window responsive while this runs and
reports any contract or compile error.

#### When it does not load

The error dialog shows GHDL's or NVC's **own** words, unedited, and adds a `Hint:`
underneath when it recognizes the failure — a missing `use ieee.numeric_std.all;`,
a reserved word used as a signal name, a syntax error reported one line late, a
positional port map with too many actuals, an entity that is not in the folder.
The catalog of them, with both engines' wordings, is in
[writing_designs.md](writing_designs.md#when-the-compiler-rejects-your-file).

GHDL's `^` column marker keeps its column, so it still points at the character it
was aimed at. **[Copy]** (or `C`) puts the title, the compiler's text and the
hints on the clipboard together. **[View Example]** (or `V`) opens the board's
own example beside the error; the dialog stays open so you can compare them. A
message too long for the panel scrolls with **↑ ↓ / PgUp / PgDn / Home / End**
or the wheel, and the footer says so when there is more to see.

Every error is also printed to the terminal you launched from — the whole thing,
hints included — so you never have to transcribe it from the screen.

#### Bring your own project: one folder is one project

You do not have to rename anything to match a contract. If a **constraint file** —
your `.qsf` from Quartus, your `.xdc` from Vivado — sits in the same folder as the
design you pick, the simulator maps your design onto the board **by pin**, and your
own port names stop mattering. `reset` lands on whichever key its pin belongs to,
each `hex` bit on its digit and segment, and polarity comes from the board, so an
active-low button is inverted for you. The preview shows which file was used, and
the run is badged with it.

The contract is one directory: **the design, whatever it instantiates, and one
constraint file, together.** The simulator reads that folder and nothing else — it
does not learn Quartus's or Vivado's project layout, because Vivado's is
user-configurable and version-dependent, and a tool that guessed wrong there would
wire a design to the wrong pins without saying so.

So if your files live inside a tool's project tree, copy them into one folder first.
Vivado in particular keeps sources and constraints several directories apart. Point
the simulator at a design still sitting in such a tree and it will **tell you where
the constraint file is** instead of failing quietly. To keep one elsewhere on
purpose, name it: `fpga-sim --pinmap path/to/board.xdc`.

Two constraint files in one folder is a question only you can answer — a project
with both a `.qsf` and an `.xdc` is targeting two boards — so the simulator asks
rather than guessing. See
[writing_designs.md](writing_designs.md#your-projects-own-pin-map) for the formats
read, what happens to a port with no pin assignment, and the rest of the rules.

### 4. Run the simulation

The selected simulator (GHDL or NVC) compiles and simulates the VHDL design via
cocotb, clocked at the board's actual frequency. The simulation runs **in the same
window** — the board you previewed stays on screen and becomes interactive, while the
simulator itself runs headless in the background:

- **Switches/buttons** drive FPGA inputs in real time
- **Hold `0`-`9` / `A` `B` `C`** (or the numpad) to press buttons from the
  keyboard — several at once, released in any order. Alt-Tabbing away or opening
  the help overlay releases held keys, so nothing is left stuck down; latches
  survive both
- **Right-click a button** to **latch** it down — the way to hold a reset or an
  enable while you work the rest of the board. Latches survive the help overlay
  and a pause; `R` clears them
- **LEDs** reflect FPGA outputs from the simulation
- **7-segment digits** show live hex glyphs on supported boards
- **Hover a component** → tooltip with its net name, pin, direction, vector bit,
  and whether it is latched
- **Toolbar** (bottom-left) → **[Back to Boards]**, **[Change VHDL]**, or
  **[Reload VHDL]** — Reload re-analyzes the current file (pick up edits you just
  made in your editor) and restarts, without leaving the simulation
- **R** — reset all switches off and release every held button, latches included
  (inputs only; design state is unaffected)
- **S** — toggle the [stats panel](#stats-panel)
- **D** — toggle the [debug duty-bar view](#debug-duty-bar-view)
- **F1 / ?** — open the help overlay
- **ESC** or **[■ Stop]** (bottom-right) → stop the simulation, return to the board list
- **Close the window (X)** → quit the app. The launcher is a single window for the
  whole session, so closing it exits — the same as on every other screen

## LED brightness

LEDs and 7-segment digits render at their **measured brightness**, not merely on
or off. A design that PWMs an LED shows a real fade, and a display digit that
switches too fast for the eye shows the honest dim blur it would produce on
hardware — where a single sampled snapshot would show whichever side of the pulse
it happened to land on.

Duty is measured exactly, inside the simulation, so there is no minimum pulse
width and no aliasing. Two consequences are worth knowing:

- **PWM slower than the simulation rate looks like slow-motion blinking.** That is
  the truthful sub-real-time view, not a bug — a faster simulator or a higher
  speed setting fuses it into a steady glow. `hdl/blinky_pwm.vhd` is tuned so a
  full breath takes about 8 seconds on GHDL-mcode and 1 on NVC.
- **A design that multiplexes LEDs in time renders the honest average.** A
  one-hot walker scanning 27 LEDs faster than the eye shows each LED at its real
  fractional brightness — the same dim moving trail the physical board would
  show — because within every measurement window the lit time is measured
  exactly (the walker's per-window duties sum to 100%).
- **Hovering an LED shows its exact duty** (`Duty 73.2%`) alongside the net and
  pin, whenever it is something other than plainly on or off. An **RGB LED's
  tooltip always shows all three channels** (`R 73% · G 0% · B 100%`) — the mix
  is the whole story. The puck itself renders the per-channel γ-encoded mix, so
  equal duties on all three channels wash to white exactly like the real part.

**[PAUSE] holds brightness.** Pausing freezes the board exactly as it looked,
and resuming carries on as though you had not paused — pause is there so you can
inspect the board, so it must not change what the board shows. The duty engine
takes one final measurement at the instant pause lands, so the frozen numbers
describe the moment you paused; a channel that was plainly off or on still
follows live switch input while paused, so a combinational switch→LED design
stays responsive under inspection.

### Debug duty-bar view

Realistic brightness encodes duty as luminance — exactly the thing that is hard
to *read* precisely. The debug view encodes it as **length** instead: toggle it
with **D** in the simulation (or the **Duty bars** row in the
[Settings dialog](#settings-dialog); the choice persists across sessions).

- An **RGB LED** becomes three stacked R/G/B bars — fill length is the *linear*
  channel duty (no gamma), with a % readout whenever the bar is tall enough.
- A **mono LED** keeps its circle, showing the exact duty as digits inside it,
  and gains a thin duty bar underneath.
- The unfilled span renders near-black: it is *off time*, not a dark LED.

Bar length reads to a percent where luminance cannot, and it pairs naturally
with pause: **pause, hit D, and read the frozen numbers** — the high-precision
counterpart to the running realistic view. Realistic rendering stays the
default, and tooltips show duties in both modes.

Measurement costs almost nothing on designs whose LEDs change at human-visible
rates. A channel that toggles on *every clock* is the expensive case — the
6-digit hex odometer in `counter_7seg.vhd` is one — so if you want that run at
full speed, set `FPGA_SIM_DUTY=off` to fall back to plain on/off rendering.

## Stats panel

A strip at the bottom of the window shows live simulation statistics across three
zones. Toggle it with **S**.

### Info (left)

| Stat | Description |
|------|-------------|
| Board clk | Native clock frequency of the selected board |
| Sim time | Total simulated time elapsed this session |
| Clk/frame | Clock cycles advanced in the last simulation step |
| Eff. rate | Actual measured throughput (clocks/frame × GUI fps) |
| GUI FPS | 30-frame rolling average of display frames per second |
| G/D/I % | **G** = simulator step (share of the headless simulator's own loop); **D**raw / **I**dle = host frame shares. The simulator runs in a separate process now, so these are measured against different clocks and need not total 100%. |

On a [board-native run](#board-native-runs) this zone also carries the active-low
note described below.

### Simulation speed (center)

A logarithmic slider from **0.001× to 10×** (default **0.1×**; the last-used value
is remembered across sessions) controls how many simulated nanoseconds are passed to
each `await Timer(...)` call, effectively slowing the design below real-time for
debugging. When GHDL/NVC throughput limits the step, an amber **(CPU-limited)** note
appears — dragging right won't help; try lowering the virtual clock instead.

### Virtual clock (right)

**[-] / [+]** cycle through the clock frequencies declared in the board's definition.
The new half-period is written directly to the VHDL wrapper; the clock changes within
one half-period without restarting the simulator. A **[PAUSE] / [RESUME]** button
freezes simulation while keeping the simulator process alive.

## Board-native runs

Most designs use the generic `clk/sw/btn/led` contract, but a design can instead be
written to a board's **own** port names (Terasic `CLOCK_50`/`SW`/`KEY`/`LEDR`/`HEX0…`,
litex `clk100`/`user_led`/`user_sw`/`user_btn`, and so on). When the simulator
recognizes such a file against the selected board, the run is board-native and the
UI signals it in three places. (For how to write these designs, see
[docs/writing_designs.md](writing_designs.md#board-native-designs).)

- **Analysis spinner.** Picking a native file shows the title
  `Analyzing board-native <file>…` with the detail line
  `Board-native (<maker>) — <SIM> analysis & elaboration…`, where `<maker>` is the
  matched convention (e.g. `terasic`).
- **Active-low note.** The stats-panel **Info** zone gains a line
  `board-native · active-low: <roles>` listing the roles the board's convention
  drives active-low — some combination of **LED**, **SW**, **BTN**, **HEX** (or
  `none`). This is the physical truth the simulator applies for you: on a board whose
  LEDs light when the pin is driven low, your `'1'` still lights the LED — the
  wrapper inverts at the boundary. The note is present on every board-native run and
  absent on generic runs, so it doubles as the "you're in native mode" indicator.
- **Session log.** The per-run [session log](#session-logs) records `"mode":
  "native"` and `"convention": "<maker>"` (both are `"generic"` / `null` for a
  standard contract run).

### Scan displays (Basys 3, Nexys 4 / 4 DDR / A7)

On boards whose 7-segment display is physically **multiplexed**, a board-native
design drives the real scan interface — the shared segment lines plus the digit
enables (`seg`/`dp`/`an` on Basys 3; the `CA..CG`/`DP`/`AN` scalars on the Nexys
family), all active-low exactly as the reference manuals specify. The simulator
demultiplexes the scan and shows each digit at its **honest scan brightness**: a
digit lit one slot in N measures 1/N duty, so an 8-digit Nexys display renders
dimmer than a 4-digit Basys 3 — just like the real boards. Three things to know:

- **Use the Full measurement mode** (the default). The Off/Color-only modes sample
  instantaneous levels, and an instant of a scan shows only the one digit whose
  enable is active.
- **Pausing** shows the actually-active digit — a stopped scan on real hardware
  also lights just one digit.
- A design that **doesn't drive the display** still runs board-native with dark
  digits; driving only *part* of the scan interface is rejected with a message
  naming the missing ports.

## Session and preferences

Preferences and history live under `~/.fpga_simulator/`. Loading and saving are
best-effort — a corrupt or missing file never breaks the app.

### Session persistence

The last-used board, VHDL file, simulator, selector sort/filters, window size, and
sim-speed slider are saved to `~/.fpga_simulator/session.json` and restored on the
next run. The session updates whenever you pick a file or change the board or
simulator — not only when a simulation launches.

### Recent files

The last **10** (board, VHDL) pairs are remembered as a recent-files list. Clear it
from the [Settings dialog](#settings-dialog).

### Settings dialog

Open it with the **gear button** in the board preview. It can:

- switch the UI **theme** (see below);
- **reset** the remembered sim speed;
- toggle **waveform capture** (off / VCD / FST);
- toggle **Auto-open** of the waveform viewer after a run;
- toggle **LED PWM** — see [LED PWM and speed](#led-pwm-and-speed) below;
- toggle **Duty bars** — the [debug duty-bar view](#debug-duty-bar-view), same
  as the in-sim **D** key;
- **clear** the recent-files list.

### LED PWM and speed

LEDs and 7-segment digits normally render **continuous brightness**, measured
from the design's real duty cycle — a half-lit LED is a signal that is high half
the time. Turning **LED PWM** off in the Settings dialog renders them plain
on/off instead.

It is worth knowing that this is also the biggest **speed** control the
simulator offers, because measuring duty is not free: it splices an integrator
into the generated wrapper, once per output channel. The cost therefore scales
with how many channels a board has, and a many-digit 7-segment display has a
lot of them (8 per digit):

| Design / board | Speed-up with PWM off |
|---|---|
| `counter_7seg` / DE10-Lite (6 digits, 48 segment channels) | **4.7x–5.5x** |
| `rgb_rainbow` / Arty A7 (16 LED channels) | ~1.1x |

(Measured over several runs on one machine; the spread is background load rather
than the setting. Your own numbers come from `--benchmark`.)

So on a board with a big display, turning PWM off buys back most of the run
speed; on a board with a handful of LEDs it changes little. The choice is
remembered between sessions, and changing it re-analyzes on the next launch
(the wrapper itself differs). `FPGA_SIM_DUTY=off` pins the same thing for a
scripted run without touching the saved preference.

### Themes

Three themes — **PCB Green**, **Dark**, and **High Contrast** — are applied live and
restored at startup; because the simulation now renders in the same window, it always
matches the launcher. The active theme is stored in `session.json`.

### Waveform capture

When waveform capture is enabled (Settings dialog, or `FPGA_SIM_WAVEFORM` below),
each run writes a timestamped file:

```text
~/.fpga_simulator/waveforms/<design>_<YYYY-MM-DD_HH-MM-SS>.<vcd|fst>
```

Successive runs accumulate for side-by-side comparison in GTKWave. **VCD** is plain
text; **FST** is compact for long runs. The path is printed when the run ends. Set
`FPGA_SIM_WAVEFORM_DIR` to keep captures in your own project tree instead of the
default directory.

### GTKWave save files (`.gtkw`)

Each capture also gets a matching `.gtkw` save file, so
`gtkwave <design>_<timestamp>.gtkw` opens preloaded with the board's
`clk`/`sw`/`btn`/`led` (and `seg`) signals instead of an empty view.

### Auto-open a viewer

Turn on **Auto-open** in the Settings dialog (or set `FPGA_SIM_WAVEFORM_OPEN=1`) to
launch a viewer on the dump after each run. The command comes from
`FPGA_SIM_WAVEFORM_VIEWER` (default `gtkwave {gtkw}`; e.g. `surfer {dump}` for another
viewer). `{dump}` and `{gtkw}` expand to the capture and its save file; a program that
isn't found falls back to your OS default handler.

### Headless and CI environment variables

For headless or CI runs (no Settings dialog), these environment variables control
capture:

| Variable | Effect |
|----------|--------|
| `FPGA_SIM_WAVEFORM=off\|vcd\|fst` | Enable capture in the chosen format |
| `FPGA_SIM_WAVEFORM_DIR=<path>` | Write captures under `<path>` instead of the default |
| `FPGA_SIM_WAVEFORM_OPEN=1` | Auto-open a viewer after the run |
| `FPGA_SIM_WAVEFORM_VIEWER=<cmd>` | Viewer command template (`{dump}` / `{gtkw}`) |
| `FPGA_SIM_WAVEFORM_MEMORIES=1` | Also dump nested arrays/memories (the embedded-core RAM/ROM/registers); off by default because arrays add size |

And one for LED rendering:

| Variable | Effect |
|----------|--------|
| `FPGA_SIM_DUTY=off\|color\|full` | Duty measurement: `full` (default) renders PWM brightness; `off` renders plain on/off and skips the integrator. Overrides the Settings **LED PWM** row for that run |

### Session logs

After each simulation session a compact performance summary is written to
`~/.fpga_simulator/sessions/<timestamp>_<board>.json` — board, simulator, duration,
avg FPS, simulated time, the G/D/I breakdown, and (for a
[board-native run](#board-native-runs)) the `mode` and `convention` fields.
