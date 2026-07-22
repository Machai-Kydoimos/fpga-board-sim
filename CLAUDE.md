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

The simulator runs in a **single window** (U34): the launcher's pygame process owns the one window for the whole session, and simulation runs in a **headless GHDL/NVC + cocotb child process** that streams signal state back over an IPC link (`sim_link`). No window is created or destroyed between launcher start and app exit.

### Key Files

| File | Role |
|------|------|
| `src/fpga_sim/__main__.py` | Thin entry point: arg parsing, pygame/window setup, headless benchmark |
| `src/fpga_sim/controller.py` | `ScreenController` + `SessionState`: drives the launcher screen flow (selector → preview → picker → simulate) |
| `src/fpga_sim/board_loader.py` | Loads board definitions from JSON into `BoardDef` objects (runtime loader) |
| `src/fpga_sim/sim_bridge.py` | GHDL/NVC analysis + elaboration; `start_simulation()` spawns the headless child (`SimChild`) + `finish_waveform()`; platform-specific VPI env setup |
| `src/fpga_sim/sim_link.py` | IPC transport between the UI host and the headless sim child (`multiprocessing.connection` over 127.0.0.1 + random HMAC authkey); pygame-free (U34) |
| `src/fpga_sim/ui/` | pygame UI package (board_selector, board_display, simulation_screen, sim_panel, components, etc.) |
| `src/fpga_sim/ui/simulation_screen.py` | `SimulationScreen`: renders the board in the launcher's window while the headless child streams signal state over `sim_link`; returns a `SimExit` (U34) |
| `boards/` | JSON board definitions (multi-source: `amaranth-boards/`, `litex-boards/`, `digilent-xdc/`, `custom/`) |
| `boards/schema/board.schema.json` | JSON Schema for board definition validation |
| `scripts/sync_amaranth_boards.py` | Syncs board definitions from amaranth-boards GitHub repo |
| `scripts/amaranth_parser.py` | Mock-exec parser: amaranth `.py` board files → `BoardDef` (used by `sync_amaranth_boards.py`); emits framework-derived `port_conventions.amaranth` (U32) |
| `scripts/sync_litex_boards.py` | Syncs board definitions from litex-boards GitHub repo |
| `scripts/litex_parser.py` | Mock-exec parser: litex `_io` platform files → board dicts (used by `sync_litex_boards.py`); emits framework-derived `port_conventions.litex` (U32) |
| `scripts/framework_conventions.py` | Source-agnostic builder shared by the litex & amaranth parsers: groups led/switch/button resources into `port_conventions` banks (vector or `names[]`), picks the primary LED group, applies polarity, and stamps `naming: "framework-derived"` (U32) |
| `scripts/sync_digilent_xdc.py` | Syncs board definitions from Digilent master XDC files (with port_conventions) |
| `scripts/digilent_parser.py` | XDC regex parser → board dicts + `port_conventions` (used by `sync_digilent_xdc.py`) |
| `scripts/sync_common.py` | Shared sync scaffolding (download, ref-resolve, naming, schema-validated JSON/metadata output) for all three `sync_*.py`; merges `port_conventions` per sub-key so hand-authored / registry blocks survive a re-sync (A1); re-stamps cited LED colors from `docs/led_color_sources/` on every write so a re-sync can't drop them (U36) |
| `scripts/led_metadata.py` | Shared LED-color helpers for the sync pipeline: `color_from_name` (LED-name heuristic, e.g. `led_r`→red, used by all three parsers) + the cited color registry loader/applier (`load_color_registry` / `apply_registry_colors` / `colorize_content`); registry (cited) outranks the name heuristic (U36) |
| `scripts/check_board_drift.py` | Board-data drift tripwire (U38, CI job "Board-data drift"): re-syncs every generated `boards/` source **in place at its recorded pin** (`_sync_metadata.json` `source_commit`; in place because a fresh-dir re-sync drops canonical conventions — the A1 trap) and requires zero git diff (the carry-forward makes a true no-op re-sync byte-identical), then chains `sync_port_conventions --check` + `sync_led_colors --check`. Needs `GITHUB_TOKEN` for pin resolution (unauthenticated API rate limit reads as false drift; unpinnable branch refs skip loudly) |
| `scripts/sync_led_colors.py` | Stamps `leds[].color` from the cited color registry (`docs/led_color_sources/`) onto board JSONs in place, no network — offline companion to the color stamping `sync_common.write_outputs` does during a full re-sync; canonical boards re-serialize, hand-authored `custom/` boards keep their one-object-per-line layout; `--check` reports drift (U36) |
| `docs/led_color_sources/*.toml` | Cited LED-color registry: per board, per LED bank, a schema color + a **fetched-source** citation (verify-or-omit); mirrors `docs/port_convention_sources/`. For colors not encoded in the LED name (e.g. Terasic `LEDR`=red / `LEDG`=green) (U36) |
| `sim/sim_testbench.py` | Headless cocotb testbench (no pygame): drives the sim loop and streams led/seg state + receives sw/btn/speed/clk/pause/stop over `sim_link` (U34) |
| `sim/sim_wrapper_template.vhd` | Unified VHDL wrapper template; seg port/generic spliced in by `_generate_wrapper()` when needed, plus the U9 duty integrator in Full measurement mode |
| `src/fpga_sim/sim_duty.py` | Duty-cycle math shared by the headless child and its tests: unpacks the wrapper's per-channel on-time accumulators and differences two snapshots into an exact window duty (`DutyTracker`); pygame- and cocotb-free (U9) |
| `sim/duty/*.vhd.frag` | Swappable duty-integrator splice fragments, one file per splice point per algorithm (`fix_ns_1p` default, `fix_ns_pc`); selected by `FPGA_SIM_DUTY_ALGO` (U9) |
| `sim/duty_probe.vhd` | Test fixture with exactly-known duty cycles (stuck-off/stuck-on/25%/50%/switch-driven) that `sim/test_duty.py` measures against; parked under `sim/` so the picker never lists it (U9) |
| `sim/test_duty.py` | Headless cocotb duty-engine tests: measured duty vs. `duty_probe`'s ground truth, mid-run gate flips, and the >2.147 s INTEGER-overflow probe |
| `src/fpga_sim/sim_session_log.py` | Writes per-session JSON summaries to ~/.fpga_simulator/sessions/ |
| `hdl/blinky.vhd` | Example VHDL design (use as template for the expected port interface) |
| `hdl/native/` | Board-native reference designs (a board's own port names + fixed widths, no `NUM_*`): Terasic `de10_standard.vhd`, `de0.vhd`, `de25_standard.vhd`; litex `arty_litex.vhd` (LiteX names `clk100`/`user_led`/`user_sw`/`user_btn`, U32); `arty_rgb.vhd` (Arty A7-100 native RGB channel scalars `led0_r`..`led3_b` via the `leds_rgb` bank, U38 — color wheel + `btn(0)` lamp test). Each matches via a board's `port_conventions` and is not in the file picker (U21) |
| `tests/` | pytest integration test suite |
| `sim/test_blinky.py` | Headless cocotb tests for the blinky design |
| `hdl/rgb_rainbow.vhd` | RGB LED demo (U37): per-channel PWM color mixing on the `NUM_RGB_LEDS` contract; switch-selected modes (rotate / static hue / cube scan / white breathe); all site math loops inside one process — GHDL-mcode does not re-elaborate generic-dependent *generate* structure for `-r`-time overrides |
| `sim/test_rgb.py` | Headless cocotb duty tests for `rgb_rainbow`, run against the generated `sim_wrapper` (never a bare toplevel — the mcode generate/override trap above) via `tests/test_rgb_design.py` |
| `sim/test_7seg.py` | Headless cocotb tests for the counter_7seg design |
| `sim/test_cpu_walking.py` | Shared headless cocotb behavioral suite run by the six walking-style embedded-core designs (6502 + Z80) |
| `sim/test_cpu_hello.py` | Headless cocotb test for the `mx65_hello_7seg` on-ramp design (static: one LED + one digit, never changes) |
| `sim/test_cpu_dice.py` | Headless cocotb test for the `mx65_dice_7seg` peripheral-extension design (LFSR-driven die roll on `btn(0)`) |
| `sim/test_cpu_wide_led.py` | Headless cocotb regression for #309: on a >16-LED board (27 = DE2-115) the walker bounces within the 16-bit LED register instead of going dark — config `$E004` reports `minimum(NUM_LEDS, 16)` |
| `hdl/stopwatch_7seg.vhd` | Hand-written interactive stopwatch: `btn(0)` start/stop, `btn(1)` reset, switch speed; the RTL half of the "same behavior, hardware vs software" teaching pair with the embedded-core designs |
| `sim/test_stopwatch.py` | Headless cocotb test for `stopwatch_7seg.vhd` (start/stop/reset behavior) |
| `hdl/mx65_walking_counter_7seg.vhd` | **Generated** single-file 6502 embedded-core demo (vendored mx65 + ROM/RAM/IO/top); Z80 (T80) siblings are `hdl/t80_*.vhd`; `hdl/mx65_hello_7seg.vhd` is the ~20-line newcomer on-ramp; `hdl/mx65_dice_7seg.vhd` extends `cpu_io` with an LFSR peripheral and has an independently-sized ROM/RAM map; see `docs/embedded_core_system_guide.md` |
| `scripts/gen_embedded_core.py` | Generator: emits a single-file embedded-core system from a CPU plugin + `systems/*.toml` spec + firmware `.bin`; `--cpu`/`--rom`/`--out` are inferred from `--system` (explicit flags override) |
| `scripts/regen_embedded_cores.py` | One-command regen loop over every `systems/*.toml`: check (default), `--write` (regenerate drifted/missing files), `--assemble` (reassemble firmware with its pinned dev-time toolchain and report drift; never writes `.bin`s) |
| `scripts/embedded_core/` | Generator package: `cpu_plugin`, `system_spec`, `emitter`, `templates/` (`*.vhd.tmpl` + `templates/fragments/*.vhd.frag` for multi-line VHDL bodies), `adapters/` (per-core bus adapters), vendored `cores/` (mx65, t80), `rom_to_vhdl.py` |
| `systems/` | TOML system specs consumed by the generator (e.g. `mx65_walking_counter_7seg.toml`) |
| `firmware/` | CPU firmware: 6502 `.s` (ca65/ld65) + Z80 `.asm` (z80asm) sources + assembled `.bin`, embedded verbatim as the ROM constant |
| `scripts/capture_waveform.py` | Simulates `mx65_hello_7seg` against an inline testbench and renders `docs/assets/mx65_hello_waveform.png` (+ `.gtkw`) — an annotated GTKWave-idiom waveform for the guide's debugging section, with all five callouts located programmatically from the parsed VCD |
| `docs/install.md` | Full install reference: GHDL/NVC per-OS matrix (incl. from-source, AUR/Gentoo/FreeBSD), uv setup, Windows run notes + PATH/DLL/MSYS2 troubleshooting, pygame-ce note (absorbed from README) |
| `docs/user_guide.md` | User-facing runtime reference: the four launcher screens, in-sim controls, stats panel, board-native runs (info tag / active-low note / session-log fields), and session/preferences (persistence, recent files, settings, themes, waveform capture + env vars, session logs) |
| `docs/architecture.md` | Architecture reference: single-window process model (U34), project tree, board loading, pygame UI, simulation pipeline + backends, "How board-native works" internals, and contributor notes (absorbed from README's "How It Works" + CONTRIBUTING's "Architecture overview") |

### Data Flow

1. `src/fpga_sim/board_loader.py` reads JSON board definitions from `boards/` subdirectories (each subdirectory is a "source": `amaranth-boards/`, `litex-boards/`, `digilent-xdc/`, `custom/`, etc.) and constructs `BoardDef` objects. The offline mock-exec pipeline for parsing upstream amaranth `.py` board files lives in `scripts/amaranth_parser.py` (used by `scripts/sync_amaranth_boards.py`); the litex and digilent parsers live in `scripts/litex_parser.py` and `scripts/digilent_parser.py` (self-contained, no `fpga_sim` dependency).

2. `src/fpga_sim/controller.py` (`ScreenController`, constructed by `__main__.main()`) drives four sequential screens: `BoardSelector` → `FPGABoard` (preview) → `VHDLFilePicker` → simulation start.

3. When simulation starts, `ScreenController.on_simulate()` (the launcher window stays open) calls `start_simulation()` in `src/fpga_sim/sim_bridge.py`, which returns a `SimChild` handle, then renders a `SimulationScreen` in the same window and calls `finish_waveform()` when it returns.

4. `sim_bridge.py` builds a platform-aware environment (PATH, LD_LIBRARY_PATH/PYTHONHOME, VPI paths) and spawns a **headless** `ghdl -r ... --vpi=cocotbvpi_ghdl.so` child (no display). The board JSON rides in `FPGA_SIM_BOARD_JSON`; the IPC link port + authkey ride in `FPGA_SIM_LINK_PORT` / `FPGA_SIM_LINK_KEY`. Both `src/` and `sim/` are on `PYTHONPATH` so the child can import `fpga_sim` and find `sim_testbench`.

5. `sim/sim_testbench.py` is loaded by cocotb inside the child (pygame-free). It deserializes the `BoardDef`, connects back to the host over `sim_link`, and runs a cooperative loop: `await Timer(sim_step_ns, unit="ns")` advances simulation by a configurable step, then it reads `dut.led`/`dut.seg`, applies inbound `sw/btn/speed/clk/pause` messages, and streams throttled `state` messages up to the `SimulationScreen`, which updates the board and handles pygame events.

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

#### RGB LED boards (optional `NUM_RGB_LEDS` generic)

On boards with 3-pin RGB LEDs the `led` vector carries **three channels per RGB LED**: mono LEDs occupy the low bits (JSON order), RGB channels fill the top, `(r, g, b)` per site — so `NUM_LEDS` counts *channels* (`BoardDef.num_led_channels`), e.g. Arty A7 = 4 mono + 3×4 = 16 (U37). To aim at them, additionally declare `NUM_RGB_LEDS : natural := 0` (must be `natural` — boards without RGB LEDs pass 0; the checker rejects `positive`); the simulator sets it at launch whenever the design declares it. Layout: `MONO = NUM_LEDS - 3*NUM_RGB_LEDS`; `led(MONO + 3*i + 0/1/2)` = site i red/green/blue. A design that omits the generic keeps working everywhere — RGB channels are then anonymous `led` bits. Guard site math with `for i in 0 to NUM_RGB_LEDS - 1 generate`. `is_rgb` = `name == "rgb_led" and len(pins) == 3` (1-pin = serial addressable impostor, 4-pin = RGBW — both stay mono bits).

#### Embedded CPU systems (single-file soft-core designs)

A design can instead be a **single self-contained file** that embeds a soft CPU core (the vendored mx65 6502 or T80 Z80) + ROM + RAM + IO (memory-mapped, or Z80 port-mapped) + a top satisfying the same `clk/sw/btn/led[/seg]` contract above. These are **generated** by `scripts/gen_embedded_core.py` from a vendored core + a `systems/*.toml` spec + an assembled firmware `.bin`; the firmware reads the board's resource counts from IO config registers, so one design fits any board (proven across 2/4/6-digit boards). Two spec axes select optional features — `irq_mode` (none/simple/vectored interrupts) and `io_transport` (memory/port) — each realized by a per-core bus adapter under `scripts/embedded_core/adapters/`. They add a generation-time **`PRESCALER_BITS`** generic — a free-running tick the firmware polls to decouple the visible rate from raw CPU speed; the wrapper never overrides it, so it keeps its default (`--prescaler-bits` on the generator overrides that default at generation time, e.g. for a temporary faster-stepping capture build). The generated file also embeds the firmware assembly source verbatim as a `--` comment block above the ROM constant, so the single file shows the program it runs. The committed `hdl/{mx65,t80}_*.vhd` designs are the generator's output — **regenerate them** (and the firmware `.bin`) rather than hand-editing. See `docs/embedded_core_system_guide.md`.

#### Board-native designs (a board's own port names)

A design can instead be written to a **board's own port names and fixed widths** rather than the generic contract — e.g. a Terasic design using `CLOCK_50`, `KEY(3 downto 0)`, `LEDR(9 downto 0)`, `SW(9 downto 0)`, and `HEX0`-`HEX5`, with **no `NUM_*` generics**. When the toplevel's ports don't match the generic contract, `check_vhdl_contract()` (`sim_bridge.py`) matches them against the *selected board's* `port_conventions` (the `terasic` block, etc.); on a full match the file is accepted and a native `sim_wrapper` adapts the native ports to the simulator's `clk/sw/btn/led/seg` boundary — inverting active-low LEDs and buttons, and packing an `individual`-style 7-seg per digit — so the cocotb testbench and run mechanics stay untouched. A design need only declare the roles the board's convention names — **clk + LEDs** at minimum, where either the mono `leds` bank *or* a `leds_rgb` channel bank satisfies the LED floor (U38 — RGB-only boards like Cora Z7/Eclypse Z7 are natively targetable through their RGB bank alone), with switches/buttons matched only when the convention declares them (**U21 partial-interface support**, generalizing the "7-seg only when the board has a display" rule) — so a switch-less or button-less board runs unmodified: the wrapper ties off an absent input bank (its `sw`/`btn` boundary port kept for cocotb but floored to a one-bit dummy and left unconnected, mirroring the generic path's `NUM_* = max(1, count)`) and leaves absent outputs dark; a design declaring a *default-less input* the convention lacks is a near-miss — but an unmapped input that **carries a default** (e.g. `uart_rx : in std_logic := '1'`) is accepted, matching the generic contract, and an unmapped *output* is left `open` (as the DE0 example's `HEXn_DP` pins are). A single-LED board may declare its one LED as the natural scalar `led : out std_logic` (matched to a width-1 bank) rather than a `(0 downto 0)` vector. **The simulator always models the selected board, and the board's convention supplies polarity.** Loading a file written for a *different* board is user error and resolves safely: a differing port name (e.g. the clock is `CLOCK_50` but the selected board's is `CLOCK0_50`) makes it a *near-miss* — rejected with a message naming the mismatch, never silently coerced or polarity-flipped. Only the `individual` 7-seg style is adapted (scan / serial / per-segment-scalars stay generic → U22). **Native RGB (U38, Digilent XDC only):** a convention's `leds_rgb` bank lists the real XDC channel scalars in (r,g,b) order per site (`led0_r`..`led3_b`, or the original Nexys 4's `RGB1_Red` style); a design declaring the whole bank gets each scalar packed onto boundary channel `led(MONO + 3i + c)` with cited per-board polarity (RM tri-color prose: transistor-inverted active-high everywhere except the common-anode Cmod A7/S7 — active-low; Sword omitted, no RM). Like `leds_green` the bank is all-or-nothing and never required; the Nexys-family reset button is deliberately outside the buttons bank (active-low vs. the directionals' active-high — declare it with a default). Board-native designs get **no `COUNTER_BITS` override** (that generic belongs to the generic contract), so a design that derives its visible rate from the top bits of a full 50 MHz divider looks frozen at the simulator's sub-real-time speed — the `hdl/native/*.vhd` reference examples tap *mid* counter bits so motion stays visible. Those examples each match only their own board and are deliberately **not** surfaced in the file picker. See `docs/u21_board_native_vhdl_plan.md`.

**Framework-derived conventions (U32).** The litex and amaranth sync parsers auto-derive a `port_conventions.{litex,amaranth}` block for the bulk of their boards (230/251; floor: a clock + LEDs — RGB-only boards, whose multi-pin `rgb_led` bits have no declarable scalar port, fail it by design, as does a mixed-polarity bank) via the shared `scripts/framework_conventions.py`, advertising each framework's *own* port names — litex `clk100`/`user_led`/`user_sw`/`user_btn`, amaranth `clk100`/`led`/`switch`/`button` — so a design hand-written to those names simulates unmodified (see `hdl/native/arty_litex.vhd`). These are stamped `naming: "framework-derived"`: they use *generic* names shared across many boards (unlike distinctive vendor-canonical names), so they're lower-confidence and the matcher tries canonical/hand-authored blocks **first** (`_convention_precedence` in `sim_bridge.py`) — authoritative vendor data added for a board later (its own sub-key, coexisting via the A1 per-sub-key merge) wins. When a board carries both tiers, the framework block's LED/switch/button polarity is reconciled to the canonical block's (same role + width) via `reconcile_framework_polarity` (`scripts/framework_conventions.py`) at sync time — the cited physical truth wins, so the two never disagree (e.g. DE0-CV LEDs active-high, Sipeed Tang Nano 9K active-low). Because a framework bank can be **narrower than the board's resource count** — a litex board's `rgb_led` inflate `NUM_LEDS` past the `user_led` bank, or a board has more buttons than the primary bank — the native wrapper feeds inputs the low boundary bits and **zero-extends** the LED bank onto the board `led` boundary (`resize(unsigned(led_uut), NUM_LEDS)`; uncovered board LEDs stay dark); the wrapper's default generics mirror `build_generics` (board counts) so `analyze_vhdl` validates the same widths the run passes. To add **authoritative** conventions for a board later, add a canonical `port_conventions.<vendor>` sub-key **in place** on the existing board JSON (or via the registry / `overlay.toml`) — the A1 guard preserves it across re-syncs; do **not** fork the board into `boards/custom/` (that leaves an un-removable, auto-regenerated duplicate). See `docs/u21_board_native_vhdl_plan.md`.

### Platform Notes

- GHDL must be installed system-wide (`ghdl` on PATH)
- On Linux, `LD_LIBRARY_PATH` is used for cocotb and GHDL shared libraries
- On Windows, all DLL directories must be on PATH; Windows Store Python is unsupported — use a standalone Python installed via `uv`
- `find_libpython` is used to locate the Python shared library for cocotb VPI

### Board Definition Sources

Board definitions live in `boards/` as JSON files, organized by source:

- `boards/amaranth-boards/` — auto-generated from [amaranth-boards](https://github.com/amaranth-lang/amaranth-boards) via `scripts/sync_amaranth_boards.py` (with framework-derived `port_conventions.amaranth`, U32)
- `boards/litex-boards/` — auto-generated from [litex-boards](https://github.com/litex-hub/litex-boards) via `scripts/sync_litex_boards.py` (with framework-derived `port_conventions.litex`, U32)
- `boards/digilent-xdc/` — auto-generated from [Digilent XDC](https://github.com/Digilent/digilent-xdc) via `scripts/sync_digilent_xdc.py` (includes `port_conventions`)
- `boards/custom/` — manually maintained boards (e.g., DE10-Standard)
- Additional source directories can be added freely; the loader discovers them automatically

To add a new board, create a JSON file in `boards/custom/` following the schema at `boards/schema/board.schema.json`. The JSON format includes an optional `port_conventions` section — consumed by board-native VHDL mode (U21; see "Board-native designs" above) — and an optional `peripherals` section (not yet consumed; P5).

**LED colors (U36).** Each LED (`leds[]`) carries an optional `color` (a named color or `#RRGGBB`; absent → the renderer's theme default). It is populated two ways, both source-agnostic and re-applied on every sync so a re-sync can't drop it: (1) a **name heuristic** (`scripts/led_metadata.color_from_name`, e.g. `led_r`→red) the parsers apply, and (2) a **cited color registry** (`docs/led_color_sources/*.toml`) for colors the name doesn't encode — every entry quotes a fetched vendor source (verify-or-omit), and a cited color outranks the name heuristic. Never hand-edit a color into a generated board JSON; add it to the registry and run `scripts/sync_led_colors.py` (which also stamps hand-authored `boards/custom/` boards). See the file table above.

### Amaranth Parser Mock Namespace (sync script only)

`scripts/amaranth_parser._make_namespace()` provides mock classes (`Resource`, `Subsignal`, `Pins`, `PinsN`, `DiffPairs`, `Attrs`, `Clock`, `Connector`) and stubs for interfaces/memory (UART, SPI, I2C, SDRAM, etc.) that are not simulated. These are used only by `scripts/sync_amaranth_boards.py` to parse upstream amaranth-boards Python files into JSON. The parser imports the `BoardDef` / `ComponentInfo` / `SevenSegDef` data classes from `fpga_sim.board_loader` (one-way; the runtime loader never imports the parser). Only resources whose names contain `led`, `button`, `btn`, `switch`, or `sw` are extracted; everything else is stubbed out.
