# U34 — Single-window simulation: implementation plan

**For the implementing session (Opus): this document is self-contained.**
Read it top to bottom before writing code. Every architectural decision has
already been made and validated by a working spike — do not relitigate them;
if the code has drifted from what this plan asserts, re-grep and adapt the
mechanics, not the decisions.

- **Why & evidence:** `docs/experiments/single_window_sim.md` (measured:
  GHDL +16–26% throughput, NVC ×4.3, host UI 62 fps, input RTT p95 ≤ 32 ms).
- **Working spike:** branch `spike/single-window-sim` (commit `e75a989`) —
  `src/fpga_sim/sim_link.py`, `sim/sim_testbench_bridge.py`,
  `scripts/spike_single_window.py`. The spike is the reference
  implementation; PR1 promotes its files. **This branch exists only
  locally on Rick's machine** (unless it has since been pushed): do not
  delete it before PR1 merges, run this arc on that machine — or push it
  first (`git push -u origin spike/single-window-sim`).
- **Goal:** the launcher's pygame window persists for the entire session.
  Simulation no longer closes it and opens another: the GHDL/NVC + cocotb
  child runs headless and streams signal state over an IPC link.

## 0. Ground rules (repo conventions — non-negotiable)

1. One feature branch per PR, always branched off **freshly-pulled main**
   (`git fetch && git checkout -b <branch> origin/main`). Never commit to main.
2. Before every commit: `uv run ruff check .`, `uv run ruff format --check .`,
   `uv run mypy .` (CI runs mypy over the WHOLE repo, tests included).
   Pre-commit hooks (ruff/mypy/rumdl) may auto-fix files and abort the
   commit — `git add` the fixes and commit again.
3. Markdown: rumdl enforces fenced-code languages (MD040) and resolvable
   relative links (MD057). US spelling everywhere.
4. Use `gh` for all GitHub operations. PR bodies end with the standard
   Claude Code attribution footer; commits end with the Co-Authored-By
   trailer.
5. Each user-visible PR updates `CHANGELOG.md` under Unreleased.
6. Baseline before starting: `uv run pytest -q` must pass on main
   (~1707 tests as of v0.14.0 — record the exact number you observe).
7. New tests follow existing infra rules: session-file tests redirect
   `session_config.SESSION_FILE`; theme-touching tests take the
   `restore_theme` fixture; UI tests run headless via the established
   dummy-driver pattern (see `tests/test_board_display_events.py`).
8. New UI code must read theme colors dynamically (`THEME.xyz` at call
   time) — never capture `THEME.<attr>` into module/class attributes at
   import time (the U6 in-place theme-swap contract).
9. Cadence: merge each PR when green (Rick's standing arc cadence). The
   one exception is PR3's default-flip — see its gate. Release/tag
   decisions are Rick's; stop after PR4 and report.

## 1. Target architecture (recap)

```text
launcher process (owns THE window)          GHDL/NVC process (headless)
┌─────────────────────────────┐             ┌────────────────────────────┐
│ selector → preview → picker │             │ cocotb sim_testbench       │
│        → SimulationScreen   │  sim_link   │  loop:                     │
│  FPGABoard + SimPanel render│◄────────────│   await Timer(step)        │
│  60 fps, always responsive  │  "state"    │   read led/seg             │
│                             │────────────►│   apply sw/btn/speed/clk   │
│  clicks → "input"/"speed"…  │  "input"…   │   throttled send, pace     │
└─────────────────────────────┘             └────────────────────────────┘
```

Invariants that make this safe:

- The VHDL boundary is untouched: the child reads the same `sim_wrapper`
  ports (`clk/sw/btn/led/seg/clk_half_ns`) for generic AND board-native
  runs (the native wrapper already adapts to that boundary).
- The child never imports pygame, directly or transitively. Its allowed
  `fpga_sim` imports: `board_loader`, `sim_link`, `sim_metrics`. It must
  NOT import `fpga_sim.ui.*`, `session_config`, `sim_bridge`, or
  `controller`. (`SPEED_DEFAULT` lives in `ui.sim_panel`, which imports
  pygame — the child keeps its own `_SPEED_DEFAULT = 0.1` constant.)
- The parent never blocks on the child: all link reads are `poll(0)`-based
  drains; child startup is awaited with a spinner + timeout; shutdown is
  stop-message → bounded wait → terminate.

### Message protocol (the contract; already implemented in sim_link/spike)

| Direction | Kind | Payload |
|---|---|---|
| child→host | `hello` | `{pid:int}` |
| child→host | `state` | `{led:int, seg:int\|None, sim_ns:int, steps:int, input_seq:int, step_ns:int, timer_pct:float, at_max:bool}` |
| child→host | `bye` | `{sim_ns:int, steps:int, wall_s:float}` |
| host→child | `input` | `{sw:int, btn:int, seq:int}` |
| host→child | `speed` | `{factor:float}` |
| host→child | `clk` | `{half_ns:int}` |
| host→child | `pause` | `{on:bool}` |
| host→child | `stop` | `{}` |
| (synthetic) | `eof` | emitted by `drain()` when the peer died |

`at_max` is new relative to the spike: child sets it when the computed step
hit the cycle cap while unpaused (feeds the panel's CPU-limited indicator).
Send throttling (child): forced on `input_seq` change; otherwise on value
change with ≥4 ms spacing, heartbeat every ≤50 ms.

### Environment variables passed to the child (final state, after PR4)

| Keep | Why |
|---|---|
| `TOPLEVEL=sim_wrapper`, `COCOTB_TEST_MODULES=sim_testbench` | cocotb |
| `FPGA_SIM_BOARD_JSON` | resource counts / seg digits |
| `FPGA_SIM_LINK_PORT`, `FPGA_SIM_LINK_KEY` | the link |
| `FPGA_SIM_SPEED` | initial pacing seed (avoids a wrong-speed blip before the first `speed` message) |
| `FPGA_SIM_BENCHMARK` | free-run benchmark mode |
| `FPGA_SIM_METRICS`, `FPGA_SIM_SIMULATOR`, `FPGA_SIM_VHDL_PATH`, `FPGA_SIM_GENERICS`, `FPGA_SIM_TOPLEVEL` | metrics CSV + meta sidecar (child-side) |

| Drop (parent-side data now) | Former consumer |
|---|---|
| `FPGA_SIM_WIDTH` / `FPGA_SIM_HEIGHT` | child window size |
| `FPGA_SIM_THEME` | child theme restore |
| `FPGA_SIM_EXIT_INTENT_FILE` | exit-intent sidecar file |
| `FPGA_SIM_NATIVE_CONVENTION` | child badge/active-low note |

## 2. Decisions already made (do not reopen)

| Topic | Decision |
|---|---|
| Window-close (X) during simulation | Quits the whole app (matches every other screen now that there is one window). ESC / [■ Stop] / toolbar = stop sim, back to launcher screens. This is a deliberate UX unification — call it out in PR3's description and user_guide. |
| Modal dialogs over a running sim (Help F1, error dialogs) | Send `pause {on:true}` before opening, restore the pre-modal pause state after — preserves today's "sim time does not advance during modals" semantics. |
| Window drag/resize stalls (host blocked in OS modal loop) | Child keeps simulating; host shows latest state on release. Accepted improvement, no mitigation needed (64 KB pipe buffer absorbs the throttled send rate for many seconds; child `send()` blocking briefly on an extreme stall is harmless). |
| `SimExit` enum | Survives as the SimulationScreen result type; gains `QUIT` member (window X). PR4 relocates it `sim_bridge.py` → `ui/results.py` (beside `ScreenResult`) and updates all importers — the file-transport rationale in its docstring dies with the intent file. |
| Initial speed | Seed via `FPGA_SIM_SPEED` env; panel slider seeds from session in the parent; parent sends `speed` on any slider change; parent writes final value back to the session at screen exit (`update_session(speed_factor=…)`). The child never touches the session file again. |
| Initial virtual clock | Parent sends `clk {half_ns}` right after `hello` (mirrors today's one-time `dut.clk_half_ns` sync), then on every [-]/[+] change. |
| Stats semantics | Panel's G/D/I zones become: Sim% = child-reported `timer_pct` (share of the child's loop), Draw%/Idle% = host-frame shares. Session log `avg_ghdl_pct` = mean of `timer_pct` samples. Document the change of denominator in the panel docstring + user_guide. |
| Metrics CSV (`FPGA_SIM_METRICS`) | Stays child-side: `timer_us`/`sim_step_ns`/`clk_period_ns`/`speed_factor` real, `draw_us`/`tick_us` recorded as 0.0 (measured in the host now). Meta sidecar stays child-written. `analyze_metrics.py` rework parked as icebox P19. |
| Console prints ("SW3: ON [J4]", banner) | Move to the parent (SimulationScreen has `ComponentInfo`). Child prints only its startup line and end-of-run stats. |
| Child stdout/stderr | stdout inherits the terminal (cocotb banner, GHDL notes — today's behavior). stderr = `PIPE` with a daemon reader thread that echoes lines to the terminal AND keeps a tail ring buffer (~50 lines) for the crash dialog. |
| Startup watchdog | 90 s to `hello` (NVC/Windows headroom), spinner overlay meanwhile; child exiting pre-connect → error dialog with stderr tail. |
| `sim/capture_frames.py` + `scripts/capture_demo.py` | Untouched. They legitimately keep the pygame-in-child pattern (headless offline GIF capture, invoked outside the launcher). |
| Benchmark (`--benchmark`) | **Two modes** (Rick, 2026-07-16 — the benchmark must keep covering the whole system, not just GHDL/NVC). Default `--benchmark N` = full system: SDL dummy driver, the REAL `SimulationScreen` rendering at 60 fps (`show_toolbar=False` — parity with today's benchmark overlay rules), child free-running via `FPGA_SIM_BENCHMARK=N`. Report keeps Avg FPS / Draw% / Idle% (host-side now) and adds the child's steps / sim rate / timer%. This keeps a comparison baseline for pygame upstream changes and our own UI changes, and exercises the production render loop rather than a bespoke one. New opt-in `--benchmark N --no-ui` = child-only (no pygame import at all): drain link, wait for `bye`, print child stats — a new diagnostic capability for isolating simulator regressions from UI regressions. The two modes double as an interference probe: on multicore machines the full-system sim rate ≈ the no-ui sim rate, so a meaningful gap between them indicates host/child CPU contention (small machines, power-save governors). Session log written in both modes (UI fields zero/absent in `--no-ui`). |
| NVC cycle cap | NOT retuned. Free-running steps already saturate NVC (~268 steps/s × 9,596 cycles); the cap now only bounds per-step input latency. Revisit only if a future card asks. |
| `COUNTER_BITS` visible-rate calibration | PR4 includes a 10-minute *check*, not a change: run blinky + counter_7seg on NVC headless, eyeball capture (screenshot) for sane blink rates. File a follow-up issue only if something looks wrong. |

### Files that must NOT change in this arc (any PR)

`sim/sim_wrapper_template.vhd`, anything under `hdl/` or `boards/`, the
sync scripts/parsers, the design behavioral tests (`sim/test_*.py`),
`tests/test_simulation.py` / `test_ghdl.py` / `test_nvc.py` (they drive
cocotb with the design test modules, never sim_testbench),
`sim/capture_frames.py` + `scripts/capture_demo.py`,
`src/fpga_sim/board_loader.py`, `src/fpga_sim/session_config.py`,
`src/fpga_sim/sim_session_log.py` (their *callers* move; the modules do
not). If a change seems to require touching one of these, stop and
re-read this plan — you are off-track.

## 3. PR chain

Four PRs, each independently green and mergeable. Suggested milestone:
create one titled for the single-window release per the hybrid backlog
model, with just-in-time issues titled `U34a`…`U34d` (or one umbrella
issue) — confirm bucketing with Rick if he's responsive; don't block on it.

---

### PR1 — `feat/u34a-process-layer`: link + headless child + `SimChild` + docs (additive, inert)

Everything here is unreachable from the default launcher flow, but each
piece lands unit-tested; PR2 plugs the UI into it.

1. Import from the spike branch (then review as your own):

   ```bash
   git checkout spike/single-window-sim -- \
       src/fpga_sim/sim_link.py \
       sim/sim_testbench_bridge.py \
       docs/experiments/single_window_sim.md \
       docs/experiments/single_window_live.png \
       docs/u34_single_window_plan.md
   ```

2. Mature `sim/sim_testbench_bridge.py` beyond the spike version:
   - Add `at_max` to `state` (see §1).
   - Honor `FPGA_SIM_METRICS` exactly as today's `sim_testbench.py` does
     (SimMetrics + `_write_meta_sidecar`, with draw/tick = 0.0 — lift both
     helpers; keep them pygame-free).
   - Keep the spike's benchmark free-run + end-of-run stats print.
   - Module docstring: explain it supersedes the in-child UI (link to the
     experiment doc). Note `_SEND_MIN_S`/`_SEND_MAX_S` rationale.
3. **`src/fpga_sim/sim_bridge.py`** — additive only:

   ```python
   @dataclass
   class SimChild:
       """Handle for a running headless simulation subprocess."""
       proc: subprocess.Popen[bytes]
       link: SimLinkHost
       wave_cfg: WaveConfig | None
       generics: dict[str, str]         # finish_waveform needs these
       match: ConventionMatch | None
       stderr_tail: deque[str]          # filled by the reader thread

       def stop(self, timeout: float = 5.0) -> int: ...   # stop msg → wait → terminate → kill
       def poll(self) -> int | None: ...

   def start_simulation(...) -> SimChild:
       # parameters: launch_simulation's, minus sim_width/sim_height/theme,
       # plus benchmark_secs: float | None → FPGA_SIM_BENCHMARK (child
       # free-runs then self-stops; used by --benchmark and the e2e tests).
       # speed_factor stays — it becomes the FPGA_SIM_SPEED pacing seed.
       # body = launch_simulation's prep (seg detect, analyze-if-needed,
       # NVC elaborate, waveform resolve, env build) + link env vars +
       # Popen(stderr=PIPE, + echo/tail reader thread).

   def finish_waveform(child: SimChild) -> None:
       # today's post-run tail (gtkw write, "Waveform written" print,
       # auto-open), fed entirely from SimChild fields; no-op when
       # wave_cfg is None or the dump is missing/empty.
   ```

   Factor the shared prep into a private helper both `launch_simulation`
   (legacy, behavior unchanged) and `start_simulation` call — do NOT
   duplicate the 90 lines. Legacy keeps its own post-run waveform tail
   until PR4; share `finish_waveform` internals where easy.
4. **Tests:**
   - `tests/test_sim_link.py`: host↔client loopback in-process
     (`SimLinkHost` + `connect_from_env` with monkeypatched env), covering:
     round-trip of each message kind, `drain()` ordering, `drain()` EOF
     synthesis after peer close, `send()` returning False on closed peer,
     `wait_connected` timeout=0 returns False before any client.
   - `tests/test_sim_child.py`: `start_simulation` env construction (link
     vars present; dropped vars absent; `benchmark_secs` plumbed) with the
     subprocess monkeypatched; `SimChild.stop()` escalation with a
     scripted dummy process.
5. Roadmap edits (`docs/improvement_roadmap.md`):
   - Add the **U34** card (Part 1): single-window simulation, effort L,
     "Done when: no window is created or destroyed between launcher start
     and app exit; benchmark parity per experiment doc". Link both docs.
   - **U24** (batch Timer calls): append the measured note — ×10 batching
     gained only +3% on GHDL — and close it as *won't-do, resolved by
     measurement* (do NOT mark it delivered).
   - **U23** (dirty-flag redraw): re-point "touches `sim/sim_testbench.py`
     draw loop" → the SimulationScreen draw loop (name dependency on U34).
6. CHANGELOG: internal note (new IPC + process-handle layer, no
   user-visible change).

**Gate:** full suite green;
`uv run python -c "import fpga_sim.sim_link, fpga_sim.sim_bridge"` works;
rumdl clean on the two new docs.

---

### PR2 — `feat/u34b-simulation-screen`: attached mode behind an opt-in flag

The big one (mostly code motion). Default behavior unchanged; the new path
activates only with `FPGA_SIM_SINGLE_WINDOW=1`.

1. **`src/fpga_sim/ui/simulation_screen.py`** — the heart. A screen class
   in the style of the other screens:

   ```python
   class SimulationScreen:
       def __init__(self, screen, clock, board_def, child: SimChild, *,
                    speed_factor, match: ConventionMatch | None,
                    show_toolbar: bool = True) -> None: ...
       def run(self) -> SimExit: ...
       run_stats: RunStats  # small dataclass populated by run(): fps /
                            # draw% / idle% averages, child timer% samples,
                            # sim_ns, duration — feeds save_session_stats
                            # here and the --benchmark report in PR3
   ```

   Contents are RELOCATED from `sim/sim_testbench.py`'s
   `interactive_sim()` (keep the visuals pixel-identical) plus the spike
   host loop:
   - FPGABoard (`show_footer=False`) + SimPanel + SimToolbar (only when
     `show_toolbar`) + overlays (info strip with native tag, Pause/Stop
     buttons, S-toggle panel, hint line, F1 HelpDialog with the
     pause-wrap decision from §2).
   - Waiting phase: render board + "Starting GHDL/NVC…" overlay while
     polling `link.wait_connected(0)` + `child.poll()`; watchdog 90 s.
   - Live phase: drain link (keep latest `state`), `set_led`/`set_seg`,
     input callbacks → `input` messages (+ the SW/BTN console prints),
     slider → `speed`, [-]/[+] → `clk`, pause state → `pause`,
     panel stats via the new remote feed, `clock.tick(60)`.
   - Exit paths: toolbar → its `SimExit`; ESC/[Stop] → `STOPPED`;
     `pygame.QUIT` → `QUIT`; `eof`/`bye` → `STOPPED` (or error dialog if
     `child.poll()` is nonzero without a `bye` — show the stderr tail,
     return `STOPPED`). Classify QUIT-vs-ESC from the raw event list
     BEFORE handing events to `FPGABoard._handle_events` — the board
     collapses both into `running = False`.
     On every exit path the screen calls `child.stop()`, writes
     `update_session(speed_factor=…)`, and `save_session_stats(...)`
     (mode/convention args from `match`). Waveform announcement is NOT
     the screen's job — the caller runs `finish_waveform(child)` after
     `run()` returns (controller and benchmark both do).
   - Native badge: port `_native_convention()` / `_active_low_roles()`
     logic from sim_testbench, but source the data from the passed
     `ConventionMatch` directly (no JSON env round-trip).
   - Theme rule from §0.8 applies throughout.
2. **`src/fpga_sim/ui/sim_panel.py`** — add the remote-stats feed:
   `set_remote(sim_ns_total: int, at_max: bool)` (replaces per-frame
   `update(sim_step_ns)` accumulation in this mode) and let
   `update_timing()` accept the child `timer_pct` for the G zone (see §2
   stats decision). Keep the legacy methods untouched (old path still
   uses them until PR4).
3. **`SimExit`** — add `QUIT = "quit"` where the enum lives today
   (`sim_bridge.py`; relocation to `ui/results.py` happens in PR4).
   `_read_exit_intent` must never produce it (the legacy intent file
   cannot contain "quit" — assert or comment).
4. **`src/fpga_sim/controller.py`** — minimal, flag-gated:

   ```python
   def on_simulate(self) -> NextScreen:
       if os.environ.get("FPGA_SIM_SINGLE_WINDOW") == "1":
           return self._on_simulate_attached()
       ...existing body unchanged...
   ```

   `_on_simulate_attached()`: same re-analyze/session-save preamble as
   today (minus `pygame.quit()`/`_restore_window`), then a loop:
   `start_simulation(...)` → `SimulationScreen(...).run()` →
   `finish_waveform(child)` → route the `SimExit` exactly as the legacy
   tail does (RELOAD_VHDL revalidates via the existing
   `_revalidate_for_reload()` and loops; QUIT returns `NextScreen.QUIT`,
   whose quit-time session save already happens in `run()`).
5. **`src/fpga_sim/ui/__init__.py`** — export `SimulationScreen`.
6. **Tests:**
   - `tests/test_simulation_screen.py`: headless construction/draw, a fake
     link connection feeding `state` messages → LED/seg applied, QUIT
     event → `SimExit.QUIT`, toolbar click routing, modal-pause message
     emission. Use a real `SimLinkHost` + in-process client thread as the
     fake child (no subprocess).
   - e2e (marked `slow`, GHDL, dummy video driver): flag on, blinky+Arty
     via `start_simulation(benchmark_secs=3)` + `SimulationScreen` — the
     child free-runs and self-stops, so the screen exits `STOPPED`
     deterministically with no event injection. Assert both: LED state
     changed at least once, AND an input round-trips (invoke the switch
     callback directly, then watch the echoed `input_seq` advance —
     design-independent, unlike asserting an LED response to a switch).
     Mirror `tests/test_simulation.py` skip/guard mechanics. Must pass on
     Windows CI (TCP localhost is fine there); if the runner proves flaky
     on the handshake, lengthen the hello timeout — don't skip the test.
   - Parametrize one e2e case over ghdl+nvc if NVC present (skip
     otherwise, same guards as `tests/test_nvc.py`).
7. CHANGELOG: "experimental: `FPGA_SIM_SINGLE_WINDOW=1` keeps the launcher
   window during simulation".

**Gate:** full suite green with the flag unset; the slow e2e green with it
set (drop a temporary `pygame.image.save` into the e2e locally if you want
to eyeball a live frame — the spike branch's harness also remains available
for reference). Merge when green.

---

### PR3 — `feat/u34c-default-flip`: single-window becomes the default

1. Flip: attached path is default; `FPGA_SIM_LEGACY_WINDOW=1` selects the
   old path (escape hatch, one release).
2. Rewire `__main__._run_benchmark()` per the §2 benchmark decision:
   default = full-system (keep the `SDL_VIDEODRIVER=dummy` setup, drive the
   real `SimulationScreen`, report host fps/draw%/idle% + child stats);
   add `--no-ui` = child-only with no pygame import. The full-system sim
   rate must stay comparable to the historical baseline series (it is the
   same "whole app, headless" measurement — only decoupled now). The
   report reads the screen's public `run_stats` (PR2) — don't reach into
   screen/panel privates.
3. Update tests that assumed the legacy default (grep for
   `FPGA_SIM_SINGLE_WINDOW` and invert; `tests/test_controller.py`
   transition tests point at the attached path now).
4. Docs, first pass: `docs/user_guide.md` (persistence wording, stats
   panel zone semantics, the X-closes-app change, board-native tag
   unchanged visually); CHANGELOG user-facing entry.
5. Benchmark parity check, recorded in the PR description (reference
   ranges from the experiment doc, same machine: GHDL/Arty/blinky
   ≈ 0.0039–0.0041×; NVC ≈ 0.024–0.027×; tolerance ±10%).

**Gate:** full suite green; benchmark numbers in range; **request Rick's
2-minute interactive spot-check before merging this one** (the UX flip).
If he defers with his standing "proceed, review later", merge on green.

---

### PR4 — `feat/u34d-legacy-removal`: delete the old path + closeout

1. Replace `sim/sim_testbench.py` with the bridge (rename
   `sim_testbench_bridge.py` → `sim_testbench.py`; set
   `COCOTB_TEST_MODULES=sim_testbench` in `start_simulation`). Delete the
   pygame testbench entirely.
2. Delete: `launch_simulation()`'s blocking run tail (keep/absorb prep
   helpers), `_EXIT_INTENT_NAME`/`_read_exit_intent`, the `SimExit`
   docstring's file-transport rationale, `FPGA_SIM_LEGACY_WINDOW`, the
   dropped env vars (§1 table). (`scripts/spike_single_window.py` lives
   only on the spike branch — nothing to delete on main; after this PR
   merges the spike branch is fully superseded and may be deleted.)
3. Relocate `SimExit` → `src/fpga_sim/ui/results.py`; update importers
   (`sim_toolbar.py`, `controller.py`, `sim_bridge.py` if still needed,
   tests). This removes the ui→sim_bridge import from the toolbar.
4. Tests:
   - `tests/test_sim_exit.py`: intent-file tests die; enum/routing tests
     survive against the new location.
   - `tests/test_native_convention.py` (B3b section): the subprocess
     env-JSON tests become ordinary in-process tests of the
     SimulationScreen badge helpers (simplification — no subprocess).
   - `tests/test_sim_testbench_lint.py`: still lints `sim/sim_testbench.py`
     (now the bridge); update the module-level-env subprocess import test
     to the new env surface.
5. Docs, final: `docs/architecture.md` (two-phase section rewritten around
   the link; "How board-native works" run-mechanics paragraph), `CLAUDE.md`
   (Key Files rows for sim_testbench/sim_link/simulation_screen + Data
   Flow steps 3–5), roadmap U34 → delivered (follow the roadmap completion
   checklist: context, downstream deps — U23 pointer — file lists,
   delivery log). Icebox: add **P19** `analyze_metrics.py` rework for
   split-process metrics; optionally **P20** modernize `capture_frames.py`.
6. The `COUNTER_BITS` NVC visible-rate check (§2, last row).
7. CHANGELOG.

**Gate:** full suite green; `grep -rn "EXIT_INTENT\|FPGA_SIM_WIDTH\|FPGA_SIM_THEME"
src sim tests scripts` returns nothing (docs/history excepted); a final
headless e2e on both backends; report totals to Rick (suite count delta,
benchmark table) and STOP — release is his call.

## 4. Verification playbook (run per PR as applicable)

```bash
uv run pytest -q                                   # full suite
uv run pytest -q -m slow                           # sim integration only
uv run ruff check . && uv run ruff format --check . && uv run mypy .
# benchmark parity (PR3/PR4) — full system (default) AND child-only:
uv run fpga-sim --benchmark 10 --board ArtyA7_35Platform --vhdl hdl/blinky.vhd
uv run fpga-sim --benchmark 10 --sim nvc --board ArtyA7_35Platform --vhdl hdl/blinky.vhd
uv run fpga-sim --benchmark 10 --board DE10LitePlatform --vhdl hdl/counter_7seg.vhd
uv run fpga-sim --benchmark 10 --board ArtyA7_35Platform --vhdl hdl/blinky.vhd --no-ui
# full-system vs --no-ui sim rates should agree within noise on this machine;
# a gap = host/child CPU contention (worth noting in the PR if seen)
# headless visual proof (adapt the spike's --screenshot flow to the real path):
FPGA_SIM_SINGLE_WINDOW=1 SDL_VIDEODRIVER=dummy ...  # PR2; default from PR3
```

Reference throughput on Rick's machine (AMD Ryzen AI 9 HX 370, ±10%):
GHDL/Arty/blinky ≈ 0.0039–0.0041×; GHDL/DE10-Lite/counter_7seg ≈ 0.0065×;
NVC/Arty/blinky ≈ 0.024–0.027×. A regression BELOW the old baselines
(0.0034 / 0.0051 / 0.0060) is a stop-and-investigate.

Agent sessions cannot do interactive window checks — use dummy-driver
screenshots for evidence and flag interactive items for Rick explicitly.

## 5. Known traps (learned during the spike — read before coding)

1. `multiprocessing.connection.Listener.address` is typed `str` in
   typeshed; AF_INET actually yields a tuple → keep the `cast` in
   `sim_link.env_vars()`.
2. Ruff docstring rules (D1xx) apply to every new public def/class,
   including in `scripts/`; `mypy .` covers tests and `scripts/`.
3. The child's `time.sleep` pacing replaces `tick(60)` — when paused,
   still step 1 ns + sleep ~16 ms so control messages keep draining
   (today's semantics).
4. `int(dut.led.value)` raises on X/Z at t=0 — keep the try/except guards
   and re-send last-known values.
5. Don't import `SPEED_DEFAULT`/anything from `fpga_sim.ui` in the child
   (pygame transitively). CI has no way to catch this except the slow e2e
   — add a lint-style unit test asserting `sim_testbench`'s import list
   stays pygame-free (extend `test_sim_testbench_lint.py`).
6. pre-commit rumdl will rewrite bare code fences in your docs edits and
   abort the commit — language-tag them up front.
7. `FPGABoard._handle_events` owns VIDEORESIZE + sets `_help_requested`;
   the screen must re-sync panel height offset after resize (see the
   `_show_panel`/`set_height_offset` dance in today's `sim_testbench.py` —
   move it verbatim).
8. GHDL and NVC exit codes are unreliable on clean stops (the reason the
   intent file existed) — never infer failure from returncode alone; use
   `bye`-received / stop-requested state, and treat nonzero-rc-without-bye
   as the crash path.
9. PR numbers share the issue sequence — never predict PR numbers in docs;
   fill them in after creation.

## 6. Out of scope for U34

- Start-on-last-board flow rework (Rick's "first window is the DE10 /
  last-used board" idea) — becomes trivial after U34; propose as its own
  small card once this lands.
- Live board hot-swap during simulation, multi-child A/B runs.
- C VPI shim child (measured unnecessary), NVC cycle-cap retune,
  `analyze_metrics.py` rework (P19), `capture_frames.py` modernization.
