# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
