# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup
```bash
# Initialize board definitions submodule (required)
git submodule update --init

# Install runtime dependencies
uv sync

# Install with dev dependencies (includes pytest)
uv sync --group dev
```

### Run the simulator
```bash
uv run fpga-sim
# or: uv run python -m fpga_sim
```

### Run tests (no display needed)
```bash
uv run pytest
```

Tests cover board loading, JSON serialization, GHDL analysis, and cocotb simulation.

## Architecture

The simulator has two distinct phases: a **launcher phase** (pygame process) and a **simulation phase** (GHDL+cocotb subprocess).

### Key Files

| File | Role |
|------|------|
| `src/fpga_sim/__main__.py` | Main entry point; pygame UI with four screens |
| `src/fpga_sim/board_loader.py` | Parses amaranth-boards `.py` files using mock classes |
| `src/fpga_sim/sim_bridge.py` | GHDL analysis + simulation launcher; platform-specific VPI env setup |
| `src/fpga_sim/ui/` | pygame UI package (board_selector, board_display, components, etc.) |
| `sim/sim_testbench.py` | cocotb test that runs pygame inside the GHDL simulation |
| `sim/sim_wrapper_template.vhd` | VHDL wrapper template; drives clock internally |
| `hdl/blinky.vhd` | Example VHDL design (use as template for the expected port interface) |
| `tests/` | pytest integration test suite |
| `sim/test_blinky.py` | Headless cocotb tests for the blinky design |
| `amaranth-boards/` | Git submodule with 74+ real board definitions |

### Data Flow

1. `src/fpga_sim/board_loader.py` strips `import` statements from amaranth-boards `.py` files, executes them in a mock namespace, and extracts `BoardDef` objects (containing `ComponentInfo` lists for LEDs, buttons, switches).

2. `src/fpga_sim/__main__.py` displays four sequential screens: `BoardSelector` → `FPGABoard` (preview) → `VHDLFilePicker` → simulation start.

3. When simulation starts, `__main__.py` calls `pygame.quit()`, serializes the `BoardDef` to JSON, and calls `launch_simulation()` in `src/fpga_sim/sim_bridge.py`.

4. `sim_bridge.py` builds a platform-aware environment (PATH, LD_LIBRARY_PATH/PYTHONHOME, VPI paths) and runs `ghdl -r ... --vpi=cocotbvpi_ghdl.so`. The board JSON is passed via the `FPGA_SIM_BOARD_JSON` env var. Both `src/` and `sim/` are added to `PYTHONPATH` so the subprocess can import `fpga_sim` and find `sim_testbench`.

5. `sim/sim_testbench.py` is loaded by cocotb inside GHDL. It deserializes the `BoardDef`, creates a new `FPGABoard` (pygame), and runs a cooperative loop: `await Timer(2, "us")` advances GHDL simulation, then the test reads `dut.led.value`, updates the display, and processes pygame events.

### VHDL Design Contract

#### Standard boards (no 7-segment display)

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

#### 7-segment boards (DE0, DE0-CV, DE1-SoC, DE10-Lite, Nandland-Go, Nexys4-DDR, RZ-EasyFPGA-A2/2, StepMXO2)

```vhdl
entity my_design is
  generic (
    NUM_SWITCHES : positive := 4;
    NUM_BUTTONS  : positive := 4;
    NUM_LEDS     : positive := 4;
    NUM_SEGS     : positive := 4;   -- number of digits; set by simulator to board value
    COUNTER_BITS : positive := 32
  );
  port (
    clk : in  std_logic;
    sw  : in  std_logic_vector(NUM_SWITCHES - 1 downto 0);
    btn : in  std_logic_vector(NUM_BUTTONS  - 1 downto 0);
    led : out std_logic_vector(NUM_LEDS     - 1 downto 0);
    seg : out std_logic_vector(8 * NUM_SEGS - 1 downto 0)
    -- digit i occupies bits [8i+7 : 8i] = {dp, g, f, e, d, c, b, a}, active-high
  );
end entity;
```

The simulator sets generics to match the selected board's resource counts and provides a 100 MHz clock. The entity name must match the filename stem (e.g. `blinky.vhd` → entity `blinky`). Use `counter_7seg.vhd` in `hdl/` as a working 7-seg example.

### Platform Notes

- GHDL must be installed system-wide (`ghdl` on PATH)
- On Linux, `LD_LIBRARY_PATH` is used for cocotb and GHDL shared libraries
- On Windows, all DLL directories must be on PATH; Windows Store Python is unsupported — use a standalone Python installed via `uv`
- `find_libpython` is used to locate the Python shared library for cocotb VPI

### Board Loader Mock Namespace

`fpga_sim.board_loader._make_namespace()` provides mock classes (`Resource`, `Subsignal`, `Pins`, `PinsN`, `DiffPairs`, `Attrs`, `Clock`, `Connector`) and stubs for interfaces/memory (UART, SPI, I2C, SDRAM, etc.) that are not simulated. Only resources whose names contain `led`, `button`, `btn`, `switch`, or `sw` are extracted; everything else is stubbed out.
