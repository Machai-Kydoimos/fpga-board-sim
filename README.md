# FPGA Simulator

Interactive FPGA board simulator with GHDL-backed VHDL simulation. Select from 76 real FPGA board definitions (sourced from [amaranth-boards](https://github.com/amaranth-lang/amaranth-boards)), then run VHDL designs against a virtual board with switches, buttons, and LEDs — all driven by [GHDL](https://github.com/ghdl/ghdl) + [cocotb](https://github.com/cocotb/cocotb).

## Quick Start

### Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (Python package manager)
- **GHDL** (VHDL simulator)

### Clone the repository

```bash
git clone --recurse-submodules https://github.com/Machai-Kydoimos/simulator.git
cd simulator
```

> If you already cloned without `--recurse-submodules`, run `git submodule update --init` to populate the `amaranth-boards/` directory.

### Install GHDL

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

### Set up Python environment

`uv` manages the venv and all dependencies automatically. It also installs a standalone Python when needed — which matters on Windows where the Windows Store Python can't be embedded by GHDL.

```bash
uv sync
```

### Run

**Linux / macOS:**
```bash
uv run fpga-sim
# or: uv run python fpga_board.py
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
- **"Start Simulation"** button → opens the VHDL file picker
- **ESC** → back to board list

### 3. Select a VHDL file

Navigate to a `.vhd` / `.vhdl` file. The `hdl/` directory contains six ready-to-run designs (`blinky.vhd`, `blinky_counter.vhd`, `blinky_morse.vhd`, `blinky_pwm.vhd`, `blinky_walking.vhd`, `blinky_alt.vhd`) as starting points.

### 4. Simulation runs

GHDL compiles and simulates the VHDL design via cocotb, clocked at the board's actual frequency. The pygame UI becomes interactive:

- **Switches/buttons** drive FPGA inputs in real time
- **LEDs** reflect FPGA outputs from the simulation
- **ESC** or close window → stops simulation, returns to board list

> **Session persistence:** The last-used board and VHDL file are saved to `~/.fpga_simulator/session.json` and pre-selected on the next run.

## Project Structure

```
fpga_board.py              Entry point — runs main() and orchestrates the screen flow
board_loader.py            Parses amaranth-boards definitions without the full amaranth toolchain
sim_bridge.py              GHDL analysis + cocotb simulation launcher (handles Windows VPI setup)
sim_testbench.py           cocotb test that bridges GHDL signals ↔ pygame UI
session_config.py          Session persistence (~/.fpga_simulator/session.json)
generate_board_images.py   Renders static board previews (used for documentation/thumbnails)
ui/                        pygame UI package
ui/constants.py            Colour constants and _ui_scale helper (single source of truth)
ui/components.py           FPGAChip, LED, Switch, Button — low-level board components
ui/board_selector.py       Board picker screen
ui/fpga_board.py           Board preview screen (FPGABoard class)
ui/vhdl_picker.py          VHDL file browser screen
ui/error_dialog.py         Error dialog overlay
hdl/blinky.vhd             Example VHDL design (switches XOR counter → LEDs, buttons OR → LEDs)
hdl/blinky_alt.vhd         Alternate blinky using independent per-LED counters
hdl/blinky_counter.vhd     Binary counter displayed on LEDs
hdl/blinky_morse.vhd       Morse code blinker
hdl/blinky_pwm.vhd         PWM-based LED brightness control
hdl/blinky_walking.vhd     Walking-light / knight-rider pattern
sim/test_blinky.py         Headless cocotb tests for the blinky design
tests/                     pytest integration suite (board loading, serialization, GHDL, UI)
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

2. **`FPGABoard`** (preview mode) — renders the selected board's components on a green PCB-style background. An auto-layout engine arranges LEDs, buttons, and switches into a grid that adapts to the component count and window size. LEDs get 3× the vertical weight since boards can have many (up to 64+). Components are interactive even in preview — switches toggle, buttons press. A **"Start Simulation"** button leads to step 3.

3. **`VHDLFilePicker`** — minimal file browser that shows directories and `.vhd`/`.vhdl` files. Navigate by clicking directories, select a VHDL file to proceed.

4. **`FPGABoard`** (simulation mode, inside `sim_testbench.py`) — same rendering as preview, but now driven by the GHDL simulation. Switch/button callbacks write to DUT inputs; DUT LED outputs update the display each frame.

In simulation mode, pygame is the sole interface between the user and GHDL. Mouse events on switches and buttons trigger callbacks that write directly to `dut.sw` / `dut.btn` via cocotb — there is no queue or IPC; the write is synchronous in the event handler. LED state flows the other way: once per frame, after `await Timer(2µs)` has advanced the simulation, `dut.led.value` is read and each LED's display state is updated.

Note that pygame runs in two separate OS processes. The launcher (board selector → file picker) calls `pygame.quit()` before spawning GHDL; `sim_testbench.py` calls `pygame.init()` fresh inside the GHDL subprocess.

### Simulation Pipeline

When the user clicks "Start Simulation" and picks a VHDL file, the following happens:

```
fpga_board.py                    sim_bridge.py                     GHDL + cocotb
─────────────                    ─────────────                     ─────────────
1. Serialize BoardDef to JSON
2. Call launch_simulation() ───→ 3. Analyze VHDL with GHDL
   pygame.quit()                 4. Build env (PATH, PYTHONHOME,
                                    VPI DLL paths, cocotb vars)
                                 5. ghdl -r ... --vpi=cocotb ────→ 6. GHDL loads VPI DLL
                                                                   7. cocotb initializes
                                                                   8. Imports sim_testbench.py

                                 sim_testbench.py
                                 ────────────────
                                 9.  Deserialize BoardDef from env
                                 10. pygame.init(), create FPGABoard
                                 11. Start board clock coroutine (board frequency)
                                 12. Wire switch/button callbacks:
                                     on click → collect all states
                                     into bit vector → dut.sw.value
                                 13. Main loop:
                                     await Timer(2us)     ← advances GHDL simulation
                                     read dut.led.value   ← get outputs
                                     set_led() for each   ← update pygame
                                     _handle_events()     ← process mouse/keyboard
                                     _draw()              ← render frame
                                     clock.tick(60)       ← 60fps cap
```

The key insight is that **pygame runs inside the cocotb test function**. Each frame, `await Timer(2, unit="us")` advances the GHDL simulation by 2 microseconds, then the test reads outputs and processes pygame events. This cooperative loop gives smooth 60fps rendering with live simulation.

### The Blinky Design (`hdl/blinky.vhd`)

A simple but complete VHDL design that exercises all board I/O:

- **Counter**: free-running N-bit counter incremented on each rising clock edge
- **LED logic**: `led(i) = sw(i) XOR counter(top-i) OR btn(i)`
  - Switches XOR with counter bits → LEDs blink at different rates depending on which switches are on
  - Buttons OR directly → LEDs light immediately while held
- **Generics**: `NUM_SWITCHES`, `NUM_BUTTONS`, `NUM_LEDS`, `COUNTER_BITS` are set by the simulator to match the selected board. `COUNTER_BITS=10` in simulation keeps the blink rate visible at typical board clock frequencies.

### Platform-Specific VPI Setup (`sim_bridge.py`)

Getting GHDL's VPI (Verilog Procedural Interface) to work with cocotb requires platform-aware environment setup. `_build_sim_env()` handles this automatically:

**Linux:** Straightforward — GHDL and cocotb are typically system packages. The bridge sets `LD_LIBRARY_PATH` to include the cocotb shared libraries and GHDL lib directory.

**Windows:** More complex due to DLL search semantics:

- **`cocotbvpi_ghdl.dll`** depends on `gpi.dll`, `gpilog.dll` (cocotb internal), `libghdlvpi.dll` (GHDL's VPI library), and `python312.dll`
- All DLL directories must be on `PATH` so Windows can resolve the dependency chain
- `PYTHONHOME` must point to the base Python installation (not a venv) so the embedded interpreter finds stdlib
- `PYTHONPATH` includes the venv's `site-packages` so cocotb and project modules are importable
- The Windows Store Python is sandboxed and **cannot** be embedded by external processes — a standalone Python (installed via `uv python install`) is required

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

Tests cover board loading, JSON serialization, GHDL analysis, and cocotb simulation — no display needed.

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
| cocotb | 2.0+ | Python ↔ GHDL simulation bridge |
| GHDL | 5.0+ | VHDL compilation and simulation (mcode backend) |

## License

Board definitions in `amaranth-boards/` are from [amaranth-lang/amaranth-boards](https://github.com/amaranth-lang/amaranth-boards) (BSD-2-Clause).
