# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Setup

```bash
# Install runtime dependencies
uv sync

# Install with dev dependencies (includes pytest)
uv sync --group dev

# (Optional) Re-sync board definitions from upstream sources
uv run python scripts/sync_amaranth_boards.py  # amaranth-boards
uv run python scripts/sync_litex_boards.py     # litex-boards
uv run python scripts/sync_digilent_xdc.py     # Digilent XDC
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
| `src/fpga_sim/board_loader.py` | Loads board definitions from JSON into `BoardDef` objects (runtime loader) |
| `src/fpga_sim/sim_bridge.py` | GHDL analysis + simulation launcher; platform-specific VPI env setup |
| `src/fpga_sim/ui/` | pygame UI package (board_selector, board_display, components, etc.) |
| `boards/` | JSON board definitions (multi-source: `amaranth-boards/`, `litex-boards/`, `digilent-xdc/`, `custom/`) |
| `boards/schema/board.schema.json` | JSON Schema for board definition validation |
| `scripts/sync_amaranth_boards.py` | Syncs board definitions from amaranth-boards GitHub repo |
| `scripts/amaranth_parser.py` | Mock-exec parser: amaranth `.py` board files → `BoardDef` (used by `sync_amaranth_boards.py`) |
| `scripts/sync_litex_boards.py` | Syncs board definitions from litex-boards GitHub repo |
| `scripts/litex_parser.py` | Mock-exec parser: litex `_io` platform files → board dicts (used by `sync_litex_boards.py`) |
| `scripts/sync_digilent_xdc.py` | Syncs board definitions from Digilent master XDC files (with port_conventions) |
| `scripts/digilent_parser.py` | XDC regex parser → board dicts + `port_conventions` (used by `sync_digilent_xdc.py`) |
| `scripts/sync_common.py` | Shared sync scaffolding (download, ref-resolve, naming, schema-validated JSON/metadata output) for all three `sync_*.py` |
| `sim/sim_testbench.py` | cocotb test that runs pygame inside the GHDL simulation |
| `sim/sim_wrapper_template.vhd` | Unified VHDL wrapper template; seg port/generic spliced in by `_generate_wrapper()` when needed |
| `src/fpga_sim/sim_session_log.py` | Writes per-session JSON summaries to ~/.fpga_simulator/sessions/ |
| `hdl/blinky.vhd` | Example VHDL design (use as template for the expected port interface) |
| `tests/` | pytest integration test suite |
| `sim/test_blinky.py` | Headless cocotb tests for the blinky design |
| `sim/test_7seg.py` | Headless cocotb tests for the counter_7seg design |
| `sim/test_cpu_walking.py` | Headless cocotb tests for the embedded 6502 walking counter |
| `hdl/mx65_walking_counter_7seg.vhd` | **Generated** single-file 6502 embedded-core demo (vendored mx65 + ROM/RAM/IO/top); see `docs/embedded_core_system_plan.md` |
| `scripts/gen_embedded_core.py` | Generator: emits a single-file embedded-core system from a CPU plugin + `systems/*.toml` spec + firmware `.bin` |
| `scripts/embedded_core/` | Generator package: `cpu_plugin`, `system_spec`, `emitter`, `templates/`, vendored `cores/mx65.vhd`, `rom_to_vhdl.py` |
| `systems/` | TOML system specs consumed by the generator (e.g. `mx65_walking_counter_7seg.toml`) |
| `firmware/` | 6502 firmware: `.s` sources + assembled `.bin` (ca65/ld65), embedded verbatim as the ROM constant |

### Data Flow

1. `src/fpga_sim/board_loader.py` reads JSON board definitions from `boards/` subdirectories (each subdirectory is a "source": `amaranth-boards/`, `litex-boards/`, `digilent-xdc/`, `custom/`, etc.) and constructs `BoardDef` objects. The offline mock-exec pipeline for parsing upstream amaranth `.py` board files lives in `scripts/amaranth_parser.py` (used by `scripts/sync_amaranth_boards.py`); the litex and digilent parsers live in `scripts/litex_parser.py` and `scripts/digilent_parser.py` (self-contained, no `fpga_sim` dependency).

2. `src/fpga_sim/__main__.py` displays four sequential screens: `BoardSelector` → `FPGABoard` (preview) → `VHDLFilePicker` → simulation start.

3. When simulation starts, `__main__.py` calls `pygame.quit()`, serializes the `BoardDef` to JSON, and calls `launch_simulation()` in `src/fpga_sim/sim_bridge.py`.

4. `sim_bridge.py` builds a platform-aware environment (PATH, LD_LIBRARY_PATH/PYTHONHOME, VPI paths) and runs `ghdl -r ... --vpi=cocotbvpi_ghdl.so`. The board JSON is passed via the `FPGA_SIM_BOARD_JSON` env var. Both `src/` and `sim/` are added to `PYTHONPATH` so the subprocess can import `fpga_sim` and find `sim_testbench`.

5. `sim/sim_testbench.py` is loaded by cocotb inside GHDL. It deserializes the `BoardDef`, creates a new `FPGABoard` (pygame), and runs a cooperative loop: `await Timer(sim_step_ns, unit="ns")` advances simulation by a configurable step (controlled by the speed slider), then the test reads `dut.led.value` and `dut.seg.value`, updates the display, and processes pygame events.

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

The simulator sets generics to match the selected board's resource counts and provides a 100 MHz clock. **`COUNTER_BITS` is overridden at runtime** to a value lower than the `:= 24` / `:= 32` defaults shown above — a floor of 17, widened for many-digit 7-seg displays — because at the simulator's sub-real-time throughput a full 24-bit counter's MSB would toggle too slowly to see; real hardware would use the full default. The entity name must match the filename stem (e.g. `blinky.vhd` → entity `blinky`). Use `counter_7seg.vhd` in `hdl/` as a working 7-seg example.

#### Embedded CPU systems (single-file soft-core designs)

A design can instead be a **single self-contained file** that embeds a soft CPU core (e.g. the vendored mx65 6502) + ROM + RAM + memory-mapped IO + a top satisfying the same `clk/sw/btn/led[/seg]` contract above. These are **generated** by `scripts/gen_embedded_core.py` from a vendored core + a `systems/*.toml` spec + an assembled firmware `.bin`; the firmware reads the board's resource counts from IO config registers, so one design fits any board (proven across 2/4/6-digit boards). They add a generation-time **`PRESCALER_BITS`** generic — a free-running tick the firmware polls to decouple the visible rate from raw CPU speed; the wrapper never overrides it, so it keeps its default. The committed `hdl/mx65_*.vhd` is the generator's output — **regenerate it** (and the firmware `.bin`) rather than hand-editing. See `docs/embedded_core_system_guide.md`.

### Platform Notes

- GHDL must be installed system-wide (`ghdl` on PATH)
- On Linux, `LD_LIBRARY_PATH` is used for cocotb and GHDL shared libraries
- On Windows, all DLL directories must be on PATH; Windows Store Python is unsupported — use a standalone Python installed via `uv`
- `find_libpython` is used to locate the Python shared library for cocotb VPI

### Board Definition Sources

Board definitions live in `boards/` as JSON files, organized by source:

- `boards/amaranth-boards/` — auto-generated from [amaranth-boards](https://github.com/amaranth-lang/amaranth-boards) via `scripts/sync_amaranth_boards.py`
- `boards/litex-boards/` — auto-generated from [litex-boards](https://github.com/litex-hub/litex-boards) via `scripts/sync_litex_boards.py`
- `boards/digilent-xdc/` — auto-generated from [Digilent XDC](https://github.com/Digilent/digilent-xdc) via `scripts/sync_digilent_xdc.py` (includes `port_conventions`)
- `boards/custom/` — manually maintained boards (e.g., DE10-Standard)
- Additional source directories can be added freely; the loader discovers them automatically

To add a new board, create a JSON file in `boards/custom/` following the schema at `boards/schema/board.schema.json`. The JSON format includes optional `peripherals` and `port_conventions` sections for future use.

### Amaranth Parser Mock Namespace (sync script only)

`scripts/amaranth_parser._make_namespace()` provides mock classes (`Resource`, `Subsignal`, `Pins`, `PinsN`, `DiffPairs`, `Attrs`, `Clock`, `Connector`) and stubs for interfaces/memory (UART, SPI, I2C, SDRAM, etc.) that are not simulated. These are used only by `scripts/sync_amaranth_boards.py` to parse upstream amaranth-boards Python files into JSON. The parser imports the `BoardDef` / `ComponentInfo` / `SevenSegDef` data classes from `fpga_sim.board_loader` (one-way; the runtime loader never imports the parser). Only resources whose names contain `led`, `button`, `btn`, `switch`, or `sw` are extracted; everything else is stubbed out.
