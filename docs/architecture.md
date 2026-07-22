# Architecture

How the simulator is put together: the single-window process model, the project layout,
board loading, the pygame UI, the simulation pipeline, the simulator backends, and
how board-native VHDL is recognized and adapted. This is the map for contributors
and the curious. For using the app see [docs/user_guide.md](user_guide.md); for
writing designs see [docs/writing_designs.md](writing_designs.md). Back to the
[README](../README.md).

## Single-window process model

The simulator uses **one window for the whole session**, split across **two OS
processes** (U34):

- a **UI host** process (pygame) that owns the one window and drives the board
  selector → preview → VHDL picker → simulation-screen flow, and
- a **headless simulation child** (GHDL or NVC + cocotb) that runs the chosen
  design with no display of its own.

The window is never created or destroyed between launcher start and app exit: when
a simulation starts, the launcher keeps rendering and the child streams signal
state back over an IPC link (`sim_link`). The board definition crosses to the child
as JSON in an environment variable; live signal state and input/control messages
cross over the link (see [Simulation pipeline](#simulation-pipeline)). The child
must never import pygame — its only `fpga_sim` imports are `board_loader`,
`sim_link`, and `sim_metrics`.

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
  sim_testbench.py         headless cocotb testbench; main sim loop, streams state over sim_link (no pygame)
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
4. **`FPGABoard`** (simulation mode, driven by `ui/simulation_screen.py`) — same
   rendering as preview, but fed by the headless simulator over `sim_link`.

In simulation mode, the launcher window is the user's interface. Mouse events on
switches and buttons trigger callbacks in `SimulationScreen` that send an `input`
message over `sim_link`; the headless child applies it to `dut.sw` / `dut.btn`. LED
state flows the other way: the child reads `dut.led` after each `await Timer(...)` and
streams a `state` message, which the screen applies to each LED once per frame.

**Board components and hover overlays.** LEDs, switches, and buttons share a
`UIComponent` base (`ui/components.py`) and are registered in one
`FPGABoard.components` list used for hover hit-testing. The hover tooltip
(`ui/tooltip.py`) is drawn at the *end* of `FPGABoard._draw()`; because both the
preview loop and `SimulationScreen` drive that same `_draw`, any board-area overlay
added there appears in both — no simulation-screen change. Per-component metadata to
surface goes in `tooltip_rows()`.

## Simulation pipeline

When the user clicks "Start Simulation" and picks a VHDL file, the launcher window
stays open and the child runs headless:

```text
controller.py + ui/simulation_screen.py    sim_bridge.py           headless Simulator + cocotb
────────────────────────────────────────   ─────────────           ───────────────────────────
1. on_simulate()  (window stays open)
2. start_simulation() ───────────────────→  3. Analyze VHDL (GHDL: elaborate;
                                               NVC: elaborate with generics next)
                                            4. Build env (PATH, PYTHONHOME, VPI/VHPI
                                               paths, cocotb vars, PYTHONPATH src/+sim/,
                                               FPGA_SIM_LINK_PORT / _KEY, board JSON)
                                            5. Popen headless simulator -r ──→ 6. load VPI/VHPI, cocotb init
                                               (returns a SimChild handle)     7. import sim/sim_testbench.py

7. SimulationScreen.run():                  sim/sim_testbench.py (pygame-free)
   ──────────────────────                   ─────────────────────────────────
   render board + panel @ 60 fps            8.  Deserialize BoardDef; connect to host
   drain link → set_led / set_seg           9.  Main loop:
   clicks    → "input" messages ──────────────→  apply sw / btn / speed / clk / pause
   slider/clk → "speed" / "clk" ─────────────→   await Timer(step_ns)  ← advance sim
   ◄──────── "state" (led/seg/…) ──────────────  read dut.led / dut.seg
   [Stop]/ESC/X → return a SimExit          10. send throttled "state" up; heartbeat
8. finish_waveform(child)                   11. on stop/bye: close link, exit
```

The simulator loop runs **in a separate headless process**; the pygame UI runs in the
launcher and never blocks on the child (all link reads are `poll(0)` drains, child
startup is awaited with a spinner + watchdog, shutdown is stop-message → bounded wait
→ terminate). Each child frame, `await Timer(step_ns, unit="ns")` advances the
simulation by a configurable number of nanoseconds (the speed slider), then the child
reads outputs and streams a throttled `state` message to the host, which applies it to
the board. Input, speed, clock, and pause changes travel the other way as messages.

**VHDL-side clock.** The clock is generated entirely inside the generated
`sim_wrapper` entity (`sim/sim_wrapper_template.vhd`), not by a Python coroutine. This
eliminates per-half-period GPI callbacks — the only GPI round-trips per frame are the
two endpoints of the single `await Timer(...)` call. The wrapper exposes a
`clk_half_ns` port; when the panel's **[-]/[+]** buttons change the virtual clock, the
host sends a `clk` message and the child writes the new half-period, which the VHDL
process picks up within one half-cycle.

**Duty-cycle measurement (U9).** A PWM-driven LED has no meaningful instantaneous
value — sampling `dut.led` once per frame reports whichever side of the pulse the
sample landed on, which is why PWM designs looked broken. Duty is therefore
**measured, never inferred**: static analysis of the design is impossible in
principle (the embedded-core designs compute their duty from firmware bytes at run
time), and any Python-side sampling or edge callback either aliases or reintroduces
the per-event GPI round-trips the VHDL-side clock exists to avoid.

Instead the generated wrapper integrates on-time in VHDL. For every channel of
`led` (and `seg` — segments are LEDs) it accumulates the nanoseconds spent high,
exporting two vectors: `led_acc` (on-time over `[0, led_tch]`) and `led_tch`
(when the channel last changed). The interval still in progress is deliberately
*not* in `acc` — it is folded in only when it ends, which is what keeps the
integrator free of cross-channel state. The child reads both at send cadence,
adds the in-progress tail (`T_on = acc + (t - tch)` when the channel is high —
exactly the on-time over `[0, t]` by construction), and differences two snapshots
into the window's exact duty, which rides along as `led_duty` / `seg_duty`. See
`fpga_sim/sim_duty.py` for the math.

**Duty → pixels (U9b/U37/U38).** On the launcher side `SimulationScreen` smooths
the incoming duties with a wall-clock persistence-of-vision EMA (τ = 0.1 s; the
first sample snaps) — display smoothing only, the measurements stay exact — then
routes them in the **channel domain**: `BoardDef.led_channels` maps each boundary
bit to its component, so a mono LED gets `set_led_level` while an RGB LED's three
channels land in its `RGBLED` widget via `set_channel` (U37). Realistic rendering
is perceptual — `brightness = duty^(1/2.2)`, mixed per channel for RGB pucks so
`(1,1,1)` washes to white — and the U38 **debug duty-bar view** (a global render
mode in `ui/components.py`, toggled by the in-sim `D` key / Settings, persisted
as `debug_view`) swaps it for *linear-length* bars with % readouts, because
length reads to a percent where luminance cannot.

**Pause semantics.** While paused the child's step shrinks to ~1 ns, so a
between-sends window would span less than a clock period and every duty would
collapse to 0%/100%. Instead the child takes **one final measurement at the
instant pause lands** and then holds it — the frozen numbers describe the moment
of pause — while `state` messages keep flowing with the live (frozen) bits. On
the launcher, a held channel that is exactly 0/1 follows those live bits
(`_pause_follow_binary`), so a combinational switch→LED still responds under
pause; a mid-PWM channel holds its exact duty. The tracker is not advanced
further while paused, so the first post-resume window simply spans the pause and
stays exact.

The integrator is a **swappable splice fragment** (`sim/duty/<algo>.*.vhd.frag`),
because its cost is entirely a function of how often it is woken, and that is a
property of the design. `fix_ns_1p` (the default) uses one process per monitored
vector, waking once per *instant* at which anything changes; `fix_ns_pc` uses one
process per channel, waking once per *channel transition*. The ratio between
those two counts is exactly how correlated the channels are — a shared PWM
compare drives every LED in lockstep, so one wake covers them all.
`FPGA_SIM_DUTY_ALGO` selects between them. Measured overhead is ~0% on designs
whose LEDs change slowly and ~2% on a design PWM-ing 8 LEDs at 390 kHz; a channel
that toggles *every clock* (a fast display digit) is the pathological case and
costs multiples, which is why measurement is also a per-run policy:
`FPGA_SIM_DUTY` selects `full` (default — integrator spliced), `color` or `off`
(no integrator at all; the generated wrapper is byte-identical to the pre-U9 one).

**Sim → launcher signalling.** The child streams `state` messages (led / seg / sim
progress) and a final `bye` over the link; `SimulationScreen.run()` returns a `SimExit`
describing *why the run ended* — **[Back to Boards]** / **[Change VHDL]** / **[Reload
VHDL]** (toolbar), `STOPPED` (ESC / **[■ Stop]**), or `QUIT` (window X → quit the app).
`ScreenController.on_simulate()` routes it (RELOAD re-validates and relaunches in
place). A nonzero child exit *without* a received `bye` is treated as a crash — the
simulators own their exit codes, which are unreliable on a clean stop, so failure is
never inferred from the return code alone. To add a sim-screen action, add a `SimExit`
member (in `ui/results.py`), a toolbar button, and a routing arm.

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
`start_simulation()` then re-elaborates with the real board generics before running.
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
keep the board and panel in sync (`SimulationScreen` does this at the top of every
frame).

**Session-state ownership.** `~/.fpga_simulator/session.json` is loaded at startup;
every write is a **merge** (read-modify-write), and keys have owners — never write a
key another writer owns. The **launcher** owns the board / VHDL / simulator / selector
prefs / window size / `recent[]`; the **Settings dialog** owns `theme` and the
waveform-capture settings; **`SimulationScreen`** owns `speed_factor` — it seeds the
headless child's pacing via `FPGA_SIM_SPEED` and writes the final slider value back to
the session at screen exit (`update_session`); the child never touches the session
file. It is best-effort — load/save failures are
silently ignored. See [docs/user_guide.md](user_guide.md) for the user-facing view of
what persists.
