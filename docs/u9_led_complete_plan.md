# LED-complete arc plan — U9 · U36 · U37 · U38

**Status:** planned 2026-07-18 (planning session on `main` @ `98798fe`, v0.16.0); not started.
**Executor:** a future Claude session ("you"). This document is written to be executed without
the planning conversation. Every repo claim below was verified by reading the code at the
commit above; re-verify anchors cheaply before building on them (files move).
**Owner:** Rick. Decisions in "Locked decisions" were adopted in the planning conversation;
if implementation reveals a reason to deviate, stop and ask Rick rather than improvising.

---

## 0. Executive summary

Make every board **LED-complete**: for every board in `boards/` (and any future source),
every LED-class output is (1) represented in data with channel-accurate width, bank
identity, polarity, and — where known, *cited* — color; (2) fully drivable from
generic-contract VHDL and, where conventions exist, from board-native VHDL under its real
port names; (3) rendered with **measured duty-cycle → brightness** and true RGB color
mixing; (4) covered by tests and at least one demo design.

Four roadmap cards, two releases:

| Card | Contents | PRs | Release |
|---|---|---|---|
| **U9** | Duty engine (wrapper-side exact PWM measurement) + brightness rendering, LED **and** 7-seg | 2 | v0.17.0 "brightness" |
| **U36** | LED banks + colors data model, parser heuristics, citable color registry wave, bank-clustered rendering | 2 | v0.17.0 |
| **U37** | RGB LEDs as 3 boundary channels end-to-end, `NUM_RGB_LEDS` generic, RGB puck widget, `rgb_rainbow.vhd` | 2 | v0.18.0 "RGB" |
| **U38** | Board-native RGB port names (Digilent XDC), debug tri-bar view, docs closeout | 2 | v0.18.0 |

The architectural centerpiece: **PWM is measured, never inferred.** Static VHDL analysis is
impossible in principle (the embedded-core designs compute LED duty from *firmware bytes*
at runtime; generics are overridden at launch; obfuscation defeats pattern-matching).
The simulator is already executing the design, so measurement happens **inside the
generated `sim_wrapper`** as an event-driven VHDL time integrator — exact, native-speed,
zero Python callbacks, identical for the generic and native paths, and it covers `seg`
for free.

## 0a. Locked decisions (adopted by Rick, 2026-07-18)

1. **Measurement = VHDL integrator in the wrapper** (not static analysis, not sampling,
   not Python `Edge` callbacks — see §2 rationale).
2. **RGB boundary model = "B3"**: RGB channels live in the existing `led` vector
   (mono block low, `(r,g,b)` triples high), plus an *optional* `NUM_RGB_LEDS : natural := 0`
   generic. No new port. `NUM_LEDS` becomes **channel count** (Arty A7: 8 → 16).
   Rejected: a separate `rgb` port (goes dark for every existing design on RGB-only boards
   like Cora Z7 / ECPIX-5 / Fomu — a regression).
3. **Two releases**: v0.17.0 = U9+U36, v0.18.0 = U37+U38. Each card independently shippable.
4. **Unknown LED color ⇒ theme fallback** (`THEME.led_on`, exactly today's look). Colors
   change only where we have real, cited data. No guessed defaults across 278 boards.
5. **7-seg brightness ships with U9** (same duty machinery; segments are LEDs).
6. Rendering default = realistic (color + brightness); **global debug toggle** swaps RGB
   pucks for per-channel bars (U38). Tooltips always show exact duty %.

## 0b. Workflow guardrails (non-negotiable, from CLAUDE.md + project memory)

- Feature branch per PR off fresh `main`; **never commit to main**. `git fetch --prune` first.
- Before every commit: `uv run ruff check .` && `uv run ruff format --check .` &&
  `uv run mypy .` (strict, whole repo incl. tests) && `uv run pytest`.
- PRs that touch `sim_wrapper` / `sim_testbench.py` / `sim_bridge.py`: also run the slow
  suite under **GHDL-mcode and NVC at minimum** (all three GHDL backends if cheap — they
  are installed; PATH or `--sim ghdl-{mcode,llvm,jit}` selects), and run the
  **benchmark gate** (§2.8).
- UI PRs: attach screenshots (recipe in memory `reference_headless_sim_testing.md`).
- Never hand-edit generated board JSONs (`boards/{amaranth-boards,litex-boards,digilent-xdc}/`)
  — change the parsers/registry and re-run the sync scripts (they fetch upstream; network
  needed). `boards/custom/` is hand-maintained.
- Docs + tests ride in the same PR as the feature. US spelling. VHDL files plain ASCII.
- Hybrid backlog model: create milestone + issues for the **active** card only, at its start.
  Never predict PR numbers in docs/memory.
- Roadmap edits follow the completion checklist: card text, sprint table, status paragraph,
  file-map lines, "independently shippable" list — all interconnected sections.
- End PR bodies / commits per the repo's existing conventions (see recent merged PRs).

---

## 1. Verified current state (evidence map)

All line numbers at `main` @ `98798fe`.

| Fact | Evidence |
|---|---|
| LEDs render binary, one global color; glow halo hardcoded red | `src/fpga_sim/ui/components.py:129-157` (`LED.draw`, `THEME.led_on`, glow `(255,40,40,50)`); `ui/theme.py:64` |
| Child samples `dut.led` instantaneously once per `await Timer(step)`; step capped at 9,596 cycles ≈ 96 µs sim @100 MHz | `sim/sim_testbench.py:207-237` (`_MAX_CYCLES_PER_STEP` line 62) |
| State sends throttled: forced on input, else ≥4 ms wall on change, 50 ms heartbeat | `sim_testbench.py:66-69, 263-287` |
| `hdl/blinky_pwm.vhd` exists: 8-bit PWM @ 390 kHz (256 clks), breath period 2^(CB+8) clks — aliased into garbage today; U9 card says "looks broken" | `hdl/blinky_pwm.vhd`; `docs/improvement_roadmap.md:80-83` |
| Every run goes through a wrapper **we generate** — generic template + native renderer; clock generated in VHDL for perf ("cutting simulator step time ~10x") | `sim/sim_wrapper_template.vhd`; `sim_bridge.py:1519` (`_render_native_wrapper`), `:1667` (`_generate_wrapper`, `.format()` splice) |
| Both backends analyze/elaborate VHDL-2008 | `sim_bridge.py:162,171,182` (`--std=08`), `:234,242,261` (`--std=2008`) |
| 67 boards have `rgb_led` components (one component, **3 pins**) from all three parsers; each counts as **one** `led` bit today → 2 of 3 channels unreachable | census §7; parsers: `scripts/digilent_parser.py:342-371`, `scripts/litex_parser.py:304-305`, `scripts/amaranth_parser.py:193-210` |
| 21 boards have multi-name mono banks (e.g. `custom/de2_115.json`: 18×`led` + 9×`led_g`; Black Ice `led_b/g/o/r` = 4 *discrete* colors; UPduino `led_r/g/b` = one RGB in disguise) | census §7 |
| `NUM_LEDS = max(1, len(board.leds))`; `COUNTER_BITS = max(17, 4*num_segs)` | `src/fpga_sim/controller.py:75-99` (`build_generics`) |
| Contract checker: required generics tuple, seg⇄NUM_SEGS pairing rules, unknown-generic-with-default accepted, fixed-width port check | `sim_bridge.py:626` (`_REQUIRED_GENERICS`), `:795-905` |
| Native wrapper: intermediate `*_uut` signals, polarity inversion, LED zero-extend `resize(unsigned(led_uut), NUM_LEDS)`, generic defaults mirror `build_generics` | `sim_bridge.py:1519-1666` |
| Host applies state: `led` int → `set_led(i, bool)`; leds laid out as one section | `ui/simulation_screen.py:303-308`; `ui/board_display.py:358-485` (sections), `:248-251` (`set_led`), `:661-663` (section title blit) |
| `port_conventions` already has a secondary-bank precedent (`leds_green`, DE2-115 LEDG) and an A1 per-sub-key merge protecting `port_conventions`/`peripherals` (only!) across re-syncs | `boards/schema/board.schema.json:256-259`; `scripts/sync_common.py:129-198` |
| Citable-registry precedent (U33): `docs/port_convention_sources/*.toml` + `scripts/sync_port_conventions.py` + `scripts/port_convention_parsers/` | those paths |
| Perf baselines (v0.15.0/v0.16.0): GHDL-mcode ~0.004×, NVC ~0.027×, host ~62 fps; `--benchmark N [--no-ui]` | `memory/project_sim_performance.md`; roadmap "verification recipes" |

**Timing consequences** (why the design below is shaped as it is): at mcode speed a state
send covers ~96–200 µs of sim time. blinky_pwm's 2.56 µs PWM period fits ~40-75 periods
per send → steady duty. A 1 kHz-sim PWM (1 ms period) spans many sends → renders as
slow-motion blinking, which is *truthful* sub-real-time behavior; a faster backend or
speed setting fuses it. No thresholds or design-dependent guesses anywhere.

---

## 2. Architecture: the duty engine (U9 core)

### 2.1 Why not the alternatives (do not relitigate)

- **Static VHDL analysis**: undecidable (soft-CPU firmware decides duty at runtime),
  defeated by generics/obfuscation, duplicates the simulator. Dead end in principle.
- **Sampling (the old U9 sketch "N sub-steps per frame")**: aliasing is fundamental —
  blinky_pwm strobes at any fixed sampling rate; more sub-steps multiply the Python↔GPI
  wakeups that the U34/perf work spent months removing (see the wrapper template's own
  header comment about moving the clock into VHDL).
- **Python cocotb `Edge` callbacks**: exact but blinky_pwm generates ~780k vector
  events/sim-s; at NVC's 0.027× that's ~21k Python wakeups/wall-s ≈ tens of % slowdown
  on the fastest backend, on the flagship demo. Disqualified.
- **Clocked VHDL counters** (`if led(i)='1' then cnt := cnt+1` every clk edge): correct
  but pays every cycle on every design, including the 90% whose LEDs are near-static.
  The event-driven integrator below costs ~nothing when LEDs are static and ~ns per event
  when they are not.

### 2.2 The integrator (spliced into BOTH wrapper variants)

Add to the generic template (`sim/sim_wrapper_template.vhd`) and the native renderer
(`_render_native_wrapper`) an identical block. Prerequisites in the generic template:
add `use ieee.numeric_std.all;`, and introduce an internal signal so the monitored value
is a plain signal in both variants (2008 allows reading out-ports, but the internal
signal keeps the two paths uniform and sidesteps simulator quirks):

- generic path: uut port-maps `led => led_int`; concurrent `led <= led_int;`
- native path: the existing `led <= resize(...)` assignment becomes
  `led_int <= std_logic_vector(resize(...)); led <= led_int;`
- same treatment for `seg` (`seg_int`) when the seg port is present.

New **output ports** on `sim_wrapper` (ports, not internal signals — guaranteed visible
to cocotb on every backend, no VPI-hierarchy risk):

```vhdl
led_acc : out std_logic_vector(48 * NUM_LEDS - 1 downto 0);  -- per-channel on-time, ns
led_tch : out std_logic_vector(48 * NUM_LEDS - 1 downto 0);  -- per-channel last-change time, ns
-- and, only when the seg port exists:
seg_acc : out std_logic_vector(48 * (8 * NUM_SEGS) - 1 downto 0);
seg_tch : out std_logic_vector(48 * (8 * NUM_SEGS) - 1 downto 0);
```

One process per monitored vector, sensitive to **the vector only** (not the clock).
Normative sketch (validate in phase 0; adjust syntax, keep the semantics):

```vhdl
type u48_array is array (natural range <>) of unsigned(47 downto 0);

duty_led : process (led_int)
  constant NS_PER_SEC : unsigned(29 downto 0) := to_unsigned(1_000_000_000, 30);
  variable last_v : std_logic_vector(NUM_LEDS - 1 downto 0) := (others => '0');
  variable last_t : time := 0 fs;
  variable acc    : u48_array(0 to NUM_LEDS - 1) := (others => (others => '0'));
  variable secs, rem_ns : natural;
  variable d_ns, now_ns : unsigned(47 downto 0);
begin
  -- CRITICAL: VHDL INTEGER is 32-bit. `delta / 1 ns` overflows past 2.147 s of
  -- sim time (a static LED across a long benchmark WILL hit this). Decompose:
  secs   := (now - last_t) / 1 sec;                       -- safe (< 2**31)
  rem_ns := ((now - last_t) - secs * 1 sec) / 1 ns;       -- < 1e9, safe
  d_ns   := resize(to_unsigned(secs, 31) * NS_PER_SEC, 48) + to_unsigned(rem_ns, 48);
  secs   := now / 1 sec;
  rem_ns := (now - secs * 1 sec) / 1 ns;
  now_ns := resize(to_unsigned(secs, 31) * NS_PER_SEC, 48) + to_unsigned(rem_ns, 48);
  for i in 0 to NUM_LEDS - 1 loop
    if to_x01(last_v(i)) = '1' then
      acc(i) := acc(i) + d_ns;              -- wraps mod 2**48; host uses modular deltas
    end if;
    if led_int(i) /= last_v(i) then
      led_tch((i + 1) * 48 - 1 downto i * 48) <= std_logic_vector(now_ns);
    end if;
    led_acc((i + 1) * 48 - 1 downto i * 48) <= std_logic_vector(acc(i));
  end loop;
  last_v := led_int;
  last_t := now;
end process;
```

Semantics: `acc(i)` = completed on-time in ns (metavalues count as off via `to_x01`);
`tch(i)` = sim-ns of the channel's last value change. Delta-cycle glitches integrate to
zero width. Sub-ns truncation ≤1 ns/event (≤0.1% duty error at worst-case event rates
— acceptable, documented). Processes execute once at t=0, initializing cleanly.

### 2.3 Child-side duty math (`sim/sim_testbench.py`)

Read `led_acc`/`led_tch` (and seg twins) **only when about to send** (4–50 ms cadence,
not every loop), in the same loop iteration as the existing `dut.led` read so bits and
accumulators are mutually coherent (no `await` between reads; an event exactly at the
boundary instant lands wholly in the next window). Guard reads with the same
`try/except` as the existing led read (X at t=0).

Per send, with `t1 = sim_elapsed_ns`, `t0 = sim-ns of previous send`:

```text
window = t1 - t0                       # 0 when paused → resend previous duties
raw_i  = (acc_i - prev_acc_i) mod 2**48
if bit_i == 1:                         # instantaneous bit from the existing read
    raw_i += t1 - max(tch_i, t0)       # in-progress on-interval correction
duty_i = min(1.0, raw_i / window)
```

The correction term is what makes free-running accumulators exact: a channel stuck ON
across the whole window has `raw = 0 + (t1 - t0)` → duty 1.0; stuck OFF → 0.0; a channel
currently ON mid-interval gets its partial interval added. Without it, stuck-ON channels
would read 0 — **write a test for exactly this case.**

State message gains (keep the existing `led`/`seg` ints untouched — tests and binary
consumers rely on them):

```text
"led_duty": [round(f, 4), ...],        # len == NUM_LEDS, 0.0-1.0
"seg_duty": [round(f, 4), ...] | None  # len == 8*NUM_SEGS
```

### 2.4 Host-side rendering (`ui/simulation_screen.py`, `ui/components.py`)

- **Wall-clock persistence-of-vision EMA** per channel in `SimulationScreen._apply_state`:
  `ema += (duty - ema) * (1 - exp(-dt_wall / TAU))`, `TAU = 0.1` s, first sample snaps.
  This is the *only* smoothing; duty itself is exact. Consequence (document it): PWM slow
  relative to sim rate renders as slow-motion blinking — truthful; faster backend/speed
  fuses it into steady light.
- `FPGABoard.set_led(index, state: bool)` grows a float sibling
  `set_led_level(index, level: float)`; the bool form delegates (`1.0/0.0`) so existing
  callers/tests keep working.
- `LED` widget: `state: bool` → `level: float`. Draw:
  `k = level ** (1 / 2.2)` (perceptual γ so 10% duty is clearly visible, as on real LEDs);
  `px = lerp(THEME.led_off, on_color, k)` per 8-bit channel; glow uses `on_color` with
  alpha scaled by `k` (replaces the hardcoded red halo). `on_color` = resolved LED color
  (U36) with **draw-time** `THEME.led_on` fallback — never captured at import
  (`memory/project_u6_theme_system_facts.md` trap).
- `SevenSeg`: `bits: int` → also per-segment levels; same γ-lerp `seg_off → seg_on`.
  Keep the `bits` API for binary callers.
- Tooltips (U3 machinery): LED hover shows `duty 73.2%`.
- `_write_gtkw` (sim_bridge): exclude `led_acc/led_tch/seg_acc/seg_tch` from the emitted
  signal list — accumulator noise would drown the waveform view.

### 2.5 Protocol/compat notes

`sim_link` host and child always ship together — no version negotiation needed. Keep
payload floats rounded (4 dp). `--benchmark` free-run paths are unaffected (sends already
throttled; duty math only runs at send time).

### 2.6 What U9 explicitly does NOT change

Board JSONs, schema, `NUM_LEDS` semantics, contract checker, parsers. U9 is renderer +
wrapper + child + demos + docs. It ships alone and already fixes "PWM designs look broken".

### 2.7 Demo + test work in U9

- **Retap `blinky_pwm.vhd`**: breath is 2^(CB+8) clks — at runtime CB=17 and mcode speed
  that's ~84 wall-seconds per breath. Retap the envelope (e.g. breath = 2^(CB+4) clks)
  so a full breath lands ≤ ~10 s wall on mcode at default speed, ~1-2 s on NVC. Keep the
  8-bit sawtooth in `counter(7 downto 0)` (2.56 µs period — deliberately fast-vs-window).
  Update the header comment's math. Acceptance: visible smooth breathing on mcode + NVC.
- **New `hdl/duty_probe.vhd`** (test fixture, generic contract): channels with exact
  static duties — e.g. led(0) stuck '0', led(1) stuck '1', led(2) 25% @ 256-clk period,
  led(3) 50% @ a *non-power-of-two* period (aliasing regression), plus sw-gating so a
  test can flip a channel mid-run. Not surfaced in the picker? It's in `hdl/` so it will
  appear — either name it clearly as a test fixture or park it under `sim/` next to the
  testbench and reference by path in tests (preferred: `sim/duty_probe.vhd`, mirroring
  `sim_wrapper_template.vhd` placement; the picker lists `hdl/`).
- **New `sim/test_duty.py`** (cocotb, both backends in CI like the other slow tests):
  elaborate the wrapper around `duty_probe`, read acc/tch ports directly, assert:
  window duty within ±1% for the static-duty channels; **stuck-ON and stuck-OFF exact**
  (the correction-term case); duty tracks a mid-run gate flip; accumulators survive a
  >2.2 s sim-time static gap (the INTEGER-overflow trap — run one long window);
  wrap-around arithmetic sanity (can be a host-side unit test with synthetic values).
- **Host unit tests** (`tests/`): EMA math, γ-lerp, `set_led_level` compat, `_apply_state`
  with `led_duty` payloads, gtkw exclusion. Update the theme value-preservation tests
  and any test touching `LED.state`/`set_led` signatures.

### 2.8 Benchmark gate (mandatory for U9 PR-1)

`uv run fpga-sim --benchmark 10 --no-ui` before/after on: blinky/Arty, counter_7seg/
DE10-Lite, mx65_walking/DE10-Lite × GHDL-mcode + NVC (llvm if cheap). Acceptance:
**≤3% regression on the three static-ish designs** (integrator idles between LED events).
Also measure blinky_pwm (informational — expect ≲5% mcode / ≲10% NVC from ~780k native
events/sim-s). If the gate fails, stop and bring numbers to Rick — do not ship a silent
perf regression. Record results in the PR description and update
`memory/project_sim_performance.md`.

---

## 3. U36 — LED banks + colors (data model)

### 3.1 Schema + loader

- `boards/schema/board.schema.json` `component` gains optional
  `"color"`: enum `red|green|blue|yellow|orange|amber|white` **or** `"#RRGGBB"` string.
- `ComponentInfo` gains `color: str = ""`; `to_json`/`from_json` round-trip it
  (emit only when set — keep JSON diffs minimal).
- `BoardDef.led_banks` derived property: group **consecutive same-`name` runs** of
  `leds[]` → `[(name, [components])]`. No new JSON section — `leds[]` stays the single
  source of truth; banks are a view.

### 3.2 Color population (three tiers, in precedence order)

1. **Name heuristics at sync time** (shared helper, e.g. `scripts/led_metadata.py`, used
   by all three parsers): `led_r/led_red→red`, `_g→green`, `_b→blue`, `_o→orange`, etc.
2. **Registry wave** (mirror the U33 pattern exactly: `docs/port_convention_sources/*.toml`
   - `scripts/sync_port_conventions.py` flow): per-board cited color entries for the
   popular boards. **Only commit rows you have verified against a fetched source
   (vendor manual/schematic). Do not invent citations.** Starter list to verify: DE2-115
   (LEDR red / LEDG green), DE10-Lite + DE1-SoC + DE0-CV (LEDR red), DE0 (LEDG green),
   Arty A7/S7 (LD4-7 green), Basys 3 / Nexys A7 (green), Cmod A7 (2 green),
   iCEBreaker (red + green), TinyFPGA BX, Fomu.
3. **No data → `color` unset → theme fallback** (visuals change nowhere we lack evidence).

The A1 merge (`sync_common.py:129-198`) protects only `port_conventions`/`peripherals`,
so colors on synced boards MUST flow through parsers/registry (sync-time), never
hand-edits. `boards/custom/*` may be hand-edited directly (add DE2-115 colors there).

### 3.3 Census + reclassification (phase task, do first in U36)

Re-run and extend the planning census (§7 script): classify every board's LED shapes;
flag (a) scalar-trio RGBs mislabeled as mono banks (UPduino/iCESugar/ice40-UP5K-B-EVN
`led_r/g/b` → parser emits one 3-pin `rgb_led`), (b) discrete multi-color banks that must
NOT merge (Black Ice has `led_o` — orange proves discreteness), (c) **serial impostors**:
any `rgb_led` without exactly 3 pins, or ws2812-named resources — these are protocol
peripherals, route to `peripherals` (P5), never analog RGB. Ambiguities → registry
overrides, decided with citations. Commit the census table into this doc (§7).

### 3.4 Renderer

- `board_display._layout()` (`:358-485`): split the single `("leds", ...)` section into
  per-bank clusters with labels — convention names when available (`LEDR`, `LEDG` from
  `port_conventions`), else the bank name uppercased. Mirror the existing section-title
  blit (`:661-663`). RGB components cluster separately (still drawn as today's single
  LEDs until U37).
- Per-LED `on_color` from `ComponentInfo.color` via a small module-level color map;
  off-state gets a faint tint of the bank color (colored epoxy look) — subtle, keep
  `THEME.led_off` dominant.
- `BoardDef.summary` shows banks: `"18+9 LEDs"` / `"4 LEDs + 4 RGB"` (adjust tests).
- Showcase screenshot: DE2-115 (red row + green row) in the PR.

### 3.5 Tests

Schema validation (new field), loader round-trip, `led_banks` grouping, parser heuristic
units (each parser: fixture → color), regen determinism (run sync scripts twice → no
diff), all-278-boards-load stays green, layout tests for bank clusters
(`tests/test_board_display_layout.py`).

---

## 4. U37 — RGB channels end-to-end

### 4.1 Data mapping (no JSON reordering)

Add to `BoardDef`:

```python
@property
def led_channels(self) -> list[tuple[ComponentInfo, str]]:
    """Boundary bit k -> (component, channel). Mono first (JSON order),
    then (r, g, b) per rgb_led component (JSON order). This IS the layout
    convention the VHDL contract documents."""
mono = [c for c in self.leds if not c.is_rgb]     # is_rgb: name == "rgb_led" and len(pins) == 3
rgb  = [c for c in self.leds if c.is_rgb]
return [(c, "mono") for c in mono] + [(c, ch) for c in rgb for ch in ("r", "g", "b")]

@property
def num_led_channels(self) -> int: ...            # len(led_channels)
@property
def num_rgb_leds(self) -> int: ...
```

Display order stays physical (`leds[]` as-is); only the *boundary* mapping is normalized
mono-first. No sync-side reordering, no JSON churn.

### 4.2 The audit (do this systematically — typed-refactor round-trip)

Every `len(*.leds)` / LED-count call site must choose **channels vs components**
deliberately. Known sites: `controller.build_generics` (`controller.py:88` →
`num_led_channels`), `sim_testbench.py:152` (num_leds → channels; `led_mask` follows),
`sim_bridge._board_port_widths` (`:762` region — fixed-width check → channels),
native-wrapper generic defaults (`sim_bridge.py:~1600` → channels),
`simulation_screen.py:306,509` (apply/print — via mapping), `board_display.py:189`
(widgets → per-component, NOT channels), `BoardDef.summary`. Grep exhaustively;
list the decision per site in the PR description.

### 4.3 Contract + checker + wrapper

- `NUM_RGB_LEDS : natural := 0` becomes a **known generic** (`sim_bridge.py:870`
  `known_generics`). When the design declares it, the simulator passes it
  (`build_generics` conditional injection — mirror the NUM_SEGS pattern documented in
  `build_generics`'s docstring); when not declared, not passed, design works as before
  (RGB channels are anonymous `led` bits).
- Checker additions: friendly error if declared as `positive` (must be `natural` —
  boards without RGB pass 0); fixed-width `led` check now validates channel count with
  a message that spells out the mono+3·RGB math.
- Generic wrapper template: new `{rgb_generic}` / `{rgb_generic_map}` placeholders
  (empty when the design lacks the generic) — same `.format()` splice as seg
  (`_generate_wrapper`, `sim_bridge.py:1690-1708`). **No new port.**
- Native wrapper: no change in U37 (native RGB names are U38).
- Layout convention documented (contract docs + `writing_designs.md`):
  `MONO = NUM_LEDS - 3*NUM_RGB_LEDS`; `led(MONO + 3*i + 0/1/2)` = site i r/g/b.

### 4.4 Renderer

- New `RGBLED(UIComponent)` widget in `components.py`: one puck, three levels;
  color = per-channel γ-encode of linear duties
  (`px_c = round(255 * ema_c ** (1/2.2))` — (1,1,1) → white wash, matching real RGB
  LEDs); off = dark neutral; white outline + glow like `LED`.
- `simulation_screen._apply_state` routes `led_duty[k]` through `led_channels` to
  either `LED.level` or an `RGBLED` channel.
- Tooltip: `R 73% · G 12% · B 0%`.

### 4.5 Demo + tests

- **`hdl/rgb_rainbow.vhd`** (generic contract, declares `NUM_RGB_LEDS`): three
  phase-offset triangle-wave duty envelopes (120° apart ≈ full-saturation hue sweep)
  feeding per-channel PWM compares; mode select on `sw`:
  0 = rainbow rotate (RGB sites phase-offset from each other), 1 = static hue from
  switches, 2 = RGB-cube scan (nested counters — every color at the chosen
  granularity), 3 = white breathe (validates white mix). Guard all site math with
  `for i in 0 to NUM_RGB_LEDS - 1 generate` (empty on non-RGB boards → behaves like a
  plain contract design; mono LEDs mirror switches or stay dark — author's choice,
  document it in the header). PWM period ≈ 2.56 µs (8-bit @100 MHz) so duty resolves
  crisply at every backend speed; rotation rate derived from COUNTER_BITS like the
  blinky_pwm retap.
- `sim/test_rgb.py`: assert per-channel duty relationships at sampled points
  (triangle phase offsets), mode switching, and that a non-RGB elaboration
  (`NUM_RGB_LEDS=0`) is clean.
- Regen: **no board JSON changes needed for U37 itself** (mapping is derived), but the
  U36 census reclassifications (scalar-trio → `rgb_led`) must have landed first so
  `is_rgb` sees them.
- Update `tests/test_controller.py` (generics), contract-checker tests
  (`tests/test_vhdl_validation*`), `tests/test_native_convention.py` if width
  expectations shift (native defaults now channel counts).

### 4.6 Migration note (CHANGELOG, breaking-ish)

On the 67 RGB boards, `NUM_LEDS` grows (Arty A7 8→16) and existing generic designs light
RGB channels as anonymous bits (a walking counter marches through colors). Honest and
intended; call it out in the v0.18.0 CHANGELOG.

### 4.7 Docs (verbatim draft, adopted by Rick)

`docs/writing_designs.md` gains subsection **"RGB LED boards"** after "7-segment boards"
(draft below — adjust only if implementation details force it), plus the U9 measurement
note in "Contract details" (ships with U9), plus `rgb_rainbow.vhd` in "Example designs".
CLAUDE.md's contract section gains the same generic + layout convention.

> ### RGB LED boards
>
> Boards with RGB LEDs (Arty A7/S7/Z7, Cmod A7/S7, Cora Z7, ECPIX-5, Fomu, …) expose
> each RGB LED as **three channels** of the `led` vector. Mono LEDs occupy the low bits
> exactly as on standard boards; RGB channels fill the top, three bits per LED in
> `(r, g, b)` order. To aim at them, declare one extra generic — the simulator sets it
> to the board's RGB LED count at launch:
>
> ```vhdl
> generic (
>   ...
>   NUM_LEDS     : positive := 4;   -- total channels: mono + 3 per RGB LED
>   NUM_RGB_LEDS : natural  := 0    -- RGB sites; keep the := 0 default
> );
> ```
>
> ```text
> MONO = NUM_LEDS - 3*NUM_RGB_LEDS          -- led[MONO-1:0] = mono LEDs
> led(MONO + 3*i + 0/1/2)                   -- RGB LED i: red / green / blue
> ```
>
> Drive a channel high for a primary, or PWM it for shades — the simulator measures
> duty per channel and mixes the rendered color, so three phase-offset PWM compares
> sweep the full palette (see `hdl/rgb_rainbow.vhd`). Iterate sites with
> `for i in 0 to NUM_RGB_LEDS - 1 generate`: on a board without RGB LEDs the loop
> generates nothing and your design behaves like a plain standard-contract design, so
> one file still fits every board. Never assume `NUM_RGB_LEDS > 0` in bare index
> arithmetic. A design that omits the generic keeps working everywhere — RGB channels
> are then just anonymous `led` bits, which light white-ish when driven together.

U9's "Contract details" note (ships in U9's PR-2):

> LEDs may be PWM-driven at any frequency — the simulator integrates each channel's
> duty cycle exactly (no sampling artifacts) and renders it as brightness. PWM that is
> slow relative to the simulation rate renders as slow-motion blinking, which is the
> truthful sub-real-time view; a faster backend or speed setting fuses it into steady
> brightness.

---

## 5. U38 — native RGB names + debug view + closeout

### 5.1 Native RGB (Digilent XDC only — locked non-goal: litex/amaranth native RGB

naming is ambiguous for flat VHDL ports; skip)

- `scripts/digilent_parser.py` already sees the real XDC port names (`led0_r`…): emit a
  canonical `port_conventions.<vendor>` RGB bank (schema: new `leds_rgb` mapping —
  scalar `names` per channel triple, mirror `leds_green`'s shape + `seg_port_mapping`'s
  `names` precedent; add to `board.schema.json`).
- Matcher (`sim_bridge.py` `_best_convention_attempt` region, `:1225-1272`): new
  optional role `leds_rgb`, matched like `leds_green` (only when the convention
  declares it; absence of the bank in the design = the usual U31 partial-interface
  rules).
- Native wrapper: pack matched scalar triples onto the boundary's RGB channel block
  (`(r,g,b)` order, polarity per convention `active_low` — Digilent RGB cathodes are
  active-HIGH on Arty; verify per board from the XDC/manual, don't assume).
- `hdl/native/` example for one board (e.g. `arty_rgb.vhd` with `led0_r`-style ports),
  not in the picker (same rule as the other native references).
  Tests: `tests/test_convention_matcher.py`, `tests/test_native_convention.py`,
  `tests/test_digilent_parser.py` fixtures.

### 5.2 Debug view

- Global toggle: settings-dialog checkbox + session persistence
  (`session_config.update_session` pattern) + an in-sim hotkey (pick one not taken —
  check `simulation_screen` key handling; `S` and theme keys are taken).
- Debug mode: `RGBLED` renders as three stacked mini-bars (R/G/B, length = duty, %
  text if space); mono LEDs get a thin duty bar under the circle. Bars, not
  mini-LEDs — length encodes far more accurately than luminance (that inaccuracy is
  the very thing being debugged).
- Realistic mode stays default. Tooltips show duties in both modes.

### 5.3 Docs + closeout

- `docs/user_guide.md`: brightness semantics (the slow-mo paragraph), debug toggle,
  tooltip duties, bank labels.
- `docs/architecture.md`: duty engine section (integrator, protocol fields, EMA).
- CLAUDE.md: contract addendum (NUM_RGB_LEDS + layout), file-table rows for new files.
- Roadmap: mark U9/U36/U37/U38 ✅ per the completion checklist; Icebox entries:
  physical LED coordinates (per-board curation), session-log duty stats, bi-color
  2-pin LEDs / LED matrices-charlieplex card (note: the duty engine already renders
  time-multiplexed LEDs honestly — 1/N duty → 1/N brightness — which is also the seed
  of U22 scan-display support), ws2812/addressable → P5.
- This plan doc gets a closeout header line (shipped PRs + dates), like the U21 plan.

---

## 6. Phase 0 (start of U9, ~1 session): spikes that de-risk everything

1. **Integrator probe**: hand-write a throwaway wrapper around `duty_probe.vhd`; run
   under GHDL-mcode, ghdl-llvm, ghdl-jit, NVC (all installed; `--sim` slugs / PATH).
   Assert: acc/tch math exact; **>2.2 s static gap does not overflow** (the INTEGER
   trap); metavalue handling; delta-glitch = zero width; ports readable from cocotb on
   all backends. This validates §2.2 before any real wiring.
2. **Census re-run** (script in §7) + serial-impostor sweep; commit results to §7.
3. **Benchmark baseline capture** for §2.8 (before-numbers on today's main).

If any spike falsifies a §2 assumption, stop and revise this plan with Rick — the
fallback design (clocked counters, §2.1 last bullet) changes the perf story.

---

## 7. Census (2026-07-18 planning session; re-run in phase 0)

Script (run from repo root):

```python
import json, glob, collections
rgb_boards, multi = [], []
for f in sorted(glob.glob('boards/*/*.json')):
    if '/_' in f: continue
    d = json.load(open(f)); leds = d.get('leds') or []
    names = collections.Counter(l['name'] for l in leds)
    if any('rgb' in n for n in names):
        pins = sorted({len(l['pins']) for l in leds if 'rgb' in l['name']})
        rgb_boards.append((f, dict(names), pins))
    elif len(names) > 1:
        multi.append((f, dict(names)))
# report counts, any rgb with pins != [3], and the multi-name list
```

Results at `98798fe`: **67 boards** with `rgb_led` components (all sampled had 3 pins —
verify exhaustively in phase 0), across all three synced sources. **21 boards** with
multiple mono LED names. Notables: Arty A7 (4 mono + 4 RGB), Cora Z7 (RGB-only ×2),
ECPIX-5 (4 RGB, RGB-only), Fomu (RGB), Cmod A7 (2 mono + 1 RGB), DE2-115
(18 `led` + 9 `led_g` — the bank showcase), Black Ice (`led_b/g/o/r` — discrete, orange
proves it), UPduino v1 / iCESugar / iCE40-UP5K-B-EVN (`led_r/g/b` scalar-trio = RGB in
disguise → reclassify), `versa_ecp5` (`alnum_led` — leave as labeled mono; future
seg-family card), `mister` (`power_led`/`disk_led` — plain mono banks).

---

## 8. Release plumbing

- **v0.17.0 "brightness release"** after U9+U36: milestone (create at U9 start, issues
  per PR), CHANGELOG (`[Unreleased]` → dated section + comparison links), version bump
  in `pyproject.toml` **then `uv lock`** (memory: uv-lock-after-bump lesson), release
  branch → PR → tag on merge → GitHub Release. Follow CONTRIBUTING "Releasing" verbatim.
- **v0.18.0 "RGB release"** after U37+U38: same, with the §4.6 migration note.
- Required CI checks: Linux+Windows × GHDL+NVC matrix (memory
  `project_ci_linux_simulators.md`); the GHDL-LLVM job is non-required but watch it.

## 9. Risk register

| Risk | Mitigation |
|---|---|
| Integrator perf on fast backends (event-heavy PWM) | native-speed events ≈ ns each; §2.8 gate with hard numbers; fallback = clocked counters (worse constant cost — Rick decision) |
| VHDL INTEGER overflow in time math | §2.2 decomposition; explicit long-gap test |
| Stuck-channel blindspot | tch correction term; explicit test |
| Wide-port read cost (DE2-115: 91 ch × 2 × 48 bits) | reads only at send cadence (≤250/s); measure in phase 0; fallback: pack 32-bit fields |
| `len(.leds)` semantic split (channels vs components) | §4.2 audit table in PR description |
| Colors wiped on re-sync | colors flow through parsers/registry only (§3.2); regen-twice determinism test |
| Wrong color citations | verify-or-omit rule; theme fallback is always safe |
| Theme pixel tests break | expected churn; draw-time THEME reads only (U6 trap) |
| Digilent RGB polarity assumptions | read each board's XDC/manual; polarity lives in the convention, never hardcoded |

## 10. Sizing

U9: 2 PRs + phase-0 spike (~2-3 sessions). U36: 2 PRs (~2 sessions, census + citation
legwork). U37: 2 PRs (~2 sessions, the audit is the long pole). U38: 2 PRs (~2 sessions).
Total ≈ 8 PRs / 2 releases. Ship value at every merge; stop at any card boundary.
