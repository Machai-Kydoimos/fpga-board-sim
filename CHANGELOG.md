# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
  the catalogue is now 275 definitions (272 loadable) across four sources
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

[Unreleased]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/releases/tag/v0.1.0
