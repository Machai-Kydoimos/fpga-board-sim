# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/releases/tag/v0.1.0
