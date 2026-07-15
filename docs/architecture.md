# Architecture

How the simulator is put together: the two-phase process model, the project layout,
board loading, the pygame UI, the simulation pipeline, the simulator backends, and
how board-native VHDL is recognized and adapted. This is the map for contributors
and the curious. For using the app see [docs/user_guide.md](user_guide.md); for
writing designs see [docs/writing_designs.md](writing_designs.md). Back to the
[README](../README.md).

## Two-phase process model

The simulator runs in two distinct phases in **two separate OS processes**:

- a **launcher** process (pygame) that drives the board selector → preview → VHDL
  picker flow, and
- a **simulation** subprocess (GHDL or NVC + cocotb) that runs the chosen design.

The launcher calls `pygame.quit()` before spawning the subprocess; the subprocess
calls `pygame.init()` fresh. Never assume pygame state persists across that
boundary. The board definition crosses it as JSON in an environment variable.

## Project structure

```text
src/fpga_sim/              Installable Python package (src layout)
  __main__.py              Entry point — arg parsing, window setup/restore, --benchmark CLI, --sim flag
  controller.py            ScreenController + SessionState — drives the launcher screen flow
  board_loader.py          Loads board definitions from JSON into BoardDef objects
  sim_bridge.py            GHDL/NVC analysis + cocotb simulation launcher; _SimBackend ABC + _GHDLBackend/_NVCBackend
  sim_session_log.py       Writes per-session JSON summaries to ~/.fpga_simulator/sessions/
  sim_metrics.py           Optional per-frame CSV metrics (set FPGA_SIM_METRICS=<path> to enable)
  session_config.py        Session persistence, merge-on-write (~/.fpga_simulator/session.json)
  generate_board_images.py Renders static board previews (used for documentation/thumbnails)
  ui/                      pygame UI subpackage
    constants.py           Base neutral colors, get_font cache, _ui_scale helper
    theme.py               Theme dataclass + THEME instance — the semantic color roles
    components.py          UIComponent base + FPGAChip, LED, Switch, Button — low-level board components
    board_selector.py      Board picker screen
    board_display.py       Board preview + simulation screen (FPGABoard class)
    sim_panel.py           Stats strip rendered during simulation (SimPanel class)
    sim_toolbar.py         In-simulation navigation toolbar (SimToolbar class)
    vhdl_picker.py         VHDL file browser screen
    error_dialog.py        Error dialog overlay
    help_dialog.py         Help overlay (F1 / ? / the (?) button)
    settings_dialog.py     Settings overlay (gear button): theme, sim speed, waveform, recent files
    tooltip.py             Hover tooltip — component net name / pin / direction
    spinner.py             Analysis busy-spinner overlay (run_with_spinner)
    results.py             ScreenResult / DialogResult enums
    widgets/               Shared button rendering (ButtonStyle + draw_button)
sim/                       Simulation infrastructure (not part of the installed package)
  sim_testbench.py         cocotb test that bridges simulator signals ↔ pygame UI; main sim loop
  sim_wrapper_template.vhd VHDL wrapper template — seg port/generic spliced in when needed
  test_blinky.py           Headless cocotb tests for the blinky design
  test_7seg.py             Headless cocotb tests for the counter_7seg design
hdl/                       Example VHDL designs (see docs/writing_designs.md for the catalog)
systems/                   TOML system specs consumed by the embedded-core generator
firmware/                  CPU firmware: 6502 .s (ca65/ld65) + Z80 .asm (z80asm) sources + assembled .bin
scripts/
  sync_amaranth_boards.py  Syncs board definitions from amaranth-boards
  amaranth_parser.py       Mock-exec parser used by sync_amaranth_boards.py
  sync_litex_boards.py     Syncs board definitions from litex-boards
  litex_parser.py          Mock-exec parser used by sync_litex_boards.py
  sync_digilent_xdc.py     Syncs board definitions from Digilent XDC files (with port_conventions)
  digilent_parser.py       XDC regex parser used by sync_digilent_xdc.py
  sync_common.py           Shared scaffolding (download/naming/output) for the sync scripts
  framework_conventions.py Shared builder for framework-derived port_conventions (litex + amaranth)
  gen_embedded_core.py     Generates one embedded-core system from a CPU plugin + system spec + firmware .bin
  regen_embedded_cores.py  One-command regen/check loop over every systems/*.toml
  embedded_core/           Generator package: cpu_plugin, system_spec, emitter, templates/, adapters/, vendored cores/
tests/                     pytest integration suite (board loading, serialization, GHDL, NVC, UI, panel)
boards/
  amaranth-boards/         Board definitions synced from amaranth-lang/amaranth-boards
  litex-boards/            Board definitions synced from litex-hub/litex-boards
  digilent-xdc/            Board definitions synced from Digilent master XDC files (with port_conventions)
  custom/                  Manually maintained boards (e.g. DE10-Standard)
  schema/                  JSON Schema for board definition validation
pyproject.toml             Project metadata and dependencies
```

## Board loading (`fpga_sim/board_loader.py`)

Board definitions are stored as JSON files in `boards/`, organized by source:

- **`boards/amaranth-boards/`** — auto-synced from
  [amaranth-boards](https://github.com/amaranth-lang/amaranth-boards) via
  `scripts/sync_amaranth_boards.py` (~79 boards)
- **`boards/litex-boards/`** — auto-synced from
  [litex-boards](https://github.com/litex-hub/litex-boards) via
  `scripts/sync_litex_boards.py` (~167 boards across Xilinx, Intel, Lattice, Gowin,
  Efinix)
- **`boards/digilent-xdc/`** — auto-synced from
  [Digilent XDC](https://github.com/Digilent/digilent-xdc) via
  `scripts/sync_digilent_xdc.py` (~26 Digilent boards with `port_conventions` for
  board-native VHDL mode)
- **`boards/custom/`** — manually maintained boards (new boards go here)

Each subdirectory under `boards/` is a "source." The loader scans all sources and
returns every board — if two sources define the same board, both appear in the
selector with a source annotation. The result is a `BoardDef` object per board
containing `ComponentInfo` entries with display names (e.g. `LED0`, `BTN2`, `UP0`
for named buttons like `button_up`) and hardware metadata (pin names, connector
references, IO standard attributes), plus an optional `port_conventions` block.

To add a board, create a JSON file in `boards/custom/` following
`boards/schema/board.schema.json`. To re-sync from upstream:

```bash
uv run python scripts/sync_amaranth_boards.py  # amaranth-boards
uv run python scripts/sync_litex_boards.py     # litex-boards
uv run python scripts/sync_digilent_xdc.py     # Digilent XDC
```

Each upstream source has a dedicated parser module imported by its thin `sync_*.py`
script. `amaranth_parser.py` and `litex_parser.py` use **mock-exec** (strip imports,
inject mock `Resource`/`Pins`/`Attrs` classes into a namespace, `exec()` the board
file); `digilent_parser.py` uses section-aware **regex** over XDC text.
`sync_common.py` holds the shared download/naming/output scaffolding and merges
`port_conventions` per sub-key on re-sync, so hand-authored or canonical blocks
survive. The litex and amaranth parsers additionally emit framework-derived
conventions via the shared `framework_conventions.py` (see
[How board-native works](#how-board-native-works)).

## The pygame UI (`fpga_sim/ui/`)

The UI has four screens, each a class with a `run()` method:

1. **`BoardSelector`** — scrollable, filterable list of all discovered boards. Type
   to filter, click to select.
2. **`FPGABoard`** (preview mode) — renders the board's components on a green
   PCB-style background. An auto-layout engine arranges LEDs, buttons, and switches
   into a grid that adapts to the component count and window size (LEDs get 3× the
   vertical weight, since boards can have 64+). Components are interactive even in
   preview. A `SIM: GHDL` / `SIM: NVC` toggle cycles between installed simulators.
3. **`VHDLFilePicker`** — minimal file browser showing directories and `.vhd`/`.vhdl`
   files.
4. **`FPGABoard`** (simulation mode, inside `sim/sim_testbench.py`) — same rendering
   as preview, but driven by the simulator.

In simulation mode, pygame is the sole interface between user and simulator. Mouse
events on switches and buttons trigger callbacks that write directly to `dut.sw` /
`dut.btn` via cocotb — no queue or IPC; the write is synchronous in the event
handler. LED state flows the other way: once per frame, after `await Timer(...)` has
advanced the simulation, `dut.led.value` is read and each LED's display updated.

**Board components and hover overlays.** LEDs, switches, and buttons share a
`UIComponent` base (`ui/components.py`) and are registered in one
`FPGABoard.components` list used for hover hit-testing. The hover tooltip
(`ui/tooltip.py`) is drawn at the *end* of `FPGABoard._draw()`; because both the
preview loop and the sim subprocess drive that same `_draw`, any board-area overlay
added there appears in both — no `sim_testbench.py` change. Per-component metadata to
surface goes in `tooltip_rows()`.

## Simulation pipeline

When the user clicks "Start Simulation" and picks a VHDL file:

```text
fpga_sim/controller.py           fpga_sim/sim_bridge.py            Simulator + cocotb
──────────────────────           ──────────────────────            ──────────────────
1. Serialize BoardDef to JSON
2. Call launch_simulation() ───→ 3. Analyze VHDL
   pygame.quit()                    (GHDL: also elaborate here;
                                     NVC: elaborate with generics
                                     in the next step)
                                 4. Build env (PATH, PYTHONHOME,
                                    VPI/VHPI lib paths, cocotb vars,
                                    PYTHONPATH includes src/ + sim/)
                                 5. simulator -r --vpi/load=cocotb ─→ 6. Simulator loads VPI/VHPI lib
                                                                      7. cocotb initializes
                                                                      8. Imports sim/sim_testbench.py

                                 sim/sim_testbench.py
                                 ────────────────────
                                 9.  Deserialize BoardDef from env
                                 10. pygame.init(), create FPGABoard + SimPanel
                                 11. Write initial clk_half_ns to dut
                                     (VHDL sim_wrapper drives clock internally)
                                 12. Wire switch/button callbacks:
                                     on click → collect all states
                                     into bit vector → dut.sw.value
                                 13. Main loop:
                                     await Timer(step_ns)  ← advances simulation
                                     read dut.led.value    ← get LED outputs
                                     set_led() for each    ← update pygame LEDs
                                     read dut.seg.value    ← get seg outputs (7-seg boards)
                                     set_seg() for each    ← update pygame digits
                                     _handle_events()      ← process mouse/keyboard
                                     board._draw()         ← render board
                                     panel.draw()          ← render stats strip
                                     clock.tick(60)        ← 60fps cap
```

The key insight is that **pygame runs inside the cocotb test function**. Each frame,
`await Timer(step_ns, unit="ns")` advances the simulation by a configurable number of
nanoseconds (the speed slider), then the test reads outputs and processes events.

**VHDL-side clock.** The clock is generated entirely inside the generated
`sim_wrapper` entity (`sim/sim_wrapper_template.vhd`), not by a Python coroutine.
This eliminates per-half-period GPI callbacks — the only GPI round-trips per frame
are the two endpoints of the single `await Timer(...)` call. The wrapper exposes a
`clk_half_ns` port; when the panel's **[-]/[+]** buttons change the virtual clock,
`sim_testbench.py` writes the new half-period and the VHDL process picks it up within
one half-cycle.

**Sim → launcher signalling.** The subprocess reports *why* it ended through a
`SimExit` value written to an exit-intent sidecar file (path in
`FPGA_SIM_EXIT_INTENT_FILE`). The in-sim toolbar's **[Back to Boards]** /
**[Change VHDL]** / **[Reload VHDL]** buttons each write their `SimExit`; a plain stop
(ESC / close / **[Stop]**) writes nothing. `launch_simulation()` clears any stale file
first, then reads it back **only on a clean (exit code 0) run** — so a crash is never
mistaken for navigation — and `ScreenController.on_simulate()` routes it (RELOAD
re-validates and relaunches in place). To add a sim-screen action, add a `SimExit`
member, a toolbar button, and a routing arm — never overload the process exit code,
which the simulators own.

## Simulator backends (`fpga_sim/sim_bridge.py`)

`sim_bridge.py` defines a `_SimBackend` ABC with two private subclasses
(`_GHDLBackend`, `_NVCBackend`) that encapsulate all simulator-specific details:

| | `_GHDLBackend` | `_NVCBackend` |
|---|---|---|
| Interface | VPI (`libcocotbvpi_ghdl.so` / `.dll` on Windows) | VHPI (`libcocotbvhpi_nvc.so`) |
| Plugin flag | `--vpi=<lib>` on `-r` | `--load=<lib>` on `-r` |
| Work dir | `--workdir=PATH` | `--work=work:PATH` |
| VHDL standard | `--std=08` | `--std=2008` |
| Generics at | `-r` (run time) | `-e` (elaboration) |

> **Interface note:** GHDL supports both VPI (complete) and a partial VHPI (library
> loading and tracing only; signal read/write is not implemented). We use GHDL's
> **VPI** interface. NVC provides a comprehensive VHPI implementation and **no VPI at
> all**, so we use NVC's **VHPI**. GHDL additionally supports `--std=19` for analysis;
> the wrapper here uses `--std=08`.

Because NVC requires generics at elaboration time, `analyze_vhdl()` performs `-a`
followed by a structural `-e` (empty generics) to catch port-width mismatches early;
`launch_simulation()` then re-elaborates with the real board generics before running.
`detect_simulators()` returns the installed simulators. On **Linux**,
`_build_sim_env()` sets `LD_LIBRARY_PATH`; on **Windows**, all DLL directories go on
`PATH`, `PYTHONHOME` points at the base (non-venv) Python, and a standalone Python is
required (the Windows Store build cannot be embedded).

## How board-native works

A design usually satisfies the generic `clk/sw/btn/led[/seg]` contract with `NUM_*`
generics. It can instead use a **board's own** port names and fixed widths (Terasic
`CLOCK_50`/`SW`/`KEY`/`LEDR`/`HEX0…`, litex `clk100`/`user_led`/`user_sw`/`user_btn`,
etc.). Recognizing and adapting that is contained entirely in `sim_bridge.py` and the
board JSON — the cocotb testbench boundary never changes.

1. **Contract check.** `check_vhdl_contract()` first tries the generic contract. If
   the toplevel's ports don't match it (and the design doesn't declare the
   simulator's own sizing generics), it falls through to the convention matcher for
   the *selected* board.
2. **Convention matcher.** `match_convention()` tries each block in the board's
   `port_conventions`, **authoritative-first**: `_convention_precedence` ranks
   vendor-canonical blocks ahead of framework-derived ones, so cited vendor data wins
   when both exist for a board. Each block maps roles (clk, leds, switches, buttons,
   leds_green, seg) to native port names; a bank matches as a vector (`name` + width),
   a `names[]` literal cluster, or a width-1 scalar. The floor is **clk + LEDs**;
   switches and buttons are matched only when the convention *declares* them, so a
   switch-less or button-less board still matches. A full match yields a
   `ConventionMatch`; the closest failed attempt yields a **near-miss** message naming
   the exact mismatch (a differing clock name, an extra *input* port without a
   default). Extra *outputs* are left open rather than rejected.
3. **Native wrapper.** On a full match, a native `sim_wrapper` adapts the board's
   ports to the simulator's `clk/sw/btn/led/seg` boundary: it **inverts** active-low
   LEDs/buttons/switches (polarity comes from the convention), **zero-extends** a
   LED bank narrower than the board's LED count onto the `led` boundary
   (`resize(...)`; uncovered LEDs stay dark), packs an `individual`-style 7-seg per
   digit, and **ties off** absent input banks. The wrapper's default generics mirror
   the board's resource counts, so analysis validates the same widths the run passes.
4. **Unchanged boundary.** The cocotb testbench still drives `clk/sw/btn/led/seg`, so
   the run mechanics, stats panel, and waveform capture are untouched. Only the
   `individual` 7-seg style is adapted (scan/serial stay on the generic contract), and
   native designs get **no `COUNTER_BITS` override**.

Conventions come from two tiers: **vendor-canonical** blocks (cited from constraint
files, stamped `naming: "canonical"`) and **framework-derived** blocks that the litex
and amaranth parsers auto-build with `framework_conventions.py` (stamped
`naming: "framework-derived"`, lower confidence because their names are generic
across many boards). The canonical registry sources live under
[`docs/port_convention_sources/`](port_convention_sources/README.md); the design
rationale and history are in
[`docs/u21_board_native_vhdl_plan.md`](u21_board_native_vhdl_plan.md).

## The blinky design (`hdl/blinky.vhd`)

A small but complete design that exercises all board I/O, useful as the reference for
the generic contract:

- **Counter**: free-running N-bit counter incremented each rising edge.
- **LED logic**: `led(i) = sw(i) XOR counter(top-i) OR btn(i)` — switches XOR with
  counter bits (LEDs blink at rates set by which switches are on); buttons OR directly
  (LEDs light while held).
- **Generics**: `NUM_SWITCHES`, `NUM_BUTTONS`, `NUM_LEDS`, `COUNTER_BITS` are set by
  the simulator to match the board. `COUNTER_BITS` is chosen so the MSB toggle rate is
  clearly visible at the simulator's throughput (always slower than real time, so a
  smaller counter than real hardware would use).

See [docs/writing_designs.md](writing_designs.md) for the full contract and the
example catalog.

## Contributor notes

**SimPanel scaling.** `ui/sim_panel.py` owns the bottom stats strip. Its
`panel_height` is a property that re-evaluates `_ui_scale(w, h)` on every access —
call `board.set_height_offset(panel.panel_height)` whenever the window resizes to
keep the board and panel in sync (`sim_testbench.py` does this at the top of every
frame).

**Session-state ownership.** `~/.fpga_simulator/session.json` is loaded at startup;
every write is a **merge** (read-modify-write), and keys have owners — never write a
key another writer owns. The **launcher** owns the board / VHDL / simulator / selector
prefs / window size / `recent[]`; the **Settings dialog** owns `theme` and the
waveform-capture settings; the **sim subprocess** owns `speed_factor` (seeded via
`FPGA_SIM_SPEED`, written back at exit only when that env var is present, so
benchmarks and tests never touch the file). It is best-effort — load/save failures are
silently ignored. See [docs/user_guide.md](user_guide.md) for the user-facing view of
what persists.
