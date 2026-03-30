# FPGA Simulator

[![CI](https://github.com/Machai-Kydoimos/fpga-board-sim/actions/workflows/ci.yml/badge.svg)](https://github.com/Machai-Kydoimos/fpga-board-sim/actions/workflows/ci.yml)

Interactive FPGA board simulator supporting VHDL simulation via [GHDL](https://github.com/ghdl/ghdl) or [NVC](https://github.com/nickg/nvc). Select from 76 real FPGA board definitions (sourced from [amaranth-boards](https://github.com/amaranth-lang/amaranth-boards)), then run VHDL designs against a virtual board with switches, buttons, and LEDs — all driven by [cocotb](https://github.com/cocotb/cocotb).

## Quick Start

### Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (Python package manager)
- **GHDL** and/or **NVC** (VHDL simulators — at least one required)

### Clone the repository

```bash
git clone --recurse-submodules https://github.com/Machai-Kydoimos/fpga-board-sim.git
cd fpga-board-sim
```

> If you already cloned without `--recurse-submodules`, run `git submodule update --init` to populate the `amaranth-boards/` directory.

### Install a VHDL simulator

Install **GHDL**, **NVC**, or both.  GHDL is the default and is available in most package managers; NVC compiles designs to native machine code via LLVM and may be faster on complex designs.

#### GHDL

**Windows:**
```powershell
winget install ghdl.ghdl.ucrt64.mcode
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ghdl
```

**Linux (Fedora):**
```bash
sudo dnf install ghdl
```

**macOS:**
```bash
brew install ghdl
```

#### NVC

NVC is not in the standard Linux package repositories yet.  Install via Homebrew or build from source:

**macOS / Linux (Homebrew):**
```bash
brew install nvc
```

**Linux (from source):**
```bash
# Install build dependencies (Debian/Ubuntu):
sudo apt install build-essential automake autoconf flex check \
  llvm-dev pkg-config zlib1g-dev libdw-dev

git clone https://github.com/nickg/nvc && cd nvc
./autogen.sh && mkdir build && cd build
../configure && make -j$(nproc) && sudo make install
```

See the [NVC build guide](https://github.com/nickg/nvc#building-from-source) for full instructions.

### Set up Python environment

`uv` manages the venv and all dependencies automatically. It also installs a standalone Python when needed — which matters on Windows where the Windows Store Python can't be embedded by an external simulator process.

```bash
uv sync
```

### Run

**Linux / macOS:**
```bash
uv run fpga-sim                 # use default/saved simulator
uv run fpga-sim --sim nvc       # force NVC
uv run fpga-sim --sim ghdl      # force GHDL
# or: uv run python fpga_board.py [--sim ghdl|nvc]

# Headless benchmark (no window, prints a performance report):
uv run fpga-sim --benchmark 10
uv run fpga-sim --benchmark 10 --board ArtyA7_35Platform --vhdl hdl/blinky.vhd
```

**Windows:**
```powershell
# Ensure GHDL is on PATH (if not already after install)
$env:PATH = "C:\Users\$env:USERNAME\AppData\Local\Microsoft\WinGet\Packages\ghdl.ghdl.ucrt64.mcode_Microsoft.Winget.Source_8wekyb3d8bbwe\bin;$env:PATH"

uv run fpga-sim
```

## Usage

### 1. Select a board

A list of 76 FPGA boards appears. Type to filter, click to select.

### 2. Preview the board

The board renders with LEDs, buttons, and switches matching the real hardware. Components show their resource names and pin assignments.

- **Click switches** to toggle them
- **Click and hold buttons** to press them
- **`SIM: GHDL` / `SIM: NVC`** toggle → cycle between installed simulators
- **"Start Simulation"** button → opens the VHDL file picker
- **ESC** → back to board list

### 3. Select a VHDL file

Navigate to a `.vhd` / `.vhdl` file. The `hdl/` directory contains six ready-to-run designs (`blinky.vhd`, `blinky_counter.vhd`, `blinky_morse.vhd`, `blinky_pwm.vhd`, `blinky_walking.vhd`, `blinky_alt.vhd`) as starting points.

### 4. Simulation runs

The selected simulator (GHDL or NVC) compiles and simulates the VHDL design via cocotb, clocked at the board's actual frequency. The pygame UI becomes interactive:

- **Switches/buttons** drive FPGA inputs in real time
- **LEDs** reflect FPGA outputs from the simulation
- **S** — toggle the stats panel (see below)
- **ESC** or close window → stops simulation, returns to board list

#### Stats panel

A strip at the bottom of the window shows live simulation statistics across three zones:

**Info (left)**

| Stat | Description |
|------|-------------|
| Board clk | Native clock frequency of the selected board |
| Sim time | Total simulated time elapsed this session |
| Clk/frame | Clock cycles advanced in the last simulation step |
| Eff. rate | Actual measured throughput (clocks/frame × GUI fps) |
| GUI FPS | 30-frame rolling average of display frames per second |
| G/D/I % | Frame time split: **G**HDL step / **D**raw / **I**dle (cap sleep) |

**Simulation speed (center)**

A logarithmic slider from **0.001× to 10×** (default **0.1×**) controls how many simulated nanoseconds are passed to each `await Timer(...)` call, effectively slowing the design below real-time for debugging. When GHDL/NVC throughput limits the step, an amber **(CPU-limited)** note appears — dragging right won't help; try lowering the virtual clock instead.

**Virtual clock (right)**

**[-] / [+]** cycle through the clock frequencies declared in the board's amaranth-boards definition. The new half-period is written directly to the VHDL wrapper; the clock changes within one half-period without restarting the simulator. A **[PAUSE] / [RESUME]** button freezes simulation while keeping the simulator process alive.

> **Session persistence:** The last-used board, VHDL file, and simulator choice are saved to `~/.fpga_simulator/session.json` and pre-selected on the next run.  After each simulation session a compact performance summary is also written to `~/.fpga_simulator/sessions/<timestamp>_<board>.json` (board, simulator, duration, avg FPS, simulated time, G/D/I breakdown).

## Project Structure

```
fpga_board.py              Entry point — screen flow, --benchmark CLI, --sim flag
board_loader.py            Parses amaranth-boards definitions without the full amaranth toolchain
sim_bridge.py              GHDL/NVC analysis + cocotb simulation launcher; _GHDLBackend/_NVCBackend classes
sim_testbench.py           cocotb test that bridges simulator signals ↔ pygame UI; main sim loop
sim_session_log.py         Writes per-session JSON summaries to ~/.fpga_simulator/sessions/
sim_metrics.py             Optional per-frame CSV metrics (set FPGA_SIM_METRICS=<path> to enable)
analyze_metrics.py         Standalone performance report from a sim_metrics CSV
session_config.py          Session persistence (~/.fpga_simulator/session.json)
generate_board_images.py   Renders static board previews (used for documentation/thumbnails)
ui/                        pygame UI package
ui/constants.py            Color constants and _ui_scale helper (single source of truth)
ui/components.py           FPGAChip, LED, Switch, Button — low-level board components
ui/board_selector.py       Board picker screen
ui/fpga_board.py           Board preview + simulation screen (FPGABoard class)
ui/sim_panel.py            Stats strip rendered during simulation (SimPanel class)
ui/vhdl_picker.py          VHDL file browser screen
ui/error_dialog.py         Error dialog overlay
hdl/blinky.vhd             Example VHDL design (switches XOR counter → LEDs, buttons OR → LEDs)
hdl/blinky_alt.vhd         Alternate blinky using independent per-LED counters
hdl/blinky_counter.vhd     Binary counter displayed on LEDs
hdl/blinky_morse.vhd       Morse code blinker
hdl/blinky_pwm.vhd         PWM-based LED brightness control
hdl/blinky_walking.vhd     Walking-light / knight-rider pattern
sim/sim_wrapper_template.vhd  VHDL wrapper template — drives the clock internally, instantiates user design
sim/test_blinky.py         Headless cocotb tests for the blinky design
tests/                     pytest integration suite (board loading, serialization, GHDL, NVC, UI, panel)
amaranth-boards/           Board definitions from amaranth-lang/amaranth-boards
pyproject.toml             Project metadata and dependencies
```

## How It Works

### Board Loading (`board_loader.py`)

The amaranth-boards project defines 76 FPGA boards as Python classes, each with a `resources` list describing LEDs, switches, buttons, clocks, and other peripherals using amaranth's build DSL (`Resource`, `Pins`, `Attrs`, etc.).

Rather than requiring the full amaranth toolchain as a dependency, `board_loader.py` provides **lightweight mock classes** that mimic just enough of the amaranth API to execute board definition files. It:

1. Strips `import` statements from each board `.py` file
2. Executes the file in a namespace containing mock `Resource`, `Pins`, `Attrs`, `Connector`, etc.
3. Finds classes with a `resources` attribute (the board definitions)
4. Classifies each resource as LED, button, or switch based on its name
5. Extracts pin names, connector info, IO attributes, and inversion flags

The result is a `BoardDef` object per board containing `ComponentInfo` entries with display names (e.g. `LED0`, `BTN2`, `UP0` for named buttons like `button_up`) and hardware metadata (pin names, connector references, IO standard attributes).

### Pygame UI (`ui/` package)

The UI has four screens, each a class with a `run()` method:

1. **`BoardSelector`** — scrollable, filterable list of all discovered boards. Each row shows the board name and a resource summary. Type to filter, click to select.

2. **`FPGABoard`** (preview mode) — renders the selected board's components on a green PCB-style background. An auto-layout engine arranges LEDs, buttons, and switches into a grid that adapts to the component count and window size. LEDs get 3× the vertical weight since boards can have many (up to 64+). Components are interactive even in preview — switches toggle, buttons press. A **`SIM: GHDL` / `SIM: NVC`** toggle button in the footer cycles between installed simulators (grayed out when only one is available). A **"Start Simulation"** button leads to step 3.

3. **`VHDLFilePicker`** — minimal file browser that shows directories and `.vhd`/`.vhdl` files. Navigate by clicking directories, select a VHDL file to proceed.

4. **`FPGABoard`** (simulation mode, inside `sim_testbench.py`) — same rendering as preview, but now driven by the simulator. Switch/button callbacks write to DUT inputs; DUT LED outputs update the display each frame.

In simulation mode, pygame is the sole interface between the user and the simulator. Mouse events on switches and buttons trigger callbacks that write directly to `dut.sw` / `dut.btn` via cocotb — there is no queue or IPC; the write is synchronous in the event handler. LED state flows the other way: once per frame, after `await Timer(2µs)` has advanced the simulation, `dut.led.value` is read and each LED's display state is updated.

Note that pygame runs in two separate OS processes. The launcher (board selector → file picker) calls `pygame.quit()` before spawning the simulator subprocess; `sim_testbench.py` calls `pygame.init()` fresh inside that subprocess.

### Simulation Pipeline

When the user clicks "Start Simulation" and picks a VHDL file, the following happens:

```
fpga_board.py                    sim_bridge.py                     Simulator + cocotb
─────────────                    ─────────────                     ──────────────────
1. Serialize BoardDef to JSON
2. Call launch_simulation() ───→ 3. Analyze VHDL
   pygame.quit()                    (GHDL: also elaborate here;
                                     NVC: elaborate with generics
                                     in the next step)
                                 4. Build env (PATH, PYTHONHOME,
                                    VPI/VHPI lib paths, cocotb vars)
                                 5. simulator -r --vpi/load=cocotb ─→ 6. Simulator loads VPI/VHPI lib
                                                                      7. cocotb initializes
                                                                      8. Imports sim_testbench.py

                                 sim_testbench.py
                                 ────────────────
                                 9.  Deserialize BoardDef from env
                                 10. pygame.init(), create FPGABoard + SimPanel
                                 11. Write initial clk_half_ns to dut
                                     (VHDL sim_wrapper drives clock internally)
                                 12. Wire switch/button callbacks:
                                     on click → collect all states
                                     into bit vector → dut.sw.value
                                 13. Main loop:
                                     await Timer(step_ns)  ← advances simulation
                                                             step = BASE_STEP_NS
                                                              × speed_factor
                                                              capped at MAX_CYCLES
                                     read dut.led.value    ← get outputs
                                     set_led() for each    ← update pygame
                                     _handle_events()      ← process mouse/keyboard
                                     if [-]/[+] clicked:
                                       dut.clk_half_ns ←   ← change virtual clock
                                     board._draw()         ← render board
                                     panel.draw()          ← render stats strip
                                     clock.tick(60)        ← 60fps cap
```

The key insight is that **pygame runs inside the cocotb test function**. Each frame, `await Timer(step_ns, unit="ns")` advances the simulation by a configurable number of nanoseconds (controlled by the speed slider), then the test reads outputs and processes pygame events. This cooperative loop gives smooth rendering with live simulation.

The clock is generated entirely inside the VHDL `sim_wrapper` entity rather than by a Python coroutine. This eliminates per-half-period GPI callbacks — the only GPI round-trips per frame are the two endpoints of the single `await Timer(...)` call. The wrapper exposes a `clk_half_ns` port; when the panel's **[-]/[+]** buttons change the virtual clock frequency, `sim_testbench.py` writes the new half-period to `dut.clk_half_ns` and the VHDL process picks it up within one half-cycle.

### The Blinky Design (`hdl/blinky.vhd`)

A simple but complete VHDL design that exercises all board I/O:

- **Counter**: free-running N-bit counter incremented on each rising clock edge
- **LED logic**: `led(i) = sw(i) XOR counter(top-i) OR btn(i)`
  - Switches XOR with counter bits → LEDs blink at different rates depending on which switches are on
  - Buttons OR directly → LEDs light immediately while held
- **Generics**: `NUM_SWITCHES`, `NUM_BUTTONS`, `NUM_LEDS`, `COUNTER_BITS` are set by the simulator to match the selected board. `COUNTER_BITS=17` keeps the blink rate visible at typical board clock frequencies (a 100 MHz board with a 17-bit counter blinks the MSB at ~763 Hz, well within the visible range).

### Simulator Backends (`sim_bridge.py`)

`sim_bridge.py` contains two private backend classes that encapsulate all simulator-specific details:

| | `_GHDLBackend` | `_NVCBackend` |
|---|---|---|
| Interface | VPI (`libcocotbvpi_ghdl.so`) | VHPI (`libcocotbvhpi_nvc.so`) |
| Plugin flag | `--vpi=<lib>` on `-r` | `--load=<lib>` on `-r` |
| Work dir | `--workdir=PATH` | `--work=work:PATH` |
| VHDL standard | `--std=08` | `--std=2008` |
| Generics at | `-r` (run time) | `-e` (elaboration) |

Because NVC requires generics at elaboration time, `analyze_vhdl()` performs only the `-a` step for NVC; `launch_simulation()` performs `-e` (with board generics) followed by `-r`.

`detect_simulators()` returns the list of installed simulators; the UI and CLI use this to know what options to offer.

**Linux:** `_build_sim_env()` sets `LD_LIBRARY_PATH` to include the cocotb shared libraries and the simulator's lib directory.

**Windows:** All DLL directories must be on `PATH` so Windows can resolve the dependency chain. `PYTHONHOME` must point to the base Python installation (not a venv). The Windows Store Python is sandboxed and **cannot** be embedded by external processes — a standalone Python (installed via `uv python install`) is required.

## Running Tests

**Linux / macOS:**
```bash
uv run pytest
```

**Windows:**
```powershell
$env:PATH = "C:\Users\$env:USERNAME\AppData\Local\Microsoft\WinGet\Packages\ghdl.ghdl.ucrt64.mcode_Microsoft.Winget.Source_8wekyb3d8bbwe\bin;$env:PATH"
uv run pytest
```

Tests cover board loading, JSON serialization, GHDL/NVC analysis, and cocotb simulation — no display needed.

## Writing VHDL for the Simulator

The simulator expects a top-level entity with these ports:

```vhdl
entity my_design is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    COUNTER_BITS : positive := 24
  );
  port (
    clk  : in  std_logic;
    sw   : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn  : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led  : out std_logic_vector(NUM_LEDS     - 1 downto 0)
  );
end entity;
```

The simulator sets the generics to match the selected board's resource counts and drives `clk` at the board's actual clock frequency (extracted from its `Clock` resource, falling back to 12 MHz).

## Dependencies

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.10+ | Runtime (must be standalone, not Windows Store) |
| pygame | 2.5+ | GUI rendering |
| cocotb | 2.0+ | Python ↔ simulator bridge (VPI/VHPI) |
| GHDL | 5.0+ | VHDL compilation and simulation (mcode backend) |
| NVC | 1.11.0+ | Alternative VHDL simulator (LLVM native code; recommended ≥ 1.16.0) |

At least one of GHDL or NVC must be installed. Both can coexist; the active simulator is selected via the UI toggle or `--sim` flag.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, quality
standards, type annotation conventions, and architecture notes for contributors.

## Talks & Presentations

- **Virtual FPGA Boards** — InstallFest 2026
  [📹 Watch on YouTube](https://youtu.be/v4Fc6HctK1E) · [📄 Slide source (AsciiDoc)](https://raw.githubusercontent.com/Machai-Kydoimos/fpga-board-sim/main/docs/virtual-fpga-boards.adoc)

## Acknowledgements

This simulator was inspired by these working examples of interactive virtual FPGA boards:

- **[ghdl-interactive-sim](https://github.com/chuckb/ghdl-interactive-sim)** by Chuck ([Chuck's Tech Talk](https://www.chuckstechtalk.com/software/2021/12/27/interactive-vhdl-testbench.html)) — demonstrated driving GHDL interactively via VPI from Python, which is the core technique used here.

- **[ghdl-vpi-virtual-board](https://gitlab.ensta-bretagne.fr/bollenth/ghdl-vpi-virtual-board)** by bollenth (ENSTA Bretagne) — a polished FPGA virtual board simulator built on GHDL VPI (without Python). A beautiful piece of work worth admiring.

## License

Board definitions in `amaranth-boards/` are from [amaranth-lang/amaranth-boards](https://github.com/amaranth-lang/amaranth-boards) (BSD-2-Clause).
