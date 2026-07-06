# Virtual FPGA Boards — Improvement Roadmap

*Drafted 2026-05-19 · Updated 2026-07-06 · Status: draft for review · Companion to CHANGELOG.md / CONTRIBUTING.md*

A comprehensive, impact-weighted roadmap covering improvements from two perspectives:

1. **User-facing** — UX, performance, presentation, persistence, features.
2. **Developer-facing** — architecture, DRY, type safety, documentation, tests, tooling.

Each item lists *why* it matters, *what* to do, *which files* are touched, a rough effort estimate (XS / S / M / L / XL), and a *done-when* acceptance criterion. Tier numbers reflect impact-weighted priority, not strict execution order; see "Suggested merge order" at the end for a practical sequencing and "Dependencies" for required ordering constraints. Completed cards are condensed to a one-line stub here, with full shipped detail in [roadmap_delivered.md](roadmap_delivered.md).

---

## Context

The simulator is mature: ~6,000 LOC across 20+ Python modules (≈7,400 incl. `sim/`), 35 test files (1235 tests), multi-platform CI, two simulator backends (GHDL/NVC), 7-segment support shipped, embedded CPU core systems (6502/Z80) shipped, 278 board definitions from four sources, three UI themes, performance heavily tuned (PR #31), v0.11.0 released (2026-07-06).

It is feature-complete for experienced FPGA users, but the codebase and UX have grown organically. Four patterns motivated this roadmap; several are now partly addressed (noted inline):

1. **Board discovery at scale.** With 278 boards from 7 vendors, the original flat scrolling list with text-only filtering was inadequate — users could not filter by component type, vendor, or capability. **U0 ✅** added faceted filtering + sort, largely resolving this.
2. **Onboarding & discoverability gaps.** README is excellent (~605 lines) but historically unreachable from inside the app. **U1 ✅** added an in-app help overlay (workflow, shortcuts, design contract); the README itself is still not surfaced in-app.
3. **DRY drift.** Three component classes with identical structure (D3, open) remain; the 264-line main function is gone — **D6a ✅** typed its screen results and **D6b ✅** lifted the loop into a `ScreenController` (`controller.py`), leaving `main()` a thin driver. Backend/color/button drift is resolved: **D2 ✅** collapsed the two near-identical backend classes into one ABC, **D4 ✅** unified button drawing, and **D15 ✅** consolidated ~112 inline RGB literals into a `Theme` object (`ui/theme.py`). *(VHDL wrapper templates unified in D1 ✅.)*
4. **Roadmap gravity.** Features queued in memory for months (PWM LEDs, splash, settings screen, waveforms, Verilog, in-sim navigation) are now sequenced below.

This document inventories all viable improvements and ranks them by impact.

---

## Part 1 — User-facing improvements

### Tier 1 — High impact, ship first

#### U0. Board selector — faceted filtering and sort ✅

- Shipped 2026-05-27 (PR #75). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U1. Help / About overlay (clickable `(?)` button · F1 · `?`) ✅

- Shipped 2026-06-01 (PR #88). Carried-forward gotchas live on **U7** / **U14**. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U2. Inline analysis spinner during VHDL load ✅

- Shipped 2026-06-25 (PR #117). Closed Sprint 1b; established the off-main-thread `run_with_spinner()` pattern. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U3. Component tooltips on hover (preview & sim)

- **Why:** Hovering an LED/switch/button currently does nothing visible; net names and pin assignments live only in stdout `print()` callbacks.
- **What:** Hover for ~400 ms -> small tooltip with `net_name`, `pin`, `direction`. Add a `Tooltip` widget; integrate in `LED.draw`, `Switch.draw`, `Button.draw`.
- **Touches:** new `src/fpga_sim/ui/tooltip.py`; small additions in `components.py`; mouse-pos tracking in `board_display.py`.
- **Effort:** M.
- **Dependencies:** Soft: simpler with D3 (UIComponent base provides unified hit-testing).
- **Done when:** hovering a component for 400 ms shows a tooltip with net name, pin, and direction; moving away dismisses it.

#### U4. Error messages with contextual hints

- **Why:** "VHDL Error: port width mismatch" doesn't tell the user which port or expected width; the design contract lives only in CLAUDE.md.
- **What:** Augment `check_vhdl_contract()` and the analyze stderr parser to append actionable hints: *"this board has 16 LEDs -- set NUM_LEDS=16 or use `std_logic_vector(NUM_LEDS-1 downto 0)`"*. Show a "View example" button in `ErrorDialog` that opens `hdl/blinky.vhd`.
- **Touches:** `src/fpga_sim/sim_bridge.py` (`check_vhdl_contract`); `src/fpga_sim/ui/error_dialog.py`.
- **Effort:** M.
- **Dependencies:** None.
- **Done when:** error dialogs include the specific port/width mismatch details and a "View example" button that opens the correct example file.

#### U5. Settings dialog + extended session persistence ✅

- Shipped 2026-07-06 (PR #169, issue #124). Gear button (board preview header) → new `ui/settings_dialog.py`; session schema extended (`window_w`/`window_h`, `speed_factor`, `theme`, reserved `metrics_enabled`/`waveform_enabled`, `recent[]`) with **merge-on-write** so each writer owns its keys (the sim subprocess owns `speed_factor`); saves fire on board/simulator/VHDL change and at quit — not only at launch. **U6 / U10 / U18 / U19 are now unblocked.** Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U26. Visual README — interactive demo + selector GIFs (docs / marketing) ✅

- Shipped 2026-06-25 (PR #110). Headless renderer can later feed **U8** (splash). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

### Tier 2 — High impact, larger initiatives

#### U6. Theme system (light / dark / high-contrast) ✅

- Shipped 2026-07-06 (PR #178, issue #174). New `set_theme()` swaps the shared `THEME` instance's contents in place (call sites bind it once at import, so no draw code changed); alternate **dark** and **high-contrast** `Theme` instances; the Settings Theme row auto-enabled and applies live; the persisted name is restored at startup and carried into the sim subprocess via `FPGA_SIM_THEME`; every import-time `THEME` capture converted to a draw-time read; default `pcb-green` proven pixel-identical (278 board PNGs byte-for-byte vs `main`). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### U7. In-simulation navigation toolbar

- **Why:** Already queued in `project_enhancements.md` (#2). Currently the only way out of sim is ESC; users cannot reload VHDL or change board without restarting.
- **What:** Three buttons in the simulation footer: `[Back to Boards]`, `[Change VHDL]`, `[Reload VHDL]`. `Reload` re-runs `analyze_vhdl()` on the same file and re-enters sim.
- **Touches:** `sim/sim_testbench.py`, `src/fpga_sim/sim_bridge.py` (return code signalling intent), `src/fpga_sim/controller.py` (`ScreenController.on_simulate()` — handle new intents).
- **Effort:** L.
- **Dependencies:** Soft: benefits from D4 (shared button helper).
- ⚠ **Carried-forward (from D4 ✅ / U1 ✅):** reuse `ui/widgets/button.py` for the toolbar buttons (it is importable in the sim subprocess too). Also note the sim screen already has an *inert* F1/`?` help stub (set by U1 but currently unconsumed) — wire it to `HelpDialog` if you want in-sim help alongside the toolbar.
- **Done when:** all three buttons work during simulation; [Reload VHDL] re-analyzes and restarts without returning to the launcher.

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

#### U10. Waveform capture

- **Why:** Queued in memory (#5). VCD/FST output is the natural complement to live LED viewing for debugging.
- **What:** Add `Waveform: off / VCD / FST` toggle in Settings (U5 ✅). On enable: pass `--wave=<path>` (NVC) or `--vcd=<path>` (GHDL `-r`). Show "View in GTKWave" hint after sim ends.
- **Touches:** `src/fpga_sim/sim_bridge.py` (`launch_simulation`), Settings dialog.
- **Effort:** M.
- **Dependencies:** ~~**U5** (Settings dialog)~~ ✅ — shipped; the session's `waveform_enabled` key is reserved for this toggle.
- **Done when:** enabling waveform capture produces a valid VCD/FST file viewable in GTKWave.

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

#### U21. Board-native VHDL mode (port conventions)

- **Why:** Users currently must write VHDL to our generic contract (`clk`, `sw`, `btn`, `led`, `seg` with `NUM_*` generics). A real DE10-Standard design uses `CLOCK_50`, `KEY(3 downto 0)`, `LEDR(9 downto 0)`, `HEX0`-`HEX5` — these fail `check_vhdl_contract()`, the wrapper, and cocotb signal binding. The `port_conventions` data is already stored in board JSON files (e.g. `boards/custom/de10_standard.json` has a `terasic` convention) but nothing consumes it yet.
- **What:** Three changes, each building on the previous:
  1. **Contract checker** — when the user's VHDL ports don't match the generic contract, attempt to match them against the board's `port_conventions`. If a convention matches, accept the file and record which convention was used.
  2. **Wrapper generator** — generate a port-adapter wrapper that maps between cocotb's signal names (`sw`, `btn`, `led`, `seg`) and the user's actual port names (`KEY`, `LEDR`, `HEX0`-`HEX5`). Handle polarity differences (the convention records `active_low` flags). Handle decomposed 7-seg ports (`individual` style: 6 separate `HEX` ports vs. one packed `seg` vector).
  3. **cocotb testbench** — no change needed if the wrapper does the adaptation; cocotb continues reading `dut.sw`, `dut.btn`, `dut.led`, `dut.seg` from the wrapper, which internally connects to the user's port names.
- **Touches:** `src/fpga_sim/sim_bridge.py` (`check_vhdl_contract`, `_generate_wrapper`), `sim/sim_wrapper_template.vhd` (add port-adapter placeholders), `boards/schema/board.schema.json` (port_conventions already defined).
- **Sync script merge logic:** When this feature lands, `scripts/sync_amaranth_boards.py` needs a shallow-merge update: before writing a board JSON, read the existing file (if any) and preserve top-level keys the script didn't generate (`port_conventions`, `peripherals`, etc.). This lets users add conventions directly to `boards/amaranth-boards/*.json` without losing them on re-sync. ~10 lines: read existing -> update auto-generated keys -> write back.
- **Dependencies:** D1 ✅ (unified wrapper template is in place).
- **Effort:** L/XL (contract matching is moderate; the wrapper generator for decomposed 7-seg ports is the hard part).
- **Done when:** a DE10-Standard-style VHDL file with native port names (`CLOCK_50`, `KEY`, `LEDR`, `HEX0`-`HEX5`) simulates without modification.

#### U22. 7-segment v2 — physical mux mode

- **Why:** Queued in memory (#8); current v1 is logical-only. v2 enables the hardware-accurate scan interface on Nexys4-DDR, RZ-EasyFPGA, StepMXO2.
- **What:** New conditional placeholders in the unified wrapper template, updated testbench readback, new `physical_mux: bool` toggle per board.
- **Effort:** L.
- **Dependencies:** D1 ✅ (unified wrapper template is in place).
- **Done when:** a muxed 7-seg board (e.g. Nexys4-DDR) shows correct digits via the physical scan interface.
- **Carried forward (2026-07-02):** physical-mux mode must keep the logical packed-`seg` contract as
  the design-side **default** — every 7-seg example, including the generated embedded-core designs
  (`hdl/mx65_*.vhd`, `hdl/t80_*.vhd`), assumes it.

### Performance (mostly already done)

`memory/project_sim_performance.md` documents PR #31's tuning (37.7 fps, 0.0036x real-time on Arty A7-35; GHDL dominates at 98.4 %). Remaining cheap wins:

- **U23.** Dirty-flag redraw — skip `_draw()` when no LED / switch / button / 7-seg state changed since last frame. Touches `sim/sim_testbench.py` draw loop and `ui/board_display.py`. **Effort:** S. **Done when:** frame rate stays at 30 fps cap but CPU usage drops when no state changes.
- **U24.** Batch multiple `Timer` calls per frame at high speed-slider settings (today >0.1x is CPU-capped). **Effort:** M. **Done when:** high speed-slider settings show measurably higher simulation throughput.
- **U25.** Profile GHDL GPI vs VHDL eval to find the next bottleneck. **Effort:** investigative. **Done when:** a written profile report identifies the top-3 bottlenecks with data.

See also **P1** (NVC elaborate-once / run-many) in the [Icebox](#icebox).

---

## Part 2 — Developer-facing improvements

### Tier 1 — DRY: collapse the duplications

#### D1. Generate the VHDL wrapper from one source ✅

- Shipped 2026-05-28. Unblocks **U21** / **U22**. Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D2. Backend base class with override-only differences ✅

- Shipped 2026-06-25 (PR #115). `_SimBackend` is now an ABC; unblocks **U20** (a third backend overrides only `NAME` + the command builders). Full detail → [roadmap_delivered.md](roadmap_delivered.md).

#### D3. UIComponent base class

- **Why:** `LED`, `Switch`, `Button` in `components.py` share an identical `__init__(index, info)` signature, identical `label` property logic, and an identical `callback` attribute pattern. `SevenSeg` is similar but uses `(index, has_dp)`.
- **What:** Abstract base `UIComponent` with `index`, `info`, `rect`, `label` property; subclass-specific `state` / `pressed` / `bits` stay in children. Optional: register components into a single `board.components: list[UIComponent]` for unified hit-testing.
- **Touches:** `src/fpga_sim/ui/components.py`; small cleanup in `ui/board_display.py`.
- **Effort:** S.
- **Dependencies:** None. Soft: simplifies U3 (tooltips can use unified hit-testing).
- **Done when:** `LED`, `Switch`, `Button` inherit from `UIComponent`; no duplicate `__init__` / `label` code; all component tests pass.

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
| **U10** (Waveform capture) | ~~**U5** (Settings dialog)~~ ✅ | Settings dialog shipped; `waveform_enabled` session key reserved |
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
| **U3** (Tooltips) | **D3** (UIComponent base) | Unified hit-testing across component types |
| **U5** (Settings dialog) | **D4** (Shared button helper) ✅ | Reuse button rendering in dialog |
| **U7** (In-sim toolbar) | **D4** (Shared button helper) ✅ | Consistent toolbar button styling |
| **U8** (Splash) | **U0** (Board filtering) | Left panel already has filter chips |
| ~~**D9** (Literal types)~~ ✅ | — | Extend the `Simulator` alias in `sim_bridge.py` to add `"iverilog"` when U20 lands |
| **D13** (Env tests) | **D5** (Path helper) | Cleaner branches are easier to test |
| **D16** (Sandbox sim) | **D7** (`launch_simulation` split) | `_invoke_run` seam is where the `bwrap` wrap belongs |

### Dependency graph (hard dependencies only)

```text
D1 (wrapper merge) ✅ — U21 and U22 are now unblocked

D2 (backend ABC) ✅ — U20 unblocked; a third backend overrides only NAME + command builders
 └──> U20 (Verilog support)

U5 (settings dialog) ✅ — U6 shipped; U10 / U18 / U19 remain unblocked
 ├──> U6  (theme system) ✅     # also required D15 (below)
 ├──> U10 (waveform capture)
 ├──> U18 (recent files)
 └──> U19 (metrics checkbox)

D15 (color consolidation) ✅ — U6 (theme system) ✅ — both shipped
 └──> U6  (theme system) ✅

U6 (theme system) ✅ — U27 is now unblocked
 └──> U27 (user-defined JSON themes + example scheme pack)

D6a (screen-result enum) ✅ — D6b (ScreenController) ✅ — both shipped
```

All other items (U0, U1, U2, U3, U4, U7, U8, U9, U11-U17, U21-U25, D3-D5, D7-D16) are independently shippable.

---

## Suggested merge order

A practical sequencing if all items were in flight (impact-weighted, with foundations early enough to unblock later work). Sprint 1 is split into two sub-sprints to keep batch sizes manageable (~8-12 h each).

| Sprint | Theme | Items |
|---|---|---|
| **1a** | Quickest wins + foundations | ~~U0 Board filtering~~ ✅ · ~~U11 Reset key~~ ✅ · ~~U12 Board summary format~~ ✅ · ~~D1 Wrapper template merge~~ ✅ · ~~D9 Literal types~~ ✅ · ~~D10 .editorconfig + hook pins~~ ✅ · ~~D11 Mock-class docstrings~~ ✅ |
| **1b** | Small features + DRY foundations | ~~D4 Shared button helper~~ ✅ → ~~U13 Arrow/Page nav~~ ✅ → ~~U1 Help dialog~~ ✅ → ~~U2 Analysis spinner~~ ✅ · ~~D2 Backend base class~~ ✅ · ~~U26 Visual README~~ ✅ |
| **2** | Foundations that unblock later UX | ~~D6a Screen-result enum~~ ✅ · ~~D6b ScreenController~~ ✅ · ~~D15 Color consolidation~~ ✅ · ~~U5 Settings dialog + extended session~~ ✅ · ~~D8 mypy strict~~ ✅ |
| **3** | Visible polish | U3 Tooltips · U4 Contextual errors · ~~U6 Theme system~~ ✅ · U7 In-sim toolbar |
| **4** | Feature breadth | U8 Splash · U9 PWM brightness · U10 Waveform · U23 Dirty-flag redraw · U27 User JSON themes |
| **Long-horizon** | — | U20 Verilog support · U21 Board-native VHDL · U22 7-seg physical mux · U24 / U25 Performance deep-dive |

**Status (2026-07-06).** Sprints 1a, 1b, and **2 are fully shipped**; **Sprint 3 is underway** (milestone v0.12.0, issues #172/#173/#174/#175). **U6 ✅** (Theme system, #178) landed first — dark + high-contrast themes with live switching. Remaining: **U3** (Tooltips, #172) · **U4** (Contextual errors, #173) · **U7** (In-sim toolbar, #175). The phases otherwise remain correctly ordered.

---

## Icebox

**Parked / deferred-on-trigger items.** Each carries a **trigger** — the condition under which it should graduate into a tier above. Unlike the tiered backlog these are blocked or speculative, so they hold no sprint slot and don't appear in the dependency graph. *(Consolidated here 2026-06-27 from session memory, where neither contributors nor a future maintainer could see the item or watch its trigger.)*

**Embedded-core follow-up arc — complete 2026-07-02 (PRs #140–#154):** [`embedded_core_improvement_plan.md`](embedded_core_improvement_plan.md) — turned the 2026-07-02 review behind **P7**'s and **P8**'s notes below into ordered, executable phases; its status ledger has the per-phase PRs.

| ID | Item | Trigger to schedule | Effort | Notes |
|---|---|---|---|---|
| **P1** | NVC backend tuning — elaborate-once, run-many | Any push to raise NVC simulation throughput | M | `launch_simulation()` re-elaborates NVC (`-e`) on every run (see **D7**). Caching the elaborated design across runs of the same VHDL would cut per-run startup. NVC-only (GHDL has no separate elaborate step); benchmark before/after. |
| **P2** | Board-sync Phase 3 — merge-aware / curation sync | Upstream removes a board we ship (recon to date: 0 removed) | L | Retain upstream-removed boards, dual upstream/adopted timestamps, `--check`, `--with-dates`. The schema `source` block permits additive provenance fields. A *subset* (preserve hand-added `port_conventions` / `peripherals` on re-sync, ~10 lines) is already noted under **U21**. Maintainer tooling in `scripts/sync_*.py`, not the app. |
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

**Also parked (speculative, no trigger):** *LCD / OLED display support* — a stretch goal from the original `prompt_info` vision (alongside 7-seg, which shipped). No board JSON models a character LCD / OLED and no user has requested it; recorded for completeness only.

---

## Critical files modified across the roadmap

- `src/fpga_sim/__main__.py` — U2 ✅, U5 ✅ (window-size restore), U16, D6a ✅, D6b ✅ (now a thin driver), D9 ✅
- `src/fpga_sim/controller.py` — D6b ✅ (new: `ScreenController` + `SessionState`), U5 ✅ (save-on-pick/change/quit + speed plumbing), U7 (new sim intents), U18 (retry start-dir)
- `src/fpga_sim/sim_bridge.py` — U4, U5 ✅ (`speed_factor` → `FPGA_SIM_SPEED`), U10, U21, D1, D2 ✅, D5, D7, D9 ✅ (defines `Simulator`), D16 (wrap the run subprocess)
- `src/fpga_sim/board_loader.py` — U12, D11 ✅
- `src/fpga_sim/session_config.py` — U5 ✅ (merge-on-write; new `update_session` / `push_recent`), U18, D9 ✅, D14 ✅, D16 (sandbox toggle)
- `src/fpga_sim/ui/constants.py` — D15 ✅ (now base neutrals only), U17
- `src/fpga_sim/ui/theme.py` — D15 ✅ (new: `Theme` dataclass + `THEME`), U2 ✅ (`spinner_arc` / `spinner_track` roles), U5 ✅ (`THEME_NAMES` / `THEME_LABELS` + settings button styles), U6 ✅ (`dark` / `high-contrast` instances + `set_theme` / `current_theme_name`), U27 (dynamic registry + JSON loader)
- `src/fpga_sim/ui/components.py` — U3, U9, D3, D15
- `src/fpga_sim/ui/board_display.py` — U1 ✅, U3, U5 ✅ (gear trigger), U11, U16, D3, D4 ✅, D6a ✅ (`run()` returns `ScreenResult`), D9 ✅ (simulator round-trips through `FPGABoard`), D15
- `src/fpga_sim/ui/board_selector.py` — U0, U1 ✅, U8, U12, U13 ✅, D15
- `src/fpga_sim/ui/sim_panel.py` — U5 ✅ (`speed_factor` ctor param; public `SPEED_DEFAULT`), U14, U15, U19, D4 ✅, D15
- `src/fpga_sim/ui/vhdl_picker.py` — U1 ✅, U13 ✅, U18, D15
- `src/fpga_sim/ui/error_dialog.py` — U4, D4 ✅, D6a ✅ (`run()` returns `DialogResult`), D15
- New: `src/fpga_sim/ui/theme.py` (D15 ✅), `src/fpga_sim/ui/help_dialog.py` (U1 ✅), `src/fpga_sim/ui/spinner.py` (U2 ✅), `ui/settings_dialog.py` (U5 ✅), `ui/tooltip.py` (U3), `ui/widgets/button.py` (D4 ✅), `src/fpga_sim/ui/results.py` (D6a ✅), `src/fpga_sim/controller.py` (D6b ✅), `src/fpga_sim/sandbox.py` (D16), `scripts/capture_demo.py` / `scripts/capture_selector.py` / `scripts/capture_common.py` + `sim/capture_frames.py` (U26), `docs/assets/` (U26 — committed GIFs)
- `README.md` — U26 (hero GIF + screenshot embed)
- `sim/sim_wrapper_template.vhd` — D1 ✅ (absorbed 7seg template)
- `sim/sim_testbench.py` — U5 ✅ (speed restore + write-back), U7, U9, U14, U22, D15
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

1. **Tests** — `uv run pytest` (1216 tests across 35 files including UI scaling, board selector filtering, board loader, both backends, 7-seg, embedded-core generator + designs, help overlay, theme value-preservation, screen-result enums, ScreenController transitions, settings dialog + session persistence). All sprints must keep this green.
2. **Lint / type** — `uv run ruff check .` and `uv run mypy .` (`strict = true` since D8 ✅).
3. **Manual smoke** — `uv run fpga-sim` end-to-end on a known board (e.g. Arty A7-35) with `hdl/blinky.vhd`; for 7-seg work use `counter_7seg.vhd` on DE10-Lite.
4. **Benchmark regression** — `uv run fpga-sim --benchmark 10` before/after performance-touching merges (U9 / U23). Baseline: 37.7 fps, 0.0036x real-time on Arty A7-35 (from `memory/project_sim_performance.md`).
5. **Headless CI** — every PR runs the existing Linux + Windows x GHDL + NVC x Py 3.10-3.13 matrix.
6. **Visual checks** — for UI work, screenshot the affected screen on Linux and attach to the PR; no automated visual diff today.

---

## Delivery log

Completed-item detail and the cross-cutting carried-forward notes now live in **[roadmap_delivered.md](roadmap_delivered.md)**. Per-PR detail is also in `CHANGELOG.md` and the linked PRs; forward-relevant gotchas from completed work appear as **⚠ Carried-forward** notes on the open cards they affect (**U7**) and in the Tier-3 note on **U14**.
