# U25 — GHDL performance profile report

**Date:** 2026-07-23 · **Card:** U25 "Profile GHDL GPI overhead vs. VHDL eval to find the next
bottleneck" · **Machine:** Ryzen AI 9 HX 370, Fedora, GHDL 7.0.0-dev @ `e8653994f`, NVC 1.22-devel,
LLVM 21.1.8 · **Harness:** `uv run fpga-sim --benchmark 10 --no-ui --sim <path> --vhdl <file>
--board <class>` (headless child only; same commit for every GHDL backend, so each A/B isolates
exactly one variable).

## Verdict — the top three bottlenecks, with data

### 1. Build configuration: GHDL's `configure` default is a *debug* build (dominant — now fixed)

All local GHDL backends had been built with `enable_checks=true` — **GHDL's configure default**
(nothing passed `--disable-checks`). Per the generated Makefile that means: compiler + GRT runtime
compiled `-g` with **no `-O`**, **Ada assertions on** (`-gnata`) in the scheduler/signal hot path,
and — for the AOT (llvm) backend — the ieee/`numeric_std` library objects codegen'd **unoptimized**
(`LIB_CFLAGS` empty). NVC, by contrast, builds `-g -O2` by default. Every earlier cross-simulator
number was therefore *optimized NVC vs. debug GHDL*.

Rebuilding with `--disable-checks` (same commit, sibling build dirs, nothing else changed):

| design / board | mcode debug → release | llvm AOT debug → release | NVC (release) |
|---|---|---|---|
| `blinky` / Arty A7-35 | 0.00411x → 0.00448x (**+9%**) | 0.01203x → 0.01769x (**+47%**) | 0.02722x |
| `counter_7seg` / DE10-Lite | 0.00145x → 0.00147x (+2%) | 0.00252x → 0.00428x (**+70%**) | 0.02751x |
| `mx65` CPU / DE10-Lite | 0.00133x → 0.00138x (+4%) | 0.00224x → 0.00314x (**+40%**) | 0.00484x |
| `rgb_rainbow` / Arty A7-100 | 0.00056x → 0.00057x (+2%) | 0.00084x → 0.00133x (**+58%**) | 0.01147x |

(x = fraction of real time simulated. `counter_7seg` rows are duty-engine-era (U9 Full mode
default); they are consistent with the pre-U9 record once the known duty cost is factored in.)

- **LLVM AOT was leaving 40–70% on the table** to the build config alone. Honest AOT-over-mcode is
  **2.3–3.9×** (previously believed 1.5–2.8×).
- **mcode gains only +2–9%**: it JIT-compiles design *and* library code itself, so the Ada build
  flags touch only GRT — which is not its bottleneck (see §3).
- **NVC remains fastest everywhere** — but its margin over the best GHDL backend on conventional
  workloads is **~1.5×** (previously 2.2–2.7×), and the `rgb_rainbow` outlier shrinks from 13.3× to
  **8.6×**.

**Action taken:** all three local backends (mcode, llvm, llvm-jit) rebuilt `--disable-checks` at
their original prefixes (checks-enabled build dirs kept as debug fallbacks). CI is unaffected — it
pins upstream release binaries.

### 2. Per-operation standard-library call cost (architectural — explains the residual NVC gap)

gdb stack-sampling of the AOT `rgb_rainbow` run (recipe below), before and after the rebuild:

- **Debug build (2026-07-22):** leaves in `ieee__numeric_std` operator wrappers — `OPPl` ("+"),
  `OPLt` ("<"), `add_unsigned`, `resize` — with per-op `to_01` metavalue scrubbing prominent.
- **Release build (2026-07-23):** *same shape, uniformly faster.* `led_proc` appears in 15/15
  sampled stacks; leaves are `add_unsigned` (4/16), `__memmove_avx512…`/`__ghdl_memcpy` (3/16 —
  array-temporary copies for operator arguments/results), scattered `numeric_std`/`std_logic_1164`
  ops, and only ~3 GRT frames. `to_01`'s share drops visibly at `-O1` but the **call-per-operator +
  array-temp structure is the cost**, and no build flag removes it.

This is why NVC keeps an 8.6× edge on `rgb_rainbow`-class workloads (a `numeric_std` op on nearly
every clock wake): NVC specializes/lowers standard-library operators into the compiled code and
uses a leaner signal model, where GHDL emits calls into generic library routines with materialized
array temporaries. Confirmed second-order null results: design-level `-O2` at `-a`/`-e` ≈ noise
(the libraries are compiled at GHDL build time, out of its reach) and `FPGA_SIM_DUTY=off` ≈ ±5%
(the U9 integrator is innocent). A GHDL-side fix would be upstream operator specialization —
out of scope here. Design-side mitigation is real, though: hoist invariant arithmetic out of
per-clock processes (the U9a lesson — hoisting one `to_unsigned(…) * NS_PER_SEC` behind a TIME
compare took `counter_7seg`'s duty overhead from +923% to +554%).

### 3. Wake structure × per-wake cost — and GPI/VPI is *not* a bottleneck

The card's original question — "GPI overhead vs. VHDL eval" — has a clear answer: **VHDL eval
dominates; the cocotb/VPI boundary is negligible.** The child spends ~99% of its loop inside the
simulator step, the profile shows GRT scheduler frames as a minor slice, and the VPI callback
surface is one `Timer` per sim step (the U34 design), not per signal. What actually predicts cost
is the product *(wakes per simulated second) × (library work per wake)*:

- `blinky` wakes rarely → every backend looks fine.
- `counter_7seg`'s digit-0 seg blur = **one wake per clock** (150,002 wakes / 150,000 clocks,
  measured in U9) → the accepted duty-engine cost multiplier lives here too.
- `rgb_rainbow` = one wake per clock **plus** heavy per-wake `numeric_std` arithmetic → the
  worst case on GHDL, and the widest NVC margin.

Reducing either factor helps any backend: fewer wakes (design-side: derive PWM from mid-tap
counters, compute on carry, not every clock) or cheaper wakes (§2). Host-side draw cost is a
separate, smaller axis (U23 dirty-flag redraw remains open).

## Reproduction recipes

- **Benchmark:** `uv run fpga-sim --benchmark 10 --no-ui --sim <path-or-name> --vhdl hdl/<d>.vhd
  --board <ClassName>`; parse the `Sim rate : …x real-time` line. Boards used here:
  `ArtyA7_35Platform`, `DE10LitePlatform`, `ArtyA7_100Platform`.
- **Stack sampling:** start the benchmark in the background, `pgrep -x sim_wrapper` (**not**
  `pgrep -f`, which matches the wrapper shell), then loop `gdb -p <pid> -batch -ex "bt 6"` with a
  sub-second sleep and tally `#0` (leaf) and all-frame symbol counts. Library/design symbols are
  visible without DWARF (linker symbols).
- **Release rebuild:** fresh sibling build dir per backend inside the GHDL clone, `../configure
  --disable-checks --prefix=<own prefix> [--with-llvm-config | --with-llvm-jit]`, `make`,
  `make install`. Never reconfigure an existing build dir to a different backend, and never share
  a prefix between backends (std/ieee libraries are backend-specific).

## Follow-ups (assessed, not planned)

- `-O2`/`-O3` library codegen (beyond `--disable-checks`' `-O1`): possible via `LIB_CFLAGS`;
  expected minor — §2 shows the cost is call/temp *structure*, not codegen quality. Revisit only
  if a library-bound design becomes a real user pain point.
- `ghdl-gcc` backend: same library-call model → expected llvm-class on library-bound designs;
  heavy build, assessed not worth it (2026-07-22).
- U23 (dirty-flag redraw) and P1 (NVC elaborate-once) remain the open roadmap perf items.
