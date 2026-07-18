# U35 — Simulator picker (first-class backend variants): implementation plan

**For the implementing session (Opus): this document is self-contained.**
Read it top to bottom before writing code. Every design decision has already
been made with Rick (2026-07-18) and validated by hands-on experiments on his
machine — do not relitigate them. If the code has drifted from what this plan
asserts, re-grep and adapt the mechanics, not the decisions.

- **Card:** U35 in `docs/improvement_roadmap.md` (Tier 2).
- **Why & evidence:** the GHDL backend A/B (2026-07-17/18, PRs #262/#263/#264)
  proved three GHDL backends + NVC all work with the app and differ enough to
  matter. Honest rates (10 s `--benchmark --no-ui`, Ryzen AI 9 HX 370):

  | design | GHDL mcode | GHDL llvm-jit | GHDL llvm (AOT) | NVC |
  |---|---|---|---|---|
  | blinky / Arty A7-35 | 0.00427x | 0.00522x | 0.0120x | 0.0266x |
  | counter_7seg / DE10-Lite | 0.00687x | 0.00845x | 0.0181x | 0.0498x |
  | mx65 CPU / DE10-Lite | 0.00134x | 0.00170x | 0.00225x | 0.00487x |

- **Goal:** every installed simulator appears as a truthfully-labeled,
  selectable, persistable choice — discovered automatically or registered
  manually — honored end-to-end (launch, benchmark, session log), with
  compiled-backend validation parity and a CI job for the LLVM backend.

## 0. Ground rules (repo conventions — non-negotiable)

1. One feature branch per PR, branched off **freshly-pulled main**
   (`git fetch && git checkout -b <branch> origin/main`). Never commit to main.
2. Before every commit: `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy .` (CI runs mypy over the WHOLE repo, tests included).
   Pre-commit hooks (ruff/mypy/rumdl) may auto-fix files and abort the commit —
   `git add` the fixes and commit again.
3. Markdown: rumdl enforces fenced-code languages (MD040) and resolvable
   relative links (MD057). US spelling everywhere, including UI label strings.
4. Use `gh` for all GitHub operations. PR bodies end with the standard Claude
   Code attribution footer; commits end with the Co-Authored-By trailer.
5. Each user-visible PR updates `CHANGELOG.md` under Unreleased.
6. Baseline before starting: `uv run pytest -q` must pass on main (1744 as of
   2026-07-18) and `uv run pytest -q -m slow` (97) — record the exact numbers
   you observe.
7. Test-infra rules: session-file tests redirect `session_config.SESSION_FILE`
   via monkeypatch; theme-touching tests take the `restore_theme` fixture; UI
   tests run headless via the established dummy-driver pattern (see
   `tests/test_board_display_events.py`); waveform tests redirect
   `sim_bridge.WAVEFORM_DIR`.
8. New UI code reads theme colors dynamically (`THEME.xyz` at call time) —
   never capture `THEME.<attr>` at import time (U6 in-place theme-swap
   contract).
9. **Backlog bookkeeping (do not silently skip):** create a GitHub milestone
   for the release this ships in, with just-in-time issues titled `U35a`…`U35d`
   (or one umbrella issue) per the hybrid backlog model. The U34 arc skipped
   this silently and the audit flagged it; ask Rick about bucketing if he is
   responsive, but don't block — create the milestone either way.
10. Cadence: merge each PR when green (Rick's standing arc cadence). Stop
    after PR4 and report totals; release/tag decisions are Rick's.

## 1. Whole-project view: how simulator selection works TODAY

You need this map before touching anything. Verify each claim by grep — the
listed line numbers are 2026-07-18 and will drift.

- **The type:** `Simulator = Literal["ghdl", "nvc"]` (`sim_bridge.py:43`,
  introduced by D9). It rides through: `_SimBackend.NAME` class attrs; the
  `_backend(simulator)` dispatch; `analyze_vhdl(simulator=)`;
  `start_simulation(simulator=)`; `__main__` (CLI `--sim`, benchmark
  functions); `controller.py` session state; `session_config` key
  `"simulator"`; `sim_session_log.save_session_stats(simulator: str)` (already
  a plain `str` — flexible). Re-grep the full set:
  `grep -rn "Simulator\b" src tests` and follow every hit (the
  typed-refactor-round-trip rule: the value's WHOLE loop, not a card's list).
- **Binary resolution:** `_SimBackend.find()` = `shutil.which(cls.NAME)` —
  PATH only. `detect_simulators()` returns `["ghdl"(, "nvc")]` and always at
  least `["ghdl"]` so errors surface at analysis time, not at startup.
- **The user-facing switch:** the board **preview** screen's `[SIM: GHDL]`
  toggle (`ui/board_display.py` — module docstring describes it; the click
  handler cycles `available_simulators`; D9 round-trips `board.simulator`
  back out through `run()`). There is **no** Settings-dialog simulator row.
  The Settings dialog (`ui/settings_dialog.py`) is cycle-rows only; the app
  has **no text-input widget anywhere** — that constraint shaped the
  registration design below.
- **Process model (U34):** the launcher owns the one pygame window; the sim
  runs in a **headless** GHDL/NVC + cocotb child (`sim/sim_testbench.py`,
  pygame-free) streaming over `sim_link`. **The child is out of scope** — it
  must not be touched and needs no backend awareness. The child env var
  `FPGA_SIM_SIMULATOR` (metrics meta sidecar) keeps carrying the plain engine
  slug (`"ghdl"`/`"nvc"`).
- **Command construction:** `_GHDLBackend.analyze_cmd/elaborate_cmd/run_cmd`
  and `_NVCBackend.*` in `sim_bridge.py`. Two hard-won invariants:
  1. `run_cmd` passes `-gNAME=VALUE` **after** the unit name. GHDL documents
     `-g` as a simulation option (`ghdl -r --std=08 my_unit -gDEPTH=12`);
     the compiled llvm/gcc driver **silently drops** a pre-unit `-g` (mcode
     merely tolerates it) — that mistake once inflated benchmarks 2–4x.
     `tests/test_sim_bridge_backend.py::test_ghdl_run_cmd_generics_after_unit`
     pins this. Do not touch.
  2. `_prepare_simulation` elaborates for **both** engines with
     `cwd=work_dir` (PR #262): compiled GHDL backends emit the `sim_wrapper`
     executable there, and `-r` runs from the same cwd. GHDL takes **no**
     generics at `-e` (compiled backends reject the flag).
- **Backends on Rick's machine** (all installed, all verified green on the
  97-test slow suite except the 5 tests PR3 fixes):
  `/usr/local/bin/ghdl` (mcode, the PATH default),
  `/usr/local/ghdl-llvm/bin/ghdl` (AOT), `/usr/local/ghdl-llvm-jit/bin/ghdl`
  (JIT), `/usr/local/bin/nvc`. Each install resolves its own libraries from
  its binary path — no env vars needed for installed backends.

## 2. Decisions already made (do not reopen)

| Topic | Decision |
|---|---|
| Identity model | The `Simulator` engine literal **stays two-valued** (it selects the `_SimBackend` command builder). Add a frozen dataclass `SimulatorInfo` in `sim_bridge.py`: `engine: Simulator`, `path: str` (resolved absolute), `backend: str` (`"mcode" \| "llvm" \| "llvm-jit" \| "nvc"`), `label: str` (display), `version: str`. Discovery returns `list[SimulatorInfo]`. |
| Backend labeling | Probe each candidate with `--version` (subprocess, `timeout=5`, mirror the `_simulator_version` pattern in `sim/sim_testbench.py`; any failure → skip the candidate silently — a broken binary must never block launch). GHDL's backend is on the **third** line. **Parse order matters:** check `"mcode"` FIRST (the mcode line reads `"static elaboration, mcode JIT code generator"` — it contains "JIT" too), then `"LLVM JIT"` → `llvm-jit`, else a line containing `"llvm"` + `"code generator"` → `llvm`. NVC: engine `nvc`, backend `"nvc"`, version from line 1. |
| Discovery set | `shutil.which("ghdl")` + `shutil.which("nvc")` + glob `/usr/local/ghdl-*/bin/ghdl` + `shutil.which()` of `ghdl-mcode` / `ghdl-llvm` / `ghdl-llvm-jit` (distro naming). De-duplicate by `os.path.realpath`. Run once per launch, cache the list. |
| Registration (undiscoverable paths) | Three layers, **no new text-input widget**: (1) session-file key `extra_simulators: list[str]` (absolute paths, hand-editable); (2) `FPGA_SIM_EXTRA_SIMS` env, `os.pathsep`-separated, additive for one-off runs; (3) CLI `fpga-sim --add-sim /path/to/binary` — probes the binary, errors with the probe output if unrecognizable, else appends to `extra_simulators` and prints the resulting `--list-sims` table. A GUI "Browse…" reusing the VHDL-picker machinery is **out of scope** (phase-2 idea; park as an Icebox note in the closeout). |
| Selection surface | The preview screen's existing `[SIM: …]` toggle cycles **all** discovered+registered entries. Short button labels (width is limited): `SIM: GHDL`, `SIM: GHDL-LLVM`, `SIM: GHDL-JIT`, `SIM: NVC`; disambiguate duplicates (same backend, different path) with a numeric suffix. Full label + path go in `--list-sims`, the session log, and the sim screen's info strip only if it fits — do not redesign the strip. |
| Persistence | Session keys: keep `simulator` (engine slug — back-compat with old sessions) and add `simulator_path: str` (`""` = PATH default). On restore, re-probe the stored path; if missing or unprobeable, **fall back to the PATH default with a one-line console note** — never crash, never block the launcher. |
| Default | Whatever `ghdl` is on PATH (or NVC if only NVC exists) — exactly today's behavior. **Never auto-prefer the fastest.** |
| `--sim` values | Existing `ghdl` / `nvc` keep meaning "engine via PATH" (back-compat). New: `ghdl-mcode` / `ghdl-llvm` / `ghdl-jit` select a discovered variant (error listing the discovered set if absent), or an absolute path (must exist + probe). One shared resolver serves CLI and UI. |
| Session log | `save_session_stats` gains additive `simulator_backend` and `simulator_path` fields. Existing readers/tests must keep passing (fields optional). |
| Child env | `FPGA_SIM_SIMULATOR` stays the engine slug. `sim/sim_testbench.py` is **untouched** (U34 invariant: pygame-free child, imports only `board_loader`/`sim_link`/`sim_metrics`). |
| Stage-3 parity probe | In `analyze_vhdl`, after the early `-e` check succeeds: **if an executable named after the toplevel exists in `work_dir`** (that existence IS the compiled-backend signature — no version parsing in sim_bridge), run `[./sim_wrapper, "--stop-time=0fs"]` with `cwd=work_dir`, `capture_output=True`, `timeout=30`. Failure = nonzero returncode OR `"error during elaboration"` in stderr. Route the stderr through the SAME message + `add_error_hints` pipeline the mcode elab error uses, so the user gets the identical load-time rejection + hint. The compiled backend's message is `"bound check failure at <path>/sim_wrapper.vhd:NN"` — read `_check_parsed_contract` / the hint helpers and the three stage-3 tests (below) to map wrapper-line references onto the existing port-name hints; the tests' expected strings are the contract. |
| The 5 mcode-assumption slow tests | Fix, don't skip. Group A (missing `-e` in direct invocations): `tests/test_simulation.py::test_cocotb_simulation_passes` and `::test_ghdl_vcd_capture_produces_populated_file` each run `elaborate_cmd` (cwd=work_dir) before `-r` — a cheap in-memory no-op on mcode. Group B (stage-3 semantics): `tests/test_vhdl_validation.py::test_fixed_width_fixture_stage3_hint_ghdl`, `::test_extra_seg_stage3_hint_names_seg_ghdl`, `::test_bad_7seg_extra_seg_fails_stage3_on_7seg_board` pass unchanged once the parity probe lands. |
| CI | One new Linux job cloned from the existing pinned-GHDL install step, using the official asset `ghdl-llvm-6.0.0-ubuntu24.04-x86_64.tar.gz` (same URL pattern + sha256-pin discipline — download once, record the hash in the workflow). Runs the full + slow suites. **Not** added to branch-protection required checks (Rick promotes later; required-check names are load-bearing). A second `ghdl-llvm-jit` variant (asset exists too) only if the first lands trivially — prefer a small matrix over copy-paste. Windows LLVM (MSYS2 packages) is out of scope. |
| Docs | `docs/install.md` gains a "Choosing a simulator" section: the relative-performance table below, a which-to-install paragraph (casual → distro ghdl; speed → NVC; GHDL-specific + speed → llvm build), and the backend build recipe (sibling build dirs off one source tree; **one `--prefix` per backend, never shared, never reconfigure an existing build dir**; `--with-llvm-config` / `--with-llvm-jit`). `docs/user_guide.md` gets a short echo near the `[SIM:…]` toggle description + `--list-sims`/`--add-sim`. Use **ratios, not absolute rates** (machine-dependent), a dated "measured on" footnote, and the reproduce command `uv run fpga-sim --benchmark 10 --no-ui`. |

Docs table content (source of truth for wording):

| Simulator | Relative speed | Startup / Reload VHDL | Notes |
|---|---|---|---|
| NVC | fastest (~4–6x mcode) | fast | full VHPI; the speed pick, esp. embedded-CPU designs |
| GHDL mcode | baseline (1x) | instant | the default; what most distros ship |
| GHDL LLVM-JIT | ~1.2x mcode | instant | mcode's feel, free speedup |
| GHDL LLVM | ~2–3x mcode | slower (compile+link per launch/reload) | width errors surface via the stage-3 probe |

### Files that must NOT change in this arc (any PR)

`sim/sim_testbench.py`, `sim/sim_wrapper_template.vhd`, anything under `hdl/`
or `boards/`, the sync scripts/parsers, `sim/test_*.py` (design behavioral
suites), `sim/capture_frames.py`, `scripts/capture_demo.py`,
`src/fpga_sim/sim_link.py`. If a change seems to require touching one of
these, stop and re-read this plan — you are off-track. (`tests/` files ARE in
scope where named above.)

## 3. PR chain

Four PRs, each independently green and mergeable.

---

### PR1 — `feat/u35a-simulator-identity`: discovery + registration + `--list-sims` (additive, inert)

1. `sim_bridge.py`: `SimulatorInfo` dataclass; `_probe_simulator(path) ->
   SimulatorInfo | None` (version parse per §2, including the mcode-contains-
   "JIT" ordering trap); `discover_simulators(extra: list[str]) ->
   list[SimulatorInfo]` (discovery set + registration paths + realpath
   de-dup, stable order: PATH ghdl, PATH nvc, variants, extras). Keep
   `detect_simulators()` working (thin wrapper) so nothing breaks yet.
2. `session_config.py`: `extra_simulators` key (documented in the module
   docstring's schema list, default `[]`).
3. `__main__.py`: `--list-sims` (prints label / backend / version / path for
   every discovered entry, then exits 0) and `--add-sim PATH` (probe →
   persist → print table; nonzero exit + probe output on failure).
   `FPGA_SIM_EXTRA_SIMS` merged into the extras list at discovery time.
4. Tests (`tests/test_simulator_discovery.py`): labeler against canned
   `--version` outputs for all four backends (the three real GHDL third-lines
   are quoted in §2 — use them verbatim); mcode-vs-JIT ordering; NVC; garbage
   output → None; timeout → None (monkeypatched subprocess); realpath de-dup;
   extras merge (env + file); `--list-sims` / `--add-sim` behavior with
   `SESSION_FILE` redirected.
5. CHANGELOG: Added (`--list-sims`, `--add-sim`, `extra_simulators`).

**Gate:** full suite green; `uv run fpga-sim --list-sims` on Rick's machine
shows four truthfully-labeled entries; default launcher flow byte-identical
(no behavior change without the new flags).

---

### PR2 — `feat/u35b-selection-roundtrip`: the choice honored end-to-end

1. Thread `SimulatorInfo` (or `engine` + `path`) through the round-trip:
   preview `[SIM:…]` toggle cycles the discovered list with the short labels
   from §2 (grep the toggle's draw + click sites in `ui/board_display.py`;
   verify label width against the button rect at the minimum window size);
   controller/session save `simulator` + `simulator_path` on change and at
   the established save points (grep `update_session(` for the pattern);
   restore-with-fallback per §2; `analyze_vhdl` + `start_simulation` +
   benchmark receive and USE the chosen path — the cleanest mechanism:
   `_SimBackend` builders take the resolved binary as their argv[0] instead
   of calling `find()` internally. Re-grep every `find()`/`which` call site.
2. `--sim` slug/path resolution (shared resolver with the UI). `--benchmark`
   header and the sim screen's info strip print the label.
3. `sim_session_log.save_session_stats`: additive `simulator_backend` /
   `simulator_path`.
4. Tests: toggle-cycle unit test (dummy driver); session round-trip incl. the
   missing-binary fallback (point `simulator_path` at a nonexistent file);
   env-construction test asserting the child still gets engine-slug
   `FPGA_SIM_SIMULATOR`; a `--sim ghdl-llvm` resolution test with discovery
   monkeypatched; session-log field test.
5. CHANGELOG: user-facing (pick any installed backend from the preview
   toggle; persisted).

**Gate:** full suite green; on Rick's machine an interactive-equivalent check
via the e2e harness: `start_simulation` launched with the llvm-jit path runs
blinky green (the slow e2e pattern in `tests/test_simulation_screen.py` shows
how to drive it headless with `benchmark_secs`).

---

### PR3 — `feat/u35c-compiled-backend-parity`: stage-3 probe + the 5 tests

1. The runtime-elaboration probe in `analyze_vhdl` per §2 (trigger =
   executable exists in work_dir; run `--stop-time=0fs`; map stderr through
   the existing hint pipeline). Mind: the probe must never fire on mcode
   (no executable is produced) — assert that in a unit test with a fake
   work_dir.
2. Group A test fixes (`-e` before `-r` in the two `tests/test_simulation.py`
   direct invocations).
3. Unit tests for the probe (fake executable script in tmp work_dir emitting
   the bound-check stderr + rc 1 → ok=False + hint present; clean script →
   ok=True; mcode-shaped dir without executable → probe skipped).
4. CHANGELOG: Fixed (compiled backends reject bad designs at load time).

**Gate:** `uv run pytest -q -m slow` **green under all three GHDL backends**
locally — run it three times with PATH prepended per backend
(`/usr/local/ghdl-llvm/bin`, `/usr/local/ghdl-llvm-jit/bin`, and plain).
Expect 97/97 in each. This is the arc's central proof; budget the ~3 minutes.

---

### PR4 — `feat/u35d-ci-docs-closeout`

1. CI job "Test Linux + GHDL-LLVM" per §2 (clone the existing install step;
   new asset name + freshly-pinned sha256; full + slow suites; non-required).
   Optional stretch: matrix in llvm-jit.
2. Docs: install.md "Choosing a simulator" + build-variants recipe;
   user_guide echo. rumdl-clean.
3. Roadmap closeout per the completion checklist: U35 → delivered (context,
   file-index rows, delivery log, downstream refs); Icebox note for the
   "Browse…" phase-2 idea.
4. CHANGELOG.

**Gate:** the new CI job green on this PR; full suite green; report totals to
Rick (suite delta, `--list-sims` output, the three-backend slow-suite proof)
and STOP — release is his call.

## 4. Verification playbook (run per PR as applicable)

```bash
uv run pytest -q                                    # fast suite (baseline 1744)
uv run pytest -q -m slow                            # 97 as of 2026-07-18
uv run ruff check . && uv run ruff format --check . && uv run mypy .
uv run fpga-sim --list-sims                         # 4 labeled entries on Rick's machine
# per-backend slow suite (PR3 gate):
PATH=/usr/local/ghdl-llvm/bin:$PATH     uv run pytest -q -m slow
PATH=/usr/local/ghdl-llvm-jit/bin:$PATH uv run pytest -q -m slow
# honest benchmark spot-checks (±10% of the §1 table):
uv run fpga-sim --benchmark 10 --sim ghdl-llvm --board ArtyA7_35Platform --vhdl hdl/blinky.vhd --no-ui
# workload-identity proof before publishing ANY new benchmark number:
# capture one VCD per backend and confirm identical clk edge spacing
FPGA_SIM_WAVEFORM=vcd FPGA_SIM_WAVEFORM_DIR=/tmp/wv uv run fpga-sim --benchmark 3 --sim ghdl-llvm --board ArtyA7_35Platform --vhdl hdl/blinky.vhd --no-ui
# load-time rejection parity (expect ok=False + a Hint on EVERY backend):
PATH=/usr/local/ghdl-llvm/bin:$PATH uv run python -c "from fpga_sim.sim_bridge import analyze_vhdl; print(analyze_vhdl('hdl/bad_contract_fixed_width.vhdl', toplevel='bad_contract_fixed_width'))"
```

Agent sessions cannot do interactive window checks — use dummy-driver
screenshots for evidence and flag interactive items (toggle label fit!) for
Rick explicitly.

## 5. Known traps (hard-won this month — read before coding)

1. **mcode's version line contains "JIT"** (`mcode JIT code generator`) —
   check `"mcode"` before `"LLVM JIT"` in the labeler or every mcode install
   is mislabeled.
2. **`-g` placement is sacred:** simulation options go AFTER the unit;
   compiled backends silently drop pre-unit `-g` (this inflated benchmarks
   2–4x before #264). A regression test pins it; never "clean up" the order.
3. **`-e` rejects `-g` on compiled backends** — never add generics to
   `elaborate_cmd` for GHDL.
4. **Executable-in-workdir is the compiled-backend signature.** Use it for
   the stage-3 probe trigger; do not parse versions inside `sim_bridge`.
5. Version probes are subprocesses: always `timeout=5`, always treat any
   exception as "not a simulator"; a hung binary must not hang the launcher.
6. The `[SIM:…]` toggle button has finite width — measure rendered label
   sizes at the minimum window size; `SIM: GHDL-LLVM` is the longest.
7. Session restore of a deleted/moved binary must fall back to the PATH
   default with a console note — never crash, never show an empty toggle.
8. `FPGA_SIM_SIMULATOR` (child env) stays the engine slug; the headless child
   and its metrics sidecar are untouched (U34 invariant).
9. NVC needs `-H 512m` at elaborate/run (existing `_NVC_HEAP`) — selection
   plumbing must not bypass the NVC backend class.
10. Windows: `shutil.which` handles `.exe`; realpath de-dup must not collapse
    distinct binaries behind case-insensitive paths incorrectly — use
    `Path.resolve()`.
11. `mypy .` covers tests and scripts; ruff docstring rules apply to every
    new public def.
12. PR numbers share the issue sequence — never predict them in docs; fill in
    after creation.
13. When you publish any performance number, first PROVE the workload is
    identical across backends (the VCD edge-spacing check in §4). A
    too-good-looking result is a prompt to verify, not celebrate.
14. rumdl rewrites bare code fences — language-tag them up front.

## 6. Out of scope for U35

- GUI "Browse for simulator…" (reuse of the VHDL picker) — phase-2 Icebox.
- Windows LLVM backends in CI (MSYS2 packaging plumbing).
- Auto-benchmarking backends or auto-selecting the fastest.
- `analyze_metrics.py` rework (P19) and any `sim_testbench.py` change.
