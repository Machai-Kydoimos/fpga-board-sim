# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/releases/tag/v0.1.0
