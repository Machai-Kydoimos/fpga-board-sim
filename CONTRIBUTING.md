# Contributing

Thank you for contributing to the FPGA Simulator.  This document covers
everything a developer needs beyond the user-facing [README](README.md).

---

## Development setup

```bash
# Clone with the board-definitions submodule
git clone --recurse-submodules https://github.com/Machai-Kydoimos/fpga-board-sim.git
cd fpga-board-sim

# Install runtime + dev dependencies (pytest, ruff, mypy, pre-commit)
uv sync --group dev

# Install the pre-commit hooks (runs ruff + mypy on every commit)
uv run pre-commit install
```

> The `uv sync` in the README installs runtime dependencies only.
> `uv sync --group dev` is required for the quality tooling.

### Windows notes for contributors

Two supported environments — pick one and use it consistently:

#### Path 1: Native Windows (PowerShell + winget) — recommended for most contributors

- Use **PowerShell 7+** (not Command Prompt; PS 5.1 lacks `&&`).
  Install from [aka.ms/powershell](https://aka.ms/powershell) if needed.
- Install uv with `winget install --id=astral-sh.uv -e` if you haven't already.
- GHDL must be on your `PATH` before running the test suite — see the
  [Troubleshooting section in README.md](README.md#windows-ghdl-not-on-path-after-winget-install).
- NVC is available via `winget install NickGasson.NVC`, but its cocotb VHPI
  integration has **not been verified** on Windows. If NVC is installed,
  NVC-related tests may run instead of skipping — confirm they pass or note
  the gap in your PR. If NVC is absent, those tests skip automatically
  (`SKIPPED (NVC is not installed)`) which is expected and does not block a merge.
- `src/fpga_sim/sim_bridge.py` owns all Windows-specific environment setup (PATH, PYTHONHOME, DLL
  discovery). If you add simulator support or change how the subprocess env is built,
  test it on Windows or note the gap in your PR.

#### Path 2: MSYS2 (UCRT64 shell) — best for NVC or a Linux-like dev experience

MSYS2 gives an environment nearly identical to Linux. Follow the
[Windows: MSYS2 alternative](README.md#windows-msys2-alternative) section in the
README to install MSYS2, GHDL, NVC, uv, and Python inside the UCRT64 shell.

Once set up, all contributor commands below work unchanged (run them in the UCRT64
shell, not PowerShell). `&&` chaining works natively in bash.

> Tools installed in MSYS2 are not visible to PowerShell and vice versa — choose
> one environment for your dev work and don't mix them.

---

## Running quality checks

All three must pass before a PR is merged.  The pre-commit hooks enforce
ruff and mypy automatically; run them manually at any time:

```bash
uv run ruff check .        # linter — must report 0 errors
uv run ruff format --check . # formatter check (ruff format . to auto-fix)
uv run mypy .              # type checker — must report 0 errors
uv run pytest              # test suite — must be 226/226 fast tests (no display needed)
```

Running all four at once:

```bash
uv run ruff check . && uv run mypy . && uv run pytest
```

> **Windows / PowerShell 5.1:** `&&` is not supported — upgrade to
> [PowerShell 7+](https://aka.ms/powershell) or run each command separately.
> In MSYS2's bash shell, `&&` works natively.

---

## Code quality standards

### Ruff (linter + formatter)

Configured in `pyproject.toml` under `[tool.ruff]`.  Enabled rule sets:

| Set | Rules | Purpose |
|-----|-------|---------|
| `E`, `W` | pycodestyle | Style and whitespace |
| `F` | pyflakes | Undefined names, unused imports |
| `I` | isort | Import ordering |
| `UP` | pyupgrade | Modern Python syntax |
| `N` | pep8-naming | Naming conventions |
| `B` | flake8-bugbear | Common bugs and design issues |
| `ANN` | annotations | Missing type annotations |
| `D` | pydocstyle | Docstring conventions |

**Exemptions** (see `[tool.ruff.lint.per-file-ignores]`):

- `tests/*` — `ANN` and `D` are relaxed; pytest fixtures and test
  functions do not require annotations or docstrings.
- `sim/sim_testbench.py` — `ANN201` (public return type) is relaxed;
  cocotb's `@cocotb.test()` decorator makes the return type implicit.
- `sim/test_blinky.py`, `sim/test_7seg.py` — `ANN` is relaxed for the same reason.

### Mypy (type checker)

Configured in `pyproject.toml` under `[tool.mypy]`.  Current strictness:

```toml
disallow_untyped_defs    = true   # all functions must be annotated
disallow_incomplete_defs = true   # no partial annotations
warn_return_any          = true   # warn when returning Any from typed func
warn_unused_ignores      = true   # keep type: ignore comments tidy
ignore_missing_imports   = true   # third-party stubs not required
```

Test files (`tests.*`, `test_blinky`, `test_7seg`) are exempt from `disallow_untyped_defs`
via `[[tool.mypy.overrides]]` — consistent with the ruff exemptions above.

The `amaranth-boards/` submodule is excluded from both ruff and mypy; its
files are not part of this project's source.

---

## Type annotation conventions

### Annotating new code

All new functions and methods in source modules must be fully annotated.
The pre-commit hook enforces this via mypy.

### pygame and cocotb boundaries

pygame's type stubs are incomplete.  Where mypy cannot verify a type
across a pygame call, use `cast()` rather than `# type: ignore`:

```python
from typing import cast
surface = cast(pygame.Surface, board.screen.copy())
```

cocotb DUT signal attributes (`dut.sw`, `dut.btn`, `dut.led`, `dut.clk_half_ns`)
are resolved dynamically at simulation time.  All DUT attribute accesses
carry `# type: ignore[attr-defined]` — this is correct, not a workaround:

```python
dut.clk_half_ns.value = new_half  # type: ignore[attr-defined]
led_val = int(dut.led.value)       # type: ignore[attr-defined]
```

Do not remove these ignores; they will cause mypy errors.

### Backend dispatch design debt (`sim_bridge.py`)

`_GHDLBackend` and `_NVCBackend` share a unified `elaborate_cmd(toplevel,
generics, work_dir)` signature — GHDL simply ignores the generics dict
(it applies them at run time via `-r`; NVC bakes them in at `-e` time).
`run_cmd` still differs between backends (GHDL takes no generics; NVC
requires them).  The two `run_cmd` call sites in `launch_simulation()`
carry `# type: ignore[call-arg,arg-type]` because mypy cannot verify calls
through a `type[_GHDLBackend] | type[_NVCBackend]` union when the signatures
differ.

The calling code uses explicit `if simulator == "nvc":` guards, so the
dispatch is correct at runtime.  A future refactor should introduce a
shared `Protocol` for the two backends; until then, leave these ignores
in place.

---

## Test suite notes

See the **Running Tests** section in the README for platform-specific
setup.  A few things that matter for contributors:

- **No display needed.** All tests use `SDL_VIDEODRIVER=dummy` so they
  run headlessly in CI and on servers.
- **`sim/test_blinky.py`** contains headless cocotb tests for the blinky
  design.  **`sim/test_7seg.py`** contains the equivalent tests for the
  `counter_7seg` design.  Both run via pytest through a cocotb–pytest
  integration and require GHDL or NVC to be installed.
- **`tests/` has an `__init__.py`**; `sim/` does not.  This matters if
  you add a mypy override — use `"tests.*"` for `tests/` and the bare
  module name (e.g. `"test_blinky"`) for `sim/` files.
- The fast test suite (`-m "not slow"`) must stay at **219/219 passed**
  before merge.

---

## CI pipeline

Every push and pull request runs the following jobs:

| Job | Runner | Simulators installed | Pytest filter |
|-----|--------|----------------------|---------------|
| Lint & type-check | ubuntu-latest | none | n/a |
| Test (matrix) | ubuntu + windows × py3.10 + py3.12 | none | `-m "not slow"` |
| Test Linux + GHDL | ubuntu-latest | `apt install ghdl` | full suite |
| Test Linux + NVC | ubuntu-latest | `nickg/setup-nvc` action | full suite |
| Test Windows + GHDL | windows-latest | GHDL zip from GitHub Releases | full suite |

### The `slow` marker

Tests in `test_ghdl.py`, `test_nvc.py`, `test_simulation.py`, and
`test_vhdl_validation.py` are marked `@pytest.mark.slow` — they invoke a
real simulator subprocess.  The pure-Python matrix jobs skip them with
`-m "not slow"`.

The `ghdl` and `nvc` fixtures both call `pytest.skip()` when the
respective binary is absent, so running the full suite locally without one
or both simulators is safe — those tests are skipped, not failed.

### Required checks (branch protection)

A PR cannot be merged until these five checks all pass:

- `Lint & type-check`
- `Test (ubuntu-latest, Python 3.10)`
- `Test (ubuntu-latest, Python 3.12)`
- `Test (windows-latest, Python 3.10)`
- `Test (windows-latest, Python 3.12)`

The simulator-specific jobs are not required checks — they surface
regressions but do not block merge on their own.  If you introduce a
change that touches `sim_bridge.py` or the simulator backends, confirm
those jobs are green before merging.

---

## Releasing

### Version scheme

This project follows [Semantic Versioning](https://semver.org):

| Bump | When |
|------|------|
| `PATCH` (0.x.**y**) | Bug fixes, security patches, documentation-only changes |
| `MINOR` (0.**x**.0) | New features or meaningful refactors; backward-compatible |
| `MAJOR` (**x**.0.0) | Breaking changes to the public interface or VHDL design contract |

### Release checklist

1. **Create a release branch** from `main`:
   ```bash
   git checkout main && git pull
   git checkout -b release/vX.Y.Z
   ```

2. **Update `CHANGELOG.md`** — move items from `[Unreleased]` into a new
   `[X.Y.Z] - YYYY-MM-DD` section and update the comparison links at the
   bottom of the file.

3. **Bump the version** in `pyproject.toml`:
   ```toml
   version = "X.Y.Z"
   ```

4. **Commit, push, and open a PR** targeting `main`:
   ```bash
   git add CHANGELOG.md pyproject.toml
   git commit -m "chore: bump version to X.Y.Z and update CHANGELOG"
   git push -u origin release/vX.Y.Z
   gh pr create --title "chore: release vX.Y.Z"
   ```

5. **After the PR is merged**, tag the merge commit and push the tag:
   ```bash
   git checkout main && git pull
   git tag -a vX.Y.Z -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

6. **Create a GitHub Release** from the tag.  Use the `[X.Y.Z]` section of
   `CHANGELOG.md` as the release body.

---

## Architecture overview

The README's **How It Works** section covers the architecture in depth.
A few additional notes for contributors:

**Two pygame processes.**  The launcher (board selector → VHDL picker)
calls `pygame.quit()` before spawning the simulator subprocess.
`sim/sim_testbench.py` calls `pygame.init()` fresh inside that subprocess.
Never assume pygame state persists across the boundary.

**VHDL-side clock.**  The clock is driven by the generated `sim_wrapper`
entity (see `sim/sim_wrapper_template.vhd` for standard boards and
`sim/sim_wrapper_7seg_template.vhd` for 7-seg boards), not by a Python
coroutine.  This eliminates per-half-period GPI callbacks — only two GPI
calls happen per frame (the Timer endpoints).  The wrapper exposes
`clk_half_ns`; the testbench writes to it when the panel's **[-]/[+]**
buttons change the virtual clock frequency.

**SimPanel.**  `src/fpga_sim/ui/sim_panel.py` owns the stats strip drawn at the bottom
of the simulation window.  Its `panel_height` is a property that re-evaluates
`_ui_scale(w, h)` on every access — call `board.set_height_offset(panel.panel_height)`
whenever the window resizes to keep the board and panel areas in sync.
`sim_testbench.py` does this check at the top of every frame.

**`fpga_sim/board_loader.py` mock namespace.**  Board definition files are
executed via `exec()` in a mock namespace that provides lightweight
stand-ins for `Resource`, `Pins`, `Attrs`, etc.  The mock classes are
typed with `object` at variadic boundaries (`*ios: object`, `**kwargs: object`)
because the amaranth API accepts heterogeneous arguments.  Use `cast()`
if you need a narrower type after extracting a value from a mock object.

**Session state** is stored in `~/.fpga_simulator/session.json` and
loaded at startup.  It is intentionally best-effort — load and save
failures are silently ignored so a corrupt or missing file never breaks
the app.  After each simulation run, a separate per-session performance
summary is appended to `~/.fpga_simulator/sessions/` by `fpga_sim/sim_session_log.py`.
