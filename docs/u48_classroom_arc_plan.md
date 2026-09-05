# Pre-semester "classroom" arc — U48–U52 + D17 → v0.23.0

> **SUPERSEDED 2026-09-05 by [u48_classroom_arc_plan_v2.md](u48_classroom_arc_plan_v2.md)** after
> Rick's review and inspection of the real course lab files, which replaced this draft's central
> assumption (that the course's designs are board-native by name). Kept as the record of how the
> arc was first framed (only spelling and Markdown lint were normalized afterward); do not execute
> from this file.

*Drafted 2026-09-05 · Status: **DRAFT — superseded by v2 the same day**; not started, no cards filed,
no issues opened · Companion to [improvement_roadmap.md](improvement_roadmap.md)*

> **How to use this document.** It is written to be executable from cold. §2 records decisions
> already made so they are not relitigated; §4 is the evidence map, every claim carrying a
> `file:line` so it can be re-verified before work starts (the codebase moves); §7 records the
> options that were *rejected* and why, so they are not re-derived. When this plan is approved,
> PR 0 commits this file and files the cards; the roadmap's *Plan documents index* gains a row.

---

## 1. Context

The first VHDL/FPGA lab session is in **~3 weeks** (from 2026-09-05). Rick's framing decides
everything in this plan:

> "The labs with the real FPGA boards are all outside of this project. A primary goal of this
> project is to give students a tool they can use **outside of the lab** to practice and
> validate their VHDL files."

**The user to design for** is a student alone at 11 pm with a `.vhd` file they wrote for their
real lab board, checking it works before the session — no TA, no instructor, no handout. Some
of them are accomplished programmers who will read this repo's source and judge it.

**Target boards** (Rick, 2026-09-05): Intel/Terasic — DE10-Lite, DE0-CV, DE1-SoC, DE2-115 — and
Lattice/Gowin/small — iCEstick, Tang Nano, ULX3S. *Not* Digilent/Xilinx.
**Install path:** both pre-installed lab machines **and** students' own laptops (Windows, macOS,
Linux).

That reframes the work away from *features* and toward **self-service**: it must install, it
must load *their* file, it must say what is wrong when it does not, and it must not look sloppy.
The queued U39–U41 peripherals arc (9 phases, one L-risk phase) serves none of that, and nothing
has a hard dependency on it ([dependency table](improvement_roadmap.md#dependency-table)), so it
is postponed by one release.

**Postponement bonus.** Docs & Assets round 2 PRs 3–6 were deferred *specifically* so the asset
re-capture happened once, after peripherals ("shine with the latest" once, not twice). Postponing
peripherals removes that reason, so the documentation refresh becomes available now. It turns out
most of it is not even needed — see §8.

### 1.1 The two structural facts that set the priorities

**(a) Terasic lab files are board-native.** A DE10-Lite Quartus top level uses `MAX10_CLK1_50`,
`SW(9 downto 0)`, `KEY(1 downto 0)`, `LEDR(9 downto 0)`, `HEX0..HEX5` — and the board JSON already
carries exactly those as **canonical** `port_conventions`. Verified 2026-09-05:

| Board | Convention | Clock | LEDs | Switches | Buttons | 7-seg |
|---|---|---|---|---|---|---|
| DE10-Lite | `terasic` canonical | `MAX10_CLK1_50` | `LEDR`×10 | `SW`×10 | `KEY`×2 active-low | `HEX0..5`, individual, 7-bit, active-low |
| DE0-CV | `terasic` canonical | `CLOCK_50` | `LEDR`×10 | `SW`×10 | `KEY`×4 active-low | `HEX0..5`, individual, active-low |
| DE1-SoC | `terasic` canonical | ✓ | ✓ | ✓ | ✓ | ✓ |
| DE2-115 | `terasic` (hand-authored; absent `naming` defaults to canonical — `sim_bridge.py:1481`) | ✓ | ✓ + `leds_green` | ✓ | ✓ | ✓ |
| Tang Nano 9K | `sipeed` canonical | `sys_clk` | `led`×6 active-low | — | — | — |
| iCEstick | amaranth *framework-derived* only | — | 5 LEDs, **0 switches, 0 buttons** | — | — | — |
| ULX3S | litex *framework-derived* only | — | — | — | — | — |

So **U21 board-native mode is the load-bearing path this semester.** Conversely, iCEstick /
ULX3S students will use the *generic* contract (their toolchains impose no port names), where the
`COUNTER_BITS` override already exists.

**(b) Therefore the frozen-board problem is concentrated on exactly the Terasic family Rick uses
most** — see finding F2 in §4.

---

## 2. Decisions already locked (Rick, 2026-09-05) — do not relitigate

| # | Question | Decision |
|---|---|---|
| D-1 | Timeline | **~3 weeks** to the first lab |
| D-2 | Target boards | **Intel/Terasic** + **Lattice/Gowin/small** (see §1) |
| D-3 | Where lab material lives | **Outside this project.** No `labs/` directory, no exercises, no solutions. The repo's job is the *tool*, plus reference examples and docs. |
| D-4 | Install path | **Both** lab machines and students' own laptops |
| D-5 | Multi-file designs | **Ship in this arc** (scoped down — see PR 7 and §7.2) |
| D-6 | `sim_bridge.py` split | **Do the full split now** (de-risked — see PR 2 and §4 F13) |
| D-7 | The two `.adoc` talk decks | **Leave untouched this arc** |

D-3 is the most consequential: it is why this plan contains no curriculum and no exercises, and
why the example work in PR 9 is scoped to *reference designs for the target boards* rather than a
teaching ladder.

---

## 3. Baseline — what is already good

Stated first because it changes how much of the budget goes to "code cleanup". Measured
2026-09-05 on `main` at `3213b39`:

- `uv run ruff check .` → **All checks passed**; `uv run mypy .` (strict) → **Success, 174 files**
- **2,479 tests** collected across 90 files; non-slow suite **green in 17 s**; zero `xfail`s; all
  16 skips are legitimate environment gates; `pytest-randomly` enforces order independence
- **Zero** `TODO` / `FIXME` / `HACK` / `XXX` in the entire tree; zero commented-out code; zero
  bare `except`; zero mutable default arguments
- Test:source ratio **1.8:1** (24,822 test lines to 13,609 source lines)
- Docstring coverage complete by construction (`D` enabled repo-wide, only `D203`/`D213` off)
- CI: 4 platforms × 3 Pythons × 5 simulator jobs + board-data drift, all green
- `work/` and `work-obj08.cf` are correctly `.gitignore`d and untracked

**A sharp student browsing this repo will be impressed, not dismissive.** The cleanup ask is a
short list of real items (§4, F13–F16), not a rewrite — so this arc spends most of its budget on
the student experience instead.

---

## 4. Evidence map (verified findings)

Every line below was checked directly on 2026-09-05. Re-verify before starting — the codebase
moves.

### Student-blocking

**F1 — The file picker's first seven entries are deliberately-broken fixtures.**
`hdl/` contains `bad_contract_7seg_extra_seg.vhdl`, `bad_contract_7seg_missing_seg.vhdl`,
`bad_contract_blinky.vhdl`, `bad_contract_fixed_width.vhdl`, `bad_contract_wrong_direction.vhdl`,
`bad_encoding_blinky.vhdl`, `bad_semantic_blinky.vhdl` — and `sorted()` puts all seven above
`blinky.vhd`. `VHDLFilePicker._scan` (`ui/vhdl_picker.py:51-61`) filters only dotfiles and
non-`.vhd*` suffixes; a fresh profile has no preselection (`controller.py:440-443` preselects only
a previously-used file). **The README's own "Try it" step 4 (`README.md:97`) walks a new user
straight into this.** They are referenced from `tests/test_vhdl_validation.py`,
`tests/test_sim_bridge_errors.py`, `tests/test_nvc.py`, and one line of `docs/u35_simulator_picker_plan.md`.

**F2 — A real lab design renders a dead board with no message.** *The single most likely "your
simulator is broken" report.*
`build_generics` (`controller.py:88-120`) floors `COUNTER_BITS` at **17** bits (**20** on NVC —
`_COUNTER_BITS_FLOOR` at `controller.py:84-85`) precisely because a 24-bit divider is unwatchable
at simulator throughput. **Board-native designs get no such override**, and
`_render_native_wrapper` instantiates *"a generic-map-less uut with native names"*
(`sim_bridge.py:1872`) by design. A real DE10-Lite lab file divides 50 MHz by 2²⁴–2²⁵ — **128–256×
past watchable**, i.e. one LED toggle every 5–10 minutes at ~52k simulated cycles/s.
**Neither existing lever rescues it:** the speed slider is a *throttle* (`_SPEED_MIN`/`_SPEED_MAX`
= 0.001–10× of *real time*, `ui/sim_panel.py:57-58`; the panel already shows "MAX SPEED" when the
request exceeds the machine), and the virtual-clock preset changes only how much *simulated time*
an edge represents, not how many edges per wall-second.

**F3 — Only one file can be compiled.** `analyze_vhdl` (`sim_bridge.py:2315`) runs exactly one
`analyze_cmd(vhdl_path, …)`. Multiple design *units within one file* already work — the contract
checks `stem in [all entities found]` (`sim_bridge.py:1616-1630`) — but a student's multi-file
Quartus project cannot be loaded. Both backends accept several files on one `-a`
(`sim_bridge.py:85`, `:312`); GHDL additionally has `-i`/`-m` for dependency ordering, NVC does not.

**F4 — Compiler errors are mostly unhinted.** `add_error_hints` (`sim_bridge.py:1682-1770`)
recognizes four patterns. Verified misses: **missing `use ieee.numeric_std` / undefined
`unsigned`** (the repo's *own* `bad_semantic_blinky.vhdl` fixture is this case, and the sibling
`std_logic` regex at `sim_bridge.py:1698` is one word away), **every syntax error**, undeclared
identifier, and entity-not-found-in-`work`.

**F5 — GHDL's caret/column marker is destroyed.** `ErrorDialog._draw`
(`ui/error_dialog.py:113-124`) word-wraps with `raw_line.split(" ")` and `.strip()`, collapsing
leading whitespace, so GHDL's `^` lands alone at column 0. The font is already monospace
(`ui/constants.py:54-61`). No copy-to-clipboard either.

**F6 — Board selector defects.** `_filtered()` (`ui/board_selector.py:131-177`) has sort branches
for vendor / leds / switches / buttons / 7seg / total but **no `"name"` branch**, so the
default-labeled "Name" sort returns discovery order (source directory, then filename — four hard
blocks: amaranth 80, custom 8, digilent 26, litex 171). The filter text matches only `b.name` and
`b.class_name` (`:134-136`), so typing `terasic` returns zero despite vendor chips existing.
`hovered = -1` on construction (`:50`) with `K_RETURN` requiring `0 <= self.hovered`, so **Enter is
silently inert on first run**, contradicting the help overlay's "Enter or click to choose".

**F7 — Sixteen board display names are mangled, two in target families.**
`_prettify_class_name` (`scripts/amaranth_parser.py:584-591`) does
`re.sub(r"([a-z\d])([A-Z])", r"\1 \2", name)`, splitting digit-then-capital, then `_`→`-`:
`DE1SoCPlatform` → **`"DE1 So C"`**; `ULX3S_45F_Platform` → **`"ULX3 S-45 F-"`** (four ULX3S
variants, each with a dangling trailing dash). Also `AX7325 B`, `Cora Z7-07 S`,
`Colorlight-5 A75 B-R70`, `Logicbone85 F`, `Orange Crab R0-2-25 F`, `Orange Crab R0-2-85 F`,
`TE0714-03-50-2 I`, `Genesys ZU-3EG-D`, `Genesys ZU-5EV-D`, `Sitlinv A E115fb`.
`scripts/litex_parser.py:467` `_prettify_filename` is a second copy of the same idea; Digilent
derives names from the XDC filename with a metadata override (`scripts/digilent_parser.py:766-775`).

**F8 — No health check; the documented smoke test is the whole suite.** `__main__.py:50-99`
defines eight flags — `--sim --benchmark --board --vhdl --no-ui --screenshots --list-sims
--add-sim` — none of them a `--doctor` or `--version`. Both `README.md:85` and
`docs/install.md:216` prescribe `uv run pytest` (2,479 tests, `addopts = "-v"`, ~68 GHDL/NVC
subprocess tests) as the install check. Separately `docs/install.md:209` says `uv sync` installs
runtime deps only and "contributors want `--group dev`", while `pytest` *is* dev-only
(`pyproject.toml:33-40`) — it works only because uv installs `dev` by default.

**F9 — `--board` / `--vhdl` are benchmark-mode only.** `ScreenController.run()`
(`controller.py:322-333`) always starts at `NextScreen.SELECTOR`. But `on_board_selected(board)`
(`:355`) and `on_vhdl_loaded(vhdl_path, work_dir)` (`:493`) are already public entry points that do
exactly what a seeded start needs.

**F10 — The picker forgets the student's directory on a validation retry.**
`controller.py:451` re-opens `VHDLFilePicker(self.screen, start_dir=_HDL_DIR)` on the non-first
pick, so after *any* contract/encoding/analysis error, [Try Another File] throws the student back
to bundled `hdl/`. This is U18's carried-forward papercut and it bites hardest exactly when a
student is iterating on a failing file.

**F11 — No native example for any target board; no combinational example at all.**
`hdl/native/` holds `arty_litex.vhd`, `arty_rgb.vhd`, `basys3_scan.vhd`, `de0.vhd`,
`de10_standard.vhd`, `de25_standard.vhd`, `nexys4ddr_scan.vhd` — **none of the seven target
boards** (DE10-*Standard* ≠ DE10-*Lite*; DE0 ≠ DE0-CV). And **every** `hdl/*.vhd` contains
`rising_edge`: there is no `led <= sw`, no gates, no mux, no `case`-statement 7-segment decoder,
no labeled-states FSM. The ladder is 62 lines (`blinky.vhd`, which already carries 4 generics,
`minimum()`, `mod`, a variable and two processes) → 314 → 1,382 (generated soft-CPU).

**F12 — No tutorial, no troubleshooting doc.** `docs/writing_designs.md` (356 lines) is a
*reference* that opens at "three ways to write a design"; `docs/user_guide.md` (382 lines) is a
feature reference. Neither has a "your first design" walkthrough or a section on student errors.
Meanwhile `hdl/blinky_survey.md` — 466 lines, 12 categorized blinky idioms, a blink-rate formula
table, and a column literally headed **"Teaching goal"** — is linked from **nothing**.

### Code quality (what a code-reading student would notice)

**F13 — `sim_bridge.py` is 3,067 lines and nine unrelated concerns.** 2.5× the next-largest source
file (`ui/board_display.py`, 1,222) and 22% of `src/`. It already carries `# ── section ──` banners
that *are* the split lines: config (`:84-150`) · backends (`:150-367`) · discovery (`:367-599`) ·
venv/libpython (`:599-674`) · VHDL interface + contract (`:674-1043`) · **board-native convention
matcher (`:1043-1771`, 728 lines)** · wrapper rendering + `analyze_vhdl` (`:1771-2497`) ·
waveform (`:2497-2765`) · runner (`:2765-3067`). 46 import statements across 35 files.
**Landmine:** it holds **four** `Path(__file__).parent.parent.parent` constants —
`_DUTY_FRAGMENT_DIR:81`, `_WRAPPER_TEMPLATE:1773`, the venv default at `:2443`, `_root:2459` — two
of which are on the exact path a student's file travels (`analyze_vhdl` → `_generate_wrapper`).
Moving the module one directory deeper would silently break all four. Five more of the same
pattern live in `board_loader.py:383`, `controller.py:64`, `__main__.py:197`,
`generate_board_images.py:823` (`ui/icons.py:30` uses the correct `.resolve().parent` form).

**F14 — Two renderers for the same widgets, already drifted.** `ui/components.py` (pygame) and
`generate_board_images.py:299-561` (SVG) re-implement LED/switch/button/7-seg independently.
Commit `2746c37` ("fix: make the SVG board renderer honor LED and segment levels (#396)") touched
both — a reviewer reading the git log will spot it. It is really a *three*-way problem:
`sim/capture_frames.py` holds a third, binary-LED renderer (which is what Docs & Assets round 2
PR 3 exists to retire).

**F15 — Duplication.** `sanitize_filename` and `unique_name` are verbatim copies across the
package boundary — `generate_board_images.py:76,99` vs `scripts/sync_common.py:23,34`.
`_page_rows` / `_ensure_visible` / `_move_cursor` are byte-identical between
`ui/vhdl_picker.py:147,152,162` and `ui/board_selector.py:277,282,292`, as is the wheel-scroll step.
Five screens hand-roll the same modal `while running:` loop.

**F16 — Presentation trivia.** `docs/` holds 24 files of which ~13 are *completed* internal
delivery plans (`u21_*_plan.md`, `docs_assets_improvement_plan_v2.md`, …), burying the five a
student wants. **224** opaque `(U37)` / `(D6b)` / `(#386)` markers appear in source comments with
no legend anywhere in the source or `docs/architecture.md` (the legend exists only in
`docs/roadmap_delivered.md`). Plus: 16 genuinely dead `# noqa` directives (mostly `E402`); the same
ten cocotb test files listed twice in `pyproject.toml` (`[tool.ruff.lint.per-file-ignores]:118-127`
and `[[tool.mypy.overrides]]:168-177`) where a glob would do; a declared-but-**unused** `ui` pytest
marker (`pyproject.toml:70`); a no-op `sys.path` insert in the root `conftest.py`; no `py.typed`;
an unsorted `__all__` with `RGBLED` unexported (`ui/__init__.py:25-48`); one unreferenced public
method `get_switch_state` (`ui/board_display.py:382`).

### Icebox triggers that fire

| ID | Item | Disposition |
|---|---|---|
| **P17** | Board-native frozen-divider warning | **Graduates → U48**, but *not* as the static lint the card describes (see §7.1) |
| **P11** | Traffic-light FSM teaching design | **Graduates → U52**, lowest item in PR 9 |
| **P13** | Waveform capture is unbounded (1–2 s runs → **42–119 MB** VCDs, accumulating, no retention sweep) | Real on quota'd student home dirs; folded into PR 9's slack or deferred |
| **P6** | External boards directory | Not scheduled; would let a lab ship a 3-board tree instead of 285 |

---

## 5. Cards to file

Standing rules: an arc does not start without a card in the roadmap; **an ID is taken the moment
it is used anywhere** (2026-09-04 corollary). Next free is **U48 · D17 · P34**, so:

| ID | Card | Tier |
|---|---|---|
| **U48** | "It looks frozen" — runtime stall advisory (**graduates P17**) | 1 |
| **U49** | Self-service first run — picker/selector defects, direct-launch flags, board-name repair | 1 |
| **U50** | Student-error diagnostics — hint coverage, caret preservation, `--doctor` | 1 |
| **U51** | Multi-file designs — sibling-file analysis | 2 |
| **U52** | Learn-by-example — target-board native references + a combinational rung (**graduates P11**) | 3 |
| **D17** | `sim_bridge.py` decomposition + a single repo-path helper | 1 |
| **P34** | Three-way renderer convergence (pygame / SVG / capture) | Icebox, no trigger yet |

PR 0 also **renumbers the queue — peripherals → v0.24.0, D16 sandbox → v0.25.0 — across all ~8
sites**, and refreshes *Current focus*. Doing it up front means the roadmap does not lie for three
weeks. Next free afterwards: **U53 · D18 · P35**.

---

## 6. Schedule

Honest capacity: three weeks *with teaching in them* is **~9–11 focused days**; the work below is
**~12–13**. The cut order in §9 is therefore part of the plan, not a contingency.

```text
Day 1     Gate A    soak-0 on real lab files + clean-machine install   (no code)
Week 1    PR 0-4    cards · direct launch · the refactor · first-run fixes
Week 2    PR 5-8    frozen board · errors · multi-file · doctor         Gate B
Week 3    PR 9-12   examples · docs · board names · release
```

Two ordering choices worth stating explicitly:

- **Gate A is day 1, before any code.** The soak is the only mechanism that finds
  unknown-unknowns; running it *after* a week of fixes chosen without it wastes it. It also
  produces the factual install matrix that `--doctor` has to encode.
- **The `sim_bridge.py` split is PR 2, not the end.** Its correct slot is *immediately after a
  release and before an arc* — which is exactly now (v0.22.0 shipped 2026-09-04). Doing it while
  nothing else is in flight means the 2,479-test net is uncontended, every later PR edits the
  smaller modules, and a failure shows up on day 3 rather than day 18.

**Tag the release ≥ 4 days before lab 1.** The tag is what surfaces the last problems.

### Gate A — soak-0 and install rehearsal (day 1, no PR)

1. **Real files.** Run 5–8 *actual course lab* `.vhd` files, board-native, on DE10-Lite / DE0-CV /
   DE1-SoC / ULX3S. Mechanical half: `uv run fpga-sim --benchmark N --screenshots DIR` (it drives
   the real `SimulationScreen` and the product renderer, so stills show true duty/RGB/scan
   brightness). Judgment half: the interactive app, for UX and course alignment.
2. **Clean machines.** Install from a clean clone on a Windows laptop and a macOS laptop following
   `docs/install.md` verbatim, recording what happens at each step. `install.md:316` already admits
   `winget install ghdl.ghdl.ucrt64.mcode` may not exist and the fallback is an 8-step MSYS2 detour
   in a shell that cannot see PowerShell tools — **pre-flight that package now, not the week of the
   lab.**

**Output:** a ranked defect list that *supersedes* §4 where they disagree, plus the install matrix.
Re-order PRs 3–12 against it before starting.

### Gate B — soak-1 confirmation (end of week 2, 0.5 d)

Re-run Gate A's lab files. New findings are **triaged, not automatically fixed**; anything M+ goes
to the post-semester queue rather than into week 3.

---

## 7. The PRs

Each: feature branch (never commit to `main`), CHANGELOG entry, and
`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`
before every commit. UI/render PRs additionally get screenshots and Rick's visual review before
merge (the standing carve-out from merge-on-green).

---

**PR 0 — arc cards + version renumber.** 0.5 d · low risk
Commit this plan document; file U48–U52, D17, P34; update *Current focus* and *Next — in order*;
renumber peripherals → v0.24.0 and D16 → v0.25.0 everywhere; record the new ID allocation; add a
row to the *Plan documents index*.
*Files:* `docs/improvement_roadmap.md`, `docs/u48_classroom_arc_plan.md`.
*Done when:* the roadmap describes the arc that is about to run, and `grep -rn "v0.23.0" docs/`
refers only to this arc.

---

**PR 1 (U49) — direct launch into the interactive app.** 0.5 d · medium risk
Drop "benchmark mode only" from `--board` / `--vhdl`; seed `ScreenController.run()`'s start state
through the existing `on_board_selected()` / `on_vhdl_loaded()` entry points (F9).
**First in the arc, because it makes every later soak iteration and manual test ~10× faster** —
and it gives lab machines a one-click desktop shortcut, which serves D-4 directly.
*Files:* `src/fpga_sim/__main__.py:50-99,136-137`, `src/fpga_sim/controller.py:322`, tests.
*Risk:* the launcher state machine. A test **must** assert the no-flag path still enters
`NextScreen.SELECTOR`.
*Done when:* `uv run fpga-sim --board DE10LitePlatform --vhdl ~/lab1/top.vhd` opens on the preview
with the file loaded and validated; the no-flag path is byte-for-byte unchanged in behavior.

---

**PR 2 (D17) — `sim_bridge.py` decomposition.** 1.5–2 d · medium risk, **de-risked as follows**
Two decisions make Rick's chosen refactor (D-6) safe:

1. **Split into sibling modules in `fpga_sim/`, not a subpackage.** A `fpga_sim/sim/` package
   would change every module's depth and silently break the four `parent.parent.parent` constants
   in F13 — two of them on the exact path a student's file travels. Flat siblings keep the depth,
   and the landmine never arms. (A subpackage would also collide conceptually with the top-level
   `sim/` directory, which is on the child process's `PYTHONPATH`.)
   Proposed modules: `sim_backends.py` · `sim_discovery.py` · `vhdl_contract.py` ·
   `conventions.py` · `wrapper.py` · `waveform.py` · `sim_runner.py`, with `sim_bridge.py` left as
   a **re-export shim** so all 46 import sites across 35 files keep working unchanged.
2. **Land `fpga_sim/paths.py` first, in the same PR.** One `REPO_ROOT` (plus `HDL_DIR`,
   `BOARDS_DIR`, `SIM_DIR`) replaces the nine fragile `parent.parent.parent` chains across five
   files. Same bug class everywhere; a genuine quality win in its own right, and it makes the split
   mechanical rather than delicate.

*Done when:* no module exceeds ~800 lines; `ruff`, `mypy` and the **full** `pytest` — including the
slow GHDL and NVC jobs, which are what actually exercise `_WRAPPER_TEMPLATE` and
`_DUTY_FRAGMENT_DIR` — are green; CI green on all four platforms.
*Revisit criterion:* if Gate A produces a long defect list, drop this to v0.24.0 (it is already
carded there) and take the §7-cheap alternative — a section map atop `sim_bridge.py` — instead.

---

**PR 3 (U49) — `hdl/` hygiene + picker defaults.** 0.5 d · low risk
`git mv hdl/bad_*.vhdl tests/fixtures/hdl/` — a **move**, not a picker filter, so `hdl/` becomes an
actual curriculum directory (F1). Repoint the three test modules and the one docs-plan line.
Preselect the example on a fresh profile (`controller.py:440-443` already has the machinery; use
`example_vhdl_for(board)`). Stop resetting the picker to `_HDL_DIR` on a validation retry
(`controller.py:451`, F10). Add the existing `draw_help_button` (`ui/help_dialog.py:283`) to the
VHDL picker and the simulation screen, which have F1/`?` handlers but no visible trigger.
*Watch:* the encoding guard (`scripts/check_encoding.py`, `tests/test_encoding_guard.py`) picking up
the BOM fixture at its new home.
*Done when:* `ls hdl/` shows only teaching designs; a fresh-profile launch lands with `blinky.vhd`
selected; a failed validation re-opens the picker in the student's own directory.

---

**PR 4 (U49) — board selector.** 0.5 d · low risk
Add the missing `"name"` sort branch; match `b.vendor` in the filter text; default `hovered = 0`,
guarding an empty `_filtered()` (F6). Ride along: extract the byte-identical scroll helpers from
`board_selector.py:277-292` and `vhdl_picker.py:147-162` into `ui/_scroll.py` (F15) — 30 mechanical
minutes while the file is already open, covered by the existing suite.
*Done when:* the default list is alphabetical; typing `terasic` returns the Terasic boards; Enter
selects on a fresh profile; both list screens scroll from one implementation.

---

**PR 5 (U48) — "it looks frozen."** 1.5 d · medium risk · **the most important functional change**
Ship *runtime observation*, not a static lint and not an automatic override:

1. **Detect.** No boundary LED/segment bit has changed for T wall-seconds **while simulated time is
   advancing**. The second clause is what distinguishes a slow divider from a hung or crashed
   child. Nearly free: `visual_signature()` (`ui/board_display.py:1003`) is already compared every
   frame by U23's redraw gate — it needs an *output-only* variant so a switch flip does not reset
   the timer. Zero false positives by construction: a legitimately slow signal *is* the thing the
   student needs told about.
2. **Say it with arithmetic** — the numbers are the teaching moment:
   > No output has changed in 10 s. The simulator has run ~1.9 M clock cycles (≈38 ms of simulated
   > 50 MHz time). A design dividing by 2²⁴ needs 16.7 M cycles ≈ 88 s here.
   > **[Switch to NVC (~8× faster)]** **[Why is my board dark?]**
3. **Offer the lever that already exists.** The simulator picker shipped (U35) and
   `controller.py:84-85` already encodes NVC ≈ 8× GHDL (`_COUNTER_BITS_FLOOR = {"nvc": 20}`, i.e.
   +3 bits). 88 s → 11 s is the difference between "broken" and "slow but alive." Costs nothing new.
4. **Document the real fix** in `docs/troubleshooting.md` (PR 10): hoist the divider constant to a
   generic whose **default is the real-hardware value**, so the board keeps 2²⁴ and a simulator can
   pass less. That is good VHDL practice worth teaching, it mirrors the generic contract exactly,
   and it makes an explicit opt-in override useful later without any heuristic.

*Files:* `ui/simulation_screen.py`, `ui/sim_panel.py`, `ui/board_display.py`, `controller.py`, tests.
*Risk:* touches the live run loop; the "sim advancing" clause must not fire on a genuinely hung child.
*Done when:* a DE10-Lite native design with a 2²⁴ divider raises the banner within ~10 s with
correct arithmetic; the mid-bit-tapping `hdl/native/*.vhd` never do; the NVC action works.

---

**PR 6 (U50) — error hints + caret preservation.** 0.5 d · low risk
Widen the `std_logic` regex at `sim_bridge.py:1698` to `unsigned|signed|to_unsigned|to_integer` →
"add `use ieee.numeric_std.all;`"; add hints for a syntax error ("check the end of the previous
line"), an undeclared identifier, and entity-not-found-in-`work` (F4). Stop `.strip()`ing leading
whitespace in `ErrorDialog._draw` so GHDL's `^` lands under the offending column, and add
copy-to-clipboard (F5). Purely additive regex + tests; near-zero regression risk; aimed straight at
the 11 pm student.
*Done when:* `tests/fixtures/hdl/bad_semantic_blinky.vhdl` produces a `numeric_std` hint on **both**
GHDL and NVC, and a caret-bearing diagnostic renders aligned.

---

**PR 7 (U51) — multi-file designs.** 1.5 d · medium risk · **scoped down deliberately**
Rick chose to ship this in-arc (D-5). The *full* version is an L arc of its own: picker
multi-select, a **new toplevel-selection screen** (needed because `toplevel = Path(vhdl_path).stem`
today), plural `SessionState` paths, and GHDL `-m` vs NVC's lack of it. The 90% that fits now needs
none of that:

> The student still picks **one** file — their top level. The simulator additionally analyzes the
> sibling `.vhd`/`.vhdl` files **in the same directory** first, then the picked file last.

- **Ordering, backend-symmetric.** Analyze all siblings; collect the ones that fail on an
  unresolved reference; retry; repeat until no progress. Converges in ≤ N passes and behaves
  identically on GHDL and NVC — no `-i`/`-m` asymmetry to maintain.
- **Sibling failures are non-fatal.** Only the picked toplevel must analyze and elaborate, so an
  unrelated or broken neighbor in the folder is simply skipped. This is what neutralizes the
  "a stray file breaks everything" objection.
- **No signature churn.** Call the existing `analyze_cmd(path, work_dir)` once per file in a loop —
  no change to the three backends, no ripple through 46 import sites.
- **[Reload VHDL] must re-analyze the whole set.** Staleness is keyed on simulator identity plus a
  wrapper-content diff (`SessionState.needs_reanalysis`, `controller.py:167-190`), not on source
  mtime — so editing a sibling is picked up via the toolbar's reload path, which is the student's
  route after an edit. Make that explicit in the code and the docs.

*Done when:* a folder holding `top.vhd` + `counter.vhd` + `seg_decoder.vhd` runs by picking
`top.vhd`; a broken unrelated `.vhd` alongside does not block it; the rule is documented in
`writing_designs.md` and `troubleshooting.md`.

---

**PR 8 (U50) — `fpga-sim --doctor`.** 0.5 d · low risk · **gated on Gate A**
Reuse `discover_simulators()` (`sim_bridge.py:507`); print Python / uv / pygame-ce / cocotb
versions, every discovered simulator (label, backend, version, path), the board count, and the
result of one real headless analyze of a bundled design against a bundled board; exit non-zero on
failure. Then replace the "run `uv run pytest`" install check in `README.md:85` and
`docs/install.md:216`, and fix the `install.md:209` dev-deps contradiction (F8).
Looks XS; is really "encode the install matrix across 3 OSes × 4 GHDL backends + NVC" — hence the gate.
*Done when:* `uv run fpga-sim --doctor` prints a pass/fail matrix on all three OSes and both docs
point at it instead of the test suite.

---

**PR 9 (U52) — examples that match the target boards.** 1 d · low risk
`hdl/native/` covers none of the seven target boards (F11). Add:

- a **DE10-Lite** reference — `MAX10_CLK1_50` / `SW(9:0)` / `KEY(1:0)` / `LEDR(9:0)` / `HEX0..HEX5`,
  KEY and HEX active-low, tapping *mid* counter bits per the existing scan-rate rule, and
  demonstrating the divider-as-generic pattern PR 5 documents;
- a **Tang Nano 9K** reference — canonical `sipeed`: `sys_clk` + 6 active-low LEDs, **no switches or
  buttons**, so it also exercises the U31 partial-interface tie-off.

Add the missing **combinational rung**: every `hdl/*.vhd` uses `rising_edge`, so lab 1 in
essentially every VHDL course has no example. Ship `gates.vhd` (switches → LEDs through
AND/OR/XOR/NOT) and `hex_decoder_7seg.vhd` (the archetypal `case` decoder); add `traffic_light.vhd`
(P11) only if time allows. Register them in `writing_designs.md`'s example table, and **link
`hdl/blinky_survey.md`** from `README.md` and `writing_designs.md` (F12).
*Slack item:* P13's waveform retention sweep + an end-of-run size line, if the day has room.
*Done when:* each new design analyzes, elaborates and animates on its own board under **both** GHDL
and NVC, with tests alongside the existing `tests/test_native_*` pattern.

---

**PR 10 — documentation.** 2 d · low risk · **the highest-ROI docs work in the arc**

- **`docs/first_design.md`** — the tutorial that does not exist: install → launch → pick a board →
  load a complete file → see it blink → change one line → reload → read an error. Source material to
  lift: the `.adoc` decks' "Blinky, Line by Line" (`virtual-fpga-boards.adoc:779-830`) and
  `hdl/blinky_survey.md`. Written for the take-home student, not for a lab.
- **`docs/troubleshooting.md`** — entity/filename mismatch; missing `numeric_std`; a syntax error;
  **"my board is dead"** (PR 5's arithmetic + the divider-as-generic fix); "my file is for a
  different board" (the near-miss message); active-low surprises; the multi-file rules from PR 7;
  where waveforms go and how large they get.
- **`git mv` the 13 completed delivery plans to `docs/plans/`** with a `docs/README.md` index, so
  the five student-facing docs are visible (F16). Fix inbound links.
- **README re-aim:** one line above the fold pointing a newcomer at `first_design.md`; move the
  CI-matrix paragraph (`README.md:11-14`) below the value proposition.
- **Two lines that retire a whole class of confusion:** a sentence in `docs/architecture.md` saying
  `(U##)` / `(D##)` markers cite `docs/roadmap_delivered.md`, and a section map atop the
  `sim_bridge.py` shim.

Per D-7, **the two `.adoc` talk decks stay untouched** — they are clearly dated March-2026 talk
artifacts and their stale counts are an accepted, deliberate state.
*Done when:* a reader who has never seen the repo can go from clone to blinking LED using only
`docs/first_design.md`, and `ls docs/*.md` shows ≤ 10 entries.

---

**PR 11 (U49) — board display names.** 1 d · **HIGH risk — isolate, and it has an abort criterion**
16 mangled names, two in target families (F7).

**Step 1 is a pre-flight, not the fix.** Run `scripts/check_board_drift.py` *unmodified* and prove
a byte-identical no-op re-sync. It re-syncs every generated source in place at its pinned commit
and **runs in CI**, so if it surfaces unrelated drift you inherit that cleanup mid-arc and every
subsequent PR goes red.

> **Abort criterion — if the no-op is not clean, stop.** Apply a curated display-name override
> table at load time in `board_loader.py` instead, sidestepping the generated data entirely.

Only on a clean pre-flight: extract **one shared prettifier** (don't split digit→capital, strip
dangling separators, acronym table for `SoC` / `ULX3S` / `EV` / trailing `F`), replacing the two
copies at `amaranth_parser.py:584` and `litex_parser.py:467`, plus Digilent metadata entries for the
two `Genesys ZU-*`. Add a **data-level guard test** over every board JSON — no standalone single
capital as a word, no leading/trailing separator — which catches all three sources regardless of
which parser produced the name. Then re-sync in place at the recorded pins:
`uv run python scripts/sync_amaranth_boards.py --ref <source_commit> --output-dir boards/amaranth-boards`
(the SHA is in each `_sync_metadata.json`; supplying it directly avoids the unauthenticated API
rate limit that reads as false drift).
*Done when:* `DE1-SoC` and `ULX3S-45F` read correctly, the guard test passes,
`check_board_drift.py` is green, and CI stays green.

---

**PR 12 — release v0.23.0, "the classroom release."** 0.5 d · low risk
Version bump in `pyproject.toml`; **`uv.lock` re-sync after the bump**; CHANGELOG `[Unreleased]` →
`[0.23.0]` (it already carries six entries from U47 and the render-cache work); card closeouts in
the roadmap; confirm PR 0's renumber still holds; short GitHub release notes (highlights +
one-liners, linking the CHANGELOG for detail).

---

## 8. Explicitly out of scope, and why

- **U39–U41 peripherals → v0.24.0.** Nine phases, one L-risk phase (Phase 3), serving the *in-lab*
  experience the courses already have in hardware. Plan stays approved and unstarted at
  [u39_peripherals_plan.md](u39_peripherals_plan.md).
- **Docs & Assets round 2 PRs 3–5 → with peripherals.** PR 3 is a *renderer refactor* wearing a
  docs label (it retires `sim/capture_frames.py`'s third, binary-LED renderer under decision A2)
  and PR 5 is new visuals. **Neither is needed for this arc:** round-2 PR 2 (#389) already put
  `--screenshots` on the product renderer, so **true-brightness stills are available today**, and
  stills are what a handout, an LMS page and `docs/` actually need. Round-2 **PR 4** (GIF
  re-capture) and **PR 6** (regeneration procedure) plus **#388** (screenshot manifest) ride along
  only if week 3 has slack.
- **#354 GHDL-Cosim doc offer.** Gated on the full asset refresh; stays gated.
- **D16 sandbox → v0.25.0.** The interim README/user-guide warning shipped 2026-08-05, and the
  threat model is a *downloaded* design — these students run files they wrote themselves.
- **Renderer convergence → P34** (F14). Real duplication, already caught drifting once, but it is a
  three-way convergence, M–L, and invisible unless someone diffs the files. Students look at board
  images, not at renderers.
- **The F16 housekeeping trivia** (dead `# noqa`s, the duplicated `pyproject.toml` lists, the unused
  `ui` marker, the no-op `conftest.py` insert, `py.typed`, `__all__` ordering, `get_switch_state`,
  keyword-only booleans). All correct, all cheap — bundle into one post-release housekeeping PR
  unless week 3 has room.
- **Relaxing the generic contract** (making `clk` / `btn` / `sw` optional so a combinational design
  need not declare a clock). Tempting, but Rick's students arrive with **board-native** files where
  partial interfaces are already supported (U31), so the value here is low relative to the churn.
- **Other carded quick wins — U15, U16, U17, U19, D5, D12, D13.** Correct findings, no semester
  value. They stay carded as between-arc filler.

---

## 9. Cut order if three weeks becomes two

Cut in this order; nothing below the line changes.

1. **PR 11 (board names)** — worst risk-to-effort ratio in the plan, and it can red-line CI for
   every other PR. `DE1 So C` is embarrassing; it is not blocking. Keep the card.
2. **PR 9's example set** reduced to the DE10-Lite native reference alone.
3. **PR 10** reduced to `troubleshooting.md` + `first_design.md`; no `docs/plans/` move, no README
   re-aim.
4. **PR 8 (`--doctor`)** — *unless Gate A shows the install is genuinely broken on Windows or
   macOS, in which case it is promoted to must-have and PR 7 slips instead.*
5. **PR 7 (multi-file)** — ship the documented one-file rule instead: *"paste your sub-entities
   above your top-level entity in one file"* is a **supported** path, not a hack (the contract
   accepts any file whose stem matches one of its entities, `sim_bridge.py:1616-1630`). Take the
   real feature post-semester, when there will be actual multi-file lab projects to test against.
6. **PR 2 (the `sim_bridge` split)** — the one judgment call to revisit if Gate A turns up a long
   defect list. It is the arc's largest non-student-facing item; its value is the impression a
   code-reading student forms, and PR 10's section map recovers much of that in minutes. Dropping
   it to v0.24.0 costs nothing — it is already carded there.

**Never cut:** PR 0 (convention), **Gate A** (the only source of truth about reality), PR 1, PR 3,
PR 4, PR 5/U48, PR 6, PR 12.

That reduced set is ~7.5 days and still delivers the whole thesis: *a student alone at 11 pm opens
a clean file list, finds their board by name, gets a hint instead of a raw compiler dump, and is
told — with numbers — why their real lab design looks dead.*

---

## 10. Verification

Per PR: `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`.

Arc-level, end to end:

1. **Fresh-profile walkthrough.** With `~/.fpga_simulator/` removed: launch, select DE10-Lite by
   keyboard alone, load a design, run it, hit an error deliberately, recover. No `bad_*` file
   visible; Enter works on first run; the picker returns to the student's own directory.
2. **The real-file test.** An actual student-shaped DE10-Lite Quartus top with a 2²⁴ divider must
   raise the stall banner with correct cycle arithmetic within ~10 s, and the **[Switch to NVC]**
   action must make it visibly animate.
3. **The multi-file test.** A folder of `top.vhd` + two sub-entities runs by picking `top.vhd`,
   including with a broken unrelated `.vhd` alongside.
4. **Fleet sweep.** `--benchmark N --screenshots DIR` green across the seven target boards on both
   GHDL and NVC, reviewed as a contact sheet.
5. **Install rehearsal, repeated.** Re-run `docs/install.md` verbatim on clean Windows and macOS
   profiles after PR 8, ending at `fpga-sim --doctor`.
6. **Board data.** `scripts/check_board_drift.py` clean; `tests/test_docs_board_counts.py` green
   after the doc edits.
7. **CI.** All 25 checks green per PR across 4 platforms × 3 Pythons × 5 simulator jobs.

---

## 11. Open at execution time

- **The stall threshold T** in PR 5 (10 s? 15 s?) and whether the banner is dismissible per run or
  per session. Decide against Gate A's observations, not in advance.
- **Whether PR 9 ships `traffic_light.vhd`** (P11). Its trigger has fired, but the Icebox card's own
  counter-argument — example sprawl next to `stopwatch_7seg.vhd` — still stands; the combinational
  rung is strictly more valuable for lab 1.
- **Whether P13's waveform retention** lands in PR 9's slack or is deferred. Real risk on quota'd
  student home directories (42–119 MB per 1–2 s run, accumulating, no sweep), but not a lab-day
  blocker.
- **Whether `--doctor` should also probe write access** to `~/.fpga_simulator/` — likely yes on
  shared lab machines, but confirm against Gate A.
