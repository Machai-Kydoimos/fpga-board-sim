# User guide

Everything the simulator does once it is installed: the four launcher screens, the
in-simulation controls and stats panel, board-native runs, and how your
preferences, waveforms, and session logs are stored. For installation see
[docs/install.md](install.md); for writing your own designs see
[docs/writing_designs.md](writing_designs.md). Back to the [README](../README.md).

## Launcher screens

The launcher walks through four screens in order: board selector → board preview →
VHDL file picker → simulation.

Need a refresher at any launcher screen? Press **F1** or **?**, or click the **(?)**
button (top-right of the selector header and the preview corner) to open an in-app
help overlay covering the workflow, keyboard shortcuts, and the VHDL design contract.

### 1. Select a board

A list of 278 FPGA boards appears. Type to filter, click to select.

### 2. Preview the board

The board renders with LEDs, buttons, switches, and — on supported boards — a
7-segment display, all matching the real hardware. Each component is labeled with
its resource name; **hover** any LED, switch, or button for a moment to reveal its
net name, pin, and direction.

- **Click switches** to toggle them
- **Click and hold buttons** to press them
- **Hover a component** → tooltip with its net name, pin, and direction
- **`SIM: GHDL` / `SIM: NVC`** toggle → cycle between installed simulators
- **"Start Simulation"** button → opens the VHDL file picker
- **R** → reset all switches off and release any held buttons
- **F1 / ? / (?)** → open the help overlay
- **Gear button** (next to the `(?)`) → open the [Settings dialog](#settings-dialog):
  switch the UI theme, reset the remembered sim speed, toggle waveform capture,
  auto-open the waveform viewer, or clear the recent-files list
- **ESC** → back to board list

### 3. Select a VHDL file

Navigate to a `.vhd` / `.vhdl` file. The `hdl/` directory contains ready-to-run
designs as starting points — LED blinkers, 7-segment counters, and the generated
6502/Z80 embedded-core systems. See [docs/writing_designs.md](writing_designs.md) for
the full catalog and the design contract.

When you pick a file, the simulator analyzes and elaborates it (a few seconds on a
large design); a spinner overlay keeps the window responsive while this runs and
reports any contract or compile error.

### 4. Run the simulation

The selected simulator (GHDL or NVC) compiles and simulates the VHDL design via
cocotb, clocked at the board's actual frequency. The simulation runs **in the same
window** — the board you previewed stays on screen and becomes interactive, while the
simulator itself runs headless in the background:

- **Switches/buttons** drive FPGA inputs in real time
- **LEDs** reflect FPGA outputs from the simulation
- **7-segment digits** show live hex glyphs on supported boards
- **Hover a component** → tooltip with its net name, pin, and direction
- **Toolbar** (bottom-left) → **[Back to Boards]**, **[Change VHDL]**, or
  **[Reload VHDL]** — Reload re-analyzes the current file (pick up edits you just
  made in your editor) and restarts, without leaving the simulation
- **R** — reset all switches off and release any held buttons (inputs only; design
  state is unaffected)
- **S** — toggle the [stats panel](#stats-panel)
- **F1 / ?** — open the help overlay
- **ESC** or **[■ Stop]** (bottom-right) → stop the simulation, return to the board list
- **Close the window (X)** → quit the app. The launcher is a single window for the
  whole session, so closing it exits — the same as on every other screen

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
- **clear** the recent-files list.

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

### Session logs

After each simulation session a compact performance summary is written to
`~/.fpga_simulator/sessions/<timestamp>_<board>.json` — board, simulator, duration,
avg FPS, simulated time, the G/D/I breakdown, and (for a
[board-native run](#board-native-runs)) the `mode` and `convention` fields.
