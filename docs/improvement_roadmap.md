# Virtual FPGA Boards — Improvement Roadmap

*Drafted 2026-05-19 · Updated 2026-07-06 · Status: draft for review · Companion to CHANGELOG.md / CONTRIBUTING.md*

A comprehensive, impact-weighted roadmap covering improvements from two perspectives:

1. **User-facing** — UX, performance, presentation, persistence, features.
2. **Developer-facing** — architecture, DRY, type safety, documentation, tests, tooling.

Each item lists *why* it matters, *what* to do, *which files* are touched, a rough effort estimate (XS / S / M / L / XL), and a *done-when* acceptance criterion. Tier numbers reflect impact-weighted priority, not strict execution order; see "Suggested merge order" at the end for a practical sequencing and "Dependencies" for required ordering constraints. Completed cards are condensed to a one-line stub here, with full shipped detail in [roadmap_delivered.md](roadmap_delivered.md).

---

## Context

The simulator is mature: ~6,000 LOC across 20+ Python modules (≈7,400 incl. `sim/`), 43 test files (1445 tests), multi-platform CI, two simulator backends (GHDL/NVC), 7-segment support shipped, embedded CPU core systems (6502/Z80) shipped, 278 board definitions from four sources, three UI themes, performance heavily tuned (PR #31), **v0.14.0 released (2026-07-16)** — the board-native release (board-native VHDL mode, U21 / U31 / U32 / U33).

It is feature-complete for experienced FPGA users, but the codebase and UX have grown organically. Four patterns motivated this roadmap; several are now partly addressed (noted inline):

1. **Board discovery at scale.** With 278 boards from 7 vendors, the original flat scrolling list with text-only filtering was inadequate — users could not filter by component type, vendor, or capability. **U0 ✅** added faceted filtering + sort, largely resolving this.
2. **Onboarding & discoverability gaps.** README is excellent (~605 lines) but historically unreachable from inside the app. **U1 ✅** added an in-app help overlay (workflow, shortcuts, design contract); the README itself is still not surfaced in-app.
3. **DRY drift.** Largely resolved. The three component classes now share a `UIComponent` base (**D3 ✅**); the 264-line main function is gone — **D6a ✅** typed its screen results and **D6b ✅** lifted the loop into a `ScreenController` (`controller.py`), leaving `main()` a thin driver. Backend/color/button drift is resolved: **D2 ✅** collapsed the two near-identical backend classes into one ABC, **D4 ✅** unified button drawing, and **D15 ✅** consolidated ~112 inline RGB literals into a `Theme` object (`ui/theme.py`). *(VHDL wrapper templates unified in D1 ✅.)*
4. **Roadmap gravity.** Features queued in memory for months (PWM LEDs, splash, settings screen, waveforms, Verilog, in-sim navigation) are now sequenced below.

This document inventories all viable improvements and ranks them by impact.

---

## Part 1 — User-facing improvements

### Tier 1 — High impact, ship first

#### U0. Board selector — faceted filtering and sort ✅

- Shipped 2026-05-27 (PR #75). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U1. Help / About overlay (clickable `(?)` button · F1 · `?`) ✅

- Shipped 2026-06-01 (PR #88). Carried-forward gotchas live on **U14** (U7 ✅ consumed the in-sim F1/`?` help stub). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U2. Inline analysis spinner during VHDL load ✅

- Shipped 2026-06-25 (PR #117). Closed Sprint 1b; established the off-main-thread `run_with_spinner()` pattern. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U3. Component tooltips on hover (preview & sim) ✅

- Shipped 2026-07-08 (PR #184, issue #172). Hovering an LED / switch / button for ~400 ms shows a `Tooltip` (`ui/tooltip.py`) with net name / pin / direction, dismissed on leave. A unified `FPGABoard.components` `list[UIComponent]` (from **D3 ✅**) drives one dwell hit-test; `_draw_hover_tooltip()` at the end of `_draw` covers preview *and* sim (both drive the same `_draw`). Reuses the shared info-panel `THEME` roles, so no `theme.py` change. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U4. Error messages with contextual hints ✅

- Shipped 2026-07-07 (PR #181, issue #173). Parsed board-aware contract checks (fixed widths vs board counts, port modes, generics now fatal-with-fix), `add_error_hints()` on GHDL/NVC stderr, and a [View Example] dialog button. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U5. Settings dialog + extended session persistence ✅

- Shipped 2026-07-06 (PR #169, issue #124). Gear button (board preview header) → new `ui/settings_dialog.py`; session schema extended (`window_w`/`window_h`, `speed_factor`, `theme`, reserved `metrics_enabled`/`waveform_enabled`, `recent[]`) with **merge-on-write** so each writer owns its keys (the sim subprocess owns `speed_factor`); saves fire on board/simulator/VHDL change and at quit — not only at launch. **U6 / U10 / U18 / U19 are now unblocked.** Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U26. Visual README — interactive demo + selector GIFs (docs / marketing) ✅

- Shipped 2026-06-25 (PR #110). Headless renderer can later feed **U8** (splash). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

### Tier 2 — High impact, larger initiatives

#### U6. Theme system (light / dark / high-contrast) ✅

- Shipped 2026-07-06 (PR #178, issue #174). New `set_theme()` swaps the shared `THEME` instance's contents in place (call sites bind it once at import, so no draw code changed); alternate **dark** and **high-contrast** `Theme` instances; the Settings Theme row auto-enabled and applies live; the persisted name is restored at startup and carried into the sim subprocess via `FPGA_SIM_THEME`; every import-time `THEME` capture converted to a draw-time read; default `pcb-green` proven pixel-identical (278 board PNGs byte-for-byte vs `main`). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U7. In-simulation navigation toolbar ✅

- Shipped 2026-07-07 (PR #182, issue #175). Three buttons drawn bottom-left during simulation — `[Back to Boards]` · `[Change VHDL]` · `[Reload VHDL]` — via the new `ui/sim_toolbar.py`, reusing the D4 `draw_button` helper and the existing `btn_select_board` / `btn_load_vhdl` / `btn_start_sim` theme roles (so every theme styles the toolbar for free). The subprocess signals the chosen action through a new `SimExit` enum written to an exit-intent sidecar file (`FPGA_SIM_EXIT_INTENT_FILE`), trusted only on a clean exit so a crash is never mistaken for navigation; `launch_simulation()` returns the `SimExit` and `ScreenController.on_simulate()` routes it — RELOAD re-validates + re-analyzes the file in place and relaunches without leaving the sim, BACK → selector, CHANGE → picker. The inert U1 F1/`?` help stub is now consumed in-sim (opens `HelpDialog`). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U8. Splash screen with random board preview

- **Why:** Queued in memory (#3). Adds polish + visual marketing of the board catalog.
- **What:** Replace the bare `BoardSelector` first paint with a two-panel layout: left = filter list, right = randomly-cycling board preview image from `board_images/`.
- **Touches:** `src/fpga_sim/ui/board_selector.py`.
- **Effort:** M.
- **Dependencies:** Consider after U0 (board filtering) so the left panel already has filter chips.
- **Done when:** board selector shows a preview panel with cycling board images alongside the filterable list.

#### U9. LED PWM brightness visualisation

- **Why:** Queued in memory (#4). Today LEDs are binary; PWM designs (`hdl/blinky_pwm.vhd` already exists) look broken.
- **What:** Sample LED state N times per displayed frame (e.g. 10 sub-steps), average to a `LED.brightness in [0,1]` float, use to interpolate `RED_OFF` -> `RED_ON`.
- **Risk:** Multiple `dut.led.value` reads per frame changes the simulation timing model. Each read requires a cocotb `Timer` await, so N sub-steps per frame multiplies the per-frame simulation cost by N. This will reduce the current 37.7 fps baseline. Mitigate by making sub-step count configurable (default 1 = current behavior, opt-in to N > 1 for PWM designs). Benchmark before/after.
- **Touches:** `sim/sim_testbench.py` (multiple `dut.led.value` reads per draw), `src/fpga_sim/ui/components.py` (`LED.draw`).
- **Effort:** M.
- **Dependencies:** None (opt-in, so no regression to existing behavior).
- **Done when:** a PWM-driven LED shows intermediate brightness proportional to duty cycle, and the default (1 sub-step) matches current performance.

#### U10. Waveform capture ✅

- Shipped 2026-07-09 (PR #187, issue #186). New Settings **Waveform** row cycles **off / VCD / FST**; `launch_simulation(waveform=…)` writes a timestamped `~/.fpga_simulator/waveforms/<design>_<timestamp>.<ext>` (dir overridable via `FPGA_SIM_WAVEFORM_DIR`; GHDL `--vcd=`/`--fst=` after the toplevel, NVC `--wave=` + `--format=` before it) and prints a GTKWave hint on exit. Native dump orthogonal to cocotb, so `sim_testbench.py` untouched; the reserved `waveform_enabled` key became the tri-state `waveform`. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U27. User-defined themes (JSON) + example scheme pack

- **Why:** Users have favorite editor/terminal color schemes (Dracula, Nord, Solarized, Gruvbox, Catppuccin, …). Shipping each as a built-in creates a permanent per-theme maintenance surface — every future `Theme` role must be designed and QA'd across all of them (the U6 bar is "renders correctly on every screen, per theme"). A JSON theme mechanism plus a copyable example pack covers the whole long tail while keeping exactly three release-gated built-ins. *(This is the "optionally loaded from JSON" idea the U6 card deliberately deferred — decided 2026-07-06 with Rick.)*
- **What:** Scan `~/.fpga_simulator/themes/*.json` at startup and merge into the theme registry, so the Settings row, `--list-themes`, session persistence, and `FPGA_SIM_THEME` pick user themes up with no extra wiring. Files are schema-validated (the `boards/schema/board.schema.json` precedent) and express **partial overrides over a declared `base` theme** — ~15 lines gets a recognizable scheme, everything unspecified inherits:

  ```json
  { "label": "Dracula", "base": "dark",
    "overrides": { "pcb_bg": [40, 42, 54], "sel_bg": [40, 42, 54],
                   "accent_bar": [68, 71, 90], "led_on": [255, 85, 85],
                   "seg_on": [255, 184, 108], "switch_on": [139, 233, 253] } }
  ```

  Invalid files warn and are skipped (never crash the launcher); unknown role names warn-don't-fail, because **role names become a compatibility surface** — document a stable core set, treat the rest as advanced. Ship `examples/themes/` with the popular schemes as ready-to-copy files, each with a one-line attribution comment (palettes are effectively uncopyrightable and all named sources are MIT — attribution is manners, not obligation).
  - **Phase 0 (internal prerequisite):** promote the component-label / section-title / component-border neutrals (`WHITE` / `GRAY` reads in the board draw paths) into `Theme` roles — white-on-cream is illegible, so **light** schemes (Solarized Light, Gruvbox Light, Catppuccin Latte) are blocked until this lands. Must keep the default pcb-green **pixel-identical** (the established byte-diff check). Dark schemes work without it; the example pack ships dark-first.
- **Touches:** `src/fpga_sim/ui/theme.py` (registry becomes dynamic; loader + schema for the JSON form, including the nested `ButtonStyle` sub-objects — the fiddly part); `ui/components.py` / `ui/board_display.py` (phase-0 neutral promotion); new `examples/themes/`; README theming section; tests (`test_theme.py` + loader suite). `sim_testbench.py`, `__main__.py`, `settings_dialog.py`, and `generate_board_images.py` all read the registry, so they extend automatically — verify, don't rewire.
- **Effort:** M (phase 0: S/M; loader/schema/registry: M; example pack: S per scheme).
- **Dependencies:** ~~**U6** (Theme system)~~ ✅ — registry, `set_theme()`, and the cross-process handoff are in place.
- ⚠ **Carried-forward (from U6 ✅):** read `THEME.<role>` at draw time only — import-time captures (`X = THEME.role` at module *or class* level) silently defeat retheming; phase 0 must re-prove pixel-identical default output; theme-switching tests take the `restore_theme` fixture. The Settings Theme row is a *cycle* button — fine for a handful of themes; consider a picker only if installed-theme counts actually grow.
- **Done when:** a user can drop a JSON file into `~/.fpga_simulator/themes/`, see it in Settings and `--list-themes`, select it, keep it across restarts, and see it inside the sim subprocess; invalid files warn and are skipped; every example-pack scheme loads and renders correctly on all four screens; pcb-green stays byte-identical after phase 0.

### Tier 3 — Quick wins (ship anytime)

| ID | Item | Files | Effort |
|---|---|---|---|
| ~~U11~~ | ~~`R` key to reset switches/buttons to default~~ ✅ | `ui/board_display.py` | XS |
| ~~U12~~ | ~~Compact board summary format (e.g. `"4 LEDs · 2 BTN · 4 SW · 4-digit 7-seg"`)~~ ✅ | `board_loader.py` (`BoardDef.summary`) | XS |
| ~~U13~~ | ~~Arrow / Page-Up / Page-Down navigation in board + file lists~~ ✅ | `ui/board_selector.py`, `ui/vhdl_picker.py` | S |
| U14 | `P` key to pause/resume simulation; pause indicator in SimPanel | `sim/sim_testbench.py`, `ui/sim_panel.py` | S |
| U15 | Compact mode for `SimPanel` (toggle via existing `S` shortcut family) | `ui/sim_panel.py` | S |
| U16 | Enforce minimum window size (800x600) with friendly warning | `__main__.py` | XS |
| U17 | Pre-allocate common font sizes at startup (eliminates LRU eviction churn) | `ui/constants.py` | XS |
| U18 | Recent-files section in `VHDLFilePicker` (consumes `recent[]` from U5 ✅) | `ui/vhdl_picker.py` | S |
| U19 | Metrics-enable checkbox surfacing `FPGA_SIM_METRICS` env var | `ui/sim_panel.py` or Settings dialog | XS |
| ~~U28~~ | ~~Auto-emit a `<design>.gtkw` GTKWave save file beside the dump (preload clk/sw/btn/led/seg)~~ ✅ | `sim_bridge.py` (`_write_gtkw`) | S |
| ~~U29~~ | ~~`FPGA_SIM_WAVEFORM` env to enable capture headlessly/CI + one-click auto-open (configurable-viewer template)~~ ✅ | `sim_bridge.py`, `platform_open.py`, Settings dialog | S |
| ~~U30~~ | ~~"Include memories" depth toggle — NVC `--dump-arrays` (GHDL's FST dumps arrays already) so embedded-core RAM/ROM/registers appear in the trace~~ ✅ | `sim_bridge.py` (`run_cmd`), Settings/env | S |

**Note on U28–U30 (waveform-capture follow-ups):** all three extend **U10 ✅** and were raised 2026-07-09 during U10 review. U28 (a ready-made `.gtkw` view) and U29 (env-enable for CI/headless + one-click auto-open) are UX polish; **U30** makes capture useful for the mx65/t80 **embedded-core** designs, whose interesting state (RAM/ROM/registers) is exactly the nested arrays NVC skips by default (GHDL's FST/GHW dump them already — see the correction below). `scripts/capture_waveform.py` already contains a `.gtkw`-writer idiom U28 can reuse. **U28 shipped 2026-07-09** (Sprint 5 lead, issue #189) — `sim_bridge._write_gtkw` writes the save file after a produced dump, naming ports from the run generics (`sim_wrapper.led[N-1:0]`, `seg[8·digits-1:0]`); signal names were cross-checked against a real `sim_wrapper` VCD (plain + 7-seg). **U29 shipped 2026-07-09** (issue #190): `$FPGA_SIM_WAVEFORM` (env capture-enable, env-wins), a Settings **Auto-open** toggle (+ `$FPGA_SIM_WAVEFORM_OPEN`), and a **command-template** viewer `$FPGA_SIM_WAVEFORM_VIEWER` (`{dump}`/`{gtkw}`, default `gtkwave {gtkw}`; any CLI viewer via env, e.g. `surfer {dump}`) with an OS-default-handler fallback — U4's opener extracted to `platform_open.py` as that fallback. **U30 shipped 2026-07-11** (issue #191, PR #196): a Settings **Memories** toggle (+ `$FPGA_SIM_WAVEFORM_MEMORIES`, env-wins) threads NVC `--dump-arrays` through a new `WaveConfig.dump_arrays` field into `run_cmd`, so the embedded-core RAM/ROM/registers land in the trace (empirically an `mx65_hello` NVC dump jumps 202 → 2254 `$var` with the flag, expanding the 2 KB `cpu_ram` into per-cell `ram[i]` vars). **Correction to the premise:** the "GHDL dumps arrays already" shorthand holds only for GHDL's **FST/GHW** writers (memories included by default) — GHDL's **VCD writer** omits a memory (array-of-`std_logic_vector`), with or without any flag, so under GHDL the path to inspect a memory is to pick FST. This is a *writer* limit, not a *format* one: a VCD can hold a memory flattened to one vector var per element, and **NVC's VCD writer emits exactly that** under `--dump-arrays` (`ram[0][7:0]`…) — GHDL's VCD writer simply doesn't. NVC omits nested arrays in *every* format (VCD **and** FST — both empirically 202 → 2254 `$var`) unless `--dump-arrays` is given, which is why the opt-in is NVC-only and a no-op for GHDL. **Follow-up parked as Icebox P14:** a GHDL-VCD + Memories=On combination silently yields no memories (a format dead-end); a small Settings hint could steer such users to FST. **Deferred idea:** U28's `.gtkw` could set a default time dimension (verify GTKWave supports it) so units read sensibly without a viewer flag.

**Note on U12:** `BoardDef.summary` already includes 7-seg digit count as of v0.5.0. Remaining work is the formatting change (dot separators, abbreviated labels).

**Note on U14 — carried-forward (from U1 ✅):** Register the new `P` key in the single `SHORTCUTS` table in `ui/help_dialog.py` (alongside ESC/S/etc.) so the help legend can't drift from the real handlers. When unit-testing the key handler, note that synthetic pygame KEYDOWN events lack `.unicode` — read it via `getattr(ev, "unicode", "")` (as `FPGABoard._handle_events` does).

**Note on U18/U19:** U5 ✅ shipped both prerequisites — `recent[]` is populated on every pick and launch, and the Settings dialog exists as U19's toggle location (the session's `metrics_enabled` key is reserved).

**Note on U18 — scope (retry start-dir):** U18 surfaces `recent[]` as an "Open Recent" section at the top of the picker; the data source is live — **U5 ✅** populates `recent[]` and saves the session on *pick* (`on_vhdl_loaded()`), so a browsed-but-unrun file and its directory already survive a restart. One adjacent papercut still belongs here: **don't reset the start dir on a validation retry** — after an encoding/contract error the re-opened picker jumps back to bundled `hdl/` instead of the user's directory (the retry branch in `ScreenController._run_vhdl_picker()`), forcing re-navigation — keep the last-visited directory across retries. Touches `controller.py` in addition to `ui/vhdl_picker.py`.

**Note on U13 — done (2026-06-01, PR #85):** Keyboard navigation on both list screens — `↑`/`↓` + `PgUp`/`PgDn` move the cursor (auto-scrolled into view) and `Enter` activates the row; each screen's KEYDOWN now routes through a unit-testable `_handle_keydown()`. 32 new tests.

### Tier 4 — Larger features (long-horizon)

#### U20. Verilog / SystemVerilog support

- **Why:** Queued in memory (#1); broadens audience significantly. Icarus Verilog is the natural first target.
- **What:** New file picker extension filter `.v / .sv`, Verilog contract validator, `TOPLEVEL_LANG="verilog"`, new VPI lib, third backend class, example `blinky.v`.
- **Effort:** XL (10-15 h).
- **Dependencies:** ~~**Requires D2** (backend ABC)~~ ✅ — the ABC now shares `find()` / `available()` / `lib_dir()` / `sim_bin_lib()`, so a third backend overrides only `NAME` + the command builders.
- **Done when:** a `.v` file with the correct port contract simulates successfully with Icarus Verilog.

#### U21. Board-native VHDL mode (port conventions) ✅

- Shipped 2026-07-13, **released in v0.14.0** (arc: groundwork #198/#199, Part A #209–#215 + follow-ups #213/#214/#218/#219, Part B #216/#217/#220/#221 + this closeout; issues #200–#208). A design written to a board's *own* port names and fixed widths (Terasic `CLOCK_50` / `KEY` / `LEDR` / `SW` / `HEX0`-`HEX5`, **no `NUM_*` generics**) now simulates unmodified. **Part A** populated `port_conventions` across the fleet — schema deltas (A0) → re-sync preservation guard (A1) → dialect parsers + `classify()` (A2) → generator + curated overlay (A3) → population waves (A4). **Part B** consumes it: `BoardDef.port_conventions` (B1); a `check_vhdl_contract()` matcher returning a typed `ContractResult` + `ConventionMatch` (B2); a native `sim_wrapper` (`_generate_wrapper`) that adapts native ports to the `clk/sw/btn/led/seg` boundary — active-low LED/button inversion, `individual` 7-seg per-digit packing — with the cocotb testbench untouched, plus `hdl/native/` examples and GHDL/NVC e2e (B3a); and the run affordances / mode badge / session-log fields (B3b). **Contract:** the simulator always models the *selected* board and the board's convention supplies polarity, so a file written for the wrong board near-misses (rejected, mismatch named) rather than silently coercing or flipping polarity. Registry + arc plan: [`docs/port_convention_sources/`](port_convention_sources/), [`u21_board_native_vhdl_plan.md`](u21_board_native_vhdl_plan.md). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U22. 7-segment v2 — physical mux mode

- **Why:** Queued in memory (#8); current v1 is logical-only. v2 enables the hardware-accurate scan interface on Nexys4-DDR, RZ-EasyFPGA, StepMXO2.
- **What:** New conditional placeholders in the unified wrapper template, updated testbench readback, new `physical_mux: bool` toggle per board.
- **Effort:** L.
- **Dependencies:** D1 ✅ (unified wrapper template is in place). U21 ✅ Part A landed the scan-style schema fields (`style: scan` + `digit_enable`) and registry-verified scan data (Basys3 packed `seg`+`an`, Nexys4-DDR `CA..CG`, Mimas A7 `SevenSegment`+`Enable` — see `docs/port_convention_sources/`) — consume that, don't re-research.
- **Done when:** a muxed 7-seg board (e.g. Nexys4-DDR) shows correct digits via the physical scan interface.
- **Carried forward (2026-07-02):** physical-mux mode must keep the logical packed-`seg` contract as
  the design-side **default** — every 7-seg example, including the generated embedded-core designs
  (`hdl/mx65_*.vhd`, `hdl/t80_*.vhd`), assumes it.
- **Data-quality prerequisite (found 2026-07-13):** the Digilent classifier currently emits
  `style: individual` for Nexys 4 DDR / Nexys A7-100T / A7-50T even though their `CA..CG` are
  *shared* scan segments (7 segment names for an 8-digit display), so those three boards **falsely**
  full-match board-native today (a physically faithful scan design would not). Fix the classifier to
  emit `scan` for shared-segment names as part of (or ahead of) this card — touches
  `scripts/port_convention_parsers/classify.py` + the regenerated `boards/digilent-xdc/*.json`.

#### Board-native VHDL coverage (post-U21 ✅) — raised 23/278 → 258/278 ✅ (v0.14.0)

U21 ✅ shipped the matcher + native wrapper, but a full-fleet sweep (2026-07-13, U21 closeout) shows
only **23 of 278 boards** were genuinely native-usable at U21 closeout — the feature was **data-starved, not
broken**. **241 boards carry no `port_conventions` at all** (all 167 litex + 74 of 79 amaranth), and
even where data existed the matcher's former **"all four roles required"** rule throttled it — of
those 241 boards, 238 have clk + LED but only **52** have clk + LED + switch + button (most FPGA
boards have no switches). **U31 ✅** (2026-07-13, PR #226, issue #223) removed that rule: a design now matches
whatever roles its board's convention declares (clk + LEDs minimum), so partial-interface boards are
no longer capped — the remaining throttle is purely missing data. The native names / counts / clock
for those 238 boards were **already parsed** into the board JSON, just not emitted as a convention —
**U32 ✅** (2026-07-14) did that, emitting framework-derived conventions for **241/246** litex+amaranth
boards; **U33 ✅** added vendor-*canonical* quality where it matters most. Realistic combined ceiling ≈
150–200 (not 278: scan/serial displays need **U22**, and some boards have no machine-parseable
source). **All shipped in v0.14.0:** **U31 ✅** + **U32 ✅** + **U33 ✅** — **258 of 278 boards** now
carry a `port_conventions` block (framework-derived + vendor-canonical), up from 23.

#### U31. Board-native partial-interface support ✅

- Shipped 2026-07-13, **released in v0.14.0** (PR #226, issue #223). `_attempt_convention` no longer requires all four roles: it now
  matches whatever roles the selected board's convention declares — clk + LEDs minimum, switches /
  buttons matched-if-the-convention-names-them — generalizing the existing "seg required only when
  the board has a display" rule, so a **switch-less or button-less** board-native design runs
  unmodified. `_render_native_wrapper` ties off an absent input bank (the top `sw`/`btn` boundary
  ports stay so the cocotb testbench is untouched, floored to a one-bit dummy and left unconnected —
  mirroring the generic path's `NUM_* = max(1, count)`) and leaves absent outputs dark; a design
  declaring an *input* the convention lacks stays an honest near-miss (an extra *output* is left
  `open`, as the DE0 example's decimal-point pins already are). `ConventionMatch.switches`/`.buttons`
  became `NativePort | None`. On today's full-interface conventions behavior is unchanged — the
  payoff is as the multiplier for **U32** (52 → ~238). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U32. Auto-derive `port_conventions` from the litex & amaranth platform files ✅

- Shipped 2026-07-14, **released in v0.14.0** (bundled with U21 + U31). The litex and amaranth sync parsers
  now emit a framework-derived `port_conventions.{litex,amaranth}` block for **241/246** boards
  (164/167 litex + 77/79 amaranth; the rest lack a clock or LEDs) via the new shared
  `scripts/framework_conventions.py`. Each advertises the framework's *own* port names — litex
  `clk100`/`user_led`/`user_sw`/`user_btn` (the raw `_io` names, not the normalized JSON net-names),
  amaranth `clk100`/`led`/`switch`/`button` — grouped into a vector or a `names[]` scalar bank (Basys3 /
  Nexys4 directional buttons), primary LED group picked (`led` over `rgb_led`), amaranth polarity from
  `PinsN`. Stamped `naming: "framework-derived"`; the matcher tries canonical blocks **first**
  (`_convention_precedence` in `sim_bridge.py`) so authoritative vendor data added later wins, and the
  A1 per-sub-key merge lets a framework block coexist with a canonical one. Exposed and fixed a native
  wrapper gap: a bank **narrower than the board's resource count** (litex `rgb_led` inflate `NUM_LEDS`
  past `user_led`) now zero-extends onto the board boundary, with wrapper default generics baked to the
  board counts so analyze == run. A litex Arty design (`hdl/native/arty_litex.vhd`) simulates unmodified
  on GHDL + NVC. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U33. Board-native population waves 2+ (registry-driven canonical conventions) ✅

- **Shipped 2026-07-15, released in v0.14.0.** Waves 1–4 populated vendor-canonical conventions across
  ~14 boards; combined board-native coverage reached **258/278**. Full detail →
  [roadmap_delivered.md](roadmap_delivered.md). The wave history and the forward notes below are
  retained as guidance for the ongoing canonical-population effort (**P2** / **P18**).
- **Progress:** ✅ **Wave 1** (5 Terasic teaching boards, U21) + the ✅ digilent-parser coverage fix
  (#229, +2). ✅ **Wave 2** (#231): 4 clean official-repo boards — Alchitry Au, Tang Nano 9K
  (active-low, cited), Icepi Zero, Trellisboard — plus a `resolve_commit_sha` `GITHUB_TOKEN` auth fix
  that unblocks clean commit-pinning for every future wave. ✅ **Wave 3** (#233): aligned the width
  cross-check with U32 (a source bank *narrower* than the board is a legit partial the native wrapper
  zero-extends — only *wider* is a mismatch) + Sipeed Tang Nano 20K (partial 6/7; the 7th LED is an
  RGB; active-low cited). ✅ **Wave 4** (#235): board-data quality fix — the litex & amaranth parsers
  classified LEDs with a bare `"led" in name` substring test that swept in `oled*` (OLED buses) and
  `segled_*` (7-seg lines); tightened to a token-boundary rule (keeps `m2led`/`led0`, drops
  `oled`/`segled`), fixing the phantom-LED counts on 7 boards and modeling Nexys4 (34→18 LEDs) + Numato
  Mimas A7 (20→8) `segled_*` as their real multiplexed 7-seg displays. This was the ULX3S "10-vs-8
  LEDs" blocker (a data-quality wart, not a canonical-population gap). Wave 4 also **populated Litefury
  - Nitefury II** (#237) — RHS Research PCIe cards, a clk+LED partial convention (`pcie_clkin_p` +
  `LED_A1..A4`), active-low cited to the vendor's own `CodeBlinker.v` — and established that **ICEBreaker
  Bitsy** stays on its framework convention (its canonical bank classifies to the RGB breakout, not the
  red+green primary, so a canonical block would regress it). **Empirical scoping
  (2026-07-14):** force-checking all 61 gate-eligible boards showed only **13** produce a clean,
  complete convention today; the *marquee* hobbyist boards (ICEBreaker, iCESugar, Tang Nano 20K, ULX3S,
  ULX4M) are **width-blocked** (source-vs-board-JSON count mismatch — the RZEasy pattern, needs
  per-board reconciliation and likely board-JSON edits, part of which Wave 4 addressed at the parser
  level), the Xilinx eval boards are **clk-only** (their pin-XML has no GPIO LEDs), so the "prioritize
  popular boards" aim below needs that reconciliation first (Wave 3+). Deferred map recorded in
  `waves.toml`.
- **Why:** U21 Part A built the whole registry → parser → generator → overlay pipeline but only
  **Wave 1 (3 Terasic boards)** shipped; the registry (#198) has ~124 fetch-verified sources awaiting
  population. This is the *quality* path — vendor-**canonical** conventions with distinctive real
  names (Terasic `LEDR` / `KEY` / `HEX`) and manual-verified polarity, which is where board-native
  mode earns its keep versus U32's framework names.
- **What:** Run successive population waves via `scripts/sync_port_conventions.py` (`waves.toml`),
  curating per-board as A4 did: verify each source is parseable + trusted, cross-check widths, add
  cited overlay entries for polarity / multi-clock / name-overrides. Prioritize boards users actually
  hand-write HDL for (Terasic teaching boards, popular Digilent / Xilinx dev boards).
- **Touches:** `docs/port_convention_sources/waves.toml` + `overlay.toml`; regenerated
  `boards/*/*.json` (production path). Mostly overlay-only, but two board-*parser* quality fixes fell
  out of the arc: the digilent section-header fix (#229) and the litex/amaranth LED-classifier
  token-boundary fix (#235).
- **Effort:** L (incremental; per-wave S–M).
- **Dependencies:** U21 ✅ (pipeline complete). Overlaps **P2** (sync curation).
- **Done when:** the registry's verified-source boards are populated wave-by-wave, each wave recorded
  in `waves.toml` with cited sources; unparseable-source boards (PDF / README-only) explicitly
  deferred.
- **Family disambiguation (the Arty case — keep in mind going forward):** "Arty" is a *family*, not a
  board. The repo already carries **15 Arty files**: **7 authoritative Digilent variants**
  (`digilent-xdc/`: original Arty + A7-35 / A7-100 / S7-25 / S7-50 / Z7-10 / Z7-20, each its own master
  XDC with a real `device`), 5 amaranth, and 3 litex (the litex A7/S7 leave `device: ""` because the
  variant is a runtime param, so they don't pin the silicon). A canonical convention must attach to the
  *exact* variant — key on `class_name` + `device`, never the fuzzy "Arty" name — and the
  low-specificity framework entries (litex's generic "Digilent Arty") are precisely the ones
  authoritative `digilent-xdc` data should out-rank via `_convention_precedence`. Multi-variant,
  multi-source families are the population-wave (and P18) stress test.
- **✅ Digilent XDC parser section-header fix (shipped 2026-07-14, #229 — one of the arc's two code
  touches; the other is the Wave 4 litex/amaranth LED-classifier fix #235; population waves themselves
  are overlay-only).** `digilent_parser._classify_section` recognized a
  clock section only when the header contained **both** "clock" *and* "signal", and a plain-LED section
  only by the *exact* string `led`/`leds`. Digilent's titles vary, so real clock/LED ports were silently
  dropped (the frequency still survived via the section-agnostic `create_clock` regex, so
  `default_clock_hz` stayed correct while `clocks[]` was empty and the convention had no `clk` → the
  native clk+LEDs floor failed). The clock matcher now accepts "clock" + a freq/`system`/`signal`
  qualifier **and excludes transceiver/mezzanine reference clocks** (an FMC card's GTP/MGT clock is the
  mezzanine's, not the FPGA fabric's — e.g. Nexys-Video `FMC Transceiver clocks … 156.25 MHz`; a fabric
  clock merely *sourced* from a peripheral — Eclypse-Z7's `125MHz Clock from Ethernet PHY`, port `clk` —
  is kept); the LED matcher is now a `\bleds?\b` word-boundary match (`4 LEDs`, not `OLED Display`).
  Regenerated from the pinned upstream (data-only diff, U32 regen discipline) + parser tests.
  **Recovered:** `usb104_a7-100t`, `cmod_s7-25` native (→ 267/278; Cmod S7-25 also regained 4 dropped
  user LEDs, count 1→5). **Still deferred:** `cora_z7-07s`/`cora_z7-10`/`eclypse_z7` regained a clock but
  are **RGB-LEDs only** (needs a treat-RGB-as-LED-bank decision); `genesys_zu-3eg`/`-3eg-d`/`-5ev-d` have
  **no fabric clock in the XDC** (Zynq US+ PL clock is PS-sourced) → need a cited **overlay** clock, not
  a parser change.

### Performance (mostly already done)

`memory/project_sim_performance.md` documents PR #31's tuning (37.7 fps, 0.0036x real-time on Arty A7-35; GHDL dominates at 98.4 %). Remaining cheap wins:

- **U23.** Dirty-flag redraw — skip `_draw()` when no LED / switch / button / 7-seg state changed since last frame. Touches the `SimulationScreen` draw loop (`ui/simulation_screen.py`, now that **U34 ✅** has landed) and `ui/board_display.py`. **Effort:** S. **Done when:** frame rate stays at the fps cap but CPU usage drops when no state changes.
- **U24.** ~~Batch multiple `Timer` calls per frame at high speed-slider settings.~~ **Won't-do — resolved by measurement (U34 spike, 2026-07-16):** batching ×10 `Timer` calls per frame gained only **+3 %** on GHDL — the GPI round-trip is not the bottleneck (VHDL eval dominates), so the loop complexity is not worth it. The single-window child (U34) already free-runs the simulator to saturation on the benchmark path. **Effort:** M (not pursued).
- **U25.** Profile GHDL GPI vs VHDL eval to find the next bottleneck. **Effort:** investigative. **Done when:** a written profile report identifies the top-3 bottlenecks with data.

The larger active performance + UX initiative:

- **U34 ✅.** Single-window simulation. Shipped to main 2026-07-17 (arc: process layer #252 → flag-gated `SimulationScreen` #253 → default flip + two-mode benchmark #254 → single-window review fixes #255 → legacy-removal closeout). The launcher's pygame window persists for the whole session; the GHDL/NVC + cocotb child runs **headless** and streams signal state over an IPC link (`sim_link`) to a `SimulationScreen` rendered in place — no window is created or destroyed between launcher start and app exit. Measured throughput gain (GHDL **+16–26 %**, NVC **×4.3**) at a responsive ~62 fps host UI; `SimExit` relocated to `ui/results.py`. Unblocks **U23** (its draw loop is now `ui/simulation_screen.py`). **Released in v0.15.0** (2026-07-17). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

See also **P1** (NVC elaborate-once / run-many) in the [Icebox](#icebox).

---

## Part 2 — Developer-facing improvements

### Tier 1 — DRY: collapse the duplications

#### D1. Generate the VHDL wrapper from one source ✅

- Shipped 2026-05-28. Unblocks **U21** / **U22**. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D2. Backend base class with override-only differences ✅

- Shipped 2026-06-25 (PR #115). `_SimBackend` is now an ABC; unblocks **U20** (a third backend overrides only `NAME` + the command builders). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D3. UIComponent base class ✅

- Shipped 2026-07-07 (PR #183). Abstract `UIComponent` base holds the `(index, info)` ctor, `index` / `info` / `rect`, and the `label` property (prefix fallback via `_LABEL_PREFIX`, else `ComponentInfo.display_name`); `LED` / `Switch` / `Button` inherit it, `FPGAChip` / `SevenSeg` stay standalone. Enables **U3** (single `list[UIComponent]` for hover hit-testing). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D4. Shared button-drawing helper ✅

- Shipped 2026-05-31 (PR #83). `ui/widgets/button.py` (`ButtonStyle` + `draw_button`); **U7** should reuse it (U5 ✅ did). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D5. Platform-aware path helper

- **Why:** `_build_sim_env()` (`sim_bridge.py`) repeats the PATH-prepend pattern for Windows and Linux; the `IS_WINDOWS` branching is interleaved with logic that doesn't actually differ.
- **What:** Extract `_compose_path(extra: list[str], var: str = "PATH") -> str`; flatten Windows/Linux branches to differ only in their `extra` list contents.
- **Touches:** `src/fpga_sim/sim_bridge.py`. Modest LOC reduction, large clarity win.
- **Effort:** S.
- **Dependencies:** None.
- **Done when:** `_build_sim_env()` has no interleaved `if IS_WINDOWS` blocks; platform differences are isolated to the `extra` path lists.

#### D15. Consolidate scattered colors into the single source of truth ✅

- Shipped 2026-06-24 (PR #109). `ui/theme.py` (`Theme` + swappable `THEME`); front-loads **U6**'s container shape (see U6's ⚠ carried-forward note). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

### Tier 2 — Architecture & state

#### D6. Extract a `ScreenController` from `__main__.py` ✅

- Shipped in two stages: **D6a ✅** (screen-result enums, PR #121) + **D6b ✅** (2026-07-05, PR #168 — `ScreenController` + `SessionState` in `controller.py`; `main()` is now a thin driver). U5's save-on-pick landed in `on_vhdl_loaded` as designed (U5 ✅). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D7. Decompose `launch_simulation()`

- **Why:** `sim_bridge.py` mixes env construction, generic injection, NVC re-elaboration, env-var marshalling, and subprocess invocation — ~100 LOC.
- **What:** Split into `_prepare_run_env(board_json, vhdl_path, generics, sim_dims) -> env, cmd` and `_invoke_run(cmd, env, cwd) -> bool`. Makes env construction unit-testable.
- **Touches:** `src/fpga_sim/sim_bridge.py`; new tests in `tests/test_sim_bridge_backend.py`.
- **Effort:** M.
- **Dependencies:** None.
- **Done when:** `launch_simulation()` is a thin orchestrator; `_prepare_run_env()` has unit tests that verify env dict contents without launching a subprocess.

#### D16. Sandbox the simulation subprocess (untrusted-VHDL isolation)

- **Why:** A user-supplied `.vhd` is *executed*, not just parsed — the tool analyzes, elaborates, and **runs** it — so a downloaded design is a code-execution vector. On the **default GHDL** backend a design can read/write any file the user can via `std.textio` (enough to exfiltrate `~/.ssh/id_rsa` or overwrite `~/.bashrc`); on **NVC** it escalates to full native code execution — a `VHPIDIRECT` foreign binding resolves arbitrary libc symbols (`system`/`execve`/`socket`), empirically verified with a bare `.vhd` calling `getpid`/`geteuid`. It runs with the invoking user's privileges (not root — so not a direct kernel rootkit, but ample for data theft, tampering, a reverse shell, or fetching a second stage). Board **JSON is not a risk** (pure `json.loads` + typed coercion; values reach VHDL only as single `-g` argv elements — no shell, no injection). Reported to NVC via private disclosure (2026-07-04); **this card is the local mitigation and does not depend on an NVC fix** — it also closes the GHDL file-I/O vector that exists on the default backend.
- **What:** A new `sandbox.py` that wraps the sim **run** subprocess in **bubblewrap (`bwrap`)** when available. Policy: **auto-on when `bwrap` + unprivileged user namespaces are present; warn-and-continue otherwise** — encourage, never mandate (mandating breaks Windows/macOS, hardened-kernel Linux, and adoption). Override via `FPGA_SIM_SANDBOX=auto|off|require|bwrap` (and a toggle in the **U5 ✅** Settings dialog). The sim legitimately needs **zero network**, so `--unshare-net` is a zero-cost, high-value control that kills the NVC exfil path outright.
- **Verified bind set** — *prototyped against `bwrap` 2026-07-04: a real headless `blinky` GHDL+cocotb run behaved identically sandboxed vs. unsandboxed (same `TESTS=4 PASS=3 FAIL=1`, VPI loaded); `pygame`+`cocotb`+`fpga_sim` imported fine inside; an in-sandbox network connect was blocked; a planted `$HOME` secret was hidden:*
  - **Strategy A (recommended default — robust, distro-agnostic):** `--ro-bind / /`, then *subtract* — `--dev /dev`, `--proc /proc`, `--tmpfs /tmp`, `--bind <work_dir> <work_dir>` (rw) + `--chdir <work_dir>`, `--tmpfs $HOME` (hides personal files), then re-expose **read-only** the two paths under `$HOME` the sim needs: the **project root** (`src/`, `sim/`, `.venv` incl. cocotb libs, `hdl/`) and the **uv interpreter root** `~/.local/share/uv/python` (venv-symlink target + libpython). Plus `--unshare-net --die-with-parent --new-session`.
  - **Strategy B (tighter minimal allowlist):** bind only `/usr` (+ usrmerge symlinks `/lib`,`/lib64`,`/bin`,`/sbin`), `/etc`, the project root, and the uv interpreter root — same isolation/`$HOME`/work-dir/net flags. Both confirmed working.
  - **Derive the bind list from the paths `_build_sim_env()` already computes** (`PATH` / `LD_LIBRARY_PATH` / `PYTHONPATH` / `PYGPI_*`), not a hard-coded list, so it stays correct if the venv or toolchain moves.
- **Touches:** new `src/fpga_sim/sandbox.py`; `src/fpga_sim/sim_bridge.py` (`launch_simulation` — wrap the final `subprocess.run(cmd, env, cwd)`; optionally the analyze/elaborate runs); `session_config.py` / Settings (**U5** ✅) for the toggle; a docs note that HDL is executable code; new `tests/test_sandbox.py`; one Linux-only CI job.
- **Effort:** M (wrapper + detection + tests + docs + CI job). The wrapper is small; getting the bind set right was the risk, and it is now prototyped.
- **Performance (benchmarked 2026-07-04):** negligible for bwrap and for syd's Landlock-only `syd-lock`; catastrophic only for the full `syd` seccomp supervisor. **bwrap** adds a **one-time ~5–6 ms** namespace/mount-setup cost (lost in the sim's ~150–200 ms elaboration jitter) and leaves **steady-state throughput at ~94–97% of native** (~50.2k `full_ro` / ~48.9k `allowlist` vs ~52.3k plain cocotb-driven cycles/s, median of 5, = 96%/94%; an earlier same-day session measured ~97%, 48.6k vs 49.9k) — i.e. the **effective simulated clock rate is not meaningfully lowered.** Namespaces are transparent after setup (no per-syscall interception; bwrap applies no seccomp filter by default), bind mounts are native-speed, and `--unshare-net` is free at runtime. Measured headless (the compute path that defines the rate); a bound display socket should add no per-frame cost (bind-mounted sockets are native I/O — inferred, not separately benchmarked). **syd splits into two very different tools when benchmarked.** **(a) The full `syd` supervisor (seccomp + user-notify)** *can* run the pipeline — via three exec relaxations (`allow_unsafe_exec_{nopie,stack,memory}`, the last so the mcode JIT isn't SIGSYS-killed), pointing cocotb at libpython by **absolute path** through `LIBPYTHON_LOC` (all cocotb libs carry `RPATH=$ORIGIN`, so the libpython *soname* search was `LD_LIBRARY_PATH`'s only job — and no flag preserves `LD_LIBRARY_PATH`), and restoring `PYTHONPATH` with `-mpassenv+PYTHONPATH` — reaching `TESTS=1 PASS=1`. **But steady-state collapses to ~280–300 cocotb cyc/s, ~170–190× slower than native's ~52k**, and mediating *only* the network (`-msandbox/net:on`) is just as slow (~304 vs ~279 cyc/s) as full FS+net: the tax is intrinsic to seccomp user-notify trapping the syscall-heavy GPI hot loop — **no fast-but-protective `syd`-supervisor config exists** (plain seccomp-BPF filtering is cheap; the tax is the user-notify supervisor) — plus ~175 ms setup (≈30× bwrap). **(b) syd's Landlock-only launcher `syd-lock(1)` is the opposite — it runs the sim at native throughput: 52,687 cyc/s, 100.8% of plain (parity — the +0.8% is measurement noise), ~2.5 ms setup (below bwrap's ~6 ms)** — because Landlock is an in-kernel LSM with no userspace round-trip. Scoped read rules (`-r /usr -r /etc -r <project> -r <uv-python>`, `$HOME` omitted) blocked reading a planted `~/.secret` (open → EACCES; unlike bwrap's `--tmpfs $HOME` this denies content, not *existence* — stat is not a Landlock-handled right); writes confine via `-w <work_dir>`; and on Landlock ABI ≥4 (kernel ≥6.7; this host reports ABI 8) **TCP egress is denied by default** (connect → EACCES unless a port is granted via `-c`), closing the NVC *TCP* exfil path at zero runtime cost (caveat: Landlock's net rights are TCP-only — UDP/ICMP are unhandled, so e.g. UDP DNS can still pass; bwrap's `--unshare-net`, which removes the interface entirely, stays the stronger network cut). `syd-lock` needs none of the seccomp relaxations (no ELF check) and no env fixes beyond native. **Net: on a modern-kernel Linux host, `syd-lock` matches native speed with in-kernel FS + network confinement — a viable bwrap alternative or a defense-in-depth co-layer; only the *seccomp* `syd` supervisor is the wrong tool.** The lesson: for this workload kernel-space enforcement (namespaces *or* Landlock) is ~free, while userspace syscall mediation (seccomp user-notify) costs ~180×.
- **Dependencies:** Soft: **D7** (decomposing `launch_simulation` into `_invoke_run` gives the clean seam to wrap). Independent of the NVC upstream fix.
- **Open issues to resolve at implementation:**
  - **GUI-in-sandbox is the residual hole.** pygame renders *inside* the sandboxed process, so a total lock-down still needs display access (X11 has no inter-client isolation). Short-term: dropping network + hiding `$HOME` (both proven) already removes the two worst vectors even with the display exposed; headless runs (CI, capture) have no display and lock down fully. **Medium-term (could graduate to its own card):** split the render loop out — run the untrusted sim headless in the tight sandbox and stream LED/switch/seg state over a pipe to a *separate, unsandboxed* pygame front-end, so the sandbox needs no display at all.
  - **Cross-platform gap:** `bwrap` is Linux-only. Document the reduced protection on Windows/macOS; future per-OS backends = macOS `sandbox-exec`, Windows AppContainer / Job objects.
  - **userns availability:** unprivileged user namespaces are off on some distros / WSL1 / hardened kernels — detect and fall back with a visible warning.
  - **Session log:** `save_session_stats()` writes `~/.fpga_simulator/`, which `--tmpfs $HOME` hides — either bind that one dir rw or have the unsandboxed parent write it (pairs with the headless-split option).
  - **firejail** is an easier-UX alternative but is **setuid-root** (a wrong-direction attack surface for running untrusted code) — offer as opt-in, not the default. **`syd-lock`** (syd's Landlock-only launcher) is a measured **performant** backend worth supporting as an alternative/co-layer where Landlock ABI ≥4 (kernel ≥6.7) is present — native throughput with in-kernel FS + default-deny-TCP confinement (derive `-r`/`-w`/port rules from the same `_build_sim_env()` paths; below ABI 4 it degrades to FS-only, and Landlock adds no PID/mount/user-namespace isolation — bwrap's layer — which is what makes co-layering attractive). The full **syd** seccomp supervisor (~180× slower here, and syd 3.56's supervisor has a confirmed not-profile-fixable self-kill defect under syscall-heavy load on many-CPU hosts — `syd-lock` is structurally immune) and **nsjail** remain power-user options, not the default.
- **CI:** add a Linux-only job — install `bubblewrap`, run the existing headless sim *through* the wrapper, and assert (a) output matches the unsandboxed run and (b) an in-sandbox network connect fails. Headless (`SDL_VIDEODRIVER=dummy`) exercises the fully-locked-down config. Don't gate the cross-platform matrix on it.
- **Done when:** the sim run is wrapped in `bwrap` when available (auto, with an explicit log line), falls back with a visible warning when not, and honors `FPGA_SIM_SANDBOX`; a headless sim runs identically sandboxed; an in-sandbox network attempt fails and `$HOME` is not readable; a Linux CI job proves both; docs state that simulating an untrusted design without a sandbox runs it with your privileges.

### Tier 3 — Type safety & tooling

#### D8. mypy strict mode ✅

- Shipped. `pyproject.toml`'s `[tool.mypy]` now carries a single `strict = true` (13 bundled flags, superseding the five it used to list individually); `uv run mypy .` is clean across 84 files and CI enforces it via the existing `uv run mypy .` step. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D9. `Literal` types for stringly-typed identifiers ✅

- Shipped. `Simulator = Literal["ghdl", "nvc"]` in `sim_bridge.py`; extend with `"iverilog"` when **U20** lands. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D10. Pin pre-commit hooks consistently; add `.editorconfig` ✅

- Shipped; superseded 2026-06-22 (#102) — hooks now run *local*, tracking `uv.lock`. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

### Tier 4 — Documentation

#### D11. Module + mock-class docstrings ✅

- Shipped (#104 later moved the parser to `scripts/amaranth_parser.py`). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D12. Architecture diagram in CONTRIBUTING.md (partially done)

- **Why:** CLAUDE.md has a great file-role table. CONTRIBUTING.md now *has* an "Architecture overview" section (two-process model, VHDL-side clock, SimPanel, board-sync table, session state) — but in **prose**, deferring the deep view to the README, with no diagram or dataclass/contract summary.
- **What (remaining):** Add an **ASCII data-flow diagram** (launcher → sim subprocess) plus the `BoardDef` / `ComponentInfo` / `SevenSegDef` dataclass shapes and the VHDL contract summary — or, if the prose section is judged sufficient, close D12 as done.
- **Touches:** `CONTRIBUTING.md` (extend the existing `## Architecture overview`).
- **Effort:** XS (section scaffolding already exists).
- **Dependencies:** None.
- **Done when:** the Architecture overview includes an ASCII data-flow diagram and the dataclass/contract summary (or a documented decision that the prose suffices).

### Tier 5 — Tests

#### D13. Platform-specific `_build_sim_env` coverage

- **Why:** `tests/test_sim_bridge_backend.py` doesn't exercise the Windows vs Linux PATH / PYTHONHOME divergence; bugs there only surface on the actual platform.
- **What:** Parametrise tests with `monkeypatch` on `sim_bridge.IS_WINDOWS`; assert env dict shape for both branches.
- **Touches:** `tests/test_sim_bridge_backend.py`.
- **Effort:** S.
- **Dependencies:** None. Easier after D5 (platform-aware path helper) since branches will be cleaner.
- **Done when:** tests verify env dict contents for both `IS_WINDOWS=True` and `IS_WINDOWS=False`.

#### D14. Session-config edge cases ✅

- Shipped incrementally; completed by **U5 ✅** (2026-07-06, PR #169), whose merge-on-write made unknown-key preservation load-bearing. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

---

## Dependencies

### Dependency table

Hard dependencies ("requires") must be completed before the blocked item can start. Soft dependencies ("benefits from") are not blockers but reduce effort or improve quality.

| Blocked item | Requires | Reason |
|---|---|---|
| ~~**U6** (Theme system)~~ ✅ | ~~**U5** (Settings dialog)~~ ✅ | Theme row now enabled and applies the choice live — both shipped |
| ~~**U6** (Theme system)~~ ✅ | ~~**D15** (Color consolidation)~~ ✅ | `set_theme()` swaps the `Theme` object's contents in place — both shipped |
| **U27** (User JSON themes) | ~~**U6** (Theme system)~~ ✅ | Registry + `set_theme()` shipped; U27 makes the registry dynamic |
| ~~**U10** (Waveform capture)~~ ✅ | ~~**U5** (Settings dialog)~~ ✅ | Both shipped; the reserved key became the tri-state `waveform` |
| **U18** (Recent files) | ~~**U5** (Settings dialog)~~ ✅ | `recent[]` is populated on every pick + launch |
| **U19** (Metrics checkbox) | ~~**U5** (Settings dialog)~~ ✅ | Settings dialog shipped; `metrics_enabled` session key reserved |
| **U20** (Verilog support) | ~~**D2** (Backend ABC)~~ ✅ | Third backend now overrides only `NAME` + command builders |
| ~~**U21** (Board-native VHDL)~~ | ~~**D1** (Wrapper merge)~~ ✅ | Adapter logic in unified template |
| ~~**U22** (7-seg physical mux)~~ | ~~**D1** (Wrapper merge)~~ ✅ | Placeholders in unified template |
| ~~**D6b** (ScreenController)~~ ✅ | ~~**D6a** (Screen-result enum)~~ ✅ | Enum-typed transitions in the controller — both shipped |

### Soft dependencies

| Item | Benefits from | Reason |
|---|---|---|
| **U1** (Help dialog) | **D4** (Shared button helper) ✅ | Consistent "Close" button styling |
| **U3 ✅** (Tooltips) | **D3 ✅** (UIComponent base) | Unified hit-testing across component types |
| **U5** (Settings dialog) | **D4** (Shared button helper) ✅ | Reuse button rendering in dialog |
| ~~**U7** (In-sim toolbar)~~ ✅ | **D4** (Shared button helper) ✅ | Consistent toolbar button styling |
| **U8** (Splash) | **U0** (Board filtering) | Left panel already has filter chips |
| ~~**D9** (Literal types)~~ ✅ | — | Extend the `Simulator` alias in `sim_bridge.py` to add `"iverilog"` when U20 lands |
| **D13** (Env tests) | **D5** (Path helper) | Cleaner branches are easier to test |
| **D16** (Sandbox sim) | **D7** (`launch_simulation` split) | `_invoke_run` seam is where the `bwrap` wrap belongs |

### Dependency graph (hard dependencies only)

```text
D1 (wrapper merge) ✅ — U21 and U22 are now unblocked

D2 (backend ABC) ✅ — U20 unblocked; a third backend overrides only NAME + command builders
 └──> U20 (Verilog support)

U5 (settings dialog) ✅ — U6 ✅ + U10 ✅ shipped; U18 / U19 remain unblocked
 ├──> U6  (theme system) ✅     # also required D15 (below)
 ├──> U10 (waveform capture) ✅
 ├──> U18 (recent files)
 └──> U19 (metrics checkbox)

D15 (color consolidation) ✅ — U6 (theme system) ✅ — both shipped
 └──> U6  (theme system) ✅

U6 (theme system) ✅ — U27 is now unblocked
 └──> U27 (user-defined JSON themes + example scheme pack)

D6a (screen-result enum) ✅ — D6b (ScreenController) ✅ — both shipped
```

All other items (U0, U1, U2, U3, U4, U8, U9, U11-U17, U21-U25, U28-U30, D3-D5, D7-D16) are independently shippable.

---

## Suggested merge order

A practical sequencing if all items were in flight (impact-weighted, with foundations early enough to unblock later work). Sprint 1 is split into two sub-sprints to keep batch sizes manageable (~8-12 h each).

| Sprint | Theme | Items |
|---|---|---|
| **1a** | Quickest wins + foundations | ~~U0 Board filtering~~ ✅ · ~~U11 Reset key~~ ✅ · ~~U12 Board summary format~~ ✅ · ~~D1 Wrapper template merge~~ ✅ · ~~D9 Literal types~~ ✅ · ~~D10 .editorconfig + hook pins~~ ✅ · ~~D11 Mock-class docstrings~~ ✅ |
| **1b** | Small features + DRY foundations | ~~D4 Shared button helper~~ ✅ → ~~U13 Arrow/Page nav~~ ✅ → ~~U1 Help dialog~~ ✅ → ~~U2 Analysis spinner~~ ✅ · ~~D2 Backend base class~~ ✅ · ~~U26 Visual README~~ ✅ |
| **2** | Foundations that unblock later UX | ~~D6a Screen-result enum~~ ✅ · ~~D6b ScreenController~~ ✅ · ~~D15 Color consolidation~~ ✅ · ~~U5 Settings dialog + extended session~~ ✅ · ~~D8 mypy strict~~ ✅ |
| **3** | Visible polish | ~~U3 Tooltips~~ ✅ · ~~U4 Contextual errors~~ ✅ · ~~U6 Theme system~~ ✅ · ~~U7 In-sim toolbar~~ ✅ |
| **4** | Feature breadth | U8 Splash · U9 PWM brightness · ~~U10 Waveform~~ ✅ · U23 Dirty-flag redraw · U27 User JSON themes |
| **5** | Waveform polish | ~~U28 Auto-emit `.gtkw`~~ ✅ · ~~U29 `FPGA_SIM_WAVEFORM` env + auto-open~~ ✅ · ~~U30 "Include memories" (`--dump-arrays`)~~ ✅ |
| **6** | Board-native VHDL (lab↔sim round-trip) | ~~U21~~ ✅ **shipped 2026-07-13** (A0–B4, PRs #209–#222) per [`u21_board_native_vhdl_plan.md`](u21_board_native_vhdl_plan.md). **Coverage follow-on (raised the 23/278 genuine-usable count to 258/278 — see the "Board-native VHDL coverage" note under U22):** ~~U31~~ ✅ partial-interface → ~~U32~~ ✅ litex/amaranth auto-derive (241/246 boards) → ~~U33~~ ✅ canonical population waves. **All released in v0.14.0** |
| **7** | Iteration & panel UX | U18 Recent files (+ keep dir on retry) · U14 Pause/resume · U15 Compact SimPanel · U19 Metrics checkbox |
| **8** | Startup hardening + dev-DRY base | U16 Min window size · U17 Font pre-alloc · **D5 Path helper** → D13 Env-branch tests · D12 Arch diagram |
| **9** | Untrusted-VHDL isolation | **D7 Decompose `launch_simulation`** → D16 Sandbox the sim subprocess |
| **10** | Performance deep-dive | U25 Profile GHDL GPI vs eval · ~~U24 Batch `Timer` calls~~ (won't-do, resolved by measurement) · **U34 single-window** *(in progress — own release, ahead of this sprint)* |
| **11** | Verilog / SystemVerilog | U20 Verilog support (Icarus) |
| **12** | 7-seg physical mux | U22 7-seg physical mux (shares U21's wrapper-template 7-seg context) |

**Status (2026-07-09).** Sprints 1a, 1b, **2, and 3 are fully shipped**, and **milestone v0.13.0 is now a waveform-themed release** (re-cut 2026-07-09): **U10 ✅** (capture, PR #187, issue #186) plus the folded-in **Sprint 5 waveform-polish** cards **U28 ✅** (`.gtkw`, PR #192) / **U29 ✅** (env + auto-open, PR #193) / **U30 ✅** (include memories, PR #196 / issue #191 — completing **Sprint 5** and the **v0.13.0** waveform release, 2026-07-11); the other Sprint-4 UX cards **U8 / U9 / U23 / U27** moved to **v0.14.0**. Sprint 3 (milestone v0.12.0) delivered **U6 ✅** (Theme system, PR #178), **U4 ✅** (Contextual errors, PR #181), **U7 ✅** (In-sim toolbar, PR #182), and **U3 ✅** (Tooltips, PR #184) — with the **D3 ✅** UIComponent-base refactor (PR #183) landed first as prep for U3. The phases otherwise remain correctly ordered. **Sprints 5–12 are now mapped** (2026-07-09) from the previously-unscheduled backlog — waveform polish (5) → board-native VHDL (6, its own sprint per the lab↔sim round-trip priority) → iteration / panel UX (7) → startup + dev-DRY base (8) → untrusted-VHDL isolation (9) → performance (10) → Verilog (11) → 7-seg physical mux (12). The only cross-item constraints are the soft chains **D5 → D13** and **D5 + D7 → D16**, both honored (D5 in 8; D7 + D16 in 9); every other 5–12 sprint is order-free. Per the hybrid backlog model, only the *active* sprint gets a GitHub milestone + issues — 5–12 stay strategy-only until promoted.

---

## Icebox

**Parked / deferred-on-trigger items.** Each carries a **trigger** — the condition under which it should graduate into a tier above. Unlike the tiered backlog these are blocked or speculative, so they hold no sprint slot and don't appear in the dependency graph. *(Consolidated here 2026-06-27 from session memory, where neither contributors nor a future maintainer could see the item or watch its trigger.)*

**Embedded-core follow-up arc — complete 2026-07-02 (PRs #140–#154):** [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md) — turned the 2026-07-02 review behind **P7**'s and **P8**'s notes below into ordered, executable phases; its status ledger has the per-phase PRs.

| ID | Item | Trigger to schedule | Effort | Notes |
|---|---|---|---|---|
| **P1** | NVC backend tuning — elaborate-once, run-many | Any push to raise NVC simulation throughput | M | `launch_simulation()` re-elaborates NVC (`-e`) on every run (see **D7**). Caching the elaborated design across runs of the same VHDL would cut per-run startup. NVC-only (GHDL has no separate elaborate step); benchmark before/after. |
| **P2** | Board-sync Phase 3 — merge-aware / curation sync | Upstream removes a board we ship (recon to date: 0 removed) | L | Retain upstream-removed boards, dual upstream/adopted timestamps, `--check`, `--with-dates`. The schema `source` block permits additive provenance fields. A *subset* (preserve hand-added `port_conventions` / `peripherals` on re-sync, ~10 lines) shipped as **U21 Phase A1 ✅** (#210). Maintainer tooling in `scripts/sync_*.py`, not the app. |
| **P3** | Mercury board 7-segment | A user requests it, or the I2C-expander path becomes worth modeling | M/L | Mercury's display sits behind an I2C GPIO expander (not directly pinned), so it was excluded from 7-seg v1. Needs an expander model + readback path. |
| **P4** | Python 3.14 in the CI matrix | pygame **and** cocotb both ship `cp314` wheels | S | As of 2026-06, pygame 2.6.1 / cocotb 2.0.1 top out at `cp313`; adding 3.14 breaks `uv sync` (pygame sdist build). Re-check PyPI wheel tags before bumping the matrix upper bound. |
| **P5** | Sync-time peripheral extraction | A peripheral type becomes consumable — the sim gains a peripheral model (VGA/audio/…), or the board-info UI wants to list on-board peripherals | M | All three parsers extract only LED/button/switch (+clock/7-seg) and discard everything else — `peripheral` appears nowhere in `scripts/` or `src/`. Upstream exposes the data richly: amaranth already has typed `Resource` stubs (`VGAResource`, `UARTResource`, `SDRAMResource`, `DDR3Resource`, …) that are currently inert; Digilent XDC section headers (`## VGA`, `## Audio`, …) are already parsed, then dropped; litex `_io` names (`serial`, `sdram`, `eth`, …) need a name→type map. `BoardDef` has no `peripherals` field, so the 6 hand-authored `custom/` boards' `peripherals` blocks are schema-valid but silently dropped at load. Needs: parser extraction → new `BoardDef.peripherals` field → JSON round-trip (the schema already defines `peripheral`). Auto-extracted data is shallower than the hand-curated attributes (`bits_per_channel`, `size_mb`, chip names). Complements **P2** / **U21** (preserve hand-added peripherals on re-sync) and the eventual per-type discriminated-union schema. |
| **P6** | User-configurable / external boards directory | A user installs via wheel (custom boards under the package dir are wiped on upgrade), or asks to keep board JSON outside the package | S/M | `get_default_boards_path()` hardcodes `<package>/../../boards` with no override and `discover_boards()` is only ever called with it, so the board selector is closed to the bundled tree (custom boards must live in `boards/custom/` *inside* the package). Add a `FPGA_SIM_BOARDS_PATH` env var and/or a Settings entry (U5) pointing at an extra source root (e.g. `~/.fpga_simulator/boards/`), merged with the bundled sources. The loader already treats each subdirectory as an independent source, so an external root drops in with no schema change. Distinct from **P2** (upstream sync curation) — this is user-supplied boards. Pairs with **U5** / **U18** (same Settings/persistence surface; the VHDL picker already browses arbitrary dirs, so this closes the equivalent gap on the board side). |
| **P7** | VHDL lint/format via **VSG** (VHDL Style Guide) | The embedded-core **generator (Stage 3, see [embedded_core_system_plan.md](embedded_core_system_plan.md)) starts emitting VHDL** — at which point a canonical formatter pays off (stable generated diffs + consistent hand-written `hdl/` examples). | S | VHDL is the only language here with no linter/formatter; the others run as `uv run <tool>` *local* pre-commit hooks pinned by `uv.lock` and mirrored in CI (see **D10 ✅**). VSG (`uv`-installable) slots into that exact pattern: add to the `dev` group, a `vsg` local hook, and a **check-only** CI step (like `ruff format --check`; `--fix` stays a local convenience). **Hard exclusions — VSG must never touch:** `scripts/embedded_core/cores/**` (vendored verbatim; reformatting breaks byte-identity and the pinned-commit integrity tests in `test_embedded_core.py`), `hdl/bad_*` (deliberately broken negative-test fixtures), `sim/sim_wrapper_template.vhd` (`{placeholder}` tokens are not valid VHDL), and `scripts/embedded_core/templates/**` (`.vhd.tmpl` files carry `@@TOKEN@@` markers, and `.vhd.frag` fragments are partial design units — VSG cannot parse either, for the same reason as `sim_wrapper_template.vhd`). **Generator nuance:** a generated `mx65_*.vhd` embeds the verbatim mx65, so never `--fix` generated output — author templates to the ruleset's style by hand (VSG never parses them; CI checks hand-written `hdl/` only). *Refinement idea, not a requirement:* a generated file's system blocks (everything after the `-- System blocks (generated)` ruler) are complete, valid design units on their own and could be mechanically style-checked via a temp-file slice — the vendored core above the ruler is what must stay untouched. Land it as its own PR (the one-time reformat of the ~9 `hdl/*.vhd` examples is isolated churn; tune a ruleset that respects the readable teaching style rather than fighting it). **Limit:** style only — not a substitute for `ghdl -a` / `nvc -a` analysis (the real correctness gate) and won't catch logic bugs (e.g. the `walking_counter` switch-rate issue, [#133](https://github.com/Machai-Kydoimos/fpga-board-sim/issues/133)). |
| **P8** | Third core: **RISC-V (NEORV32)** embedded-core example | Appetite for a 32-bit third core to prove the "any core" abstraction beyond 8-bit; best started after #135 (the embedded-core feature) merges. NEORV32 is the natural pick — it's the standout **VHDL** RISC-V core; most compact ones (PicoRV32, VexRiscv) are Verilog, which GHDL/NVC can't analyze. | L | **Feasibility spike done 2026-07-02 — the core is clean; this is a skeleton-generalization arc, not a Z80-style drop-in.** Against a fresh `stnolting/neorv32` clone: the CPU (`rtl/file_list_cpu.f`, 20 files, ~11k lines — CPU only; the full SoC is far larger) **analyzes 100% clean under both GHDL `--std=08` and NVC `--std=2008` with no `-fsynopsys`** (standard IEEE, `std_ulogic`), clearing the core requirement (guide §4.1). The real work is the **8→32-bit jump** the 6502/Z80 never forced: **(1) bus bridge** — NEORV32 exposes *two* 32-bit **handshaked** buses (Harvard `ibus_req_o`/`dbus_req_o` of record `bus_req_t`: `addr(31:0)`, `data(31:0)`, byte-enable `ben(3:0)`, `stb`/`rw`; + `bus_rsp_t` data/ack/err) vs our normalized **8-bit same-cycle combinational** bus, so the adapter becomes real logic (arbitrate or keep Harvard, generate `ack`, honor `ben`), not a trivial `block`; **(2) data width** — parameterize the ROM/RAM/IO skeleton to 32-bit (word-addressed IO) or bridge byte lanes (`cpu_din`/`cpu_dout` are 8-bit today); **(3) named library** — the core uses `library neorv32; use neorv32.…` (analyze with `--work=neorv32`), so the single-file/`work` model needs a mechanical `neorv32.`→`work.` rewrite across the files (a broader T80-style patch) or multi-library support; **(4)** `std_ulogic`/records at the boundary (minor); **(5)** boot is easy — a `BOOT_ADDR` generic, no fixed reset vector. **Firmware toolchain:** none installed, but Fedora packages it — `binutils-riscv32-linux-gnu` (`as`/`ld`/`objcopy` → an assembly-source→`.bin` flow mirroring ca65/z80asm) and `gcc-riscv32-linux-gnu` (adds C); one `dnf install` when the arc starts (rv32 target = the riscv32 packages; riscv64 works via `-march=rv32i` multilib). They are `-linux-gnu` (not bare-metal `-elf`), but a **freestanding** build (`-ffreestanding -nostdlib -nostartfiles` + our own linker script) is fine for minimal firmware — we don't need NEORV32's own `riscv-none-elf` software framework. (clang also targets riscv32, but `ld.lld` is absent, so binutils is the simpler linker path.) The `qemu-*`/`edk2-*` RISC-V packages aren't relevant (we simulate the RTL in GHDL/NVC). Dev-time only — the checked-in `.bin` stays the source of truth, not a CI dep. **Vendoring:** CPU-only, configure unused features off via generics (FPU/PMP/crypto/debug/`C`) to shrink the ~11k lines inlined per design. Start with the data-width decision + a minimal `neorv32_cpu` + bridge spike before any firmware. **Sequencing (2026-07-02):** build the bus bridge as **"normalized bus v2 first"** — a handshaked, width-parameterized bus (valid/ready + byte enables) — and re-express the mx65/T80 adapters as its degenerate case (ack always `'1'`, width 8) rather than special-casing a second bus beside v1. Script the `neorv32.` → `work.` library rewrite as a re-runnable patch script (a T80-style documented patch, but automated — 20 files is too many to hand-edit reproducibly). **Decision point:** at ~11k inlined lines per design, evaluate whether `sim_bridge`'s single-file rule should gain a relief valve (analyze a design + companion files) before committing to inline-everything for a 32-bit core. **Requires** [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md) Phases 0–4 (spec validation + the emitter's fragment seam) to land first. |
| **P9** | Embedded-core walking firmware: `N_LEDS >= 2` clamp | First real report of someone running a CPU design on a 1-LED board, or the next planned firmware reassembly wave | S | The bounce logic in the walking-style firmwares (`mx65_walking_counter_7seg.s`, `mx65_irq_counter_7seg.s`, and all four `t80_*` walking-style `.asm` sources) underflows `POS` when `NUM_LEDS = 1` (no second LED to bounce toward), going dark on a 1-LED board (the 7-seg odometer is unaffected). Documented as a known gap in the guide (Phase 0 of [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md)) rather than fixed, because a fix means re-editing and reassembling all six checked-in `.bin`s — churn unjustified without a real report. |
| **P10** | Committed T80 IM 1 (`irq_mode = "simple"`) reference design | A third core lands (completing the interrupt-mode matrix then has real demonstration value), or a user asks for an IM 1 reference | S/M | Z80 IM 1 is generator-supported today — the base `t80.vhd` adapter plus the same emitter branch `mx65_irq_counter_7seg` already exercises — but no committed `systems/*.toml` selects it, so the path is declared but unexercised by any shipped design. A 7th ~150 KB generated design + new firmware would complete the (core × `irq_mode` × `io_transport`) matrix, but Phase 7 of [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md) judged the pedagogical return too low to justify the size right now. |
| **P11** | Traffic-light FSM teaching design | Curriculum/course use surfaces a need for a labeled-states FSM example | S/M | A classic labeled-states FSM (red → green → yellow → red) would round out the hand-written teaching examples, but `hdl/stopwatch_7seg.vhd` (Phase 7 of [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md)) already demonstrates FSM-ish control plus live user interaction, so adding a second, narrower FSM example was judged example sprawl for now rather than added teaching value. |
| **P12** | Hex-counter firmware variant | Never, by design — unless the guide gains a solutions appendix | S | Deliberately **not** implemented: `docs/embedded_core_system_guide.md` §13 already names "hex vs BCD" as the reader's own first-firmware exercise (the walking counter's BCD ripple is the worked example to adapt). Implementing it here would remove the homework value it is meant to have. |
| **P13** | Waveform capture is unbounded in size — weigh the consequences | A capture fills the disk or hits a quota (the U29 smoke run's `/tmp` `EDQUOT`-truncated a dump mid-write), or a user reports a surprisingly large file | S/M | Native waveform capture (**U10 / U28 / U29**, now shipped) writes for the **entire** simulated run with **no size bound**. Concrete: ~1–2 s smoke runs produced **42–119 MB** VCDs; FST is ~10–20× leaner (2–5 MB) but still unbounded, and a mid-write `/tmp` `EDQUOT` **truncated** one dump (GTKWave then reads the torn VCD as "times range zero"). **Consequences to weigh:** filling `~/.fpga_simulator/waveforms/` / the disk / a tmpfs quota; torn dumps on `ENOSPC`; sluggish viewer loads; and that successive runs **accumulate** timestamped dumps with no retention/cleanup. **Candidate resolutions (open — decide at schedule time, not prescriptive):** a **size cap** (stop at *N* MB, keep + flag the partial); a **pre-/post-run "capture is ~N MB" heads-up** (Settings hint or an end-of-run line); nudging **FST as the leaner default**; a **retention sweep** of the waveforms dir; documenting the existing `FPGA_SIM_WAVEFORM_DIR` escape hatch; or something else we choose then. **Not a U29 bug** — capture works as designed; this is about the ergonomics/safety of the unbounded default. (The `/tmp` tmpfs per-user quota that triggered the truncation is a separate environmental footgun.) |
| **P14** | GHDL-VCD + Memories=On is a silent dead-end — steer users to FST | A user enables the **Memories** toggle under GHDL with VCD selected and sees no memories (or reports it) | XS/S | U30's Memories toggle drives NVC `--dump-arrays` but is a **no-op under GHDL**: GHDL's VCD *writer* omits memories (its FST/GHW writers include them by default, no flag), so **GHDL + VCD + Memories=On silently yields nothing**, with no indication why. Correct-by-design, but a confusing combination. **Candidate resolutions (open):** a Settings hint when GHDL+VCD+Memories is selected ("memories need FST under GHDL"); auto-suggesting/switching to FST; or a one-line end-of-run note. Cosmetic/ergonomic only — the format matrix is documented (embedded-core guide §15, CHANGELOG, `WaveConfig` docstring). Sibling of **P13** (both waveform-capture ergonomics). |
| **P15** | Global cross-board convention *ambiguity* detection | A future board introduces a name+width-identical, polarity-*different* collision (today's `test_native_convention.py` invariant would fail loudly first), or a user reports a board-native file matching the "wrong" board | S/M | U21 ✅ resolves the wrong-board case safely by construction: a native file either near-misses on a differing port name or matches an electrically identical board (the only cross-board full match in the current data is DE23-Lite ↔ DE25-Standard, same polarity). What's **not** built is *global* ambiguity detection — "does this file also match another board *better* than the selected one?" Not needed for the current fleet (proven by the data-invariant regression test, which fails loudly if a name+width-identical, polarity-different pair ever appears), so it's deferred rather than speculatively built. **If triggered:** sweep the fleet's canonical conventions at match time and surface a "this also matches board X" note, or gate on a distinct discriminator (e.g. a unique clock name). See U21's plan §"Cross-board safety". |
| **P16** | Surfer waveform signal *preselection* (`-c`/`--command-file`) | A user asks for an auto-preselected signal list in Surfer (not just GTKWave), or Surfer's command-file API stabilizes | S | U21 B3 ✅ made the auto-`.gtkw` save file preselect a board-native run's *own* `sim_wrapper.uut.<native>` signals (was contract names) — but `.gtkw` is **GTKWave-only**. Surfer (installed; opened via `$FPGA_SIM_WAVEFORM_VIEWER=surfer {dump}`) already shows the full tree with both the native and contract names present, so there's no wrong-default — just no auto-*preselect*. A symmetric Surfer preselection via its `-c`/`--command-file` is **orthogonal to U21** (it would help generic mode too), and Surfer's `--help` flags that API as "not permanent," so it's parked rather than built. Pairs with **U29 ✅** (the configurable-viewer template that already launches Surfer). |
| **P17** | Board-native "frozen-divider" warning heuristic | A user reports a board-native design that renders as static LEDs/digits because it divides the full clock down, or board-native authoring becomes common enough to warrant a lint | S | Board-native designs (U21 ✅) carry **no `COUNTER_BITS` override** — that generic is generic-contract-only — so a design that derives its visible rate from the top bits of a real 50 MHz divider looks **frozen** at the simulator's sub-real-time throughput (a real board would tick it fast). U21 handled this **by documentation**: the `hdl/native/*.vhd` examples tap *mid* counter bits, and CLAUDE.md's board-native section calls out the gotcha. A **literal-constant warning heuristic** — detect a large fixed divider threshold / top-bit tap in a native design and warn "this may look static at sim speed; tap lower bits or reduce the divider" — was parked here (U21 decision 6) rather than built, since it's advisory and easy to get wrong (false positives on legitimate slow signals). |
| **P18** | `add_port_convention.py` — one-command authoritative-convention authoring | A user (or maintainer) finds an authoritative source for a specific board's port names and wants it usable board-native without hand-editing JSON | S | Today, adding a *vendor-canonical* convention for one board means either the registry + `waves.toml` + `overlay.toml` path (rigorous, cited, but needs a machine-parseable constraint file) or a hand-edited `port_conventions.<vendor>` block in the board JSON (preserved by the A1 guard, but hand-written JSON). Neither is a *single* command. A small helper — `add_port_convention.py --board X --key terasic --clk CLOCK_50 --leds LEDR:10 --buttons KEY:4:active_low --seg HEX:6:active_low --cite <URL>` — would emit a schema-valid `naming: "canonical"` block with a `source` citation and merge it via the existing `merged_board_json` path (coexisting with any U32 framework-derived block, winning via `_convention_precedence`). Raised during U32 (2026-07-14) when weighing how a future authoritative source gets incorporated as ground truth; the data model already supports it, so this is pure authoring ergonomics. |
| **P19** | `analyze_metrics.py` rework for split-process metrics | Someone analyzes the per-frame metrics CSV again and finds the draw/idle columns zeroed | S | Single-window (**U34 ✅**) split the sim loop (headless child) from rendering (host). The `FPGA_SIM_METRICS` CSV is still written child-side with real `timer_us` / `sim_step_ns` / `clk_period_ns` / `speed_factor`, but `draw_us` / `tick_us` are now **`0.0`** there (rendering moved to the host, which does not write the CSV). `scripts/analyze_metrics.py` therefore reports zero draw/idle for single-window runs. Rework it to read the host-side draw/idle (from the session log / `SimulationScreen.run_stats`) or merge the two sources. Parked at U34 closeout — no active metrics-analysis consumer today. |
| **P20** | Modernize `sim/capture_frames.py` (offline GIF capture) | The offline GIF/demo-capture path needs updating, or it drifts far enough from the single-window model to confuse | XS/S | `sim/capture_frames.py` + `scripts/capture_demo.py` legitimately keep the **pygame-in-the-cocotb-child** pattern (headless offline GIF capture, invoked outside the launcher), so **U34 ✅** left them untouched. They now diverge from the production single-window path (which renders in the host). Optionally refactor them to drive the sim over `sim_link` and render via `SimulationScreen` for a single rendering path, or leave them as the standalone capture tool they are. Cosmetic / DRY only — they work as-is. |

**Also parked (speculative, no trigger):** *LCD / OLED display support* — a stretch goal from the original `prompt_info` vision (alongside 7-seg, which shipped). No board JSON models a character LCD / OLED and no user has requested it; recorded for completeness only.

---

## Critical files modified across the roadmap

- `src/fpga_sim/__main__.py` — U2 ✅, U5 ✅ (window-size restore), U21 ✅ (`res.match` → analyze/launch), U16, D6a ✅, D6b ✅ (now a thin driver), D9 ✅
- `src/fpga_sim/controller.py` — D6b ✅ (new: `ScreenController` + `SessionState`), U4 ✅ (`example_vhdl_for` wiring), U5 ✅ (save-on-pick/change/quit + speed plumbing), U7 ✅ (`on_simulate` acts on the returned `SimExit`; reload/back/change routing), U21 ✅ (`SessionState.convention` + `ConventionMatch` threading), U18 (retry start-dir)
- `src/fpga_sim/sim_bridge.py` — U4 ✅ (parsed contract checks + `add_error_hints`), U5 ✅ (`speed_factor` → `FPGA_SIM_SPEED`), U7 ✅ (`SimExit` enum + exit-intent sidecar; `launch_simulation()` returns it), U10 ✅, U21 ✅ (convention matcher + native `_render_native_wrapper`; native `.gtkw` preselection), D1, D2 ✅, D5, D7, D9 ✅ (defines `Simulator`), D16 (wrap the run subprocess)
- `src/fpga_sim/board_loader.py` — U12, D11 ✅, U21 ✅ (B1: `BoardDef.port_conventions` + serialization)
- `src/fpga_sim/session_config.py` — U5 ✅ (merge-on-write; new `update_session` / `push_recent`), U18, D9 ✅, D14 ✅, D16 (sandbox toggle)
- `src/fpga_sim/ui/constants.py` — D15 ✅ (now base neutrals only), U17
- `src/fpga_sim/ui/theme.py` — D15 ✅ (new: `Theme` dataclass + `THEME`), U2 ✅ (`spinner_arc` / `spinner_track` roles), U5 ✅ (`THEME_NAMES` / `THEME_LABELS` + settings button styles), U6 ✅ (`dark` / `high-contrast` instances + `set_theme` / `current_theme_name`), U27 (dynamic registry + JSON loader)
- `src/fpga_sim/ui/components.py` — U3 ✅, U9, D3 ✅, D15
- `src/fpga_sim/ui/board_display.py` — U1 ✅, U3 ✅, U5 ✅ (gear trigger), U11, U16, D3 ✅, D4 ✅, D6a ✅ (`run()` returns `ScreenResult`), D9 ✅ (simulator round-trips through `FPGABoard`), D15
- `src/fpga_sim/ui/board_selector.py` — U0, U1 ✅, U8, U12, U13 ✅, D15
- `src/fpga_sim/ui/sim_panel.py` — U5 ✅ (`speed_factor` ctor param; public `SPEED_DEFAULT`), U21 ✅ (native-convention INFO note), U14, U15, U19, D4 ✅, D15
- `src/fpga_sim/ui/vhdl_picker.py` — U1 ✅, U13 ✅, U18, D15
- `src/fpga_sim/ui/error_dialog.py` — U4 ✅ (`example_path` → [View Example]), D4 ✅, D6a ✅ (`run()` returns `DialogResult`), D15
- New: `src/fpga_sim/ui/theme.py` (D15 ✅), `src/fpga_sim/ui/help_dialog.py` (U1 ✅), `src/fpga_sim/ui/spinner.py` (U2 ✅), `ui/settings_dialog.py` (U5 ✅), `ui/sim_toolbar.py` (U7 ✅), `ui/tooltip.py` (U3 ✅), `ui/widgets/button.py` (D4 ✅), `src/fpga_sim/ui/results.py` (D6a ✅), `src/fpga_sim/controller.py` (D6b ✅), `src/fpga_sim/sandbox.py` (D16), `scripts/capture_demo.py` / `scripts/capture_selector.py` / `scripts/capture_common.py` + `sim/capture_frames.py` (U26), `docs/assets/` (U26 — committed GIFs)
- `README.md` — U26 (hero GIF + screenshot embed)
- `sim/sim_wrapper_template.vhd` — D1 ✅ (absorbed 7seg template)
- `sim/sim_testbench.py` — U5 ✅ (speed restore + write-back), U7 ✅ (toolbar draw + click → intent-file write; F1/`?` → in-sim `HelpDialog`), U21 ✅ (board-native mode tag + session-log `mode`/`convention`), U9, U14, U22, D15
- `pyproject.toml` — D8 ✅ (`[tool.mypy]` now just `strict = true`), U26 (`dev` group gains Pillow)
- `.pre-commit-config.yaml`, new `.editorconfig` — D10 ✅
- `CONTRIBUTING.md` — D12

## Existing utilities to reuse

- `ErrorDialog` modal pattern (`ui/error_dialog.py`) -> reuse layout for help / settings / tooltip dialogs.
- `get_font()` LRU cache (`ui/constants.py`) -> already used everywhere; pre-allocation in U17 just primes it.
- `_generate_wrapper()` (`sim_bridge.py`) -> unified template substitution with conditional 7-seg splicing (D1 ✅).
- `_SimBackend` ABC (`sim_bridge.py`) — D2 ✅ made it an ABC sharing `find()` / `available()` / `lib_dir()` / `sim_bin_lib()` as classmethods; a third backend (U20) overrides only `NAME` + the command builders.
- `session_config.save_session` / `load_session` / `update_session` / `push_recent` (`session_config.py`) -> U5 ✅ extended the schema with merge-on-write; U18 consumes `recent[]`, U6 ✅ writes `theme`, U10/U19 write their keys via `update_session`.
- `sim_metrics.py` / `scripts/analyze_metrics.py` -> consumed by U19; no new infra needed.
- `BoardDef.summary` property (`board_loader.py`) -> update format for U12; extend for U0 filter logic.
- `ui/theme.py` `THEME` object (D15 ✅) — the grouped semantic palette, rethemed in place by U6 ✅'s `set_theme()`; `ui/constants.py` retains the base neutrals (`WHITE`, `GRAY`, …) until U27's phase 0 promotes the component-label/border neutrals into themed roles.

---

## Verification

Per-item verification is described in each entry's "Done when" criterion above. Cross-cutting checks for any merge:

1. **Tests** — `uv run pytest` (1393 tests across 40 files including UI scaling, board selector filtering, board loader, both backends, 7-seg, embedded-core generator + designs, help overlay, theme value-preservation, screen-result enums, ScreenController transitions, settings dialog + session persistence, in-sim toolbar + exit-intent round-trip, UIComponent base contract, component hover tooltips). All sprints must keep this green.
2. **Lint / type** — `uv run ruff check .` and `uv run mypy .` (`strict = true` since D8 ✅).
3. **Manual smoke** — `uv run fpga-sim` end-to-end on a known board (e.g. Arty A7-35) with `hdl/blinky.vhd`; for 7-seg work use `counter_7seg.vhd` on DE10-Lite.
4. **Benchmark regression** — `uv run fpga-sim --benchmark 10` before/after performance-touching merges (U9 / U23). Baseline: 37.7 fps, 0.0036x real-time on Arty A7-35 (from `memory/project_sim_performance.md`).
5. **Headless CI** — every PR runs the existing Linux + Windows x GHDL + NVC x Py 3.10-3.13 matrix.
6. **Visual checks** — for UI work, screenshot the affected screen on Linux and attach to the PR; no automated visual diff today.

---

## Delivery log

Completed-item detail and the cross-cutting carried-forward notes now live in **[roadmap_delivered.md](roadmap_delivered.md)**. Per-PR detail is also in `CHANGELOG.md` and the linked PRs; forward-relevant gotchas from completed work appear as **⚠ Carried-forward** notes on the open cards they affect (e.g. the Tier-3 note on **U14**).
