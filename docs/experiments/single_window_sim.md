# Experiment: single-window simulation (no launcher→sim window flip)

**Status: spike VALIDATED — recommend adoption.**
Branch `spike/single-window-sim`, 2026-07-16.

## The problem

Starting a simulation is jarring for newcomers: the launcher window
disappears (`pygame.quit()` in `ScreenController.on_simulate()`), then a new
window appears a few seconds later. Users ask "What happened? Did I do
something wrong?" The same flip happens in reverse when the simulation ends,
and on every [Reload VHDL].

## Why the flip exists today

Not for rendering performance. cocotb must run *inside* the GHDL/NVC process
(that is what VPI/VHPI is), and the simulation UI was built inside the cocotb
testbench because it was the simplest thing that worked: zero IPC, direct
`dut.led.value` reads next to the `pygame` draw calls. The window flip is a
side effect of the UI living in a different process during simulation.

The measured cost structure says the in-process UI buys nothing: in the
baseline benchmark, GHDL stepping is ~98.5% of frame time and drawing ~1.3%.
Worse, the UI actively *costs* throughput, because every sim step is serially
followed by event-pump + draw + `tick(60)` — and the `tick(60)` frame-lock
caps the loop at 60 steps/s, which NVC (much faster per step) slams into.

## Architecture tested

The launcher process keeps its one pygame window forever. The GHDL/NVC +
cocotb child runs **headless** and shuttles signal state over a socket:

```text
launcher process (owns THE window)          GHDL/NVC process (headless)
┌─────────────────────────────┐             ┌────────────────────────────┐
│ selector → preview → picker │             │ cocotb sim_testbench_bridge│
│        → SimulationScreen   │  sim_link   │  loop:                     │
│  FPGABoard + SimPanel render│◄────────────│   await Timer(step)        │
│  60 fps, always responsive  │  "state"    │   read led/seg             │
│                             │────────────►│   apply sw/btn/speed/clk   │
│  clicks → "input"/"speed"…  │  "input"…   │   throttled send, pace     │
└─────────────────────────────┘             └────────────────────────────┘
```

- `src/fpga_sim/sim_link.py` — `multiprocessing.connection` over 127.0.0.1
  TCP (works on Linux/Windows/macOS), random per-run HMAC authkey, ephemeral
  port passed to the child via env vars. Messages are small tuples:
  `state` (led/seg ints + counters) child→host at ≤250/s;
  `input`/`speed`/`clk`/`pause`/`stop` host→child.
- `sim/sim_testbench_bridge.py` — the headless testbench: same step math as
  `sim_testbench.py` (`_REAL_STEP_NS`, `_MAX_CYCLES_PER_STEP` cap), pacing by
  `time.sleep` instead of `tick(60)`, no pygame import anywhere in its chain.
- `scripts/spike_single_window.py` — the host: full launcher pipeline
  (contract check → analyze), then ONE window running `FPGABoard`, child
  spawned with the link env; "Starting GHDL…" overlay while waiting — the
  board preview simply comes alive when the child connects.

Board-native runs (U21/U31/U32) need nothing special: the native wrapper
already adapts to the same `clk/sw/btn/led/seg` boundary on `sim_wrapper`,
which is all the bridge reads.

## Results (2026-07-16)

Machine: AMD Ryzen AI 9 HX 370, Fedora (kernel 7.1.3-100.fc43), Python
3.13.12, pygame-ce 2.6.1 (SDL 2.28.4), GHDL 7.0.0-dev (6.0.0.r205), nvc
1.22-devel (1.21.0.r94). Headless (`SDL_VIDEODRIVER=dummy`), 10 s runs
(6 s where noted). Baseline = current `--benchmark` (UI inside the sim
process); bridge = this spike, child free-running. Run-to-run variance ≈ ±3%.

### Throughput (sim rate, × real-time)

| Config | Baseline | Bridge | Δ |
|---|---|---|---|
| GHDL · Arty A7-35 · blinky (n=3) | 0.003479 / 0.003448 / 0.003392 (mean **0.00344**) | 0.003907 / 0.004086 / 0.003969 (mean **0.00399**) | **+16%** |
| GHDL · DE10-Lite · counter_7seg (6-digit) | **0.00515** | **0.00650** | **+26%** |
| NVC · Arty A7-35 · blinky (6 s) | **0.00597** | **0.02573** | **×4.3** |

- The GHDL gain is the serial per-step UI work (event pump + draw + tick)
  removed from the sim loop; bigger for the 7-seg board because its draw is
  heavier (baseline UI fps had sunk to 27).
- The NVC number is the headline: NVC steps are fast enough that the current
  loop's `tick(60)` frame-lock is the binding constraint (baseline sits at
  exactly ~60 steps/s × 95,960 ns = 0.0058×). Untethered from the display,
  NVC runs ~268 steps/s. **The current architecture throttles NVC ~4×.**

### UI smoothness

| | Baseline | Bridge |
|---|---|---|
| UI frame rate during sim | 27–37 fps (locked to GHDL step time) | **62 fps** (all configs) |

Sliders, hovers, and button animations currently degrade with sim load; in
the bridge they never do. A stalled/blocked host (e.g. Windows window drag)
no longer stalls the simulator, and a busy simulator can never freeze the UI.

### Input round-trip latency (host sends input → child applies → echo received)

| Config | n | avg | p50 | p95 | max |
|---|---|---|---|---|---|
| GHDL free-run (~24 ms steps) | 13 | 19.6 ms | 15.9 | 31.9 | 32.6 |
| GHDL paced, speed 0.001 | 18 | 15.9 ms | 15.8 | 16.5 | 16.8 |
| NVC free-run (~3.7 ms steps) | 13 | 15.9 ms | 16.0 | 16.4 | 16.5 |

Bounded by the host's 60 fps send cadence plus at most one sim step — same
order as today's once-per-UI-frame event handling at 27–37 fps (≈27–37 ms
worst case). No regression; NVC/paced cases are strictly better.

### Control fidelity

- Pacing: paced mode at speed 0.001 measured 0.0009949× (−0.5%) — the speed
  slider semantic is preserved by `time.sleep` pacing in the child.
- Timer batching probe (`--step-mult 10`, GHDL): 0.00412× vs 0.00399×, only
  **+3%** — per-`Timer` GPI overhead is already small at the standard 9,596
  cycle cap. (Data point for roadmap U24: little headroom there.)

### Proof screenshot

`single_window_live.png` (this directory): the **host** window — which never
closed — rendering a live 6-digit 7-seg counter and LED pattern streamed from
the headless GHDL child, status line `sim 0.006378x real-time`.

## What the full implementation touches (knock-on inventory)

Mostly *code motion*, not invention — the sim-screen UI already speaks
`FPGABoard`/`SimPanel` APIs and moves from the child to a launcher screen:

1. **`sim/sim_testbench.py`** → becomes the headless bridge (spike's
   `sim_testbench_bridge.py` grown up): drop ~450 lines of pygame/overlay
   code; keep step math, pacing, benchmark accounting.
2. **`controller.py`** — `on_simulate()` no longer quits pygame; new
   `ui/simulation_screen.py` hosts FPGABoard + SimPanel + toolbar + overlays
   (moved from sim_testbench, largely intact) and owns the child handle.
   `_restore_window()` and the reload window-teardown dance are deleted;
   [Reload VHDL] becomes: stop child → spinner in place → relaunch child.
3. **`sim_bridge.py`** — split `launch_simulation()` into prepare (env, cmd,
   work dir) + a non-blocking `SimChild` handle (Popen + link + stderr
   capture + stop/wait). The whole `SimExit`/exit-intent-file side channel
   dies — toolbar clicks are now direct in-process calls. Env surface to the
   child shrinks (theme/speed/native-badge/exit-intent vars all become
   parent-side; `FPGA_SIM_BOARD_JSON` + link vars remain).
4. **Session/stats/logging** — the child stops writing the session file
   (removes a cross-process write race); `sim_session_log` written by the
   parent from `state`/`bye` stats; SimPanel gets a set-remote-stats path
   (child reports `timer_pct`, steps, sim_ns).
5. **Benchmark mode** — `--benchmark` spawns the free-running child and
   reports from `bye` stats (numbers shown above prove parity of meaning).
6. **Tests** — sim/test_*.py design tests untouched (no pygame there);
   integration tests that exercise sim_testbench's UI loop move to the
   SimulationScreen; new cheap unit tests for `sim_link` (loopback) and the
   message protocol; the headless-screenshot recipe captures from the parent.
7. **Docs** — architecture.md two-phase section, user_guide screens/controls
   (behavior identical, wording changes), CLAUDE.md data flow.
8. **Calibration review** — visible-rate assumptions (`COUNTER_BITS` floor
   17) were tuned at GHDL ~0.0036×; NVC now reaching ~0.026× makes low
   counter bits blink ~4× faster than before. Verify defaults still look
   right on NVC; the cycle cap itself can now be retuned per-backend since UI
   responsiveness no longer depends on it (only input latency does).

Windows notes: `multiprocessing.connection` TCP + authkey works there; the
child no longer initializes SDL/pygame inside GHDL at all, which *removes* a
class of Windows DLL/window quirks. The cocotb PYTHONHOME/PATH plumbing is
unchanged. macOS (if ever): pygame-on-main-thread becomes trivially satisfied.

## New UX unlocked (beyond removing the flip)

- Preview → simulate → stop → tweak → resimulate, all in one window; the
  "which screen am I on" model collapses to one continuous surface.
- Rick's proposed flow (start on last/default board preview, e.g.
  `boards/custom/de10_standard.json`, with board/file pickers reachable from
  it) is pure screen-flow work once the window persists.
- Sim-crash errors become in-window dialogs with captured child stderr — no
  vanish-then-reappear-with-terminal-text.
- Future: live board hot-swap (kill child, keep window), side-by-side stats,
  A/B same design on two boards (two children, one window).

## Risks / limitations

- **Backpressure**: `Connection.send` blocks if the host stops draining
  (~64 KB buffer ≈ several seconds at the throttled send rate). Worst case
  the child pauses until the host drains — equivalent to today, where the
  sim and UI block together. Mitigation if ever needed: drop-oldest send.
- **Child crash mid-run**: host sees `eof` and shows an error dialog; needs
  stderr capture in the real implementation (spike inherits the terminal).
- **Startup failure before connect**: host watchdog + returncode check
  (spike has a 15 s watchdog).
- **Security**: listener binds 127.0.0.1 with a random per-run HMAC authkey
  passed via the child's environment; single accepted connection.
- **Print streams**: child cocotb banner still goes to the terminal;
  SW/BTN toggle prints move to the parent with the rest of the UI.

## Alternatives considered and rejected

- **Reparent/reuse the OS window** (`SDL_CreateWindowFrom`, `SDL_WINDOWID`):
  X11-era hacks; no Wayland story; fragile on Windows. Rejected.
- **Cosmetic softening** (same position/size/title, splash overlay): Wayland
  doesn't let apps position windows; still two windows and a flicker; doesn't
  answer "did I do something wrong?". Not worth it given the spike works.
- **In-process simulation** (libghdl / linking the design): unsupported for
  interactive VPI-style use; NVC has no embedding API; loading per-design
  native code into the UI process is a stability/security downgrade. Rejected.
- **One-way VCD streaming**: no input path; rejected.
- **C VPI shim instead of cocotb in the child**: the +3% step-mult probe says
  cocotb/GPI overhead is small; not worth a compiled component. Icebox.

## Recommendation

Adopt, as a 3-phase arc (mirrors the U21 Part-B shape):

- **A** — land `sim_link` + headless testbench + `SimulationScreen` behind an
  opt-in flag (`FPGA_SIM_SINGLE_WINDOW=1`), both paths tested.
- **B** — flip the default; port toolbar/help/stats/session-log/reload flows;
  benchmark parity check; delete the exit-intent channel.
- **C** — remove the legacy in-child UI path + env plumbing; retune the NVC
  cycle cap; docs.

## Reproduce

```bash
git checkout spike/single-window-sim
# interactive demo (the one-window experience):
uv run python scripts/spike_single_window.py --board DE10StandardPlatform \
    --vhdl hdl/counter_7seg.vhd
# benchmarks:
uv run fpga-sim --benchmark 10 --board ArtyA7_35Platform --vhdl hdl/blinky.vhd
uv run python scripts/spike_single_window.py --board ArtyA7_35Platform \
    --vhdl hdl/blinky.vhd --headless 10
# input latency / paced / NVC / batching variants:
#   --headless 8 --latency          --paced --speed 0.001
#   --sim nvc                       --step-mult 10
```
