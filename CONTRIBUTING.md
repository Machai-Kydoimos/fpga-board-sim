# Contributing

Thank you for contributing to the FPGA Simulator. This document covers
everything a developer needs beyond the user-facing [README](README.md).

---

## Finding something to work on

The backlog uses a lightweight **hybrid** model — a strategy document plus
GitHub issues for the sprint in progress:

1. **Start at the open milestone.** Browse the
   [open issues](https://github.com/Machai-Kydoimos/fpga-board-sim/issues) in the
   current `vX.Y.0`
   [milestone](https://github.com/Machai-Kydoimos/fpga-board-sim/milestones), or
   filter by the
   `good first issue` / `help wanted` / `enhancement` labels. These are the tasks
   queued for the active sprint — pick one that isn't blocked by another.
2. **Read the matching roadmap card for context.** Each issue title carries a
   roadmap ID (e.g. `U5`, `D6b`). Open
   [`docs/improvement_roadmap.md`](docs/improvement_roadmap.md) and find that card
   for the rationale, the files it touches, the effort estimate, the *done-when*
   acceptance criterion, and any ⚠ carried-forward gotchas.
3. **Nothing queued in the milestone?** The roadmap is the source of truth for
   what comes next: read its **Suggested merge order** and **dependency graph**,
   pick the next unblocked item, and open an issue for it (titled by its roadmap
   ID). Completed work is summarized in
   [`docs/roadmap_delivered.md`](docs/roadmap_delivered.md).

The roadmap's **Icebox** holds parked, deferred-on-trigger items — don't start
one unless its listed trigger condition has been met. Found something that isn't
on the roadmap (a bug, a rough edge)? Open an issue, or for a trivial fix go
straight to a PR.

---

## Development setup

```bash
# Clone the repository
git clone https://github.com/Machai-Kydoimos/fpga-board-sim.git
cd fpga-board-sim

# Install runtime + dev dependencies (pytest, ruff, mypy, pre-commit)
uv sync --group dev

# Install the pre-commit hooks (runs ruff, mypy, and rumdl on every commit)
uv run pre-commit install
```

> `uv` includes the `dev` dependency group by default, so plain `uv sync` (as in the
> README) already installs the quality tooling (pytest, ruff, mypy, pre-commit); the
> explicit `--group dev` above is equivalent.

### Windows notes for contributors

Two supported environments — pick one and use it consistently:

#### Path 1: Native Windows (PowerShell + winget) — recommended for most contributors

- Use **PowerShell 7+** (not Command Prompt; PS 5.1 lacks `&&`).
  Install from [aka.ms/powershell](https://aka.ms/powershell) if needed.
- Install uv with `winget install --id=astral-sh.uv -e` if you haven't already.
- GHDL must be on your `PATH` before running the test suite — see the
  [Troubleshooting section in docs/install.md](docs/install.md#windows-ghdl-not-on-path-after-winget-install).
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
[Windows: MSYS2 alternative](docs/install.md#windows-msys2-alternative) section in
docs/install.md to install MSYS2, GHDL, NVC, uv, and Python inside the UCRT64 shell.

Once set up, all contributor commands below work unchanged (run them in the UCRT64
shell, not PowerShell). `&&` chaining works natively in bash.

> Tools installed in MSYS2 are not visible to PowerShell and vice versa — choose
> one environment for your dev work and don't mix them.

---

## Running quality checks

All of these must pass before a PR is merged. The pre-commit hooks enforce
ruff, mypy, and rumdl automatically; run them manually at any time:

```bash
uv run ruff check .        # linter — must report 0 errors
uv run ruff format --check . # formatter check (ruff format . to auto-fix)
uv run mypy .              # type checker — must report 0 errors
uv run rumdl check .       # Markdown linter (rumdl check --fix to auto-fix)
uv run pytest              # test suite — all fast tests must pass (no display needed)
```

Running them all at once:

```bash
uv run ruff check . && uv run mypy . && uv run rumdl check . && uv run pytest
```

> **Windows / PowerShell 5.1:** `&&` is not supported — upgrade to
> [PowerShell 7+](https://aka.ms/powershell) or run each command separately.
> In MSYS2's bash shell, `&&` works natively.

---

## Code quality standards

### Ruff (linter + formatter)

Configured in `pyproject.toml` under `[tool.ruff]`. Enabled rule sets:

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

Configured in `pyproject.toml` under `[tool.mypy]`. Current strictness:

```toml
disallow_untyped_defs    = true   # all functions must be annotated
disallow_incomplete_defs = true   # no partial annotations
check_untyped_defs       = true   # type-check bodies of untyped (e.g. test) funcs too
warn_return_any          = true   # warn when returning Any from typed func
warn_unused_ignores      = true   # keep type: ignore comments tidy
ignore_missing_imports   = true   # third-party stubs not required
```

Test files (`tests.*`, `test_blinky`, `test_7seg`) are exempt from
`disallow_untyped_defs` via `[[tool.mypy.overrides]]` — their functions need not
be annotated. But `check_untyped_defs = true` (the first slice of roadmap D8)
still type-checks the *bodies* of those untyped functions, so test code is not a
type-checking blind spot. Consistent with the ruff exemptions above.

The `boards/` directory (JSON board definitions) is excluded from both ruff
and mypy; its files are data, not source code.

### rumdl (Markdown linter)

[rumdl](https://github.com/rvben/rumdl) lints and formats the repo's Markdown,
configured in `pyproject.toml` under `[tool.rumdl]`. It respects `.gitignore`,
so untracked files (e.g. `memory/`) are skipped automatically.

Two rules are disabled project-wide:

- **MD013** (line length) — prose, tables, and long links read fine unwrapped,
  and hard-wrapping Markdown hurts diffs without improving rendering.
- **MD036** (emphasis-as-heading) — its autofix rewrites bold/italic lead-ins
  and bylines into real headings, changing document structure and the TOC.

`rumdl check --fix` (or `rumdl fmt`) auto-corrects the remaining issues — mostly
blank lines around code fences and lists, fenced-block languages, and stray
whitespace.

### Pre-commit hooks track `uv.lock`

All four hooks — `ruff`, `ruff-format`, `mypy`, and `rumdl` — are local hooks
that run `uv run <tool>`, so they use the exact versions pinned in `uv.lock`
(the same ones CI and the manual commands above use). One source of truth for
tool versions; the hooks can never silently drift from CI.

This is deliberate and diverges from Astral's recommended
`astral-sh/ruff-pre-commit` mirror, which pins ruff by a separate hook `rev:`
that Dependabot doesn't track. **Please don't convert the ruff hook back to the
mirror** — it reintroduces a second, drift-prone version pin. Full rationale is
in the comment block atop `.pre-commit-config.yaml`.

### Spelling and text encoding

Two conventions the linters don't catch:

- **US spelling** in code, comments, docs, and commit messages — `color`,
  `behavior`, `standardize` (not `colour`, `behaviour`, `standardise`).
- **VHDL files must be plain ASCII, or UTF-8 without a BOM**, and free of
  decorative Unicode. Some simulator/toolchain front-ends choke on a byte-order
  mark or stray non-ASCII bytes in HDL source, so the launcher's
  `check_vhdl_encoding()` rejects a BOM or any byte > 127 (reporting the
  offending line) before analysis.

---

## Type annotation conventions

### Annotating new code

All new functions and methods in source modules must be fully annotated.
The pre-commit hook enforces this via mypy.

### pygame and cocotb boundaries

pygame's type stubs are incomplete. Where mypy cannot verify a type
across a pygame call, use `cast()` rather than `# type: ignore`:

```python
from typing import cast
surface = cast(pygame.Surface, board.screen.copy())
```

cocotb DUT signal attributes (`dut.sw`, `dut.btn`, `dut.led`, `dut.clk_half_ns`)
are resolved dynamically at simulation time. All DUT attribute accesses
carry `# type: ignore[attr-defined]` — this is correct, not a workaround:

```python
dut.clk_half_ns.value = new_half  # type: ignore[attr-defined]
led_val = int(dut.led.value)       # type: ignore[attr-defined]
```

Do not remove these ignores; they will cause mypy errors.

### Backend dispatch design (`sim_bridge.py`)

`_GHDLBackend` and `_NVCBackend` subclass the `_SimBackend` ABC. The four
discovery helpers (`find`, `available`, `lib_dir`, `sim_bin_lib`) live once on the
ABC as classmethods keyed on each backend's `NAME`; the subclasses override only
`NAME` plus the per-simulator command builders, whose `elaborate_cmd` and `run_cmd`
signatures are fully unified:

- `elaborate_cmd(toplevel, generics, work_dir)` — GHDL ignores generics (applies at
  run time via `-r`); NVC bakes them into the elaboration artifact.
- `run_cmd(toplevel, generics, plugin_lib, work_dir)` — GHDL injects `-gKEY=VALUE`
  flags; NVC ignores generics (already applied during elaboration).

`_backend()` returns `type[_SimBackend]`. Because every backend shares the ABC's
method signatures, mypy resolves all call sites in `launch_simulation()` without
any `# type: ignore` suppressions.

**Why GHDL uses VPI and NVC uses VHPI.** cocotb talks to each simulator through a
different interface because of what each implements: GHDL ships a *complete* VPI
(its VHPI is only partial), so cocotb is loaded with `--vpi=…ghdl.so` on
`ghdl -r`; NVC ships a comprehensive VHPI and no VPI at all, so cocotb is loaded
with `--load=…nvc.so`. This is also why generics apply at different stages — GHDL
takes `-gKEY=VALUE` at run time, while NVC bakes them into the elaboration
artifact (the `elaborate_cmd` / `run_cmd` split above).

---

## Test suite notes

See the **Running Tests** section in the README for platform-specific
setup. A few things that matter for contributors:

- **No display needed.** All tests use `SDL_VIDEODRIVER=dummy` so they
  run headlessly in CI and on servers.
- **Randomized order (`pytest-randomly`).** Tests run in a random order
  each session — the seed is printed as `Using --randomly-seed=N` — which
  guards against hidden inter-test coupling (global state leaking across
  modules). To reproduce a failure, re-run with that exact seed:
  `uv run pytest -p randomly --randomly-seed=N`; to force the old
  deterministic collection order, use `uv run pytest -p no:randomly`. A
  test that only fails under some seeds is a real ordering bug — fix the
  shared state, don't pin the seed. (Concretely: never give a test module
  its own pygame `init`/`quit` fixture — use the shared session
  `headless_pygame` in `tests/conftest.py`. A mid-session `pygame.quit()`
  invalidates the cached fonts other modules render with.)
- **Session-file isolation.** `save_session()` / `update_session()` /
  `push_recent()` write the real `~/.fpga_simulator/session.json`. Any test
  that constructs a `ScreenController` or `SettingsDialog` — or otherwise
  triggers a session write — must redirect the target first, or the test run
  clobbers the developer's own saved session:

  ```python
  monkeypatch.setattr("fpga_sim.session_config.SESSION_FILE", tmp_path / "session.json")
  ```

  `tests/test_controller.py` and `tests/test_settings_dialog.py` do this with
  an autouse fixture; follow that pattern in new test modules.
- **`sim/test_blinky.py`** contains headless cocotb tests for the blinky
  design. **`sim/test_7seg.py`** contains the equivalent tests for the
  `counter_7seg` design. Both run via pytest through a cocotb–pytest
  integration and require GHDL or NVC to be installed.
- **`tests/` has an `__init__.py`**; `sim/` does not. This matters if
  you add a mypy override — use `"tests.*"` for `tests/` and the bare
  module name (e.g. `"test_blinky"`) for `sim/` files.
- The fast test suite (`-m "not slow"`) must pass with zero failures
  before merge.

---

## Smoke-testing a board

To confirm a board JSON + VHDL design compiles, elaborates, and runs end-to-end
(wrapper generation → simulator analysis → elaboration → cocotb readback) without
opening the GUI, use the built-in **headless benchmark**:

```bash
# LED-only board:
uv run fpga-sim --benchmark 5 --board ArtyA7_35Platform --vhdl hdl/blinky.vhd

# 7-segment board:
uv run fpga-sim --benchmark 5 --board DE10LitePlatform --vhdl hdl/counter_7seg.vhd
```

It runs the real pipeline headlessly (`SDL_VIDEODRIVER=dummy`) for the given
number of seconds and prints a board / VHDL / simulator summary and a performance
report; a clean exit with `PASS=1 FAIL=0` means the combination builds and runs.
`--board` takes a board **class name** (e.g. `ArtyA7_35Platform`; omit it to use
the first discovered board), `--vhdl` defaults to `hdl/blinky.vhd`, and
`--sim ghdl|nvc` picks the backend.

For a *visual* check (rendered LED / 7-seg frames saved as PNGs), see
`scripts/capture_demo.py`, which drives the same headless pipeline.

---

## Regenerating the documentation assets

The README and embedded-core guide embed GIFs/PNGs captured live from the
running simulator (headless, `SDL_VIDEODRIVER=dummy`) — none are hand-drawn or
post-processed. To regenerate them:

```bash
# Board selector filtering GIF
uv run python scripts/capture_selector.py

# README hero GIF (interactive snake_7seg storyboard)
uv run python scripts/capture_demo.py

# Embedded-CPU walking-counter GIFs need a temporary faster-stepping variant
# build first (--prescaler-bits 14), so the CPU free-runs while the display
# steps at a viewable rate (see the guide's "Timing & throughput" section):
uv run python scripts/gen_embedded_core.py --system systems/mx65_walking_counter_7seg.toml \
    --prescaler-bits 14 --out /tmp/variant.vhd

uv run python scripts/capture_demo.py --scenario plain --sim nvc --vhdl /tmp/variant.vhd \
    --vhdl-label hdl/mx65_walking_counter_7seg.vhd --step-ns 336000 --frames 144 \
    --board step_mxo2 --out docs/assets/mx65_walking_counter_2digit.gif
# ...repeat with --board de0 / de10_lite for the 4-digit / 6-digit GIFs

uv run python scripts/capture_demo.py --scenario cpu_walk --sim nvc --vhdl /tmp/variant.vhd \
    --vhdl-label hdl/mx65_walking_counter_7seg.vhd --prescaler-bits 14 --step-ns 336000 \
    --board de10_lite --out docs/assets/mx65_walking_counter_demo.gif

# Dice-roller GIF and hello-design PNG use the committed designs directly --
# ticks only gate button sampling, so no variant build is needed:
uv run python scripts/capture_demo.py --scenario dice --sim nvc \
    --vhdl hdl/mx65_dice_7seg.vhd --step-ns 336000 --board de10_lite \
    --out docs/assets/mx65_dice_7seg.gif

uv run python scripts/capture_demo.py --scenario plain --sim nvc \
    --vhdl hdl/mx65_hello_7seg.vhd --step-ns 336000 --frames 12 --png \
    --board de10_lite --out docs/assets/mx65_hello_7seg.png
```

**Visually review every regenerated GIF/PNG before committing** (loop-seam
continuity, readable step rate, strip/caption text): these are captured live,
so a logic change anywhere in the pipeline can subtly change what they show.

---

## CI pipeline

Every push and pull request runs the following jobs:

| Job | Runner | Simulators installed | Pytest filter |
|-----|--------|----------------------|---------------|
| Lint & type-check | ubuntu-latest | none | n/a |
| Test (matrix) | ubuntu + windows × py3.10 + py3.12 + py3.13 | none | `-m "not slow"` |
| Test Linux + GHDL | ubuntu-24.04 | GHDL tarball from GitHub Releases (pinned v6.0.0) | full suite |
| Test Linux + NVC | ubuntu-latest | `nickg/setup-nvc` action | full suite |
| Test Windows + GHDL | windows-latest | GHDL zip from GitHub Releases | full suite |

### The `slow` marker

Tests in `test_ghdl.py`, `test_nvc.py`, `test_simulation.py`, and
`test_vhdl_validation.py` are marked `@pytest.mark.slow` — they invoke a
real simulator subprocess. The pure-Python matrix jobs skip them with
`-m "not slow"`.

The `ghdl` and `nvc` fixtures both call `pytest.skip()` when the
respective binary is absent, so running the full suite locally without one
or both simulators is safe — those tests are skipped, not failed.

### Required checks (branch protection)

A PR cannot be merged until these seven checks all pass:

- `Lint & type-check`
- `Test (ubuntu-latest, Python 3.10)`
- `Test (ubuntu-latest, Python 3.12)`
- `Test (ubuntu-latest, Python 3.13)`
- `Test (windows-latest, Python 3.10)`
- `Test (windows-latest, Python 3.12)`
- `Test (windows-latest, Python 3.13)`

The simulator-specific jobs (Linux + GHDL, Linux + NVC, Windows + GHDL) are not
required checks — they surface regressions but do not block merge on their own.
If you introduce a change that touches `sim_bridge.py` or the simulator
backends, confirm those jobs are green before merging.

### Gotchas

- **`mypy` is whole-repo.** The `Lint & type-check` job runs `mypy .` across
  `src/`, `tests/`, `sim/`, and `scripts/` — not just `src/`. A type change has
  to keep the tests and scripts clean too.
- **Don't `paths-ignore` the required jobs.** The workflows aren't path-filtered,
  so even a docs-only PR runs and *satisfies* the required checks. If you skip
  them with `paths-ignore`, the required check never reports and the PR can't
  merge without an admin override — leave them running (they're fast on no-op
  diffs).
- **Branch protection requires an up-to-date branch.** If `main` advanced after
  you opened the PR, update the branch or GitHub blocks the merge.
- **CodeQL is GitHub default-setup** (no workflow file in the repo); a neutral or
  "skipping" CodeQL result on a docs/no-op PR is expected, not a failure.
- **Dependabot.** A *rebase* of a Dependabot PR doesn't re-trigger CI — close and
  reopen to force a fresh run — and Dependabot won't propose a *downgrade*, so a
  bad pin must be fixed by hand.

---

## Releasing

### Version scheme

This project follows [Semantic Versioning](https://semver.org):

| Bump | When |
|------|------|
| `PATCH` (0.x.**y**) | Bug fixes, security patches, documentation-only changes |
| `MINOR` (0.**x**.0) | New features or meaningful refactors; backward-compatible |
| `MAJOR` (**x**.0.0) | Breaking changes to the public interface or VHDL design contract |

### When to cut a release

- **MINOR (`0.x.0`)** — at the end of each roadmap sub-sprint, *or* when
  `[Unreleased]` has accumulated ~3–5 user-visible changes, whichever comes
  first. Always cut at a green-suite, no-open-PR boundary.
- **PATCH (`0.x.y`)** — promptly for any shipped bug or security fix a user
  would hit; don't wait for the next minor.
- **Avoid "release gravity."** Don't let `[Unreleased]` grow past roughly one
  sprint of work — small, frequent releases keep the changelog reviewable and
  the tag history meaningful.
- **Changelog entries land with the PR, not at release time.** A PR that
  changes anything user-visible (feature, fix, behavior change) adds its own
  `[Unreleased]` entry in that same PR; multi-PR arcs add entries per PR or as
  an explicit arc-close step. Docs-only changes, dependency bumps, and
  internal churn superseded before it ever ships need no entry. This keeps
  the "~3–5 user-visible changes" trigger above readable at a glance and
  makes release-checklist step 2 a pure move instead of after-the-fact
  authorship.

### Release checklist

**Pre-flight** — before cutting the branch, confirm the generated artifacts and
board data are in sync with their sources. Both commands only report drift; neither
writes:

```bash
uv run python scripts/sync_port_conventions.py --check  # port_conventions vs registry
uv run python scripts/regen_embedded_cores.py           # embedded-core files vs specs (check only)
```

Investigate and resolve any reported drift before proceeding.

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

6. **Create a GitHub Release** from the tag. Use the `[X.Y.Z]` section of
   `CHANGELOG.md` as the release body.

---

## Architecture overview

The architecture reference now lives in
[docs/architecture.md](docs/architecture.md) — the two-phase process model, project
layout, board loading, the pygame UI, the simulation pipeline, the simulator
backends, and how board-native VHDL is matched and adapted. It also carries the
contributor notes that used to sit here: `SimExit` sim → launcher signalling,
`SimPanel` scaling, hover overlays, the sync-script parsers, and session-state
ownership.
