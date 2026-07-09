# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Waveform capture (U10).** The Settings dialog gains a **Waveform** row that
  cycles **off / VCD / FST**. When enabled, the simulation dumps a native
  waveform (GHDL `--vcd`/`--fst`; NVC `--wave` + `--format`) to a timestamped
  `~/.fpga_simulator/waveforms/<design>_<timestamp>.<ext>` — overridable with
  `FPGA_SIM_WAVEFORM_DIR` to keep captures in your own project tree — ready to
  open in GTKWave; successive runs accumulate so you can compare iterations. The file's path is printed when the
  run ends. Capture is a simulator run-command flag (independent of the cocotb
  interface) and is off by default, so the standard run and benchmarks are
  unaffected. Refines the reserved `waveform_enabled` session key into the
  tri-state `waveform` (#186, #187)

## [0.12.0] - 2026-07-08

### Added

- **Component hover tooltips (U3).** Hovering an LED, switch, or button for
  ~400 ms shows a small tooltip with its net name, pin(s), and direction;
  moving the cursor away dismisses it. Works in both the board preview and the
  running simulation, and follows the active theme (#172, #184)
- **In-simulation navigation toolbar (U7).** The running simulation gains three
  buttons at the bottom-left — **[Back to Boards]**, **[Change VHDL]**, and
  **[Reload VHDL]** — so it is no longer a dead end reachable only by ESC.
  **[Reload VHDL]** re-validates and re-analyzes the current file (pick up edits
  you just made in your editor) and restarts the simulation without returning to
  the launcher; **[Change VHDL]** opens the file picker; **[Back to Boards]**
  returns to the selector. The buttons follow the active theme. Pressing
  **F1** or **?** during a simulation now opens the help overlay too (#175)
- **Error messages with contextual hints (U4).** The pre-simulation contract
  check now parses the design's toplevel entity and explains violations in
  terms of the selected board — e.g. *"Port 'led' is a fixed 16 bits wide,
  but DE10-Lite has 10 LEDs. The simulator sets NUM_LEDS=10 for this board —
  declare the port as `led : out std_logic_vector(NUM_LEDS - 1 downto 0)`"*.
  It also catches wrong port directions (which GHDL/NVC accept silently,
  yielding dead LEDs), missing required generics (previously a console-only
  warning followed by a cryptic `sim_wrapper.vhd` error), extra ports or
  generics without defaults, and `seg`-without-`NUM_SEGS` on 7-seg boards.
  GHDL/NVC analysis errors gain appended `Hint:` lines for the common
  failure modes, quoting the board's real resource counts. Error dialogs
  gain a **[View Example]** button (`V` key) that opens the
  board-appropriate bundled example design (#173, #181)
- **Theme system (U6).** Three selectable UI themes: the default **PCB Green**,
  **Dark** (graphite PCB, slate-blue accents), and **High Contrast** (pure
  black surfaces, white text and borders, yellow accents, saturated component
  states). The Settings dialog's Theme row — shipped disabled in 0.11.0 — is
  now enabled and applies the choice live; the persisted theme is restored at
  startup and carried into the simulation subprocess via `FPGA_SIM_THEME`.
  `generate-board-images` gains a `--theme` option. The default theme is
  pixel-identical to 0.11.0 (all 278 board PNGs byte-for-byte) (#174, #178)
- **Theme-aware board-image batch runs.** `generate-board-images --theme` now
  accepts a comma-separated list or `all` — a single theme keeps the flat
  output layout (byte-identical to before), several themes render into
  per-theme subdirectories with stable basenames — and a new `--list-themes`
  flag prints the selectable themes with their Settings-dialog labels (#179)

## [0.11.0] - 2026-07-06

### Added

- **Settings dialog + extended session persistence (U5).** A gear button in
  the board preview header opens a new Settings overlay (`ui/settings_dialog.py`)
  with three rows: the UI theme (cycles `THEME_NAMES`; disabled until U6 adds
  alternates), the remembered sim-speed with a [Reset], and the new
  recent-files list with a [Clear]. The session file now also persists the
  window size (restored at startup), the speed slider (seeded into the sim
  via `FPGA_SIM_SPEED` and written back at sim exit; benchmark/test runs
  never touch it), a `theme` name, reserved `metrics_enabled` /
  `waveform_enabled` toggles (for U19/U10), and `recent[]` — the last 10
  (board, VHDL) pairs for U18's picker section. All session writers now
  merge into the file instead of rewriting it, and the launcher saves on
  every board / simulator / VHDL change and at quit — not only at simulation
  launch — so a browsed-but-unrun file and its directory survive a restart
  (#124, #169)

### Changed

- **`main()`'s 264-line screen loop extracted into a `ScreenController` (D6b).**
  New `src/fpga_sim/controller.py` holds a `SessionState` dataclass (the VHDL /
  work-dir / simulator tuple plus the persisted selector preferences) and a
  `ScreenController` whose public transition methods (`on_board_selected`,
  `on_vhdl_loaded`, `on_simulate`, `on_back`) form an explicit state machine,
  dispatched by a `match` on the D6a `ScreenResult` enum; `__main__.main()` is
  now a thin driver and `_build_generics` moved to `controller.build_generics`.
  No behavior change; 33 new tests (#123, #168)

## [0.10.0] - 2026-07-03

### Added

- **README badge row + CI matrix note.** The README now shows a project-info
  badge trio (license, latest release, Python 3.10+) alongside the existing
  CI badge and a new tooling trio (ruff, mypy, uv), plus a one-line "tested
  on" summary of the CI matrix (Ubuntu + Windows × Python 3.10/3.12/3.13,
  plus GHDL/NVC simulator jobs) in place of per-OS badges, which GitHub
  Actions cannot express per-job (#159)
- **Embedded-core generated designs now carry their firmware source.** Above
  the ROM constant, every generated `hdl/*.vhd` embeds its firmware assembly
  listing verbatim as a `--` comment block, so the single file shows both the
  machine code and the program that produced it. `scripts/gen_embedded_core.py`
  also gains a `--prescaler-bits` generation-time override for the
  `PRESCALER_BITS` generic default (e.g. for a temporary faster-stepping
  capture build), and all 8 committed designs are regenerated (#161)
- **New capture scenarios + assets: `cpu_walk` and `dice`.** `sim/capture_frames.py`'s
  interactive-storyboard machinery is generalized into a `_Storyboard` base
  class shared by the snake, embedded-CPU walking-counter, and dice-roller
  demos. `scripts/capture_demo.py` gains `--prescaler-bits`, `--vhdl-label`,
  and `--png` (save a still frame instead of assembling a GIF). New assets:
  an interactive `mx65_walking_counter_demo.gif` for the README, an
  `mx65_dice_7seg.gif`, and an `mx65_hello_7seg.png`, all embedded in the
  guide/README (#162)
- **Annotated waveform for guide §15.** New `scripts/capture_waveform.py`
  simulates `mx65_hello_7seg` against an inline testbench, hand-parses the
  resulting VCD, and renders `docs/assets/mx65_hello_waveform.png` in a
  GTKWave-like visual idiom (black background, green traces, hexagonal bus
  lanes) with five annotations — POR release, reset-vector fetch, first
  opcode, the LED-on store, and the terminal spin loop — all located
  programmatically from the trace. Also (re)writes
  `docs/assets/mx65_hello_7seg.gtkw` so `gtkwave <vcd> <that file>` opens the
  identical view in real GTKWave (#163)

### Changed

- **README doc references are now links.** The `docs/embedded_core_system_guide.md`
  and `docs/embedded_core_improvement_plan.md` mentions in the README's
  embedded-CPU section are clickable relative links instead of plain
  backticked text (#159)
- **Embedded-core guide navigation.** `docs/embedded_core_system_guide.md` gains
  a table of contents, and all 61 `§N` cross-references and ~37 repo-file
  mentions are now clickable anchor/relative links; the misaligned §3 ASCII
  diagram is corrected (#160)
- **Fixed temporally-aliased embedded-CPU GIFs and the `demo.gif` loop seam.**
  The walking-counter GIFs were captured against a temporary
  `--prescaler-bits 14` variant build instead of the committed design's
  default, so the visible step rate is now readable (~6.4 steps/s) instead of
  aliased (~4 steps/frame). `demo.gif`'s storyboard now restores both `SW0`
  and `BTN0` at the end, so its loop seam is continuous in rate and
  direction. The three digit-count GIFs are renamed
  `cpu_walk_{2,4,6}digit.gif` → `mx65_walking_counter_{2,4,6}digit.gif` (#162)

## [0.9.0] - 2026-07-02

### Added

- **Embedded CPU core systems (6502 + Z80).** A design can now be a single
  self-contained `.vhd` that embeds a soft CPU core plus ROM, RAM, and a
  memory-mapped (or Z80 port-mapped) IO subsystem, with checked-in **firmware**
  producing the behavior instead of hand-written RTL. Six committed designs
  prove the skeleton is core-agnostic: the same walking counter runs on a 6502
  (vendored **mx65**) and a Z80 (vendored **T80**) across an interrupt ×
  IO-transport matrix — polled, fixed-vector IRQ, and Z80 IM 2 vectored;
  memory-mapped and Z80 port IO. The firmware reads the board's resource
  counts from IO config registers, so one design fits any board (proven across
  2/4/6-digit 7-seg boards). Each design is generated by
  `scripts/gen_embedded_core.py` from a vendored core + a `systems/*.toml`
  spec + an assembled firmware `.bin`; firmware sources are checked in as
  first-class docs (6502 `.s` for ca65/ld65, Z80 `.asm` for z88dk z80asm)
  alongside their binaries. All six pass a shared cocotb behavioral suite
  under both GHDL and NVC, and `docs/embedded_core_system_guide.md` documents
  the full architecture (#135)
- **Newcomer on-ramp: `hdl/mx65_hello_7seg.vhd`.** The smallest possible
  embedded-core design — a ~20-line 6502 firmware that lights LED 0, shows
  "0" on digit 0, and holds — committed as a runnable copy-and-start template
  (same memory map and generics as the walking counter). The README gains an
  "Embedded CPU systems" section and the guide a five-step "your first
  change" quickstart, so the feature is discoverable from the front door
  (#150)
- **Custom peripherals: `peripherals` spec axis + `hdl/mx65_dice_7seg.vhd`.**
  The generator's IO template gains four anchor points where a spec-selected
  peripheral splices in its own signals, read-mux arm, and clocked logic
  (empty by default — all pre-existing designs regenerate byte-identical).
  The worked example is a free-running 8-bit LFSR at `$E008`: each `btn(0)`
  press rolls a die, showing 1–6 on digit 0 and in binary on the LEDs. It is
  also the first design with deliberately different ROM (2 KB) and RAM (1 KB)
  sizes, proving the decoupled memory map at runtime (#152)
- **`hdl/stopwatch_7seg.vhd` — hand-written interactive stopwatch.** `btn(0)`
  starts/stops, `btn(1)` resets (without changing the running state), each
  active switch doubles the count rate, and `led(0)` shows the running state.
  Written in `counter_7seg.vhd`'s commented teaching style as the RTL half of
  the repo's "same behavior, hardware vs software" teaching pair with the
  embedded-core designs (#154)
- **Embedded-core maintainer tooling.** New `scripts/regen_embedded_cores.py`
  checks every committed generated design against its spec
  (`OK`/`DIFFERS`/`MISSING`, nonzero exit on drift), regenerates drifted files
  with `--write`, and reassembles every firmware with its pinned dev-time
  toolchain via `--assemble` — never writing a `.bin`; that stays a deliberate
  manual act. Reassembly-guard tests prove each checked-in binary reproduces
  from its source with both toolchains. `systems/*.toml` specs are now
  validated eagerly — memory-map rules (power-of-two sizes, base alignment,
  overlap, in-range placement), unknown-key rejection at every level, and a
  ROM-fit check — so a wrong spec fails at the generator with a clear message
  naming the offending region or key instead of a confusing late VHDL error.
  `gen_embedded_core.py`'s `--cpu`/`--rom`/`--out` are now inferred from
  `--system` (explicit flags still override) (#142, #144)
- Board-sync scripts now validate every generated board against
  `boards/schema/board.schema.json` before writing. Validation happens in the
  shared `write_outputs()` chokepoint, so all sources (and any future one) are
  covered; an invalid board aborts the sync with no partial output, and
  `--dry-run` doubles as a schema check. Catches parser regressions at
  generation time instead of later in the test suite.

### Changed

- Tightened the board JSON schema: the board object and the `clock_object`,
  `component`, `seven_seg`, and `source` definitions now set
  `additionalProperties: false`, so a misspelled field (e.g. `default_clk_hz`
  for `default_clock_hz`) is rejected instead of silently ignored. All 278
  boards already conform. The explicitly future-facing sections — `peripherals`
  (intentionally free-form) and the `port_conventions` subtree (shape still
  settling) — remain open.

### Fixed

- **Switch-driven speed-up in four bundled demo designs quadrupled the rate
  instead of doubling it.** `walking_counter_7seg.vhd`, `blinky_walking.vhd`,
  `blinky_counter.vhd`, and `snake_7seg.vhd` all computed the switch-driven
  step-index as `base - n * 2` (`n` = active-switch count), which halves the
  step period *twice* per switch — every header/inline comment in these files
  says "doubles" (#133). Changed to `base - n` so the code matches its own
  docs. `sim/capture_frames.py`, which mirrors `snake_7seg`'s timing in Python
  to pace the README demo-GIF capture, was updated to match or it would have
  desynced from the corrected hardware.

## [0.8.0] - 2026-06-26

### Added

- **Analysis spinner.** Loading a VHDL file (and re-checking it before a run)
  used to freeze the window for several seconds while the simulator analyzed
  and elaborated the design, with no feedback. There is now a centered
  "Analyzing &lt;file&gt;…" overlay with a rotating spinner that animates while
  the work runs on a background thread, so the app stays responsive and clearly
  shows it is busy. The overlay disappears when analysis succeeds or fails.

### Changed

- **Simulator backends now share one base class (internal refactor).**
  `_SimBackend` became an abstract base class instead of a `Protocol`: the four
  discovery helpers (`find` / `available` / `lib_dir` / `sim_bin_lib`) are
  defined once on the ABC as classmethods keyed on each backend's `NAME`, so
  `_GHDLBackend` / `_NVCBackend` now override only `NAME` plus the four
  per-simulator command builders. Removes ~19 lines of duplicated code in
  `sim_bridge.py` and clears the way for a future third backend. No behavior
  change.
- **Launcher screens return typed results instead of strings (internal
  refactor).** `FPGABoard.run()` and `ErrorDialog.run()` previously returned
  bare strings (`"simulate"` / `"load_vhdl"` / `"back"` / `"quit"`, and
  `"retry"` / `"back"`); they now return `ScreenResult` / `DialogResult` enums
  (new `fpga_sim/ui/results.py`), so the main loop dispatches on members that
  mypy type-checks rather than typo-prone literals. Groundwork for the
  forthcoming `ScreenController` extraction. No behavior change.

### Fixed

- **NVC no longer aborts on large designs with a cryptic out-of-memory error.**
  NVC's global heap defaults to 16 MB, which deep / many-instance designs
  exhausted mid-elaboration (`** Fatal: (init): out of memory … increase with
  the -H option`). The NVC backend now passes `-H 512m` on elaboration and run,
  raising the cap — it is a ceiling the heap grows into on demand, not an
  up-front reservation, so small designs are unaffected (measured peak RSS for
  a trivial design is within ~1 MB of the default). In testing this lifted the
  practical ceiling several-fold (a synthetic 64-hart multi-core that previously
  failed now elaborates cleanly); designs with hundreds of instances may
  additionally need NVC's `-M` design-unit-heap option.

## [0.7.0] - 2026-06-25

### Added

- **Board selector polish:** an always-visible scrollbar when the board list
  overflows the window, and each row now shows its definition **source**
  (litex-boards / amaranth-boards / digilent-xdc / custom) as a dim right-aligned
  tag — previously the source appeared only on names that collide across sources.
- **Visual README** — the project page now opens with two animated GIFs: an
  *interactive* live simulation (`hdl/snake_7seg.vhd` on the DE10-Lite — a faux
  cursor taps BTN0 / BTN1 / SW0 with cause→effect captions over a persistent
  "live VHDL simulation · board · running file" strip, driving the real DUT) and
  the board selector filtering its 278 boards down by component and vendor with a
  cursor clicking each chip. Both are reproducible
  via new maintainer tools `scripts/capture_demo.py` and
  `scripts/capture_selector.py` (shared helpers in `scripts/capture_common.py`;
  cocotb capture testbench in `sim/capture_frames.py`); Pillow was added to the
  `dev` group.
- **6 new boards** synced from upstream (272 → 278 loadable): amaranth Cora
  Z7-07S / Cora Z7-10; litex Adiuvo Forgix, Altera Agilex5e 065B Premium DevKit,
  Brisbanesilicon BRS-100, Trenz TEL0025. Each headless-spot-checked on NVC.
- **Parser unit tests** for litex and digilent (`tests/test_litex_parser.py`,
  `tests/test_digilent_parser.py`), closing the coverage gap on the two
  previously-untested parsers (~70% of the board catalog).

### Changed

- **Decoupled the amaranth-boards sync from the runtime board loader.** The
  mock-exec parser that turns upstream amaranth `.py` board files into
  `BoardDef`s moved out of `src/fpga_sim/board_loader.py` into a dedicated
  `scripts/amaranth_parser.py`, and `scripts/sync_boards.py` was renamed to
  `scripts/sync_amaranth_boards.py` (parallel to `sync_litex_boards.py` /
  `sync_digilent_xdc.py`). `board_loader.py` is now a pure JSON runtime loader
  (804 → 241 lines); generated board JSON is byte-for-byte unchanged.
- **Modularized the litex and digilent sync scripts** (parallel to the amaranth
  split): the parsers moved into dedicated `scripts/litex_parser.py` /
  `scripts/digilent_parser.py`; the `sync_*.py` scripts are now thin
  download/output/CLI wrappers. Generated board JSON is byte-for-byte unchanged.
- **Extracted shared sync scaffolding** into `scripts/sync_common.py` (download,
  ref resolution, filesystem-safe naming, JSON/metadata output) used by all three
  `sync_*.py` scripts; also gives the digilent script the filename-collision dedup
  it previously lacked. Output byte-for-byte unchanged.

### Removed

- Dead pre-JSON discovery fallbacks in `board_loader.py`
  (`_discover_boards_legacy` and the amaranth-boards submodule path),
  unreachable since board definitions moved to JSON.

## [0.6.0] - 2026-06-22

### Added

- **In-app help overlay** — a Help / About modal reachable from every
  launcher screen via **F1**, **?**, or a **(?)** button (board-selector
  header and preview corner). Shows a 4-step workflow, a keyboard-shortcut
  legend (rendered from a single source of truth), and the VHDL
  design-contract summary; dismiss with Esc / F1 / ?, the Close button, or a
  click outside. Resizing the window while it is open re-scales the screen
  beneath on close (U1)
- **Keyboard navigation** in the board selector and VHDL file picker —
  **↑ / ↓** and **Page Up / Page Down** move the highlight and **Enter**
  selects; on the selector, **Enter** also drives the sort dropdown when it is
  open (U13)
- **Board selector filtering & sort** — filter chips (Has LEDs / Switches /
  Buttons / 7-seg, plus per-vendor chips with an "Other" group) that compose
  with the text filter, a sort control with 7 modes (Name, Vendor, LEDs,
  Switches, Buttons, 7-seg, Total), an active-filter count ("N of 272 boards"),
  and session persistence of all filter/sort state (U0)
- **R key** resets all switches off and releases any held buttons; works
  in both the board preview screen and during live simulation. Inputs
  only — the design's internal state (counters, registers) is unaffected
  (U11)
- **Five new boards** in `boards/custom/`: **DE2-115** (Intel Cyclone IV E
  — 27 LEDs, 18 switches, 4 buttons, 8-digit 7-seg), **VEEK-MT2** (the
  DE2-115's EP4CE115 base on the VEEK-MT2 carrier), **DE23-Lite** (Intel
  Agilex 3 — 10 LEDs, 10 switches, 4 buttons, 6-digit 7-seg),
  **DE25-Standard** (Intel Agilex 5, same layout as DE23-Lite), and
  **VEEK-MT-SoCKit** (Intel Cyclone V SX — 4 LEDs, 4 switches, 4 buttons)
- Python 3.13 added to the CI test matrix

### Changed

- Unified the two VHDL wrapper templates (`sim_wrapper_template.vhd` and
  the deleted `sim_wrapper_7seg_template.vhd`) into a single template with
  conditional placeholders that `_generate_wrapper()` splices in when the
  board and design both use 7-seg. Removes ~73 lines and unblocks U21
  (board-native VHDL) and U22 (7-seg physical mux) (D1)
- **Board summary format** in the board selector is now compact:
  `"4 LEDs · 2 BTN · 4 SW · 4-digit 7-seg"` (middle-dot separator,
  abbreviated `BTN`/`SW`) instead of `"4 LEDs, 2 buttons, 4 switches,
  4-digit 7-seg"` (U12)
- Internal: simulator backend identifiers are now typed with a
  `Simulator = Literal["ghdl", "nvc"]` alias (threaded through `sim_bridge`,
  `session_config`, `__main__`, and `FPGABoard`) so mypy rejects typos like
  `_backend("gdhl")`; no behavior change (D9)
- Internal: extracted a shared `ui/widgets/button.py` (`ButtonStyle` +
  `draw_button`) and routed all four open-coded button sites through it — the
  board-preview footer, the error dialog, the simulation-speed panel's clock
  steppers, and the sim Stop/Pause overlay. Removes the per-site styling drift
  (each had hand-rolled hover/border/radius); the clock steppers now show hover
  feedback. No other visual change (D4)
- Tooling: added [rumdl](https://github.com/rvben/rumdl) as a Markdown linter —
  wired into the pre-commit hooks and the CI lint job, configured under
  `[tool.rumdl]` (MD013 line-length and MD036 emphasis-as-heading disabled), and
  applied a one-time `rumdl fmt` pass across the repo's Markdown
- Tooling: ruff and ruff-format now run as local pre-commit hooks (via
  `uv run`), like mypy and rumdl, so they use the `uv.lock`-pinned ruff rather
  than a separate `astral-sh/ruff-pre-commit` `rev:`. Removes silent drift
  between the pre-commit ruff and the version CI / `uv run` use
- Internal: documented `board_loader.py`'s exec-in-mock-namespace strategy
  and added docstrings to the eight mock classes and the resource helpers
  (D11)
- Tooling: the test suite now runs in randomized order via `pytest-randomly`
  to surface inter-test state leakage

### Fixed

- **litex-boards sync** selected the wrong platform class for non-Xilinx
  boards. The corrected re-sync updates ~148 board definitions and adds 16
  more litex boards (Colorlight, OrangeCrab, ButterStick, Logicbone,
  Machdyne, QMTech, etc.). Combined with the five new custom boards above,
  the catalog is now 275 definitions (272 loadable) across four sources
  (#67)

## [0.5.0] - 2026-05-25

### Added

- **litex-boards sync** — `scripts/sync_litex_boards.py` downloads and converts
  board definitions from [litex-hub/litex-boards](https://github.com/litex-hub/litex-boards),
  adding ~147 boards across Xilinx, Intel, Lattice, Gowin, Efinix, and CologneChip
- **Digilent XDC sync** — `scripts/sync_digilent_xdc.py` parses Digilent master XDC
  constraint files from [Digilent/digilent-xdc](https://github.com/Digilent/digilent-xdc),
  adding ~26 boards (Basys 3, Nexys A7, Arty, Zybo, etc.) with auto-generated
  `port_conventions` for future board-native VHDL mode (U21)
- 7-segment display detection in both new sources (multiplexed and non-multiplexed)
- Board count increased from ~80 to ~250 across four sources

### Changed

- Board selector now shows boards from all four sources: `amaranth-boards`,
  `litex-boards`, `digilent-xdc`, and `custom`
- Test `test_arty_a7_found` updated to allow multi-source board matches

## [0.4.0] - 2026-05-25

### Changed

- Migrated board definitions from amaranth-boards git submodule to self-contained
  JSON files in `boards/` — no submodule initialization required
- Board loader discovers JSON sources automatically; each subdirectory under
  `boards/` is an independent source (`amaranth-boards/`, `custom/`, etc.)
- Multiple sources may define the same board; all definitions are shown in the
  board selector with source annotations when names collide
- Session persistence now tracks board source for disambiguation

### Added

- `boards/schema/board.schema.json` — JSON Schema for board definition validation
- `boards/custom/de10_standard.json` — Terasic DE10-Standard (Cyclone V SX SoC,
  10 LEDs, 4 buttons, 10 switches, 6-digit 7-seg); includes `peripherals` and
  `port_conventions` sections for future use
- `scripts/sync_boards.py` — downloads and converts board definitions from the
  amaranth-boards GitHub repository without requiring a local clone
- Support for richer clock format in JSON (objects with name, Hz, pin, is_default)
- `jsonschema` added to dev dependencies for CI validation

### Removed

- `amaranth-boards/` git submodule (replaced by `boards/amaranth-boards/` JSON files)

### Security

- Hardened CI workflow: pinned actions to commit SHAs, added `permissions` blocks,
  restricted token scopes

## [0.3.1] - 2026-05-19

### Changed

- Unified `_NVCBackend.run_cmd` signature with `_GHDLBackend` (`generics` parameter
  added, ignored at runtime since NVC bakes them in at elaboration); introduced
  `_SimBackend` Protocol; removed the two remaining `# type: ignore[call-arg]`
  suppressions from `launch_simulation()` (closes #30)

## [0.3.0] - 2026-05-19

### Added

- 7-segment display support: 8 boards (DE0, DE0-CV, DE1-SoC, DE10-Lite, Nandland-Go,
  Nexys4-DDR, RZ-EasyFPGA-A2/2, StepMXO2); Mercury excluded (display behind extension
  resource list, not in `resources`)
- `SevenSegDef` dataclass: `num_digits`, `has_dp`, `is_multiplexed`, `inverted`,
  `select_inverted`; round-trips through `BoardDef` JSON
- `SevenSeg` pygame widget: amber polygon segments, scales from 24 px to any size
- `FPGABoard` horizontal split layout: FPGA chip (55 %) + 7-seg panel (45 %) in top section
- `FPGABoard.set_seg(index, bits8)` method for cocotb readback
- `sim_wrapper_7seg_template.vhd`: 7-seg wrapper with `NUM_SEGS` generic and `seg` port
- `counter_7seg.vhd`: hex digit counter, all 8 boards
- `snake_7seg.vhd`: single segment crawls figure-8 across all digits; bouncing LED + decimal point
- `walking_counter_7seg.vhd`: bouncing LED with decimal BCD counter on 7-seg digits
- SVG board previews include 7-seg digit outlines (all-OFF ghost segments)
- VHDL contract checker enforces `seg` port presence/absence based on board type

### Changed

- Upgraded ruff 0.15.12 → 0.15.13, mypy 1.20.2 → 2.1.0, pre-commit 4.5.1 → 4.6.0
- amaranth-boards submodule advanced to include Tang Mega 138k Pro Dock

## [0.2.0] - 2026-04-03

### Added

- Windows support: NVC simulator works via MSYS2; auto-detect Python DLL with `cocotb-config` (#52)
- CI: Windows test matrix (pure-Python + GHDL) (#54)
- CI: Linux GHDL and NVC full-suite jobs (#55)

### Changed

- Migrated to `src/` layout (`fpga_sim` package under `src/`) (#56)
- Improved README accuracy: board count, NVC install, VPI/VHPI details (#49)
- Corrected docs: NVC is available on Windows via MSYS2 (#53)

### Fixed

- Bumped Pygments 2.19.2 → 2.20.0 to resolve CVE-2026-4539 (#51)

## [0.1.0] - 2026-03-30

- Initial release

[Unreleased]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.12.0...HEAD
[0.12.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/releases/tag/v0.1.0
