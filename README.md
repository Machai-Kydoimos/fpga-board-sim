# FPGA Simulator

Interactive FPGA board simulator with GHDL-backed VHDL simulation. Select from 74 real FPGA board definitions (sourced from [amaranth-boards](https://github.com/amaranth-lang/amaranth-boards)), then run VHDL designs against a virtual board with switches, buttons, and LEDs — all driven by [GHDL](https://github.com/ghdl/ghdl) + [cocotb](https://github.com/cocotb/cocotb).

## Quick Start

### Prerequisites

- **Python 3.12+** (standalone, not Windows Store — see setup below)
- **GHDL** (VHDL simulator)

### Install GHDL

```powershell
winget install ghdl.ghdl.ucrt64.mcode
```

### Set up Python environment

The Windows Store Python is sandboxed and can't be embedded by GHDL. Use `uv` to install a standalone Python:

```powershell
pip install uv
python -m uv python install 3.12
```

Find the standalone interpreter path:

```powershell
python -m uv python list | Select-String "3.12"
# Look for the one under AppData\Roaming\uv\python\...
```

Create and populate the venv:

```powershell
# Use the standalone Python (adjust path if needed)
& "$env:APPDATA\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe" -m venv .venv
.venv\Scripts\pip install pygame cocotb find_libpython
```

### Run

```powershell
# Ensure GHDL is on PATH
$env:PATH = "C:\Users\$env:USERNAME\AppData\Local\Microsoft\WinGet\Packages\ghdl.ghdl.ucrt64.mcode_Microsoft.Winget.Source_8wekyb3d8bbwe\bin;$env:PATH"

# Launch
.venv\Scripts\python fpga_board.py
```

## Usage

### 1. Select a board

A list of 74 FPGA boards appears. Type to filter, click to select.

### 2. Preview the board

The board renders with LEDs, buttons, and switches matching the real hardware. Components show their resource names and pin assignments.

- **Click switches** to toggle them
- **Click and hold buttons** to press them
- **"Start Simulation"** button → opens the VHDL file picker
- **ESC** → back to board list

### 3. Select a VHDL file

Navigate to a `.vhd` / `.vhdl` file. The `hdl/` directory contains `blinky.vhd` as a starting point.

### 4. Simulation runs

GHDL compiles and simulates the VHDL design via cocotb. The pygame UI becomes interactive:

- **Switches/buttons** drive FPGA inputs in real time
- **LEDs** reflect FPGA outputs from the simulation
- **ESC** or close window → stops simulation, returns to board list

## Project Structure

```
fpga_board.py      Main entry point — pygame UI (board selector, preview, file picker)
board_loader.py    Parses amaranth-boards definitions without the full amaranth toolchain
sim_bridge.py      GHDL analysis + cocotb simulation launcher (handles Windows VPI setup)
sim_testbench.py   cocotb test that bridges GHDL signals ↔ pygame UI
hdl/blinky.vhd     Example VHDL design (switches XOR counter → LEDs, buttons OR → LEDs)
sim/test_blinky.py Headless cocotb tests for the blinky design
sim/run_tests.py   Full integration test suite (26 tests, no GUI needed)
amaranth-boards/   Board definitions from amaranth-lang/amaranth-boards
pyproject.toml     Project metadata and dependencies
```

## How It Works

### Board Loading (`board_loader.py`)

The amaranth-boards project defines 74+ FPGA boards as Python classes, each with a `resources` list describing LEDs, switches, buttons, clocks, and other peripherals using amaranth's build DSL (`Resource`, `Pins`, `Attrs`, etc.).

Rather than requiring the full amaranth toolchain as a dependency, `board_loader.py` provides **lightweight mock classes** that mimic just enough of the amaranth API to execute board definition files. It:

1. Strips `import` statements from each board `.py` file
2. Executes the file in a namespace containing mock `Resource`, `Pins`, `Attrs`, `Connector`, etc.
3. Finds classes with a `resources` attribute (the board definitions)
4. Classifies each resource as LED, button, or switch based on its name
5. Extracts pin names, connector info, IO attributes, and inversion flags

The result is a `BoardDef` object per board containing `ComponentInfo` entries with display names (e.g. `LED0`, `BTN2`, `UP0` for named buttons like `button_up`) and hardware metadata (pin names, connector references, IO standard attributes).

### Pygame UI (`fpga_board.py`)

The UI has four screens, each a class with a `run()` method:

1. **`BoardSelector`** — scrollable, filterable list of all discovered boards. Each row shows the board name and a resource summary. Type to filter, click to select.

2. **`FPGABoard`** (preview mode) — renders the selected board's components on a green PCB-style background. An auto-layout engine arranges LEDs, buttons, and switches into a grid that adapts to the component count and window size. LEDs get 3× the vertical weight since boards can have many (up to 64+). Components are interactive even in preview — switches toggle, buttons press. A **"Start Simulation"** button leads to step 3.

3. **`VHDLFilePicker`** — minimal file browser that shows directories and `.vhd`/`.vhdl` files. Navigate by clicking directories, select a VHDL file to proceed.

4. **`FPGABoard`** (simulation mode, inside `sim_testbench.py`) — same rendering as preview, but now driven by the GHDL simulation. Switch/button callbacks write to DUT inputs; DUT LED outputs update the display each frame.

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
                                 11. Start 100MHz clock coroutine
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

The key insight is that **pygame runs inside the cocotb test function**. Each frame, `await Timer(2, unit="us")` advances the GHDL simulation by 2 microseconds (200 clock cycles at 100MHz), then the test reads outputs and processes pygame events. This cooperative loop gives smooth 60fps rendering with live simulation.

### The Blinky Design (`hdl/blinky.vhd`)

A simple but complete VHDL design that exercises all board I/O:

- **Counter**: free-running N-bit counter incremented on each rising clock edge
- **LED logic**: `led(i) = sw(i) XOR counter(top-i) OR btn(i)`
  - Switches XOR with counter bits → LEDs blink at different rates depending on which switches are on
  - Buttons OR directly → LEDs light immediately while held
- **Generics**: `NUM_SWITCHES`, `NUM_BUTTONS`, `NUM_LEDS`, `COUNTER_BITS` are set by the simulator to match the selected board. `COUNTER_BITS=10` in simulation keeps the blink rate visible.

### Windows VPI Setup (`sim_bridge.py`)

Getting GHDL's VPI (Verilog Procedural Interface) to work with cocotb on Windows requires careful environment setup:

- **`cocotbvpi_ghdl.dll`** depends on `gpi.dll`, `gpilog.dll` (cocotb internal), `libghdlvpi.dll` (GHDL's VPI library), and `python312.dll`
- All DLL directories must be on `PATH` so Windows can resolve the dependency chain
- `PYTHONHOME` must point to the base Python installation (not a venv) so the embedded interpreter finds stdlib
- `PYTHONPATH` includes the venv's `site-packages` so cocotb and project modules are importable
- The Windows Store Python is sandboxed and **cannot** be embedded by external processes — a standalone Python (installed via `uv python install`) is required

`_build_sim_env()` in `sim_bridge.py` assembles all of this automatically from the `.venv` directory.

## Running Tests

```powershell
$env:PATH = "C:\Users\$env:USERNAME\AppData\Local\Microsoft\WinGet\Packages\ghdl.ghdl.ucrt64.mcode_Microsoft.Winget.Source_8wekyb3d8bbwe\bin;$env:PATH"
.venv\Scripts\python sim\run_tests.py
```

This runs 26 headless tests covering board loading, JSON serialization, GHDL analysis, and cocotb simulation — no display needed.

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

The simulator sets the generics to match the selected board's resource counts and provides a 100 MHz clock.

## Dependencies

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12+ | Runtime (must be standalone, not Windows Store) |
| pygame | 2.5+ | GUI rendering |
| cocotb | 2.0+ | Python ↔ GHDL simulation bridge |
| GHDL | 5.0+ | VHDL compilation and simulation (mcode backend) |

## License

Board definitions in `amaranth-boards/` are from [amaranth-lang/amaranth-boards](https://github.com/amaranth-lang/amaranth-boards) (BSD-2-Clause).
