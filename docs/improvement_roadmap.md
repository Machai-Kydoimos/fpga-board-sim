# Virtual FPGA Boards — Improvement Roadmap

*Drafted 2026-05-19 · Status: draft for review · Companion to CHANGELOG.md / CONTRIBUTING.md*

A comprehensive, impact-weighted roadmap covering improvements from two perspectives:

1. **User-facing** — UX, performance, presentation, persistence, features.
2. **Developer-facing** — architecture, DRY, type safety, documentation, tests, tooling.

Each item lists *why* it matters, *what* to do, *which files* are touched, and a rough effort estimate (XS / S / M / L / XL). Tier numbers reflect impact-weighted priority, not strict execution order; see "Suggested merge order" at the end for a practical sequencing.

---

## Context

The simulator is mature: ~5,800 LOC across 10+ Python modules, 21 test files (840+ tests), multi-platform CI, two simulator backends (GHDL/NVC), 7-segment support shipped, 275 board definitions from four sources, performance heavily tuned (PR #31), v0.5.0 released.

It is feature-complete for experienced FPGA users, but the codebase and UX have grown organically and now show three patterns:

1. **Onboarding & discoverability gaps.** README is excellent (~545 lines) but unreachable from inside the app. New users cannot easily find shortcuts, the design contract, or feature locations.
2. **DRY drift.** Two near-identical VHDL wrapper templates, two near-identical backend classes, three component classes with identical structure, and a 254-line main loop with stringly-typed screen results.
3. **Roadmap gravity.** Several features have been queued in memory for months (PWM LEDs, splash, settings screen, waveforms, Verilog, in-sim navigation) but never sequenced.

This document inventories all viable improvements and ranks them by impact.

---

## Part 1 — User-facing improvements

### Tier 1 — High impact, ship first

#### U1. Help / About overlay (F1 or `?` key)
- **Why:** Currently nothing in-app teaches the user the workflow or shortcuts; README is great but invisible at runtime.
- **What:** Modal overlay with a 4-step workflow diagram, keyboard shortcut legend (ESC, Enter, F1, R, P, arrows, S), the design-contract summary, and a pointer to `hdl/blinky.vhd` as a working example.
- **Touches:** new `src/fpga_sim/ui/help_dialog.py`; hotkey handler additions in `board_selector.py` (~line 78) and `board_display.py` (~line 407); reuse the `ErrorDialog` modal structure for layout.
- **Effort:** S/M.

#### U2. Inline analysis spinner during VHDL load
- **Why:** `analyze_vhdl()` can hang silently for 5–10 s with no UI feedback; users assume the app is frozen.
- **What:** Non-blocking "Analyzing <file>…" overlay with a rotating spinner while `check_vhdl_contract()` + `analyze_vhdl()` run on a worker thread (or by polling a subprocess).
- **Touches:** `src/fpga_sim/__main__.py:300-318` (analysis call site); new helper in `ui/`.
- **Effort:** M (needs threading or non-blocking subprocess wrapper).

#### U3. Component tooltips on hover (preview & sim)
- **Why:** Hovering an LED/switch/button currently does nothing visible; net names and pin assignments live only in stdout `print()` callbacks.
- **What:** Hover for ~400 ms → small tooltip with `net_name`, `pin`, `direction`. Add a `Tooltip` widget; integrate in `LED.draw`, `Switch.draw`, `Button.draw`.
- **Touches:** new `src/fpga_sim/ui/tooltip.py`; small additions in `components.py:116-233`; mouse-pos tracking in `board_display.py`.
- **Effort:** M.

#### U4. Error messages with contextual hints
- **Why:** "VHDL Error: port width mismatch" doesn't tell the user which port or expected width; the design contract lives only in CLAUDE.md.
- **What:** Augment `check_vhdl_contract()` and the analyze stderr parser to append actionable hints: *"this board has 16 LEDs — set NUM_LEDS=16 or use `std_logic_vector(NUM_LEDS-1 downto 0)`"*. Show a "View example" button in `ErrorDialog` that opens `hdl/blinky.vhd`.
- **Touches:** `src/fpga_sim/sim_bridge.py:319-375` (`check_vhdl_contract`); `src/fpga_sim/ui/error_dialog.py`.
- **Effort:** M.

#### U5. Settings dialog + extended session persistence
- **Why:** Today only board / VHDL / simulator are saved; window size, speed slider, theme, default clock are lost every restart. The roadmap also needs a place to put new toggles (metrics, waveform, theme).
- **What:** New `ui/settings_dialog.py` (gear icon in board preview header). Extend `session_config.py` schema with: `window_w`, `window_h`, `speed_factor`, `theme`, `metrics_enabled`, `waveform_enabled`, `recent[]` (last 10 board+vhdl tuples).
- **Touches:** `src/fpga_sim/session_config.py`; `ui/board_display.py` header; new `ui/settings_dialog.py`.
- **Effort:** M/L.

### Tier 2 — High impact, larger initiatives

#### U6. Theme system (light / dark / high-contrast)
- **Why:** All colours hard-coded in `ui/constants.py`; the green PCB clashes with the dark selector; accessibility (high-contrast) is impossible today.
- **What:** Move colours into a `Theme` dataclass, load from JSON, ship 3 presets (`pcb-green` default, `dark`, `high-contrast`). Toggle in the new Settings dialog (U5).
- **Touches:** rewrite `src/fpga_sim/ui/constants.py:14-27`; all `ui/` modules reference `theme.COLOR_X` instead of module constants.
- **Effort:** L (broad reach but mechanical).

#### U7. In-simulation navigation toolbar
- **Why:** Already queued in `project_enhancements.md` (#2). Currently the only way out of sim is ESC; users cannot reload VHDL or change board without restarting.
- **What:** Three buttons in the simulation footer: `[Back to Boards]`, `[Change VHDL]`, `[Reload VHDL]`. `Reload` re-runs `analyze_vhdl()` on the same file and re-enters sim.
- **Touches:** `sim/sim_testbench.py`, `src/fpga_sim/sim_bridge.py` (return code signalling intent), `src/fpga_sim/__main__.py:342-421` (handle new intents).
- **Effort:** L.

#### U8. Splash screen with random board preview
- **Why:** Queued in memory (#3). Adds polish + visual marketing of the board catalogue.
- **What:** Replace the bare `BoardSelector` first paint with a two-panel layout: left = filter list, right = randomly-cycling board preview image from `board_images/`.
- **Touches:** `src/fpga_sim/ui/board_selector.py`.
- **Effort:** M.

#### U9. LED PWM brightness visualisation
- **Why:** Queued in memory (#4). Today LEDs are binary; PWM designs (`hdl/blinky_pwm.vhd` already exists) look broken.
- **What:** Sample LED state N times per displayed frame (e.g. 10 sub-steps), average to a `LED.brightness ∈ [0,1]` float, use to interpolate `RED_OFF`→`RED_ON`.
- **Touches:** `sim/sim_testbench.py` (multiple `dut.led.value` reads per draw), `src/fpga_sim/ui/components.py:116-148` (`LED.draw`).
- **Effort:** M.

#### U10. Waveform capture
- **Why:** Queued in memory (#5). VCD/FST output is the natural complement to live LED viewing for debugging.
- **What:** Add `Waveform: off / VCD / FST` toggle in Settings (U5). On enable: pass `--wave=<path>` (NVC) or `--vcd=<path>` (GHDL `-r`). Show "View in GTKWave" hint after sim ends.
- **Touches:** `src/fpga_sim/sim_bridge.py` (`launch_simulation`), Settings dialog.
- **Effort:** M.

### Tier 3 — Quick wins (ship anytime)

| ID | Item | Files |
|---|---|---|
| U11 | `R` key to reset switches/buttons to default | `ui/board_display.py:402-468` |
| U12 | Show 7-seg digit count in board summary (e.g. `"3 LEDs · 2 SW · 4-digit 7-seg"`) | `ui/board_selector.py:123-127` (extend `BoardDef.summary`) |
| U13 | Arrow / Page-Up / Page-Down navigation in board + file lists | `ui/board_selector.py`, `ui/vhdl_picker.py` |
| U14 | `P` key to pause/resume simulation; pause indicator in SimPanel | `sim/sim_testbench.py`, `ui/sim_panel.py` |
| U15 | Compact mode for `SimPanel` (toggle via existing `S` shortcut family) | `ui/sim_panel.py:283-308` |
| U16 | Enforce minimum window size (800×600) with friendly warning | `__main__.py:179-184` |
| U17 | Pre-allocate common font sizes at startup (eliminates LRU eviction churn) | `ui/constants.py:41-49` |
| U18 | Recent-files section in `VHDLFilePicker` (consumes `recent[]` from U5) | `ui/vhdl_picker.py` |
| U19 | Metrics-enable checkbox surfacing `FPGA_SIM_METRICS` env var | `ui/sim_panel.py` or Settings dialog |

### Tier 4 — Larger features (long-horizon)

#### U20. Verilog / SystemVerilog support
- **Why:** Queued in memory (#1); broadens audience significantly. Icarus Verilog is the natural first target.
- **What:** New file picker extension filter `.v / .sv`, Verilog contract validator, `TOPLEVEL_LANG="verilog"`, new VPI lib, third backend class, example `blinky.v`.
- **Effort:** XL (10–15 h).

#### U21. Board-native VHDL mode (port conventions)
- **Why:** Users currently must write VHDL to our generic contract (`clk`, `sw`, `btn`, `led`, `seg` with `NUM_*` generics). A real DE10-Standard design uses `CLOCK_50`, `KEY(3 downto 0)`, `LEDR(9 downto 0)`, `HEX0`–`HEX5` — these fail `check_vhdl_contract()`, the wrapper, and cocotb signal binding. The `port_conventions` data is already stored in board JSON files (e.g. `boards/custom/de10_standard.json` has a `terasic` convention) but nothing consumes it yet.
- **What:** Three changes, each building on the previous:
  1. **Contract checker** — when the user's VHDL ports don't match the generic contract, attempt to match them against the board's `port_conventions`. If a convention matches, accept the file and record which convention was used.
  2. **Wrapper generator** — generate a port-adapter wrapper that maps between cocotb's signal names (`sw`, `btn`, `led`, `seg`) and the user's actual port names (`KEY`, `LEDR`, `HEX0`–`HEX5`). Handle polarity differences (the convention records `active_low` flags). Handle decomposed 7-seg ports (`individual` style: 6 separate `HEX` ports vs. one packed `seg` vector).
  3. **cocotb testbench** — no change needed if the wrapper does the adaptation; cocotb continues reading `dut.sw`, `dut.btn`, `dut.led`, `dut.seg` from the wrapper, which internally connects to the user's port names.
- **Touches:** `src/fpga_sim/sim_bridge.py` (`check_vhdl_contract`, `_generate_wrapper`, `_choose_wrapper_template`), `sim/sim_wrapper_template.vhd` (or a new template), `boards/schema/board.schema.json` (port_conventions already defined).
- **Sync script merge logic:** When this feature lands, `scripts/sync_boards.py` needs a shallow-merge update: before writing a board JSON, read the existing file (if any) and preserve top-level keys the script didn't generate (`port_conventions`, `peripherals`, etc.). This lets users add conventions directly to `boards/amaranth-boards/*.json` without losing them on re-sync. ~10 lines: read existing → update auto-generated keys → write back.
- **Dependencies:** D1 (single wrapper template) should land first to avoid duplicating the adapter logic across multiple templates.
- **Effort:** L/XL (contract matching is moderate; the wrapper generator for decomposed 7-seg ports is the hard part).

#### U22. 7-segment v2 — physical mux mode
- **Why:** Queued in memory (#8); current v1 is logical-only. v2 enables the hardware-accurate scan interface on Nexys4-DDR, RZ-EasyFPGA, StepMXO2.
- **What:** Third wrapper template, updated testbench readback, new `physical_mux: bool` toggle per board.
- **Effort:** L.

### Performance (mostly already done)

`memory/project_sim_performance.md` documents PR #31's tuning (37.7 fps, 0.0036× real-time on Arty A7-35; GHDL dominates at 98.4 %). Remaining cheap wins:

- **U23.** Dirty-flag redraw — skip `_draw()` when no LED / switch / button / 7-seg state changed since last frame. Touches `sim/sim_testbench.py` draw loop and `ui/board_display.py`. **Effort:** S.
- **U24.** Batch multiple `Timer` calls per frame at high speed-slider settings (today >0.1× is CPU-capped). **Effort:** M.
- **U25.** Profile GHDL GPI vs VHDL eval to find the next bottleneck. **Effort:** investigative.

---

## Part 2 — Developer-facing improvements

### Tier 1 — DRY: collapse the duplications

#### D1. Generate the VHDL wrapper from one source
- **Why:** `sim/sim_wrapper_template.vhd` (62 LOC) and `sim/sim_wrapper_7seg_template.vhd` (55 LOC) share ~80 % of their content — identical clock generation, identical entity boilerplate, only the `seg` port and its mapping differ. Two templates means every wrapper change must be made twice; v2 physical-mux (U21) would make a third file.
- **What:** Pick one approach:
  - **(a) Single template + Python conditional substitution** — keep one `.vhd`, splice the `seg` port + mapping when `design_has_seg`; existing `_generate_wrapper()` already does string substitution.
  - **(b) Jinja2** — heavier dependency, but better fits future mux v2.
- **Recommendation:** (a) — already aligned with current `{toplevel}` placeholder pattern in `sim_bridge.py:405`. Reserve Jinja2 for when there are ≥3 wrapper variants.
- **Touches:** delete `sim/sim_wrapper_7seg_template.vhd`; extend `_generate_wrapper()` in `src/fpga_sim/sim_bridge.py:393-408`; remove `_choose_wrapper_template()`.
- **Effort:** S/M.

#### D2. Backend base class with override-only differences
- **Why:** `_GHDLBackend` and `_NVCBackend` (`sim_bridge.py:65-177`) duplicate 8 method signatures; bodies share structure (`find()` ≡ `shutil.which(self.NAME)`; `lib_dir()` is identical logic in both; `available()` is identical). The `_SimBackend` Protocol declares the shape but does not share implementation.
- **What:** Convert `_SimBackend` from Protocol → ABC; move `find()`, `available()`, `lib_dir()`, `sim_bin_lib()` into the ABC; subclasses override only `NAME`, `plugin_lib_name()`, `analyze_cmd()`, `elaborate_cmd()`, `run_cmd()`.
- **Touches:** `src/fpga_sim/sim_bridge.py:33-185`. Net reduction ~50 LOC.
- **Effort:** S/M. Existing test suite (`tests/test_sim_bridge_backend.py`) already covers both backends — refactor is safe under it.

#### D3. UIComponent base class
- **Why:** `LED`, `Switch`, `Button` in `components.py:116-233` share an identical `__init__(index, info)` signature, identical `label` property logic, and an identical `callback` attribute pattern. `SevenSeg` is similar but uses `(index, has_dp)`.
- **What:** Abstract base `UIComponent` with `index`, `info`, `rect`, `label` property; subclass-specific `state` / `pressed` / `bits` stay in children. Optional: register components into a single `board.components: list[UIComponent]` for unified hit-testing.
- **Touches:** `src/fpga_sim/ui/components.py`; small cleanup in `ui/board_display.py`.
- **Effort:** S.

#### D4. Shared button-drawing helper
- **Why:** Footer buttons in `board_display.py:553-616` and `sim_panel.py:538-559` redraw rectangles with near-identical code; styling drift is already visible (different hover colours).
- **What:** Extract `ui/widgets/button.py: Button.draw_rect(surface, rect, label, state)` with consistent hover/pressed colours. Reuse in the board_display footer, sim_panel zones, and the new help/settings dialogs.
- **Touches:** new file; replace open-coded draws in two callers.
- **Effort:** S.

#### D5. Platform-aware path helper
- **Why:** `_build_sim_env()` (`sim_bridge.py:493-551`) repeats the PATH-prepend pattern for Windows and Linux; the `IS_WINDOWS` branching is interleaved with logic that doesn't actually differ.
- **What:** Extract `_compose_path(extra: list[str], var: str = "PATH") -> str`; flatten Windows/Linux branches to differ only in their `extra` list contents.
- **Touches:** `src/fpga_sim/sim_bridge.py:493-551`. Modest LOC reduction, large clarity win.
- **Effort:** S.

### Tier 2 — Architecture & state

#### D6. Extract a `ScreenController` from `__main__.py`
- **Why:** `main()` in `__main__.py:171-425` is a 254-line `while`-loop juggling 4 screen states with implicit transitions (`_return_to_board`, `current_vhdl_path`, `current_work_dir`, `_work_dir_simulator`, `_back_to_boards`, `_new_path`, `_first_pick`, `_intent`). Reading it requires holding all of that in your head; the nested VHDL-picker loop at lines 285-326 hits 4 levels of indentation.
- **What:** Two refactors, sequenced:
  - **D6a.** Replace the stringly-typed screen results (`"back"`, `"load_vhdl"`, `"simulate"`, `"quit"`, `"retry"`) with a `ScreenResult` enum. Same in error dialog (`"back"` / `"retry"`).
  - **D6b.** Lift the loop body into a `ScreenController` class with explicit transition methods (`on_board_selected`, `on_vhdl_loaded`, `on_simulate`, `on_back`) and a `SessionState` dataclass holding the VHDL / work-dir / simulator tuple.
- **Touches:** `src/fpga_sim/__main__.py`; new `src/fpga_sim/controller.py`; enums in `src/fpga_sim/ui/__init__.py`.
- **Effort:** M (D6a) + L (D6b). Do D6a first as it cleanly unblocks D6b.

#### D7. Decompose `launch_simulation()`
- **Why:** `sim_bridge.py:553-648` mixes env construction, generic injection, NVC re-elaboration, env-var marshalling, and subprocess invocation — ~100 LOC.
- **What:** Split into `_prepare_run_env(board_json, vhdl_path, generics, sim_dims) → env, cmd` and `_invoke_run(cmd, env, cwd) → bool`. Makes env construction unit-testable.
- **Touches:** `src/fpga_sim/sim_bridge.py:553-648`; new tests in `tests/test_sim_bridge_backend.py`.
- **Effort:** M.

### Tier 3 — Type safety & tooling

#### D8. mypy strict mode
- **Why:** `pyproject.toml` has `disallow_incomplete_defs = true` but not `strict = true`. Strict mode catches incomplete type guards, missing returns in complex branches, untyped `**kwargs`. The codebase is already well-annotated — the upgrade should produce a manageable error list.
- **What:** Flip to `strict = true`; fix the resulting errors (likely concentrated in `board_loader.py` mock classes and `sim_testbench.py`).
- **Touches:** `pyproject.toml` (mypy section); scattered annotations.
- **Effort:** M (mostly fixing reported errors).

#### D9. `Literal` types for stringly-typed identifiers
- **Why:** `simulator: str = "ghdl"` everywhere; nothing prevents a typo passing through.
- **What:** Define `Simulator = Literal["ghdl", "nvc"]`; thread through `analyze_vhdl`, `launch_simulation`, `_backend`, `detect_simulators` return type, session config.
- **Touches:** `src/fpga_sim/sim_bridge.py`, `src/fpga_sim/session_config.py`, `src/fpga_sim/__main__.py`.
- **Effort:** S.

#### D10. Pin pre-commit hooks consistently; add `.editorconfig`
- **Touches:** `.pre-commit-config.yaml`; new `.editorconfig`.
- **Effort:** XS.

### Tier 4 — Documentation

#### D11. Module + mock-class docstrings
- **Why:** `board_loader.py:17-150` mock classes (`_Attrs`, `_Pins`, `_PinsN`, `_DiffPairs`, `_Clock`, `_Subsignal`, `_Connector`, `_Resource`) are 130+ LOC with no docstrings — they are the most arcane code in the project (they exist to fool amaranth-boards `.py` files into executing in a mock namespace). Future maintainers will burn an hour reverse-engineering them.
- **What:** Module docstring on `board_loader.py` explaining the mock-namespace strategy; one-line docstring on each mock class.
- **Touches:** `src/fpga_sim/board_loader.py:17-150`; `src/fpga_sim/sim_metrics.py` (currently placeholder); `src/fpga_sim/ui/sim_panel.py` (no module docstring).
- **Effort:** S.

#### D12. Architecture diagram in CONTRIBUTING.md
- **Why:** CLAUDE.md has a great file-role table; CONTRIBUTING.md has install steps but no architecture overview for contributors. An ASCII data-flow diagram would lower the on-ramp.
- **What:** Add an "Architecture overview" section with launcher/sim phase diagram, the `BoardDef` / `ComponentInfo` / `SevenSegDef` dataclasses, and the VHDL contract summary.
- **Touches:** `CONTRIBUTING.md`.
- **Effort:** S.

### Tier 5 — Tests

#### D13. Platform-specific `_build_sim_env` coverage
- **Why:** `tests/test_sim_bridge_backend.py` doesn't exercise the Windows vs Linux PATH / PYTHONHOME divergence; bugs there only surface on the actual platform.
- **What:** Parametrise tests with `monkeypatch` on `sim_bridge.IS_WINDOWS`; assert env dict shape for both branches.
- **Touches:** `tests/test_sim_bridge_backend.py`.
- **Effort:** S.

#### D14. Session-config edge cases
- **What:** Tests for missing file, malformed JSON, schema migration (when U5 expands the schema).
- **Touches:** `tests/test_session_config.py`.
- **Effort:** S.

---

## Suggested merge order

A practical sequencing if all items were in flight (impact-weighted, with foundations early enough to unblock later work):

| Sprint | Theme | Items |
|---|---|---|
| **1** | Highest-impact / cheapest wins | U1 Help dialog · U2 Analysis spinner · U11 Reset key · U12 Board summary · D1 Wrapper template merge · D2 Backend base class · D9 Literal types · D11 Mock-class docstrings |
| **2** | Foundations that unblock later UX | D6a Screen-result enum · D6b ScreenController · U5 Settings dialog + extended session · D8 mypy strict |
| **3** | Visible polish | U3 Tooltips · U4 Contextual errors · U6 Theme system · U7 In-sim toolbar |
| **4** | Feature breadth | U8 Splash · U9 PWM brightness · U10 Waveform · U23 Dirty-flag redraw |
| **Long-horizon** | — | U20 Verilog support · U21 Board-native VHDL · U22 7-seg physical mux · U24 / U25 Performance deep-dive |

---

## Critical files modified across the roadmap

- `src/fpga_sim/__main__.py` — U1, U2, U7, D6, D9
- `src/fpga_sim/sim_bridge.py` — U4, U10, U21, D1, D2, D5, D7, D9
- `src/fpga_sim/board_loader.py` — D11; U12 (summary extension)
- `src/fpga_sim/session_config.py` — U5, U18, D9, D14
- `src/fpga_sim/ui/constants.py` — U6, U17
- `src/fpga_sim/ui/components.py` — U3, U9, D3
- `src/fpga_sim/ui/board_display.py` — U3, U11, U16, D3, D4
- `src/fpga_sim/ui/board_selector.py` — U1, U8, U12, U13
- `src/fpga_sim/ui/sim_panel.py` — U14, U15, U19, D4, D11
- `src/fpga_sim/ui/vhdl_picker.py` — U13, U18
- `src/fpga_sim/ui/error_dialog.py` — U4
- New: `src/fpga_sim/ui/help_dialog.py` (U1), `ui/settings_dialog.py` (U5), `ui/tooltip.py` (U3), `ui/widgets/button.py` (D4), `src/fpga_sim/controller.py` (D6)
- `sim/sim_wrapper_template.vhd` — D1 (absorbs 7seg template)
- `sim/sim_wrapper_7seg_template.vhd` — D1 (deleted)
- `sim/sim_testbench.py` — U7, U9, U14, U22
- `pyproject.toml` — D8
- `.pre-commit-config.yaml`, new `.editorconfig` — D10
- `CONTRIBUTING.md` — D12

## Existing utilities to reuse

- `ErrorDialog` modal pattern (`ui/error_dialog.py`) → reuse layout for help / settings / tooltip dialogs.
- `get_font()` LRU cache (`ui/constants.py:41-49`) → already used everywhere; pre-allocation in U17 just primes it.
- `_choose_wrapper_template()` / `_generate_wrapper()` (`sim_bridge.py:386-408`) → already does template substitution; D1 extends it instead of replacing.
- `_SimBackend` Protocol (`sim_bridge.py:33-62`) → becomes ABC base in D2 with no caller changes.
- `session_config.save_session` / `load_session` (`session_config.py`) → extend schema for U5; existing call sites unchanged.
- `sim_metrics.py` / `scripts/analyze_metrics.py` → consumed by U19; no new infra needed.
- `BoardDef.summary` property (`board_loader.py`) → extend for U12.

---

## Verification

Per-item verification is described in each entry above. Cross-cutting checks for any merge:

1. **Tests** — `uv run pytest` (225+ tests including UI scaling, board loader, both backends, 7-seg). All sprints must keep this green.
2. **Lint / type** — `uv run ruff check .` and `uv run mypy src/` (the latter tightens under D8).
3. **Manual smoke** — `uv run fpga-sim` end-to-end on a known board (e.g. Arty A7-35) with `hdl/blinky.vhd`; for 7-seg work use `counter_7seg.vhd` on DE10-Lite.
4. **Benchmark regression** — `uv run fpga-sim --benchmark 10` before/after performance-touching merges (U22 / U23). Baseline: 37.7 fps, 0.0036× real-time on Arty A7-35 (from `memory/project_sim_performance.md`).
5. **Headless CI** — every PR runs the existing Linux + Windows × GHDL + NVC × Py 3.10–3.12 matrix.
6. **Visual checks** — for UI work, screenshot the affected screen on Linux and attach to the PR; no automated visual diff today.
