# Contributing

Thank you for contributing to the FPGA Simulator.  This document covers
everything a developer needs beyond the user-facing [README](README.md).

---

## Development setup

```bash
# Clone with the board-definitions submodule
git clone --recurse-submodules https://github.com/Machai-Kydoimos/simulator.git
cd simulator

# Install runtime + dev dependencies (pytest, ruff, mypy, pre-commit)
uv sync --group dev

# Install the pre-commit hooks (runs ruff + mypy on every commit)
uv run pre-commit install
```

> The `uv sync` in the README installs runtime dependencies only.
> `uv sync --group dev` is required for the quality tooling.

---

## Running quality checks

All three must pass before a PR is merged.  The pre-commit hooks enforce
ruff and mypy automatically; run them manually at any time:

```bash
uv run ruff check .        # linter — must report 0 errors
uv run ruff format --check . # formatter check (ruff format . to auto-fix)
uv run mypy .              # type checker — must report 0 errors
uv run pytest              # test suite — must be 131/131 (no display needed)
```

Running all four at once:

```bash
uv run ruff check . && uv run mypy . && uv run pytest
```

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
- `sim_testbench.py` — `ANN201` (public return type) is relaxed;
  cocotb's `@cocotb.test()` decorator makes the return type implicit.
- `sim/test_blinky.py` — `ANN` is relaxed for the same reason.

### Mypy (type checker)

Configured in `pyproject.toml` under `[tool.mypy]`.  Current strictness:

```toml
disallow_untyped_defs    = true   # all functions must be annotated
disallow_incomplete_defs = true   # no partial annotations
warn_return_any          = true   # warn when returning Any from typed func
warn_unused_ignores      = true   # keep type: ignore comments tidy
ignore_missing_imports   = true   # third-party stubs not required
```

Test files (`tests.*`, `test_blinky`) are exempt from `disallow_untyped_defs`
via `[[tool.mypy.overrides]]` — consistent with the ruff exemptions above.

The `amaranth-boards/` submodule is excluded from both ruff and mypy; its
files are not part of this project's source.

---

## Type annotation conventions

### New code

All new functions and methods in source modules must be fully annotated.
The pre-commit hook enforces this via mypy.

### pygame and cocotb boundaries

pygame's type stubs are incomplete.  Where mypy cannot verify a type
across a pygame call, use `cast()` rather than `# type: ignore`:

```python
from typing import cast
surface = cast(pygame.Surface, board.screen.copy())
```

cocotb DUT signal attributes (`dut.clk`, `dut.sw`, `dut.btn`, `dut.led`)
are resolved dynamically at simulation time.  All DUT attribute accesses
carry `# type: ignore[attr-defined]` — this is correct, not a workaround:

```python
cocotb.start_soon(Clock(dut.clk, period, unit="ns").start())  # type: ignore[attr-defined]
```

Do not remove these ignores; they will cause mypy errors.

### Backend dispatch design debt (`sim_bridge.py`)

`_GHDLBackend` and `_NVCBackend` have intentionally different signatures
for `elaborate_cmd` and `run_cmd` (GHDL passes generics at run time; NVC
requires them at elaboration time).  The four call sites in
`launch_simulation()` carry `# type: ignore[call-arg,arg-type]` because
mypy cannot verify calls through a `type[_GHDLBackend] | type[_NVCBackend]`
union when the signatures differ.

The calling code uses explicit `if simulator == "nvc":` guards, so the
dispatch is correct at runtime.  A future refactor should introduce a
shared `Protocol` for the two backends; until then, leave these ignores
in place.

---

## Tests

See the **Running Tests** section in the README for platform-specific
setup.  A few things that matter for contributors:

- **No display needed.** All tests use `SDL_VIDEODRIVER=dummy` so they
  run headlessly in CI and on servers.
- **`sim/test_blinky.py`** contains headless cocotb tests for the blinky
  design.  These run via pytest through a cocotb–pytest integration and
  require GHDL or NVC to be installed.
- **`tests/` has an `__init__.py`**; `sim/` does not.  This matters if
  you add a mypy override — use `"tests.*"` for `tests/` and the bare
  module name `"test_blinky"` for `sim/test_blinky.py`.
- The test suite must stay at **131/131 passed** before merge.

---

## Architecture overview

The README's **How It Works** section covers the architecture in depth.
A few additional notes for contributors:

**Two pygame processes.**  The launcher (board selector → VHDL picker)
calls `pygame.quit()` before spawning the simulator subprocess.
`sim_testbench.py` calls `pygame.init()` fresh inside that subprocess.
Never assume pygame state persists across the boundary.

**`board_loader.py` mock namespace.**  Board definition files are
executed via `exec()` in a mock namespace that provides lightweight
stand-ins for `Resource`, `Pins`, `Attrs`, etc.  The mock classes are
typed with `object` at variadic boundaries (`*ios: object`, `**kwargs: object`)
because the amaranth API accepts heterogeneous arguments.  Use `cast()`
if you need a narrower type after extracting a value from a mock object.

**Session state** is stored in `~/.fpga_simulator/session.json` and
loaded at startup.  It is intentionally best-effort — load and save
failures are silently ignored so a corrupt or missing file never breaks
the app.
