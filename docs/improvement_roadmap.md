# Virtual FPGA Boards — Improvement Roadmap

*Drafted 2026-05-19 · Updated 2026-05-28 · Status: draft for review · Companion to CHANGELOG.md / CONTRIBUTING.md*

A comprehensive, impact-weighted roadmap covering improvements from two perspectives:

1. **User-facing** — UX, performance, presentation, persistence, features.
2. **Developer-facing** — architecture, DRY, type safety, documentation, tests, tooling.

Each item lists *why* it matters, *what* to do, *which files* are touched, a rough effort estimate (XS / S / M / L / XL), and a *done-when* acceptance criterion. Tier numbers reflect impact-weighted priority, not strict execution order; see "Suggested merge order" at the end for a practical sequencing and "Dependencies" for required ordering constraints.

---

## Context

The simulator is mature: ~5,800 LOC across 10+ Python modules, 20 test files (880+ tests), multi-platform CI, two simulator backends (GHDL/NVC), 7-segment support shipped, 275 board definitions from four sources (272 loadable), performance heavily tuned (PR #31), v0.5.0 released.

It is feature-complete for experienced FPGA users, but the codebase and UX have grown organically and now show four patterns:

1. **Board discovery at scale.** With 272 boards from 7 vendors, the flat scrolling list with text-only filtering is no longer adequate. Users cannot filter by component type, vendor, or capability — they must already know the board name.
2. **Onboarding & discoverability gaps.** README is excellent (~545 lines) but unreachable from inside the app. New users cannot easily find shortcuts, the design contract, or feature locations.
3. **DRY drift.** Two near-identical backend classes, three component classes with identical structure, and a 264-line main function with stringly-typed screen results. *(VHDL wrapper templates unified in D1.)*
4. **Roadmap gravity.** Several features have been queued in memory for months (PWM LEDs, splash, settings screen, waveforms, Verilog, in-sim navigation) but never sequenced.

This document inventories all viable improvements and ranks them by impact.

---

## Part 1 — User-facing improvements

### Tier 1 — High impact, ship first

#### U0. Board selector — faceted filtering and sort ✅
- **Completed:** 2026-05-27 (PR #75).
- **Delivered:** filter chips (4 component + data-driven vendor chips with "Other" grouping), sort dropdown with 7 modes (Name, Vendor, LEDs, Switches, Buttons, 7-seg, Total), active filter counter ("N of 272 boards"), and session persistence of all filter/sort state. Also fixed: preselect scroll with active filters, scroll clamping in both list screens, and VHDL path unnecessarily cleared on board navigation. 42 new tests.
- **Why:** 272 boards across 7 vendors with only name-substring filtering makes discoverability poor. A user who wants "a board with switches and 7-seg" must scroll the entire list reading summaries. Component distribution is highly varied: 176 boards have zero switches; only 24 have 7-seg; LED counts range from 0 to 34. The current text filter (`_filtered()` at line 68) matches on `name` and `class_name` only.
- **What:** Three additions to the board selector header area:
  1. **Filter chips** — clickable toggles below the text filter: `Has LEDs`, `Has Switches`, `Has Buttons`, `Has 7-seg`, and vendor chips (Xilinx / Lattice / Intel / Other). These compose with the existing text filter (AND logic).
  2. **Sort control** — a cycle button: Name (default) → LED count descending → total component count descending → Name.
  3. **Active filter summary** — replace the static "272 boards" counter with "42 of 272 boards" when filters are active.
- **Touches:** `src/fpga_sim/ui/board_selector.py` (expand `_filtered()` logic at line 67, add chip rendering in `_draw()` header at lines 125-163, add click handling for chips in `_click()` / `_hover()`).
- **Effort:** M. The current header has room (only title + text filter); the hard part is fitting chips into small windows gracefully.
- **Dependencies:** None.
- **Done when:** filter chips render in the header, compose with the text filter, the board count updates to show "N of 272 boards", and sort cycles through all three modes.

#### U1. Help / About overlay (F1 or `?` key)
- **Why:** Currently nothing in-app teaches the user the workflow or shortcuts; README is great but invisible at runtime.
- **What:** Modal overlay with a 4-step workflow diagram, keyboard shortcut legend (ESC, Enter, F1, R, P, arrows, S), the design-contract summary, and a pointer to `hdl/blinky.vhd` as a working example.
- **Touches:** new `src/fpga_sim/ui/help_dialog.py`; hotkey handler additions in `board_selector.py` (~line 95) and `board_display.py` (~line 407); reuse the `ErrorDialog` modal structure for layout.
- **Effort:** S/M.
- **Dependencies:** Soft: benefits from D4 (shared button helper) for consistent "Close" button styling.
- **Done when:** pressing F1 on any screen shows a modal with all shortcuts listed; ESC or clicking outside dismisses it.

#### U2. Inline analysis spinner during VHDL load
- **Why:** `analyze_vhdl()` can hang silently for 5–10 s with no UI feedback; users assume the app is frozen.
- **What:** Non-blocking "Analyzing <file>..." overlay with a rotating spinner while `check_vhdl_contract()` + `analyze_vhdl()` run.
- **Risk:** pygame is not thread-safe for rendering. Do **not** use a background thread that touches the display surface. Instead, use `subprocess.Popen` with non-blocking polling (`poll()` in the event loop) so the main thread can render the spinner between poll checks. The analysis subprocess is already a `subprocess.run()` call — converting to `Popen` + poll loop is straightforward.
- **Touches:** `src/fpga_sim/__main__.py:307-327` (analysis call site); new helper in `ui/`.
- **Effort:** M.
- **Dependencies:** None.
- **Done when:** a spinner/overlay is visible during VHDL analysis and disappears when analysis completes or fails.

#### U3. Component tooltips on hover (preview & sim)
- **Why:** Hovering an LED/switch/button currently does nothing visible; net names and pin assignments live only in stdout `print()` callbacks.
- **What:** Hover for ~400 ms -> small tooltip with `net_name`, `pin`, `direction`. Add a `Tooltip` widget; integrate in `LED.draw`, `Switch.draw`, `Button.draw`.
- **Touches:** new `src/fpga_sim/ui/tooltip.py`; small additions in `components.py:116-233`; mouse-pos tracking in `board_display.py`.
- **Effort:** M.
- **Dependencies:** Soft: simpler with D3 (UIComponent base provides unified hit-testing).
- **Done when:** hovering a component for 400 ms shows a tooltip with net name, pin, and direction; moving away dismisses it.

#### U4. Error messages with contextual hints
- **Why:** "VHDL Error: port width mismatch" doesn't tell the user which port or expected width; the design contract lives only in CLAUDE.md.
- **What:** Augment `check_vhdl_contract()` and the analyze stderr parser to append actionable hints: *"this board has 16 LEDs -- set NUM_LEDS=16 or use `std_logic_vector(NUM_LEDS-1 downto 0)`"*. Show a "View example" button in `ErrorDialog` that opens `hdl/blinky.vhd`.
- **Touches:** `src/fpga_sim/sim_bridge.py:319` (`check_vhdl_contract`); `src/fpga_sim/ui/error_dialog.py`.
- **Effort:** M.
- **Dependencies:** None.
- **Done when:** error dialogs include the specific port/width mismatch details and a "View example" button that opens the correct example file.

#### U5. Settings dialog + extended session persistence
- **Why:** Today only board / VHDL / simulator are saved; window size, speed slider, theme, default clock are lost every restart. The roadmap also needs a place to put new toggles (metrics, waveform, theme).
- **What:** New `ui/settings_dialog.py` (gear icon in board preview header). Extend `session_config.py` schema with: `window_w`, `window_h`, `speed_factor`, `theme`, `metrics_enabled`, `waveform_enabled`, `recent[]` (last 10 board+vhdl tuples).
- **Touches:** `src/fpga_sim/session_config.py`; `ui/board_display.py` header; new `ui/settings_dialog.py`.
- **Effort:** M/L.
- **Dependencies:** None. But **U6, U10, U18, U19** all depend on this (see Dependencies section).
- **Done when:** settings dialog opens from a gear icon, persists window size / speed / theme across restarts, and `recent[]` is populated on each simulation run.

### Tier 2 — High impact, larger initiatives

#### U6. Theme system (light / dark / high-contrast)
- **Why:** All colours hard-coded in `ui/constants.py`; the green PCB clashes with the dark selector; accessibility (high-contrast) is impossible today.
- **What:** Move colours into a `Theme` dataclass, load from JSON, ship 3 presets (`pcb-green` default, `dark`, `high-contrast`). Toggle in the new Settings dialog (U5).
- **Touches:** rewrite `src/fpga_sim/ui/constants.py:14-27`; all `ui/` modules reference `theme.COLOR_X` instead of module constants.
- **Effort:** L (broad reach but mechanical).
- **Dependencies:** **Requires U5** (theme toggle lives in Settings dialog).
- **Done when:** three themes are selectable in Settings and all UI screens (selector, preview, sim, dialogs) render correctly with each.

#### U7. In-simulation navigation toolbar
- **Why:** Already queued in `project_enhancements.md` (#2). Currently the only way out of sim is ESC; users cannot reload VHDL or change board without restarting.
- **What:** Three buttons in the simulation footer: `[Back to Boards]`, `[Change VHDL]`, `[Reload VHDL]`. `Reload` re-runs `analyze_vhdl()` on the same file and re-enters sim.
- **Touches:** `sim/sim_testbench.py`, `src/fpga_sim/sim_bridge.py` (return code signalling intent), `src/fpga_sim/__main__.py:351-430` (handle new intents).
- **Effort:** L.
- **Dependencies:** Soft: benefits from D4 (shared button helper).
- **Done when:** all three buttons work during simulation; [Reload VHDL] re-analyses and restarts without returning to the launcher.

#### U8. Splash screen with random board preview
- **Why:** Queued in memory (#3). Adds polish + visual marketing of the board catalogue.
- **What:** Replace the bare `BoardSelector` first paint with a two-panel layout: left = filter list, right = randomly-cycling board preview image from `board_images/`.
- **Touches:** `src/fpga_sim/ui/board_selector.py`.
- **Effort:** M.
- **Dependencies:** Consider after U0 (board filtering) so the left panel already has filter chips.
- **Done when:** board selector shows a preview panel with cycling board images alongside the filterable list.

#### U9. LED PWM brightness visualisation
- **Why:** Queued in memory (#4). Today LEDs are binary; PWM designs (`hdl/blinky_pwm.vhd` already exists) look broken.
- **What:** Sample LED state N times per displayed frame (e.g. 10 sub-steps), average to a `LED.brightness in [0,1]` float, use to interpolate `RED_OFF` -> `RED_ON`.
- **Risk:** Multiple `dut.led.value` reads per frame changes the simulation timing model. Each read requires a cocotb `Timer` await, so N sub-steps per frame multiplies the per-frame simulation cost by N. This will reduce the current 37.7 fps baseline. Mitigate by making sub-step count configurable (default 1 = current behaviour, opt-in to N > 1 for PWM designs). Benchmark before/after.
- **Touches:** `sim/sim_testbench.py` (multiple `dut.led.value` reads per draw), `src/fpga_sim/ui/components.py:116-148` (`LED.draw`).
- **Effort:** M.
- **Dependencies:** None (opt-in, so no regression to existing behaviour).
- **Done when:** a PWM-driven LED shows intermediate brightness proportional to duty cycle, and the default (1 sub-step) matches current performance.

#### U10. Waveform capture
- **Why:** Queued in memory (#5). VCD/FST output is the natural complement to live LED viewing for debugging.
- **What:** Add `Waveform: off / VCD / FST` toggle in Settings (U5). On enable: pass `--wave=<path>` (NVC) or `--vcd=<path>` (GHDL `-r`). Show "View in GTKWave" hint after sim ends.
- **Touches:** `src/fpga_sim/sim_bridge.py` (`launch_simulation`), Settings dialog.
- **Effort:** M.
- **Dependencies:** **Requires U5** (waveform toggle lives in Settings dialog).
- **Done when:** enabling waveform capture produces a valid VCD/FST file viewable in GTKWave.

### Tier 3 — Quick wins (ship anytime)

| ID | Item | Files | Effort |
|---|---|---|---|
| ~~U11~~ | ~~`R` key to reset switches/buttons to default~~ ✅ | `ui/board_display.py` | XS |
| ~~U12~~ | ~~Compact board summary format (e.g. `"4 LEDs · 2 BTN · 4 SW · 4-digit 7-seg"`)~~ ✅ | `board_loader.py` (`BoardDef.summary`) | XS |
| U13 | Arrow / Page-Up / Page-Down navigation in board + file lists | `ui/board_selector.py`, `ui/vhdl_picker.py` | S |
| U14 | `P` key to pause/resume simulation; pause indicator in SimPanel | `sim/sim_testbench.py`, `ui/sim_panel.py` | S |
| U15 | Compact mode for `SimPanel` (toggle via existing `S` shortcut family) | `ui/sim_panel.py:282-308` | S |
| U16 | Enforce minimum window size (800x600) with friendly warning | `__main__.py:184-187` | XS |
| U17 | Pre-allocate common font sizes at startup (eliminates LRU eviction churn) | `ui/constants.py:41-49` | XS |
| U18 | Recent-files section in `VHDLFilePicker` (consumes `recent[]` from U5) | `ui/vhdl_picker.py` | S |
| U19 | Metrics-enable checkbox surfacing `FPGA_SIM_METRICS` env var | `ui/sim_panel.py` or Settings dialog | XS |

**Note on U12:** `BoardDef.summary` already includes 7-seg digit count as of v0.5.0. Remaining work is the formatting change (dot separators, abbreviated labels).

**Note on U18/U19:** Both require U5 (Settings dialog) for the `recent[]` data source and metrics toggle location respectively.

### Tier 4 — Larger features (long-horizon)

#### U20. Verilog / SystemVerilog support
- **Why:** Queued in memory (#1); broadens audience significantly. Icarus Verilog is the natural first target.
- **What:** New file picker extension filter `.v / .sv`, Verilog contract validator, `TOPLEVEL_LANG="verilog"`, new VPI lib, third backend class, example `blinky.v`.
- **Effort:** XL (10-15 h).
- **Dependencies:** **Requires D2** (backend ABC) — without it, a third backend is a third copy-paste of `find()` / `available()` / `lib_dir()` / `sim_bin_lib()`.
- **Done when:** a `.v` file with the correct port contract simulates successfully with Icarus Verilog.

#### U21. Board-native VHDL mode (port conventions)
- **Why:** Users currently must write VHDL to our generic contract (`clk`, `sw`, `btn`, `led`, `seg` with `NUM_*` generics). A real DE10-Standard design uses `CLOCK_50`, `KEY(3 downto 0)`, `LEDR(9 downto 0)`, `HEX0`-`HEX5` — these fail `check_vhdl_contract()`, the wrapper, and cocotb signal binding. The `port_conventions` data is already stored in board JSON files (e.g. `boards/custom/de10_standard.json` has a `terasic` convention) but nothing consumes it yet.
- **What:** Three changes, each building on the previous:
  1. **Contract checker** — when the user's VHDL ports don't match the generic contract, attempt to match them against the board's `port_conventions`. If a convention matches, accept the file and record which convention was used.
  2. **Wrapper generator** — generate a port-adapter wrapper that maps between cocotb's signal names (`sw`, `btn`, `led`, `seg`) and the user's actual port names (`KEY`, `LEDR`, `HEX0`-`HEX5`). Handle polarity differences (the convention records `active_low` flags). Handle decomposed 7-seg ports (`individual` style: 6 separate `HEX` ports vs. one packed `seg` vector).
  3. **cocotb testbench** — no change needed if the wrapper does the adaptation; cocotb continues reading `dut.sw`, `dut.btn`, `dut.led`, `dut.seg` from the wrapper, which internally connects to the user's port names.
- **Touches:** `src/fpga_sim/sim_bridge.py` (`check_vhdl_contract`, `_generate_wrapper`), `sim/sim_wrapper_template.vhd` (add port-adapter placeholders), `boards/schema/board.schema.json` (port_conventions already defined).
- **Sync script merge logic:** When this feature lands, `scripts/sync_boards.py` needs a shallow-merge update: before writing a board JSON, read the existing file (if any) and preserve top-level keys the script didn't generate (`port_conventions`, `peripherals`, etc.). This lets users add conventions directly to `boards/amaranth-boards/*.json` without losing them on re-sync. ~10 lines: read existing -> update auto-generated keys -> write back.
- **Dependencies:** D1 ✅ (unified wrapper template is in place).
- **Effort:** L/XL (contract matching is moderate; the wrapper generator for decomposed 7-seg ports is the hard part).
- **Done when:** a DE10-Standard-style VHDL file with native port names (`CLOCK_50`, `KEY`, `LEDR`, `HEX0`-`HEX5`) simulates without modification.

#### U22. 7-segment v2 — physical mux mode
- **Why:** Queued in memory (#8); current v1 is logical-only. v2 enables the hardware-accurate scan interface on Nexys4-DDR, RZ-EasyFPGA, StepMXO2.
- **What:** New conditional placeholders in the unified wrapper template, updated testbench readback, new `physical_mux: bool` toggle per board.
- **Effort:** L.
- **Dependencies:** D1 ✅ (unified wrapper template is in place).
- **Done when:** a muxed 7-seg board (e.g. Nexys4-DDR) shows correct digits via the physical scan interface.

### Performance (mostly already done)

`memory/project_sim_performance.md` documents PR #31's tuning (37.7 fps, 0.0036x real-time on Arty A7-35; GHDL dominates at 98.4 %). Remaining cheap wins:

- **U23.** Dirty-flag redraw — skip `_draw()` when no LED / switch / button / 7-seg state changed since last frame. Touches `sim/sim_testbench.py` draw loop and `ui/board_display.py`. **Effort:** S. **Done when:** frame rate stays at 30 fps cap but CPU usage drops when no state changes.
- **U24.** Batch multiple `Timer` calls per frame at high speed-slider settings (today >0.1x is CPU-capped). **Effort:** M. **Done when:** high speed-slider settings show measurably higher simulation throughput.
- **U25.** Profile GHDL GPI vs VHDL eval to find the next bottleneck. **Effort:** investigative. **Done when:** a written profile report identifies the top-3 bottlenecks with data.

---

## Part 2 — Developer-facing improvements

### Tier 1 — DRY: collapse the duplications

#### D1. Generate the VHDL wrapper from one source ✅
- **Completed:** 2026-05-28.
- **Delivered:** Merged `sim_wrapper_template.vhd` and `sim_wrapper_7seg_template.vhd` into a single template with conditional placeholders (`{seg_generic}`, `{seg_port}`, `{seg_generic_map}`, `{seg_port_map}`). `_generate_wrapper()` splices the 7-seg lines when both board and design use seg; otherwise they are omitted. Deleted `sim_wrapper_7seg_template.vhd` and `_choose_wrapper_template()`. All 882 tests pass.
- **Why:** `sim/sim_wrapper_template.vhd` (62 LOC) and `sim/sim_wrapper_7seg_template.vhd` (55 LOC) shared ~80 % of their content — identical clock generation, identical entity boilerplate, only the `seg` port and its mapping differed. Two templates meant every wrapper change had to be made twice; v2 physical-mux (U22) would have made a third file.
- **Dependencies:** None. But **U21** and **U22** both depend on this.

#### D2. Backend base class with override-only differences
- **Why:** `_GHDLBackend` and `_NVCBackend` (`sim_bridge.py:65-177`) duplicate 8 method signatures; bodies share structure (`find()` = `shutil.which(self.NAME)`; `lib_dir()` is identical logic in both; `available()` is identical). The `_SimBackend` Protocol declares the shape but does not share implementation.
- **What:** Convert `_SimBackend` from Protocol -> ABC; move `find()`, `available()`, `lib_dir()`, `sim_bin_lib()` into the ABC; subclasses override only `NAME`, `plugin_lib_name()`, `analyze_cmd()`, `elaborate_cmd()`, `run_cmd()`.
- **Touches:** `src/fpga_sim/sim_bridge.py:33-178`. Net reduction ~50 LOC.
- **Effort:** S/M. Existing test suite (`tests/test_sim_bridge_backend.py`) already covers both backends — refactor is safe under it.
- **Dependencies:** None. But **U20** depends on this.
- **Done when:** `_SimBackend` is an ABC with shared implementations; `_GHDLBackend` and `_NVCBackend` override only the 4-5 methods that differ; all backend tests pass.

#### D3. UIComponent base class
- **Why:** `LED`, `Switch`, `Button` in `components.py:116-233` share an identical `__init__(index, info)` signature, identical `label` property logic, and an identical `callback` attribute pattern. `SevenSeg` is similar but uses `(index, has_dp)`.
- **What:** Abstract base `UIComponent` with `index`, `info`, `rect`, `label` property; subclass-specific `state` / `pressed` / `bits` stay in children. Optional: register components into a single `board.components: list[UIComponent]` for unified hit-testing.
- **Touches:** `src/fpga_sim/ui/components.py`; small cleanup in `ui/board_display.py`.
- **Effort:** S.
- **Dependencies:** None. Soft: simplifies U3 (tooltips can use unified hit-testing).
- **Done when:** `LED`, `Switch`, `Button` inherit from `UIComponent`; no duplicate `__init__` / `label` code; all component tests pass.

#### D4. Shared button-drawing helper
- **Why:** Footer buttons in `board_display.py:553-616` and `sim_panel.py` zone draws redraw rectangles with near-identical code; styling drift is already visible (different hover colours).
- **What:** Extract `ui/widgets/button.py: Button.draw_rect(surface, rect, label, state)` with consistent hover/pressed colours. Reuse in the board_display footer, sim_panel zones, and the new help/settings dialogs.
- **Touches:** new file; replace open-coded draws in two callers.
- **Effort:** S.
- **Dependencies:** None. Soft: **U1, U5, U7** should consume it for consistent styling.
- **Done when:** both `board_display.py` footer and `sim_panel.py` zones use the shared helper; hover colours are consistent.

#### D5. Platform-aware path helper
- **Why:** `_build_sim_env()` (`sim_bridge.py:493-550`) repeats the PATH-prepend pattern for Windows and Linux; the `IS_WINDOWS` branching is interleaved with logic that doesn't actually differ.
- **What:** Extract `_compose_path(extra: list[str], var: str = "PATH") -> str`; flatten Windows/Linux branches to differ only in their `extra` list contents.
- **Touches:** `src/fpga_sim/sim_bridge.py:493-550`. Modest LOC reduction, large clarity win.
- **Effort:** S.
- **Dependencies:** None.
- **Done when:** `_build_sim_env()` has no interleaved `if IS_WINDOWS` blocks; platform differences are isolated to the `extra` path lists.

### Tier 2 — Architecture & state

#### D6. Extract a `ScreenController` from `__main__.py`
- **Why:** `main()` in `__main__.py:174-438` is a 264-line function with a `while`-loop juggling 4 screen states via implicit transitions (`_return_to_board`, `current_vhdl_path`, `current_work_dir`, `_work_dir_simulator`, `_back_to_boards`, `_new_path`, `_first_pick`, `_intent`). Reading it requires holding all of that in your head; the nested VHDL-picker loop at lines 294-335 hits 4 levels of indentation.
- **What:** Two refactors, sequenced:
  - **D6a.** Replace the stringly-typed screen results (`"back"`, `"load_vhdl"`, `"simulate"`, `"quit"`, `"retry"`) with a `ScreenResult` enum. Same in error dialog (`"back"` / `"retry"`).
  - **D6b.** Lift the loop body into a `ScreenController` class with explicit transition methods (`on_board_selected`, `on_vhdl_loaded`, `on_simulate`, `on_back`) and a `SessionState` dataclass holding the VHDL / work-dir / simulator tuple.
- **Touches:** `src/fpga_sim/__main__.py`; new `src/fpga_sim/controller.py`; enums in `src/fpga_sim/ui/__init__.py`.
- **Effort:** M (D6a) + L (D6b). **D6a must land before D6b** — it cleanly unblocks the controller extraction.
- **Done when:** (D6a) all string-literal screen results are replaced with enum members and mypy catches misuse. (D6b) `main()` is a thin driver calling `ScreenController` methods; no screen-state variables in `main()`.

#### D7. Decompose `launch_simulation()`
- **Why:** `sim_bridge.py:553-648` mixes env construction, generic injection, NVC re-elaboration, env-var marshalling, and subprocess invocation — ~100 LOC.
- **What:** Split into `_prepare_run_env(board_json, vhdl_path, generics, sim_dims) -> env, cmd` and `_invoke_run(cmd, env, cwd) -> bool`. Makes env construction unit-testable.
- **Touches:** `src/fpga_sim/sim_bridge.py:553-648`; new tests in `tests/test_sim_bridge_backend.py`.
- **Effort:** M.
- **Dependencies:** None.
- **Done when:** `launch_simulation()` is a thin orchestrator; `_prepare_run_env()` has unit tests that verify env dict contents without launching a subprocess.

### Tier 3 — Type safety & tooling

#### D8. mypy strict mode
- **Why:** `pyproject.toml` has `disallow_incomplete_defs = true` but not `strict = true`. Strict mode catches incomplete type guards, missing returns in complex branches, untyped `**kwargs`. The codebase is already well-annotated — the upgrade should produce a manageable error list.
- **What:** Flip to `strict = true`; fix the resulting errors (likely concentrated in `board_loader.py` mock classes and `sim_testbench.py`).
- **Touches:** `pyproject.toml` (mypy section); scattered annotations.
- **Effort:** M (mostly fixing reported errors).
- **Dependencies:** None.
- **Done when:** `uv run mypy src/` passes with `strict = true` and CI enforces it.

#### D9. `Literal` types for stringly-typed identifiers
- **Why:** `simulator: str = "ghdl"` everywhere; nothing prevents a typo passing through.
- **What:** Define `Simulator = Literal["ghdl", "nvc"]`; thread through `analyze_vhdl`, `launch_simulation`, `_backend`, `detect_simulators` return type, session config.
- **Touches:** `src/fpga_sim/sim_bridge.py`, `src/fpga_sim/session_config.py`, `src/fpga_sim/__main__.py`.
- **Effort:** S.
- **Dependencies:** None. Soft: should be extended to include `"iverilog"` when U20 lands.
- **Done when:** `Simulator` is a `Literal` type; mypy catches `_backend("typo")` at type-check time.

#### D10. Pin pre-commit hooks consistently; add `.editorconfig`
- **Touches:** `.pre-commit-config.yaml`; new `.editorconfig`.
- **Effort:** XS.
- **Dependencies:** None.
- **Done when:** all hooks are pinned to exact versions; `.editorconfig` is consistent with existing ruff/formatter config.

### Tier 4 — Documentation

#### D11. Module + mock-class docstrings
- **Why:** `board_loader.py:17-124` mock classes (`_Attrs`, `_Pins`, `_PinsN`, `_DiffPairs`, `_Clock`, `_Subsignal`, `_Connector`, `_Resource`) are ~108 LOC with no docstrings — they are the most arcane code in the project (they exist to fool amaranth-boards `.py` files into executing in a mock namespace). Future maintainers will burn an hour reverse-engineering them.
- **What:** Module docstring on `board_loader.py` explaining the mock-namespace strategy; one-line docstring on each mock class.
- **Touches:** `src/fpga_sim/board_loader.py:17-124`; `src/fpga_sim/sim_metrics.py` (currently placeholder); `src/fpga_sim/ui/sim_panel.py` (no module docstring).
- **Effort:** S.
- **Dependencies:** None.
- **Done when:** every mock class has a one-line docstring; `board_loader.py` module docstring explains the mock-namespace strategy.

#### D12. Architecture diagram in CONTRIBUTING.md
- **Why:** CLAUDE.md has a great file-role table; CONTRIBUTING.md has install steps but no architecture overview for contributors. An ASCII data-flow diagram would lower the on-ramp.
- **What:** Add an "Architecture overview" section with launcher/sim phase diagram, the `BoardDef` / `ComponentInfo` / `SevenSegDef` dataclasses, and the VHDL contract summary.
- **Touches:** `CONTRIBUTING.md`.
- **Effort:** S.
- **Dependencies:** None.
- **Done when:** CONTRIBUTING.md contains an architecture section with a data-flow diagram.

### Tier 5 — Tests

#### D13. Platform-specific `_build_sim_env` coverage
- **Why:** `tests/test_sim_bridge_backend.py` doesn't exercise the Windows vs Linux PATH / PYTHONHOME divergence; bugs there only surface on the actual platform.
- **What:** Parametrise tests with `monkeypatch` on `sim_bridge.IS_WINDOWS`; assert env dict shape for both branches.
- **Touches:** `tests/test_sim_bridge_backend.py`.
- **Effort:** S.
- **Dependencies:** None. Easier after D5 (platform-aware path helper) since branches will be cleaner.
- **Done when:** tests verify env dict contents for both `IS_WINDOWS=True` and `IS_WINDOWS=False`.

#### D14. Session-config edge cases
- **What:** Tests for missing file, malformed JSON, schema migration (when U5 expands the schema).
- **Touches:** `tests/test_session_config.py`.
- **Effort:** S.
- **Dependencies:** None. Extended when U5 lands (new schema fields need migration tests).
- **Done when:** tests cover missing file, malformed JSON, and unknown-key-preservation scenarios.

---

## Dependencies

### Dependency table

Hard dependencies ("requires") must be completed before the blocked item can start. Soft dependencies ("benefits from") are not blockers but reduce effort or improve quality.

| Blocked item | Requires | Reason |
|---|---|---|
| **U6** (Theme system) | **U5** (Settings dialog) | Theme toggle lives in Settings |
| **U10** (Waveform capture) | **U5** (Settings dialog) | Waveform toggle lives in Settings |
| **U18** (Recent files) | **U5** (Settings dialog) | Consumes `recent[]` from U5's schema |
| **U19** (Metrics checkbox) | **U5** (Settings dialog) | Metrics toggle lives in Settings |
| **U20** (Verilog support) | **D2** (Backend ABC) | Third backend class would be a third copy-paste without ABC |
| ~~**U21** (Board-native VHDL)~~ | ~~**D1** (Wrapper merge)~~ ✅ | Adapter logic in unified template |
| ~~**U22** (7-seg physical mux)~~ | ~~**D1** (Wrapper merge)~~ ✅ | Placeholders in unified template |
| **D6b** (ScreenController) | **D6a** (Screen-result enum) | Enum enables type-safe transitions in the controller |

### Soft dependencies

| Item | Benefits from | Reason |
|---|---|---|
| **U1** (Help dialog) | **D4** (Shared button helper) | Consistent "Close" button styling |
| **U3** (Tooltips) | **D3** (UIComponent base) | Unified hit-testing across component types |
| **U5** (Settings dialog) | **D4** (Shared button helper) | Reuse button rendering in dialog |
| **U7** (In-sim toolbar) | **D4** (Shared button helper) | Consistent toolbar button styling |
| **U8** (Splash) | **U0** (Board filtering) | Left panel already has filter chips |
| **D9** (Literal types) | — | Extend to `"iverilog"` when U20 lands |
| **D13** (Env tests) | **D5** (Path helper) | Cleaner branches are easier to test |

### Dependency graph (hard dependencies only)

```
D1 (wrapper merge) ✅ — U21 and U22 are now unblocked

D2 (backend ABC)
 └──> U20 (Verilog support)

U5 (settings dialog)
 ├──> U6  (theme system)
 ├──> U10 (waveform capture)
 ├──> U18 (recent files)
 └──> U19 (metrics checkbox)

D6a (screen-result enum)
 └──> D6b (ScreenController)
```

All other items (U0, U1, U2, U3, U4, U7, U8, U9, U11-U17, U21-U25, D3-D5, D7-D14) are independently shippable.

---

## Suggested merge order

A practical sequencing if all items were in flight (impact-weighted, with foundations early enough to unblock later work). Sprint 1 is split into two sub-sprints to keep batch sizes manageable (~8-12 h each).

| Sprint | Theme | Items |
|---|---|---|
| **1a** | Quickest wins + foundations | ~~U0 Board filtering~~ ✅ · ~~U11 Reset key~~ ✅ · ~~U12 Board summary format~~ ✅ · ~~D1 Wrapper template merge~~ ✅ · D9 Literal types · D11 Mock-class docstrings |
| **1b** | Small features | U1 Help dialog · U2 Analysis spinner · D2 Backend base class · D4 Shared button helper |
| **2** | Foundations that unblock later UX | D6a Screen-result enum · D6b ScreenController · U5 Settings dialog + extended session · D8 mypy strict |
| **3** | Visible polish | U3 Tooltips · U4 Contextual errors · U6 Theme system · U7 In-sim toolbar |
| **4** | Feature breadth | U8 Splash · U9 PWM brightness · U10 Waveform · U23 Dirty-flag redraw |
| **Long-horizon** | — | U20 Verilog support · U21 Board-native VHDL · U22 7-seg physical mux · U24 / U25 Performance deep-dive |

---

## Critical files modified across the roadmap

- `src/fpga_sim/__main__.py` — U1, U2, U7, D6, D9
- `src/fpga_sim/sim_bridge.py` — U4, U10, U21, D1, D2, D5, D7, D9
- `src/fpga_sim/board_loader.py` — U12, D11
- `src/fpga_sim/session_config.py` — U5, U18, D9, D14
- `src/fpga_sim/ui/constants.py` — U6, U17
- `src/fpga_sim/ui/components.py` — U3, U9, D3
- `src/fpga_sim/ui/board_display.py` — U1, U3, U11, U16, D3, D4
- `src/fpga_sim/ui/board_selector.py` — U0, U1, U8, U12, U13
- `src/fpga_sim/ui/sim_panel.py` — U14, U15, U19, D4, D11
- `src/fpga_sim/ui/vhdl_picker.py` — U13, U18
- `src/fpga_sim/ui/error_dialog.py` — U4
- New: `src/fpga_sim/ui/help_dialog.py` (U1), `ui/settings_dialog.py` (U5), `ui/tooltip.py` (U3), `ui/widgets/button.py` (D4), `src/fpga_sim/controller.py` (D6)
- `sim/sim_wrapper_template.vhd` — D1 ✅ (absorbed 7seg template)
- `sim/sim_testbench.py` — U7, U9, U14, U22
- `pyproject.toml` — D8
- `.pre-commit-config.yaml`, new `.editorconfig` — D10
- `CONTRIBUTING.md` — D12

## Existing utilities to reuse

- `ErrorDialog` modal pattern (`ui/error_dialog.py`) -> reuse layout for help / settings / tooltip dialogs.
- `get_font()` LRU cache (`ui/constants.py:41-49`) -> already used everywhere; pre-allocation in U17 just primes it.
- `_generate_wrapper()` (`sim_bridge.py:386-414`) -> unified template substitution with conditional 7-seg splicing (D1 ✅).
- `_SimBackend` Protocol (`sim_bridge.py:33-63`) -> becomes ABC base in D2 with no caller changes.
- `session_config.save_session` / `load_session` (`session_config.py`) -> extend schema for U5; existing call sites unchanged.
- `sim_metrics.py` / `scripts/analyze_metrics.py` -> consumed by U19; no new infra needed.
- `BoardDef.summary` property (`board_loader.py:433-443`) -> update format for U12; extend for U0 filter logic.

---

## Verification

Per-item verification is described in each entry's "Done when" criterion above. Cross-cutting checks for any merge:

1. **Tests** — `uv run pytest` (884 tests across 20 files including UI scaling, board selector filtering, board loader, both backends, 7-seg). All sprints must keep this green.
2. **Lint / type** — `uv run ruff check .` and `uv run mypy src/` (the latter tightens under D8).
3. **Manual smoke** — `uv run fpga-sim` end-to-end on a known board (e.g. Arty A7-35) with `hdl/blinky.vhd`; for 7-seg work use `counter_7seg.vhd` on DE10-Lite.
4. **Benchmark regression** — `uv run fpga-sim --benchmark 10` before/after performance-touching merges (U9 / U23). Baseline: 37.7 fps, 0.0036x real-time on Arty A7-35 (from `memory/project_sim_performance.md`).
5. **Headless CI** — every PR runs the existing Linux + Windows x GHDL + NVC x Py 3.10-3.12 matrix.
6. **Visual checks** — for UI work, screenshot the affected screen on Linux and attach to the PR; no automated visual diff today.
