# Virtual FPGA Boards — Improvement Roadmap

*Drafted 2026-05-19 · Updated 2026-06-01 · Status: draft for review · Companion to CHANGELOG.md / CONTRIBUTING.md*

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
3. **DRY drift.** Two near-identical backend classes, three component classes with identical structure, and a 264-line main function with stringly-typed screen results. Colour definitions have likewise drifted out of their single source of truth: 14 named shades in `ui/constants.py` vs ~98 distinct inline RGB literals across 8 files (D15). *(VHDL wrapper templates unified in D1.)*
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

#### U1. Help / About overlay (clickable `(?)` button · F1 · `?`)
- **Why:** Currently nothing in-app teaches the user the workflow or shortcuts; README is great but invisible at runtime.
- **What:** Modal overlay with a 4-step workflow diagram, keyboard shortcut legend, the design-contract summary, and a pointer to `hdl/blinky.vhd` as a working example.
- **Triggers (decided 2026-05-31): a clickable `(?)` button + F1 + `?`, all opening the same overlay.** Three triggers because the audience is mixed — new users need a *visible* affordance, power users want a hotkey:
  - **`(?)` button** — the primary *discovery* path (U1 targets onboarding; a hidden hotkey is invisible to exactly those users). Top-right of the selector header (the title row at `board_selector.py:355-356` has free space on the right) and in the preview (corner `(?)` or via the footer). Render with the D4 shared button helper.
  - **F1** — universal GUI convention; non-printable, so it never conflicts on any screen.
  - **`?`** — keyboard-app convention (Gmail / GitHub / Vim / `less`). Already free on the preview, picker, and sim screens (no text input there). On the **selector** it must be intercepted in `BoardSelector._handle_keydown()` *before* the printable-append branch (`self.filter_text += ev.unicode`); match on `ev.unicode == "?"` (keyboard-layout-independent, unlike `Shift+/`) so it never reaches the filter. Reserving `?` costs nothing — no board name contains it.
- **Legend must reflect shortcuts that actually exist when U1 ships.** As of 2026-05-31 the real shortcuts are: F1 / `?` (this overlay), ESC (back/cancel, all screens), Enter (Start Simulation on the preview; "Try Another File" in ErrorDialog), R (reset switches/buttons — preview only, `board_display.py:417`), S (toggle SimPanel — *simulation screen only*, `sim_testbench.py:370`), plus type-to-filter and mouse-wheel scroll on the selector. **U13 (arrow/Page nav + Enter-to-select) shipped 2026-06-01**, so the legend must now list ↑/↓/PgUp/PgDn (navigate) and Enter (select) on the selector + picker as real, existing shortcuts. **P (pause) still does NOT exist** — it's a mouse-only overlay button in the sim screen, and the P key is U14, so omit P unless U14 lands first. **Implementation:** render the legend from a single `SHORTCUTS` constant so every future key (U13/U14/U15) has one obvious place to update — the structural guard against the legend drifting from the real handlers.
- **Touches:** new `src/fpga_sim/ui/help_dialog.py` (register in `ui/__init__.py`), reusing the `ErrorDialog` snapshot-dim-centred-panel structure (`error_dialog.py`) for layout. Key wiring — match F1 and `?` in each screen's keydown handler (U13 extracted `_handle_keydown()` on both list screens): `BoardSelector._handle_keydown()` (intercept `?` *above* the printable-append branch), `board_display.py:413-429` (`_handle_events`), `VHDLFilePicker._handle_keydown()` (ESC / arrows / Enter today). Button — add a hit-rect + draw in `board_selector._draw()` header and `board_display._draw()` footer, with click handling in `BoardSelector._click()` and `FPGABoard._handle_events()`.
- **Scope note:** The simulation screen is a *separate pygame process* (`sim/sim_testbench.py`, its own event loop at line ~367). Decide whether F1 / `?` help is in scope there too; if so it needs a fourth handler in `sim_testbench.py`. The launcher screens (selector / preview / picker) are the minimum.
- **Effort:** M (modal + three trigger types across three screens + a `(?)` button widget).
- **Dependencies:** Soft: **D4** (shared button helper) — the `(?)` trigger button and the overlay's Close button should both use it; landing D4 first avoids open-coding two more buttons.
- **Done when:** the `(?)` button (selector + preview), F1, and `?` each open the help overlay on the launcher screens; while it is open the underlying screen receives no input (run it as its own blocking loop like `ErrorDialog`, so a keystroke can't leak into the board filter); the overlay lists the shortcuts that exist at ship time; ESC, the Close button, or clicking outside dismisses it.

#### U2. Inline analysis spinner during VHDL load
- **Why:** `analyze_vhdl()` can hang silently for 5–10 s with no UI feedback; users assume the app is frozen. (`check_vhdl_encoding()` / `check_vhdl_contract()` are text-only and instant — only `analyze_vhdl()` is slow, so the spinner only needs to cover that call.)
- **What:** Non-blocking "Analyzing <file>..." overlay with a rotating spinner while `analyze_vhdl()` runs.
- **Risk / correction:** pygame is not thread-safe for rendering. Do **not** use a background thread that touches the display surface. ⚠️ The previous draft said "the analysis subprocess is already a `subprocess.run()` call — converting to `Popen` + poll loop is straightforward." That is **no longer accurate**: `analyze_vhdl()` (`sim_bridge.py:425-505`) makes **three** sequential `subprocess.run()` calls — analyse user VHDL (`:453`), analyse the generated wrapper (`:468`), elaborate (`:481`) — interleaved with Python file I/O (`_generate_wrapper`). So you cannot simply swap one `subprocess.run` for `Popen`. Two viable approaches: **(a)** run the whole `analyze_vhdl()` on a worker thread (it touches no pygame — only subprocesses + file I/O) and poll the thread/`Future` from the main loop, rendering the spinner on the main thread; or **(b)** have `analyze_vhdl()` accept an optional progress callback and convert its three steps to `Popen` + `poll()` internally. (a) is the smaller change and keeps the "no bg thread touches the display" rule intact.
- **Touches:** `src/fpga_sim/__main__.py` has **two** launcher call sites for `analyze_vhdl()`: the Load-VHDL path at `:330-332` (inside the picker `while` loop, encoding/contract checks at `:321-327`) and the re-analyse-before-simulate path at `:380-382`. Cover both for consistent feedback. New spinner helper in `ui/`. (The benchmark path `:145` is headless and needs no spinner.)
- **Effort:** M.
- **Dependencies:** None.
- **Done when:** a spinner/overlay is visible during VHDL analysis at both call sites and disappears when analysis completes or fails.

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
- **Why:** The green PCB clashes with the dark selector, and accessibility (high-contrast) is impossible today. **Premise correction (2026-05-31):** an earlier draft said "all colours hard-coded in `ui/constants.py`" — they are *not*. Only 14 of ~98 shades live there; the rest are scattered across 8 files (see D15). A theme switch cannot work until the palette is centralised, so this now builds on D15.
- **What:** Once D15 has consolidated the palette, move it into a `Theme` dataclass, load from JSON, and ship 3 presets (`pcb-green` default, `dark`, `high-contrast`). Toggle in the new Settings dialog (U5).
- **Touches:** `src/fpga_sim/ui/constants.py` (D15's consolidated palette → `Theme`); all `ui/` modules **and** `sim/sim_testbench.py` reference `theme.COLOR_X` instead of module constants.
- **Effort:** L **assuming D15 lands first** (then it is the broad-but-mechanical pass). Without D15 it is XL and would ship visibly broken — ~88 % of colours would stay hard-coded and silently fail to retheme.
- **Dependencies:** **Requires U5** (theme toggle lives in Settings dialog) **and D15** (palette must be centralised before it can be themed).
- **Done when:** three themes are selectable in Settings; all UI screens (selector, preview, sim, dialogs) render correctly with each; no themed screen reads a colour literal outside the `Theme`.

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
| ~~U13~~ | ~~Arrow / Page-Up / Page-Down navigation in board + file lists~~ ✅ | `ui/board_selector.py`, `ui/vhdl_picker.py` | S |
| U14 | `P` key to pause/resume simulation; pause indicator in SimPanel | `sim/sim_testbench.py`, `ui/sim_panel.py` | S |
| U15 | Compact mode for `SimPanel` (toggle via existing `S` shortcut family) | `ui/sim_panel.py:282-308` | S |
| U16 | Enforce minimum window size (800x600) with friendly warning | `__main__.py:184-187` | XS |
| U17 | Pre-allocate common font sizes at startup (eliminates LRU eviction churn) | `ui/constants.py:41-49` | XS |
| U18 | Recent-files section in `VHDLFilePicker` (consumes `recent[]` from U5) | `ui/vhdl_picker.py` | S |
| U19 | Metrics-enable checkbox surfacing `FPGA_SIM_METRICS` env var | `ui/sim_panel.py` or Settings dialog | XS |

**Note on U12:** `BoardDef.summary` already includes 7-seg digit count as of v0.5.0. Remaining work is the formatting change (dot separators, abbreviated labels).

**Note on U18/U19:** Both require U5 (Settings dialog) for the `recent[]` data source and metrics toggle location respectively.

**Note on U13 — done (2026-06-01):** Shipped keyboard navigation on both list screens. `board_selector.run()` and `vhdl_picker.run()` now delegate each KEYDOWN to a unit-testable `_handle_keydown()` returning `(exit_loop, value)`; `↑`/`↓` and `PgUp`/`PgDn` move the `self.hovered` cursor (auto-scrolled into view via the new `_ensure_visible`/`_page_rows` helpers, with no selection Down enters at top / Up at bottom), and `Enter`/`KP_Enter` activates the hovered row (select board · open dir · pick file). On the selector an open sort dropdown captures `↑`/`↓`/`Enter` while mouse interaction still works, and typing/Backspace still close it and edit the filter (cursor resets on filter change). The picker's click and Enter paths now share one `_activate()` helper. 32 new tests across `test_board_selector.py` + new `test_vhdl_picker.py`.

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
- **Why:** `_GHDLBackend` (`sim_bridge.py:71-120`) and `_NVCBackend` (`:123-183`) duplicate 8 method signatures; bodies share structure. `find()` differs only by the executable name (`shutil.which("ghdl")` vs `shutil.which("nvc")`, both equal to `NAME`); `available()`, `lib_dir()`, and `sim_bin_lib()` are byte-for-byte identical apart from the `_GHDLBackend.find()` / `_NVCBackend.find()` call inside them. The `_SimBackend` Protocol (`:39-68`) declares the shape but does not share implementation.
- **What:** Convert `_SimBackend` from Protocol -> ABC; move `find()`, `available()`, `lib_dir()`, `sim_bin_lib()` into the ABC; subclasses override only `NAME`, `plugin_lib_name()`, `analyze_cmd()`, `elaborate_cmd()`, `run_cmd()`. Optionally narrow `_backend()`'s return type (`:186`) from `type[_GHDLBackend] | type[_NVCBackend]` to `type[_SimBackend]`.
- **⚠️ `@staticmethod` -> `@classmethod` conversion required.** Today *every* backend method is a `@staticmethod` and hardcodes its own class (e.g. `lib_dir()` calls `_GHDLBackend.find()`). To hoist the four shared methods into the ABC they must read `cls.NAME` / call `cls.find()`, so they become `@classmethod`. Callers already use class-level access (`be.find()` where `be = _backend(...)`), so this is source-compatible at the call sites.
- **⚠️ This refactor is NOT safe under the current test suite — a test must change.** `tests/test_sim_bridge_backend.py:24-34` (`test_backend_has_all_protocol_methods`) explicitly asserts, via `inspect.getattr_static`, that **all 8 protocol methods are `@staticmethod`**. Converting `find`/`available`/`lib_dir`/`sim_bin_lib` to `@classmethod` makes that assertion fail. Update the test to allow `staticmethod` *or* `classmethod` for the hoisted methods (the `run_cmd`/`elaborate_cmd` signature-parity tests at `:40-53` are unaffected since those stay as subclass overrides).
- **Touches:** `src/fpga_sim/sim_bridge.py:39-191` (Protocol + both backends + `_backend()`); `tests/test_sim_bridge_backend.py` (relax the staticmethod assertion). Net reduction ~30-50 LOC in `sim_bridge.py`.
- **Effort:** S/M.
- **Dependencies:** None. But **U20** depends on this.
- **Done when:** `_SimBackend` is an ABC with shared implementations; `_GHDLBackend` and `_NVCBackend` override only the 5 members that differ (`NAME` + 4 methods); the staticmethod assertion in `test_sim_bridge_backend.py` is updated; all backend tests pass.

#### D3. UIComponent base class
- **Why:** `LED`, `Switch`, `Button` in `components.py:116-233` share an identical `__init__(index, info)` signature, identical `label` property logic, and an identical `callback` attribute pattern. `SevenSeg` is similar but uses `(index, has_dp)`.
- **What:** Abstract base `UIComponent` with `index`, `info`, `rect`, `label` property; subclass-specific `state` / `pressed` / `bits` stay in children. Optional: register components into a single `board.components: list[UIComponent]` for unified hit-testing.
- **Touches:** `src/fpga_sim/ui/components.py`; small cleanup in `ui/board_display.py`.
- **Effort:** S.
- **Dependencies:** None. Soft: simplifies U3 (tooltips can use unified hit-testing).
- **Done when:** `LED`, `Switch`, `Button` inherit from `UIComponent`; no duplicate `__init__` / `label` code; all component tests pass.

#### D4. Shared button-drawing helper ✅
- **Completed:** 2026-05-31. Added `src/fpga_sim/ui/widgets/button.py` (`ButtonStyle` + `draw_button`) and routed all four sites through it — board_display footer, error_dialog, sim_panel clock steppers, and the sim `[■ Stop]`/`[Pause]` overlay; deleted `sim_panel._draw_btn`. The clock steppers gained hover feedback; visuals otherwise preserved. New `tests/test_button_widget.py` (7 tests); full suite (900 tests) green.
- **Why:** Four button-drawing sites (across *both* processes) hand-roll rounded-rect buttons with near-identical but drifting code — even the corner radius varies (3 / 5 / 6 / 10). The drift is real and visible:
  - `board_display.py:568-644` — four footer buttons (Select Board `:571-579`, Load VHDL `:582-590`, Start Simulation `:596-612`, SIM toggle `:614-631`), each with its **own** hover colour scheme (teal / blue / green / purple) and a disabled state.
  - `error_dialog.py:160-182` — Try-Another-File / Back-to-Boards buttons, open-coded with hover.
  - `sim_panel.py:538-559` — already factored into a local `_draw_btn()` helper, but **enabled/disabled only, no hover at all** (the [-]/[+] clock buttons).
  - `sim/sim_testbench.py:439-466` — the `[■ Stop]` / `[Pause]` overlay buttons (with hover), in the **simulation subprocess**. (The previous draft missed both this caller and `error_dialog`.)
  So it is not "two open-coded callers." D4 should unify all four onto one helper and delete `sim_panel._draw_btn`.
- **Cross-process note:** `sim_testbench.py` runs in the GHDL/cocotb subprocess but already imports `fpga_sim` (its `src/` is on `PYTHONPATH` — see `sim_bridge._build_sim_env`), so a `fpga_sim.ui.widgets.button` helper is importable there; the Stop/Pause buttons can use it too.
- **What:** Extract `ui/widgets/button.py` (new `widgets/` subpackage — does not exist yet). The signature needs more than `(surface, rect, label, state)`: the callers use **different base colours**, so pass an explicit colour set (base / hover / border / fg) or named variants, plus flags for `hovered` and `enabled`. A bare `state` enum can't capture the per-button theming that exists today.
- **Touches:** new `src/fpga_sim/ui/widgets/button.py` (+ `widgets/__init__.py`); replace open-coded draws in `board_display.py`, `error_dialog.py`, and `sim/sim_testbench.py`; replace `sim_panel.py`'s `_draw_btn`. Add a unit test for the helper (colour/hover/disabled variants render without error and respect the passed rect).
- **Effort:** S/M (four callers across two processes).
- **Dependencies:** None. Soft: **U1, U5, U7** should consume it for consistent styling. **Land D4 first in 1b** — U1's `(?)` + Close buttons ride on it, and the same pass gives the sim Stop/Pause + clock buttons consistent styling.
- **Done when:** the board_display footer, error_dialog buttons, sim_panel clock buttons, and the sim Stop/Pause overlay all render through the shared helper; hover behaviour is consistent (and the sim_panel clock buttons gain the hover feedback they lack today).

#### D5. Platform-aware path helper
- **Why:** `_build_sim_env()` (`sim_bridge.py:493-550`) repeats the PATH-prepend pattern for Windows and Linux; the `IS_WINDOWS` branching is interleaved with logic that doesn't actually differ.
- **What:** Extract `_compose_path(extra: list[str], var: str = "PATH") -> str`; flatten Windows/Linux branches to differ only in their `extra` list contents.
- **Touches:** `src/fpga_sim/sim_bridge.py:493-550`. Modest LOC reduction, large clarity win.
- **Effort:** S.
- **Dependencies:** None.
- **Done when:** `_build_sim_env()` has no interleaved `if IS_WINDOWS` blocks; platform differences are isolated to the `extra` path lists.

#### D15. Consolidate scattered colours into the single source of truth
- **Why:** `ui/constants.py` was created as the one home for colours, but it has drifted: as of 2026-05-31 it names **14** shades while **~98 distinct** shades (102 inline RGB literals) live across 8 other files (`board_display.py`, `sim_panel.py`, `board_selector.py`, `components.py`, `error_dialog.py`, `vhdl_picker.py`, `sim/sim_testbench.py`, `generate_board_images.py`) — the source of truth holds ~12 % of the palette. The drift has three shapes, each with a different fix:
  - **(a) Exact-duplicate regressions (~12 literals).** A name exists and was ignored: `GRAY=(180,180,180)` hard-coded 3×, `RED_OFF=(80,0,0)` 2×, `SEL_BG=(30,30,40)` 2×, plus `BLACK`/`WHITE`/`BLUE_ON`/`SEL_ROW_A`/`DARK_GRAY`/`SEL_HOVER` once each. Changing the constant today silently desyncs these call sites.
  - **(b) Parallel constant blocks.** `board_selector.py:16-26` defines 11 module-level `_CHIP_*`/`_SORT_*`/`_DROPDOWN_*` colours; `board_display.py:38-65` defines `_STYLE_*` `ButtonStyle` tuples. The right *grouping* instinct in the wrong *location*.
  - **(c) Cross-process copy-paste.** The PCB-blue gradient pair `(20,60,110)`/`(30,80,140)` is hand-typed in **both** the launcher (`board_display.py`) and the sim subprocess (`sim/sim_testbench.py`), even though `sim_testbench` already imports `fpga_sim`.
- **What:** Re-centralise in three passes: **(1)** replace the ~12 exact-duplicate literals with their existing constant names; **(2)** lift shared shades — starting with the cross-process gradient pair — into `constants.py` and import them in both processes; **(3)** restructure the flat list into a small **palette + semantic roles** (fold the `_CHIP_*`/`_STYLE_*` families in as namespaced groups), deciding per one-off whether it earns a name or is genuinely single-use (a truly local shade may stay inline with a comment). The grouped structure is deliberately the shape U6's `Theme` dataclass wants, so this de-risks U6. (Optional: if the palette grows large, split a dedicated `ui/theme.py` and re-export from `constants.py` for compatibility.)
- **Touches:** `src/fpga_sim/ui/constants.py` (grouped palette); colour call sites in `ui/board_display.py`, `ui/board_selector.py`, `ui/sim_panel.py`, `ui/components.py`, `ui/error_dialog.py`, `ui/vhdl_picker.py`, `sim/sim_testbench.py`, `src/fpga_sim/generate_board_images.py`.
- **Effort:** S/M. Pass (1) is mechanical; the judgement is in pass (3)'s grouping — worth a short design note in the PR.
- **Dependencies:** None. But **U6** builds directly on it (see Dependencies).
- **Done when:** no inline literal duplicates a named constant; the cross-process gradient pair is defined once and imported in both processes; `constants.py` exposes a grouped palette; a grep for RGB tuples outside `constants.py` returns only genuinely single-use shades, each commented as such.

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

#### D9. `Literal` types for stringly-typed identifiers ✅
- **Why:** `simulator: str = "ghdl"` everywhere; nothing prevents a typo passing through.
- **What:** Define `Simulator = Literal["ghdl", "nvc"]`; thread through `analyze_vhdl`, `launch_simulation`, `_backend`, `detect_simulators` return type, session config.
- **Touches:** `src/fpga_sim/sim_bridge.py`, `src/fpga_sim/session_config.py`, `src/fpga_sim/__main__.py`.
- **Effort:** S.
- **Dependencies:** None. Soft: should be extended to include `"iverilog"` when U20 lands.
- **Done when:** `Simulator` is a `Literal` type; mypy catches `_backend("typo")` at type-check time.

#### D10. Pin pre-commit hooks consistently; add `.editorconfig` ✅
- **Completed:** Sprint 1a cleanup — added `.editorconfig` (Python 4-space / 100-col, matching ruff); hooks were already pinned to exact versions (`ruff v0.15.13`, `mypy v2.1.0`).
- **Touches:** `.pre-commit-config.yaml`; new `.editorconfig`.
- **Effort:** XS.
- **Dependencies:** None.
- **Done when:** all hooks are pinned to exact versions; `.editorconfig` is consistent with existing ruff/formatter config.

### Tier 4 — Documentation

#### D11. Module + mock-class docstrings ✅
- **Why:** `board_loader.py:17-124` mock classes (`_Attrs`, `_Pins`, `_PinsN`, `_DiffPairs`, `_Clock`, `_Subsignal`, `_Connector`, `_Resource`) are ~108 LOC with no docstrings — they are the most arcane code in the project (they exist to fool amaranth-boards `.py` files into executing in a mock namespace). Future maintainers will burn an hour reverse-engineering them.
- **What:** Expanded the `board_loader.py` module docstring to explain the exec-in-mock-namespace strategy; added one-line docstrings on the eight mock classes, the resource helpers (`_split_resources` + the led/button/switch/rgb wrappers), and `_make_namespace()`.
- **Touches:** `src/fpga_sim/board_loader.py` only. (The card originally also listed `sim_metrics.py` "(currently placeholder)" and `ui/sim_panel.py` "(no module docstring)", but both already had full module docstrings — those claims were stale and were dropped.)
- **Effort:** S.
- **Dependencies:** None.
- **Done when:** every mock class, resource helper, and `_make_namespace()` has a docstring; the module docstring explains the exec-in-mock-namespace strategy and when it runs (the `sync_*` scripts and `discover_boards`' legacy `.py` fallback, vs. the primary JSON path).

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
| **U6** (Theme system) | **D15** (Colour consolidation) | Palette must live in one place before it can be themed |
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
| **U1** (Help dialog) | **D4** (Shared button helper) ✅ | Consistent "Close" button styling |
| **U3** (Tooltips) | **D3** (UIComponent base) | Unified hit-testing across component types |
| **U5** (Settings dialog) | **D4** (Shared button helper) ✅ | Reuse button rendering in dialog |
| **U7** (In-sim toolbar) | **D4** (Shared button helper) ✅ | Consistent toolbar button styling |
| **U8** (Splash) | **U0** (Board filtering) | Left panel already has filter chips |
| ~~**D9** (Literal types)~~ ✅ | — | Extend the `Simulator` alias in `sim_bridge.py` to add `"iverilog"` when U20 lands |
| **D13** (Env tests) | **D5** (Path helper) | Cleaner branches are easier to test |

### Dependency graph (hard dependencies only)

```
D1 (wrapper merge) ✅ — U21 and U22 are now unblocked

D2 (backend ABC)
 └──> U20 (Verilog support)

U5 (settings dialog)
 ├──> U6  (theme system)        # U6 also requires D15 (below)
 ├──> U10 (waveform capture)
 ├──> U18 (recent files)
 └──> U19 (metrics checkbox)

D15 (colour consolidation)
 └──> U6  (theme system)

D6a (screen-result enum)
 └──> D6b (ScreenController)
```

All other items (U0, U1, U2, U3, U4, U7, U8, U9, U11-U17, U21-U25, D3-D5, D7-D15) are independently shippable.

---

## Suggested merge order

A practical sequencing if all items were in flight (impact-weighted, with foundations early enough to unblock later work). Sprint 1 is split into two sub-sprints to keep batch sizes manageable (~8-12 h each).

| Sprint | Theme | Items |
|---|---|---|
| **1a** | Quickest wins + foundations | ~~U0 Board filtering~~ ✅ · ~~U11 Reset key~~ ✅ · ~~U12 Board summary format~~ ✅ · ~~D1 Wrapper template merge~~ ✅ · ~~D9 Literal types~~ ✅ · ~~D10 .editorconfig + hook pins~~ ✅ · ~~D11 Mock-class docstrings~~ ✅ |
| **1b** | Small features + DRY foundations | ~~D4 Shared button helper~~ ✅ → ~~U13 Arrow/Page nav~~ ✅ → U1 Help dialog · U2 Analysis spinner · D2 Backend base class |
| **2** | Foundations that unblock later UX | D6a Screen-result enum · D6b ScreenController · D15 Colour consolidation · U5 Settings dialog + extended session · D8 mypy strict |
| **3** | Visible polish | U3 Tooltips · U4 Contextual errors · U6 Theme system · U7 In-sim toolbar |
| **4** | Feature breadth | U8 Splash · U9 PWM brightness · U10 Waveform · U23 Dirty-flag redraw |
| **Long-horizon** | — | U20 Verilog support · U21 Board-native VHDL · U22 7-seg physical mux · U24 / U25 Performance deep-dive |

---

## Critical files modified across the roadmap

- `src/fpga_sim/__main__.py` — U1, U2, U7, D6, D9 ✅
- `src/fpga_sim/sim_bridge.py` — U4, U10, U21, D1, D2, D5, D7, D9 ✅ (defines `Simulator`)
- `src/fpga_sim/board_loader.py` — U12, D11 ✅
- `src/fpga_sim/session_config.py` — U5, U18, D9 ✅, D14
- `src/fpga_sim/ui/constants.py` — D15, U6, U17
- `src/fpga_sim/ui/components.py` — U3, U9, D3, D15
- `src/fpga_sim/ui/board_display.py` — U1, U3, U11, U16, D3, D4 ✅, D9 ✅ (simulator round-trips through `FPGABoard`), D15
- `src/fpga_sim/ui/board_selector.py` — U0, U1, U8, U12, U13 ✅, D15
- `src/fpga_sim/ui/sim_panel.py` — U14, U15, U19, D4 ✅, D15
- `src/fpga_sim/ui/vhdl_picker.py` — U1, U13 ✅, U18, D15
- `src/fpga_sim/ui/error_dialog.py` — U4, D4 ✅, D15
- New: `src/fpga_sim/ui/help_dialog.py` (U1), `ui/settings_dialog.py` (U5), `ui/tooltip.py` (U3), `ui/widgets/button.py` (D4 ✅), `src/fpga_sim/controller.py` (D6)
- `sim/sim_wrapper_template.vhd` — D1 ✅ (absorbed 7seg template)
- `sim/sim_testbench.py` — U7, U9, U14, U22, D15
- `pyproject.toml` — D8
- `.pre-commit-config.yaml`, new `.editorconfig` — D10 ✅
- `CONTRIBUTING.md` — D12

## Existing utilities to reuse

- `ErrorDialog` modal pattern (`ui/error_dialog.py`) -> reuse layout for help / settings / tooltip dialogs.
- `get_font()` LRU cache (`ui/constants.py:41-49`) -> already used everywhere; pre-allocation in U17 just primes it.
- `_generate_wrapper()` (`sim_bridge.py:386-414`) -> unified template substitution with conditional 7-seg splicing (D1 ✅).
- `_SimBackend` Protocol (`sim_bridge.py:33-63`) -> becomes ABC base in D2 with no caller changes.
- `session_config.save_session` / `load_session` (`session_config.py`) -> extend schema for U5; existing call sites unchanged.
- `sim_metrics.py` / `scripts/analyze_metrics.py` -> consumed by U19; no new infra needed.
- `BoardDef.summary` property (`board_loader.py:433-443`) -> update format for U12; extend for U0 filter logic.
- `ui/constants.py` colour names (`WHITE`, `GRAY`, `SEL_BG`, …) -> consolidate the ~98 scattered literals onto these in D15, then wrap the grouped palette in a `Theme` for U6.

---

## Verification

Per-item verification is described in each entry's "Done when" criterion above. Cross-cutting checks for any merge:

1. **Tests** — `uv run pytest` (884 tests across 20 files including UI scaling, board selector filtering, board loader, both backends, 7-seg). All sprints must keep this green.
2. **Lint / type** — `uv run ruff check .` and `uv run mypy src/` (the latter tightens under D8).
3. **Manual smoke** — `uv run fpga-sim` end-to-end on a known board (e.g. Arty A7-35) with `hdl/blinky.vhd`; for 7-seg work use `counter_7seg.vhd` on DE10-Lite.
4. **Benchmark regression** — `uv run fpga-sim --benchmark 10` before/after performance-touching merges (U9 / U23). Baseline: 37.7 fps, 0.0036x real-time on Arty A7-35 (from `memory/project_sim_performance.md`).
5. **Headless CI** — every PR runs the existing Linux + Windows x GHDL + NVC x Py 3.10-3.12 matrix.
6. **Visual checks** — for UI work, screenshot the affected screen on Linux and attach to the PR; no automated visual diff today.
