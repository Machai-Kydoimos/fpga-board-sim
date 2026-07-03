# Docs & Assets Improvement Plan

> **Status:** DONE · Created 2026-07-03 in a planning session (Claude Fable 5 + Rick); completed
> 2026-07-03.
> **Base commit:** all facts and `file:line` locators in this plan were validated against
> `main` @ `120bdba` (2026-07-03). If `main` has advanced since, re-verify locators by
> grepping for the quoted content before relying on any line number.
> **Executor:** a future Claude session — read this document top to bottom, then execute the
> five PRs **sequentially** (they touch overlapping files). All option decisions below were
> made by Rick during planning and are **final** — do not re-litigate them; if reality
> contradicts a stated fact, stop and surface it instead of improvising.
> **Closeout:** when the last PR merges, complete the [Closeout](#closeout) section.

## Ledger

| PR | Scope | Status |
|---|---|---|
| PR 1 | README badges + tested-on line + README link fixes | ☑ [#159](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/159) |
| PR 2 | Guide hygiene: § anchor links, file links, diagram, TOC | ☑ [#160](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/160) |
| PR 3 | Generator: firmware source listing + `--prescaler-bits` override + regen | ☑ [#161](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/161) |
| PR 4 | Capture pipeline + all GIF/PNG assets, renames, captions | ☑ [#162](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/162) |
| PR 5 | Annotated waveform (script + PNG + `.gtkw`) for guide §15 | ☑ [#163](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/163) |

Umbrella issue: [#158](https://github.com/Machai-Kydoimos/fpga-board-sim/issues/158).

## Context

A review of the documentation surfaced a cluster of quality issues: the README's embedded-CPU
GIF is temporally aliased (the firmware steps ~4× per GIF frame, so LEDs flash with no visible
pattern), `demo.gif` jumps at its loop seam (SW0 is left on and BTN0's direction toggle is left
reversed), the embedded-core guide has no intra-document links for its 61 `§N` cross-references,
no repo-file links, a misaligned ASCII diagram, the CPU GIF assets are named outside the core
naming convention, the README has a single CI badge, and the generated embedded-core `.vhd`
files show only machine code with no view of the program they run. This plan fixes all of that
plus adjacent gaps found during exploration (missing "subtitle" info strip on CPU GIFs, missing
dice/hello/waveform visuals, no asset-regeneration procedure in CONTRIBUTING).

## Approved decisions (fixed)

| Topic | Decision |
|---|---|
| CPU GIF rate fix | Capture from a **temporary variant build** generated with `PRESCALER_BITS=14` (committed designs, specs, tests, and interactive UX untouched). New `--prescaler-bits` override on `scripts/gen_embedded_core.py`. |
| demo.gif loop | Storyboard restores **both** persistent inputs at the end: SW0 back off **and** BTN0 re-tapped (direction restored). Re-capture; never post-process the committed GIF. |
| README CPU GIF | Becomes an **interactive storyboard** (cursor taps BTN0, holds BTN1, toggles SW0 on/off, re-taps BTN0) — a new asset. The guide's 3-board table keeps three **plain** captures. |
| New visuals | Dice GIF, hello static PNG, annotated waveform PNG (Pillow-rendered in the **GTKWave visual idiom** + committed `.gtkw` save file so a GTKWave user can open the identical view). **No** T80 GIF — add a caption sentence saying the Z80 builds look identical (that sameness is the point). |
| Asset renames | `cpu_walk_{2,4,6}digit.gif` → `mx65_walking_counter_{2,4,6}digit.gif`. |
| Badges | Add project-info trio (license, latest release, Python 3.10+) **and** tooling trio (ruff, mypy, uv), plus a one-line "tested on" matrix note. **No CI workflow split** (GitHub badges are per-workflow only; per-OS badges would churn branch-protection required checks). |
| Firmware in .vhd | Generator embeds the firmware assembly source **verbatim as a `--` comment block** above the ROM constant (new `@@FIRMWARE_LISTING@@` token). All 8 designs regenerate. |

## Global conventions (apply to every PR)

- One feature branch per PR, branched off **freshly pulled `main`** (previous PR merged first —
  execute the PRs sequentially in the order below).
- Every PR adds a `CHANGELOG.md` entry under `## [Unreleased]` (`### Added` / `### Changed`),
  Keep-a-Changelog style: bold lead-in phrase + prose + `(#PR)`.
- Before every commit run all gates:
  `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run rumdl check . && uv run pytest -m "not slow"`.
  Run the **full** suite (including `slow`) for PR 3 and PR 4 (they touch generated VHDL / the
  capture pipeline).
- `mypy .` covers `scripts/` and `sim/` — new scripts must be fully typed. ruff `ANN`/`D` rules
  apply (docstrings on every function, like the existing capture scripts).
- US spelling everywhere. VHDL output must stay pure ASCII (the `check_vhdl_encoding` gate).
- New Markdown must pass `uv run rumdl check` (MD013/MD036 are disabled; the rest apply).
- Any **new** `§N` reference added to the guide by PR 3/4/5 text must be an anchor link too,
  using the PR 2 anchor table — the link checker catches dead anchors but NOT unlinked `§`
  glyphs, so don't reintroduce plain ones.
- Use `gh` for all GitHub operations. Optional but recommended: open one umbrella issue
  "Docs & assets improvement pass" first and link each PR to it. No roadmap card is needed
  (maintenance arc, not roadmap work).
- GIF/PNG assets are binary: in each asset PR, ask Rick to visually review the rendered
  GIFs/PNG before merge (loop-seam continuity, readable step rate, strip text).

---

## PR 1 — README badges, tested-on line, and README link fixes

**Files:** `README.md`, `CHANGELOG.md`.

1. Replace the badge line (README.md:3) with:

   ```markdown
   [![CI](https://github.com/Machai-Kydoimos/fpga-board-sim/actions/workflows/ci.yml/badge.svg)](https://github.com/Machai-Kydoimos/fpga-board-sim/actions/workflows/ci.yml)
   [![Release](https://img.shields.io/github/v/release/Machai-Kydoimos/fpga-board-sim)](https://github.com/Machai-Kydoimos/fpga-board-sim/releases)
   [![License](https://img.shields.io/github/license/Machai-Kydoimos/fpga-board-sim)](LICENSE)
   [![Python](https://img.shields.io/badge/python-3.10%2B-blue)](pyproject.toml)
   [![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
   [![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
   [![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
   ```

   (Consecutive lines render as one row on GitHub. Verify each URL renders on the PR branch;
   shields.io GitHub-data badges need no tokens for a public repo.)

2. Directly below the badges add the honest granular-status line (the agreed substitute for
   per-OS badges — GitHub Actions badges exist only per workflow, not per job):

   ```markdown
   *CI matrix: Ubuntu + Windows × Python 3.10 / 3.12 / 3.13, plus GHDL 6.0 and NVC simulator
   jobs on Linux and GHDL 6.0 on Windows. macOS is supported but not CI-tested.*
   ```

   (Facts verified against `.github/workflows/ci.yml`: matrix `os: [ubuntu-latest,
   windows-latest]`, `python-version: ["3.10", "3.12", "3.13"]`; three pinned-3.12 simulator
   jobs; no macOS job.)

3. README.md:474 references `docs/embedded_core_system_guide.md` and
   `docs/embedded_core_improvement_plan.md` as plain backticked text — convert both to links
   using the established pattern (see README.md:9 for the precedent:
   backtick-wrapped path as link text, repo-relative path as target).

4. CHANGELOG entry under `### Added`.

---

## PR 2 — Guide hygiene: § anchor links, file links, diagram, TOC

**Files:** `docs/embedded_core_system_guide.md`, `CHANGELOG.md`.

### 2a. Convert `§N` / `§N.M` references to anchor links

There are **61 `§` references outside code fences** (and 1 inside a fence in §7's asm snippet —
leave anything inside ``` fences untouched; links do not render there). Convert each `§N[.M]`
to `[§N.M](#anchor)`, keeping the `§N.M` glyph as the link text. Composite references like
"(§6, *Port-mapped IO*)" additionally link the italic subsection name to its own anchor.

**Definitive anchor table** (computed with GitHub's slug rules — lowercase; strip backticks;
drop non-word/non-space/non-hyphen chars including `—`, `×`, `&`, quotes, periods; spaces →
hyphens). Do not re-derive; use these:

| Heading | Anchor |
|---|---|
| 1. Overview & goals | `#1-overview--goals` |
| 2. Prerequisites — the simulator contract | `#2-prerequisites--the-simulator-contract` |
| 3. Anatomy of a generated system | `#3-anatomy-of-a-generated-system` |
| 4. Adding a CPU core (the core-agnostic part) | `#4-adding-a-cpu-core-the-core-agnostic-part` |
| 4.1 Requirements for a core | `#41-requirements-for-a-core` |
| 4.2 Vendoring the core | `#42-vendoring-the-core` |
| 4.3 The `CpuPlugin` | `#43-the-cpuplugin` |
| 4.4 The bus adapter — the heart of "any core" | `#44-the-bus-adapter--the-heart-of-any-core` |
| 4.5 Bus read timing — the deepest pothole | `#45-bus-read-timing--the-deepest-pothole` |
| 4.6 Adapter variants — interrupt mode × IO transport | `#46-adapter-variants--interrupt-mode--io-transport` |
| 5. Reset & cold-start (generalized) | `#5-reset--cold-start-generalized` |
| 6. Memory & IO map design | `#6-memory--io-map-design` |
| Port-mapped IO — the transport axis | `#port-mapped-io--the-transport-axis` |
| 7. Writing firmware | `#7-writing-firmware` |
| 8. Assembler & ROM embedding | `#8-assembler--rom-embedding` |
| 9. Timing & throughput | `#9-timing--throughput` |
| Vectored interrupts — the interrupt-mode axis | `#vectored-interrupts--the-interrupt-mode-axis` |
| 10. Generating the file | `#10-generating-the-file` |
| 11. Running & verifying | `#11-running--verifying` |
| 12. End-to-end worked example (the 6502 walking counter) | `#12-end-to-end-worked-example-the-6502-walking-counter` |
| Generic sizing — one design, every board | `#generic-sizing--one-design-every-board` |
| The same counter on a Z80 (the second core) | `#the-same-counter-on-a-z80-the-second-core` |
| The Z80 feature variants (IM 2, port IO, and the capstone) | `#the-z80-feature-variants-im-2-port-io-and-the-capstone` |
| 13. Extending | `#13-extending` |
| Worked example: adding a peripheral (the LFSR / dice-roller) | `#worked-example-adding-a-peripheral-the-lfsr--dice-roller` |
| 14. Troubleshooting | `#14-troubleshooting` |
| 15. Debugging with waveforms | `#15-debugging-with-waveforms` |

### 2b. Convert plain backticked repo paths to relative links

Rationale (also for the PR description): relative links resolve on GitHub's rendered view AND
in local renderers (VS Code preview, most Markdown viewers); because the link text stays the
literal backticked path, plain-text/terminal readers lose nothing. From `docs/`, targets need a
`../` prefix (e.g. `` [`hdl/blinky.vhd`](../hdl/blinky.vhd) ``).

Rules:

- Convert only paths that **exist verbatim** in the repo (files or directories). The guide's
  path-like references: ~11 `hdl/`, ~11 `firmware/`, ~5 `scripts/`, ~4 `sim/`, ~3 `systems/`,
  ~2 `tests/`, 1 `CLAUDE.md`.
- **Skip** anything inside code fences, and skip globs/placeholders (`systems/*.toml`,
  `adapters/<core>.vhd`, `templates/fragments/*.vhd.frag`, `hdl/{mx65,t80}_*.vhd`, …).
- Convert every occurrence (not just the first) — mechanical consistency beats cleverness.
- `improvement_roadmap.md` / `embedded_core_system_plan.md` mentions: link as sibling files
  (no `../`), matching the existing line-3 link.

### 2c. Replace the §3 ASCII diagram

Replace the misaligned diagram (currently guide lines 80–92) with this verified art — paste
**verbatim** inside the existing text fence (every line is exactly 90 characters):

```text
+------------------------------- top (entity = filename) --------------------------------+
|                                                                                        |
|  clk --> [ POR ] --> cpu_reset (active-high, normalized)                               |
|                                                                                        |
|  +----------------------+                            +------------------------------+  |
|  |  per-core ADAPTER    |       normalized bus       |     decode + read mux        |  |
|  |  (a VHDL `block`)    |                            |                              |  |
|  |  instantiates mx65   | cpu_addr / cpu_dout -----> |  cpu_rom | cpu_ram | cpu_io  |  |
|  |  or T80              | cpu_we ------------------> |          (regs + timer)      |  |
|  |                      | <---------------- cpu_din  |                              |  |
|  |                      | <- cpu_reset, cpu_irq_req  |                              |  |
|  +----------------------+                            +------------------------------+  |
|                                                            ^               |           |
|  sw/btn --------------------------------------------------+                |           |
|                                                                            v           |
|                                                                         led/seg        |
+----------------------------------------------------------------------------------------+
```

After pasting, verify with `awk '{ print length }'` over the fenced block: a single distinct
value (90).

### 2d. Add a table of contents

After the italic abstract (before `## 1. Overview & goals`), insert a `**Contents**` bold line
(MD036 is disabled, so no heading needed — avoids polluting the anchor namespace) followed by a
15-item bullet list linking §1–§15 using the anchor table above.

### 2e. Verification

Run this read-only checker (inline via `python3 -` or from a scratch dir); it must raise
nothing:

```python
import re, pathlib
md = pathlib.Path("docs/embedded_core_system_guide.md").read_text()
body = re.sub(r"```.*?```", "", md, flags=re.S)
seen = {}
anchors = set()
for m in re.finditer(r"^#{1,4}\s+(.*)$", body, flags=re.M):
    s = m.group(1).strip().lower().replace("`", "")
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s", "-", s)
    n = seen.get(s, -1) + 1
    seen[s] = n
    anchors.add(s if n == 0 else f"{s}-{n}")
for t in re.findall(r"\]\(#([^)]+)\)", body):
    assert t in anchors, f"dead anchor: #{t}"
for t in re.findall(r"\]\((?!#|https?:)([^)]+?)(?:#[^)]*)?\)", body):
    assert (pathlib.Path("docs") / t).resolve().exists(), f"dead path: {t}"
```

Also `uv run rumdl check docs/embedded_core_system_guide.md`, and spot-check rendering on the
pushed branch via GitHub.

---

## PR 3 — Generator: firmware source listing + `--prescaler-bits` override

**Files:** `scripts/embedded_core/emitter.py`,
`scripts/embedded_core/templates/cpu_rom.vhd.tmpl`, `scripts/gen_embedded_core.py`, all 8
`hdl/{mx65,t80}_*.vhd` (regenerated), `tests/test_embedded_core.py`,
`docs/embedded_core_system_guide.md` (§8 + §9 notes), `CLAUDE.md`, `CHANGELOG.md`.

### 3a. Firmware listing embedded in generated designs

- `scripts/gen_embedded_core.py` — `generate_vhdl(spec, plugin, rom_bytes)` is the single
  shared emit path (also used by `regen_embedded_cores.py`), so thread the feature there:
  read `REPO / "firmware" / f"{spec.firmware}{plugin.asm_ext}"` (mx65 → `.s`, t80 → `.asm`;
  `plugin.asm_ext` already exists), hard-error with a clear message if the file is missing or
  contains non-ASCII bytes (all 8 current sources are verified pure ASCII), and pass the text
  to `emit(...)` as a new parameter.
- `scripts/embedded_core/emitter.py` — new token `FIRMWARE_LISTING`, rendered as a comment
  block: a short header (`-- Firmware source: firmware/<name><ext>  (assembled with
  <plugin.asm_toolchain>; the checked-in .bin below is authoritative)`), a `--` separator
  ruler, then each source line as `-- <line>` (rstrip each line; empty lines become a bare
  `--`; two-space indent to match the template's existing comment indent). Reuse the
  `_banner_description` prefixing pattern (emitter.py:30). This is data-driven content (like
  `ROM_AGGREGATE`), so an emitter-side string builder is correct — the `.vhd.frag` policy is
  for static VHDL bodies and does not apply.
- `scripts/embedded_core/templates/cpu_rom.vhd.tmpl` — insert `@@FIRMWARE_LISTING@@` on its
  own line between the existing provenance comment (ends line 22, "…offset 16#7FC# = $00).")
  and `constant ROM : rom_t := (` (line 23). The `emit()` final `"@@" in result` guard
  (emitter.py:196) ensures the token is always filled.
- Check for any direct `emit(...)` call sites in tests and update their signatures.
- Regenerate everything: `uv run python scripts/regen_embedded_cores.py --write` — commit all
  8 regenerated `hdl/*.vhd`. Golden tests in `tests/test_embedded_core.py` compare committed
  files against fresh regeneration, so they pass automatically once regenerated. Do NOT touch
  any `.bin`.

### 3b. `--prescaler-bits` generation override

- Add `--prescaler-bits` (int) to `gen_embedded_core.py`'s CLI, following the existing
  explicit-flag-overrides-spec pattern (`--rom`/`--out`, lines 60–70): after
  `load(args.system)`, set `spec.generics["prescaler_bits"] = args.prescaler_bits` when given
  (`generics` is a plain dict — mutable even if `SystemSpec` is frozen; if that assumption
  fails, use `dataclasses.replace`). The value flows into the `PRESCALER_BITS` generic
  *default* in both `top.vhd.tmpl:16` and `cpu_io.vhd.tmpl:15` (via emitter.py:112). Document
  in the module docstring: generation-time knob, used e.g. for slowed-down GIF capture builds.

### 3c. Tests (add to `tests/test_embedded_core.py`)

- Listing: generate the hello system in-memory and assert the output contains a distinctive
  source line from `firmware/mx65_hello_7seg.s` (such as the `GLYPH0` definition) prefixed
  with `--`, and that a Z80 system embeds its `.asm` respectively.
- Override: emit with `prescaler_bits` overridden to 14 → output contains
  `PRESCALER_BITS : positive := 14`; unmodified spec still emits `:= 10`.

### 3d. Doc touches

- Guide §8: one sentence — generated files now carry the full assembly source as a comment
  above the ROM constant, so the single file shows the program it runs.
- Guide §9: extend the `PRESCALER_BITS` table with a `14 | 16384 | ~35` row and note that the
  committed GIF captures use a 14-variant build (generated with `--prescaler-bits 14`) so the
  CPU free-runs while the display steps at a viewable rate.
- CLAUDE.md: in the embedded-core key-file row / section, add half a sentence about the
  embedded firmware-source comment and the `--prescaler-bits` override.

Run the **full** pytest suite (both simulators exercise the regenerated designs).

---

## PR 4 — Capture pipeline + all GIF/PNG assets, renames, captions

**Files:** `sim/capture_frames.py`, `scripts/capture_demo.py`, `README.md`,
`docs/embedded_core_system_guide.md`, `docs/embedded_core_system_plan.md`,
`docs/embedded_core_build_notes.md`, `docs/embedded_core_improvement_plan.md`,
`docs/improvement_roadmap.md` (grep hits only), `CONTRIBUTING.md`, `docs/assets/*`,
`CHANGELOG.md`.

### 4a. Refactor `sim/capture_frames.py` storyboards

`_SnakeDemo` (capture_frames.py:96–240) already contains the reusable machinery. Extract a
`_Storyboard` base class holding: cursor state/easing/park, `_tick` (sim step + mirror + draw
board/cursor/strip/caption + save frame), `_aim`, `_travel`, `_pause`, `tap_button`,
`toggle_switch`, `coast`, and a `steps_per_frame()` hook used by `_tick` for step accounting.
Changes vs today:

- **`toggle_switch` becomes a true toggle** (`sw_value ^= 1 << idx`; widget
  `state = not state`) — needed by the demo.gif ending and the CPU storyboard. The existing
  snake flow (a single ON toggle) is unaffected by XOR semantics.
- `_SnakeDemo(_Storyboard)`: keeps snake step accounting
  (`clocks_per_frame / 2**max(1, base_idx - popcount(sw))`), `steps_per_cycle`,
  `run_to_cycle`, `_wait_central_led`.
- New `_CpuWalkDemo(_Storyboard)`: step accounting
  `clocks_per_frame / (skip * 2**prescaler_bits)` with `skip = max(1, 8 >> popcount(sw))`
  (SKIP_BASE=8 matches `firmware/mx65_walking_counter_7seg.s:30`), `prescaler_bits` from new
  env `CAPTURE_PRESCALER_BITS` (default 10), and a `run_steps(n)` helper (like `run_to_cycle`
  but counting firmware steps).
- New scenarios in the `capture()` dispatch:
  - `cpu_walk` — storyboard: `run_steps(~10)` →
    `tap_button(0, "BTN0  →  counts down, LED reverses")` → `run_steps(~8)` →
    `tap_button(1, "BTN1  →  lamp test")` → `run_steps(~4)` →
    `toggle_switch(0, "SW0  →  2x faster")` → `run_steps(~10)` →
    `toggle_switch(0, "SW0  →  normal speed")` →
    `tap_button(0, "BTN0  →  counts up again")` → `coast(~40 frames)`. (Restoring both inputs
    makes the loop seamless. Button holds: keep the default 20 frames — ≈41 prescaler ticks at
    the capture build, far above the ≥1-tick sampling requirement.) Tune dwells for
    readability; target ~10–13 s total.
  - `dice` — no step accounting: initial `_pause(~25)`, then 4 ×
    [`tap_button(0, "BTN0  →  roll")`, `_pause(~35)`], then `coast(~25)`. Die face + binary
    LED readout change per tap.
- **Plain scenario gains the bottom info strip** (`draw_strip`) — this is the "subtitle" from
  demo.gif (`live VHDL simulation · <board> (<source>) · <file>`); `CAPTURE_SOURCE` /
  `CAPTURE_VHDL_NAME` are already exported unconditionally by the orchestrator
  (capture_demo.py:191–192), only the snake branch currently consumes them.
- **demo.gif ending** — in `_run_snake` (capture_frames.py:243–257), after
  `run_to_cycle(end_cycle)` append: `toggle_switch(0, "SW0  →  normal speed")`,
  `tap_button(0, "BTN0  →  forward again")`, then the existing `coast(tail)`.

### 4b. `scripts/capture_demo.py` additions

- `--scenario` choices += `cpu_walk`, `dice` (scenario-tuned defaults: `step_ns=336000`,
  `fps=25` for both; snake/plain defaults unchanged).
- `--prescaler-bits` (int, default 10) → exported as `CAPTURE_PRESCALER_BITS` (informs the
  storyboard's step accounting; the *design* rate comes from the variant `.vhd`, so the two
  must be passed together — say so in the flag help).
- `--vhdl-label` (optional str) → overrides `CAPTURE_VHDL_NAME`, so a temp-generated variant
  file can still show `hdl/mx65_walking_counter_7seg.vhd` in the strip.
- `--png` flag: capture as usual, then instead of `assemble_gif`, save the **last** frame to
  `--out` (suffix must be `.png`). Short-circuits at the assembly step (capture_demo.py:220).

### 4c. Regenerate / create the assets

First build the capture variant (unchanged firmware, one generic default):

```bash
uv run python scripts/gen_embedded_core.py --system systems/mx65_walking_counter_7seg.toml \
    --prescaler-bits 14 --out <scratch>/mx65_walking_counter_7seg.vhd
```

(The output filename stem must stay `mx65_walking_counter_7seg` — entity name = filename is a
contract check. Never write the variant into `hdl/`.)

Rate math (for sanity): capture clock is pinned at 10 ns; `--step-ns 336000` → 33,600
clocks/frame; step period = `2^14 × 8` = 131,072 clocks → **0.256 steps/frame ≈ 6.4 steps/s**
at 25 fps — matching demo.gif's ~7 steps/s. (Old GIFs: 4.1 steps/frame — aliased.)

| Asset (docs/assets/) | Command sketch |
|---|---|
| `mx65_walking_counter_2digit.gif` | `capture_demo.py --scenario plain --sim nvc --vhdl <scratch>/mx65_walking_counter_7seg.vhd --vhdl-label hdl/mx65_walking_counter_7seg.vhd --step-ns 336000 --frames 144 --board step_mxo2 --out …` (~5.8 s, ~37 steps) |
| `mx65_walking_counter_4digit.gif` | same, `--board de0` |
| `mx65_walking_counter_6digit.gif` | same, `--board de10_lite` |
| `mx65_walking_counter_demo.gif` | `--scenario cpu_walk --sim nvc --vhdl <variant> --vhdl-label hdl/mx65_walking_counter_7seg.vhd --prescaler-bits 14 --step-ns 336000 --board de10_lite --out …` |
| `mx65_dice_7seg.gif` | `--scenario dice --sim nvc --vhdl hdl/mx65_dice_7seg.vhd --step-ns 336000 --board de10_lite --out …` (committed design — no variant; ticks only gate button sampling) |
| `mx65_hello_7seg.png` | `--scenario plain --sim nvc --vhdl hdl/mx65_hello_7seg.vhd --step-ns 336000 --frames 12 --png --board de10_lite --out …` |
| `demo.gif` (re-capture) | `uv run python scripts/capture_demo.py` (defaults; updated storyboard) |

Delete `docs/assets/cpu_walk_{2,4,6}digit.gif`. Note: Pillow merges identical consecutive
frames and sums durations — variable per-frame durations in the output GIFs are expected, not
a bug.

### 4d. Reference + caption updates

- Grep-driven rename fixes: `grep -rn 'cpu_walk_'` → `README.md:472`, guide:602,
  `docs/embedded_core_system_plan.md:196-198`, `docs/embedded_core_build_notes.md:235`,
  `docs/embedded_core_improvement_plan.md:521` (+ check `docs/improvement_roadmap.md:423`).
  Do not touch `test_cpu_walking` matches (a different thing). Update the as-built capture
  commands in `embedded_core_system_plan.md` and guide §11's "Headless GIF" bullet to the new
  commands (variant build + new flags + new filenames).
- README embedded-CPU section: swap the image to `mx65_walking_counter_demo.gif`, write alt
  text describing the storyboard, and add an italic caption mirroring the hero GIF's — the
  links below are README-relative, paste as-is:

  ```markdown
  *Above — the same virtual board, but nothing here is hand-written RTL: a **6502 soft CPU**
  (the vendored mx65 core) executes
  [`firmware/mx65_walking_counter_7seg.s`](firmware/mx65_walking_counter_7seg.s) from an
  embedded ROM, reading the switches and buttons and driving the LEDs and digits through
  memory-mapped IO. **BTN0** makes the firmware count down and reverse the bouncing LED,
  **BTN1** is a lamp test, and **SW0** doubles the step rate. The CPU free-runs at full
  simulation speed — a hardware prescaler divides the visible update rate, exactly as it
  would on real silicon. Captured headlessly via
  [`scripts/capture_demo.py`](scripts/capture_demo.py).*
  ```

- README hero-GIF caption/alt: extend with the new ending ("…and finally the inputs are
  restored so the loop plays seamlessly").
- Guide "Generic sizing" table: renamed GIF paths; add below the table the agreed Z80 sentence
  ("The four `t80_*` builds are not shown: they drive the board identically to these mx65
  captures — that sameness is the point"), with "§12" linked via the PR 2 anchor table, plus a
  pointer to the README's interactive capture.
- Guide §13 (dice worked example): embed `assets/mx65_dice_7seg.gif` with a one-line caption.
- Guide Quickstart (or §7's hello walkthrough): embed `assets/mx65_hello_7seg.png`.
- README "Project Structure" `scripts/` block: add the missing `capture_demo.py` and
  `capture_selector.py` lines (they are referenced at README:9/15 but absent from the tree).
- CONTRIBUTING.md: new short subsection "Regenerating the documentation assets" with the
  command table above (no such procedure exists anywhere today).

### 4e. Verification

- Metadata check (PIL one-liner): each new GIF is 900×640, loop=0; total durations ≈ targets.
- Visual checklist for Rick's review: cpu GIFs show a clearly readable ~6 steps/s odometer +
  bouncing LED; strip present on all; demo.gif loop seam continuous in rate AND direction;
  dice faces change per tap; hello PNG shows LED0 + "0".
- Full pytest (capture refactor touches `sim/`, which mypy also covers).

---

## PR 5 — Annotated waveform for guide §15

**Files:** new `scripts/capture_waveform.py`, new `docs/assets/mx65_hello_waveform.png`,
new `docs/assets/mx65_hello_7seg.gtkw`, `docs/embedded_core_system_guide.md` (§15),
`README.md` project-structure line, `CLAUDE.md` key-files row, `CHANGELOG.md`.

### 5a. `scripts/capture_waveform.py` (stdlib + Pillow only; no new dependencies)

1. **Simulate:** temp dir; write a tiny testbench (inline string in the script): entity
   `wave_tb` instantiating `work.mx65_hello_7seg` with generics
   `NUM_SWITCHES|NUM_BUTTONS|NUM_LEDS => 4, NUM_SEGS => 4, COUNTER_BITS => 17`, ports
   `sw`/`btn` tied to `(others => '0')` (hello never reads them, but defined inputs keep the
   trace clean), and a 10 ns clock process. Then
   `ghdl -a --std=08 hdl/mx65_hello_7seg.vhd wave_tb.vhd`, `ghdl -e --std=08 wave_tb`,
   `ghdl -r --std=08 wave_tb --vcd=<out.vcd> --stop-time=3us` (the whole hello story — POR,
   vector fetch, ~15 instructions, spin loop — completes in <1 µs; 3 µs gives loop context).
2. **Parse:** minimal hand-rolled VCD parser (GHDL emits standard VCD; handle `$scope`
   hierarchy, scalar changes and `b…` vector changes). Extract: `clk`, and from the DUT scope
   `cpu_reset`, `cpu_addr[15:0]`, `cpu_din[7:0]`, `cpu_we`, `led[3:0]`.
3. **Render (Pillow, GTKWave visual idiom** — per Rick: familiar to GTKWave users): black
   background, left signal-name gutter, top time ruler, green digital traces, buses drawn as
   GTKWave-style hexagonal lanes with centered hex values, red for any metavalue. ~1600 px
   wide, 2× supersampled text. Annotation layer in a contrasting color (white/amber arrows +
   labels), **located programmatically** from the parsed data (search for the events, do not
   hardcode times): (1) `cpu_reset` falling edge — "POR releases after 7 clocks";
   (2) `cpu_addr` = FFFC then FFFD — "6502 fetches the reset vector"; (3) first fetch at
   F800 — "first opcode (SEI)"; (4) `cpu_we` pulse with addr E020 + `led(0)` rising —
   "STA $E020 → LED0 on"; (5) the repeating F810–F812 pattern — "spin: JMP spin". Cross-check
   labels against the firmware listing embedded by PR 3.
4. **Outputs:** PNG → `docs/assets/mx65_hello_waveform.png` (committed); VCD → temp by
   default, `--vcd-out PATH` to keep it; also emit/refresh `docs/assets/mx65_hello_7seg.gtkw`
   (a small text save file listing the same signals with hex radix) so
   `gtkwave <kept.vcd> docs/assets/mx65_hello_7seg.gtkw` opens the identical view in real
   GTKWave.
5. Fully typed (mypy repo-wide), ruff `ANN`/`D` clean, docstrings in the existing
   capture-script style.

### 5b. Guide §15 rewrite (additive)

Keep the existing GHDL/NVC command sketches, then embed the PNG with a short "what you are
looking at" walkthrough tied to the five annotations, note that the figure is regenerable via
`uv run python scripts/capture_waveform.py`, and give the GTKWave command using the committed
`.gtkw` (fulfills the "looks familiar if the user also uses GTKWave" requirement). Link §15
from the §14 troubleshooting table's metavalue rows where helpful.

### 5c. Verification

Run the script end-to-end; open the PNG; confirm annotations land on the right transitions by
comparing against the firmware source (`firmware/mx65_hello_7seg.s`); `gtkwave --version`
sanity-check and, if a display is available, have Rick confirm the `.gtkw` loads. Gates +
rumdl.

---

## Final sweep (after PR 5)

- `uv run python scripts/regen_embedded_cores.py` → all `OK`.
- `grep -rn 'cpu_walk_' --include='*.md'` → no hits.
- Re-run the PR 2 link checker on the guide (PR 4/5 added new links/images).
- Unlinked-glyph sweep: `grep -nE '§' docs/embedded_core_system_guide.md | grep -v '\[§'` —
  every remaining hit must be inside a code fence (one exists today, in §7's asm snippet).
- Full `uv run pytest`.
- View README + guide rendered on GitHub; badges render; both GIF loops seamless.

## Closeout

When all five PRs are merged (fill in as you go):

1. Update the [Ledger](#ledger) above with PR numbers and check every box; flip **Status** at
   the top of this file to DONE with the completion date.
2. Confirm `CHANGELOG.md` `[Unreleased]` carries all five entries.
3. Check local-vs-remote git drift and offer Rick sync options (standing session-close
   preference).
4. Commit the final state of this plan document itself (it lives in `docs/` like the
   embedded-core plans; include it in the last PR or a trivial follow-up).

### Closeout notes (2026-07-03)

All five PRs merged sequentially as planned, each squash-merged after CI went green
(#159, #160, #161, #162, #163; umbrella issue #158). Final sweep: `regen_embedded_cores.py`
reports all 8 designs `OK`; the guide's anchor/path checker and the unlinked-`§`-glyph sweep
both pass clean (the one remaining bare `§4.5` is inside §7's asm code fence, as expected); full
`uv run pytest` is 1126 passed; all 7 README badge URLs return 200.

Two deviations from the literal plan text, both judgment calls made during execution and worth
recording:

- **Dice GIF timing.** A constant post-roll pause phase-locked the LFSR to the same few
  outcomes (3 of 4 rolls landed on the same face). Varied the pause slightly per tap
  (33/41/29/37 frames instead of a flat "~35") so the four rolls are `4 → 5 → 2 → 5` — no
  back-to-back repeat, so every tap still reads as a visible change.
- **Waveform figure time axis.** Rendering the full 3000 ns simulated window at linear scale
  made the repeating spin-loop region an illegible hatch (83 repetitions in ~1150px). The PNG
  now plots only the first 650 ns (enough to show several clean loop iterations) with a caption
  noting the loop is verified programmatically to hold stable all the way to 3000 ns; the
  simulation itself still runs the full window so that check is real, not truncated.

PR 4's assets and PR 5's waveform PNG were not visually re-reviewed by Rick before merging —
proceeded on his explicit go-ahead ("I'll review them later, but go ahead and proceed") rather
than blocking. Worth a look when convenient: the [PR 162 asset review
gallery](https://claude.ai/code/artifact/f0b7bef8-9dff-4b22-8f1a-3ad625440761) covers all 7
GIF/PNG assets from that PR with a checklist; `docs/assets/mx65_hello_waveform.png` (PR 163)
wasn't separately galleried.
