# Pre-semester "classroom" arc — U48–U54 + D17 → v0.23.0 (v2)

*v2 · Revised 2026-09-05 after Rick's review of the v1 draft and inspection of the real course lab
material · Status: **EXECUTING** — approved 2026-09-05; PR 0 ✅ (cards U48–U54 + D17 + P34
filed, the queue renumbered — peripherals → v0.24.0, D16 → v0.25.0 — and this plan committed);
PR 0b ✅ (the plans moved here, `docs/README.md` written); Gate A soak half ✅ (§4.1);
PRs 1–6c ✅ merged 2026-09-06 — U50 Synopsys acceptance, U49 first-run and board-selector repair,
D17 split + `paths.py`, and **U53, the pin map, working end to end**; then the folder contract
(D-16) ✅, the DE2-115/VEEK-MT2 display pins (D-17) ✅, `install-docs.yml` (D-19) ✅ — which found
`brew install ghdl` broken since 2026-09-01 and `uv sync` broken on Python 3.14 — and **U51** ✅
(D-5 reversed); **PR 7 + PR 8** (U48 advisory + [Generics…]) ✅, **PR 9** ✅ (hints/caret, #420) and
**PR 10** ✅ (`--doctor`, un-gated by D-19) — which closes **U50**; **PR 11** ✅ (#425, five
lab-shaped references + two natives) — which closes **U52**; **PR 12** ✅ (`first_design.md` +
`troubleshooting.md`, and the FST-first waveform default that resolves **P13** / **P14**).
**Next: PR 13** (board display names) · PR 14 (release) · Supersedes
[u48_classroom_arc_plan.md](u48_classroom_arc_plan.md) (v1, kept as the record of how the arc was
first framed) · Companion to [improvement_roadmap.md](../improvement_roadmap.md)*

> **How to use this document.** It is written to be executable from cold by a later session. §1.1
> is the ground truth about the course's files — read it before anything else. §2 records decisions
> already made so they are not relitigated. §4 is the evidence map; every claim carries a
> `file:line` verified on 2026-09-05 at `main` = `3213b39` — re-verify before touching code, the
> codebase moves. §7 is the PR list; §9 is the cut order, which is part of the plan, not a
> contingency. **This is a living document:** when execution teaches something, edit the affected
> section and add a line to the revision log (§12). PR 0 commits this file; PR 0b moves it, with the
> other plan documents, to `docs/plans/`.
>
> **Two standing rules for everything this arc writes.** (1) **US English**, in docs, plans, source,
> comments, and identifiers (`normalize`, `color`, `analyze`, `gray`); the suite-level guard
> `tests/test_us_spelling.py` scans every tracked file, and the arc extends its word list rather
> than working around it. (2) **Every PR lists the docs it touches** (README, `docs/*.md`, in-app
> help, CLAUDE.md, CONTRIBUTING, CHANGELOG `[Unreleased]`) before it opens — the standing PR-prep
> checklist, restated here because Rick asked for it explicitly in review.

---

## 1. Context

The first VHDL/FPGA lab session is in **~3 weeks** (from 2026-09-05; first lab ≈ 2026-09-26).
Rick's framing decides everything in this plan:

> "The labs with the real FPGA boards are all outside of this project. A primary goal of this
> project is to give students a tool they can use **outside of the lab** to practice and validate
> their VHDL files" — and, added in review, to use **alongside the tools available within the lab**.

**The user to design for** is a student alone at 11 pm with the `.vhd` file (and the Quartus or
Vivado project folder around it) they wrote for their real lab board, checking it works before the
session — no TA, no instructor, no handout. Some of them are accomplished programmers who will read
this repo's source and judge it.

**Target boards** (Rick, 2026-09-05, revised in review). First: the **Terasic DE10-Standard** —
the board the course's own lab material is written for (Cyclone V SoC `5CSXFC6D6F31C6`; the lab
`.qsf` files name it) — and the **Digilent Basys 3**, which "that particular course may use".
Then the rest of Rick's fleet: DE10-Lite, DE0-CV, DE1-SoC, DE2-115 (Intel/Terasic) and iCEstick,
Tang Nano 9K, ULX3S (Lattice/Gowin/small). v1's "*not* Digilent/Xilinx" is withdrawn: the Basys 3
is the repo's best-covered family (canonical `digilent` conventions in
`boards/digilent-xdc/basys_3.json`, the U22 scan reference `hdl/native/basys3_scan.vhd`).

**Install path:** both pre-installed lab machines **and** students' own laptops (Windows, macOS,
Linux). Student machines run at "all speeds" (Rick) — different hardware, OS, and background load —
so **every timing number the tool shows must be measured on that machine, never assumed**, and the
docs must explain why the simulator is slower than the hardware and by how much (§2 D-15).

That reframes the work away from *features* and toward **self-service**: it must install, it must
load *their* file **from wherever they keep it**, it must say what is wrong when it does not, and it
must not look sloppy. The queued U39–U41 peripherals arc serves none of that and nothing has a hard
dependency on it ([dependency table](../improvement_roadmap.md#dependency-table)), so it is postponed by
one release. Docs & Assets round 2 PRs 3–6 were deferred *specifically* so the asset re-capture
happened once, after peripherals; postponing peripherals removes that reason, and round-2 PR 2 (#389)
already put `--screenshots` on the product renderer, so true-brightness stills exist today — the
docs work in this arc needs none of PRs 3–6.

### 1.1 What the course files taught us (day 0 of Gate A, 2026-09-05)

Rick supplied the first three labs of the course (instructions + the example Quartus projects +
one sub-entity). Reading them replaced v1's central assumption. Everything below was verified by
running the files through GHDL and NVC on 2026-09-05.

| Lab | What the student gets | Ports of the top level | Libraries | The visible-rate idiom | Task the student must add |
|---|---|---|---|---|---|
| **1** | `test_entity.vhd` + `testbench.vhd` + `.qsf`/`.qpf` (DE10-Standard) | `clock`, `reset`, `button(2 downto 0)`, `sw(9 downto 0)`, `led_r(9 downto 0)`, `hex(27 downto 0)` — **four 7-segment digits packed into one vector** | `std_logic_1164` + **`std_logic_arith` + `std_logic_unsigned`** | none (combinational: sw → hex three ways; `led_r(7..0) <= … & button & clock & reset` — one LED shows the raw clock) | one more switch → display 0–F |
| **2a** | running lights, same shape | `clock`, `reset`, `key(2 downto 0)`, `sw`, `led_r`, `hex` | same | **`generic CNTR_LEN : integer := 24`** divides the clock; the testbench passes **4** via `generic map` | — |
| **2b** | security-lock FSM | same as 2a | same | none (buttons drive the FSM; `RESET is key[3]`) | new unlock code 011022 |
| **3** | tasks only + `counter.vhd` (a **separate sub-entity** with an `integer` output port) | student's choice, mapped to SW/LEDR/HEX | (the sub-entity uses `std_logic_arith`) | "use an auxiliary counter to divide 50 MHz to ~1 Hz" | function selector · 0–255 → two digits · 99 → 0 countdown; **"for all tasks design also a testbench"** |

**How the port names become board pins.** Not by name. The course imports a pin-assignment CSV into
Quartus, so the project's `.qsf` carries `set_location_assignment PIN_AF14 -to CLOCK`,
`PIN_AA15 -to RESET` (= the board's KEY[3]), `PIN_AA24 -to LED_R[0]` …, `PIN_AB30 -to SW[0]` …,
`PIN_W17 -to HEX[0]` … `PIN_AD20 -to HEX[27]` (= HEX0..HEX3's 28 segment pins, digit 0 first), and
`KEY[0..2]` → `PIN_AJ4/AK4/AA14`. **Those are exactly the pins `boards/custom/de10_standard.json`
records** for its clock (`AF14`), LEDs (`AA24`, `AB23`, …), switches (`AB30`, …) and buttons
(`AJ4`, `AK4`, `AA14`, `AA15`). The 7-segment pins are the one thing the board JSON does **not**
carry (F18).

**What the simulator does with these files today.**

- **GHDL (the default backend): analysis fails** —
  `error: use of synopsys package "std_logic_arith" needs the -fsynopsys option` — because
  `_GHDLBackend.analyze_cmd` passes `-a -O2 --std=08` and nothing else (`sim_bridge.py:232-237`).
  Elaboration needs the flag too (verified: `-e` without it fails after an `-a` with it). NVC accepts
  the packages. (F17)
- **Either backend, after that: contract near-miss.** The ports are neither the generic contract
  (`clk/sw/btn/led/seg` + `NUM_*`) nor the DE10-Standard's canonical `terasic` names
  (`CLOCK_50/SW/KEY/LEDR/HEX0..5`), so `check_vhdl_contract` rejects the file with a naming message.
  The student cannot run a single unmodified course file. (F18)
- **Lab 2a would render a dead board** even once loaded: 2²⁴ cycles per step is minutes per LED
  step at simulator throughput. (F2)
- **Two of the three course testbenches do not compile as shipped** (Labs 1 and 2b:
  `port map (…, open, open, open)` — seven actuals for six ports; GHDL and NVC both reject them).
  They sit beside the design in the same folder. Any sibling-file mechanism must therefore treat a
  broken neighbor as *irrelevant to the picked design*, never as fatal. (F19)

### 1.2 The structural facts that set the priorities

1. **The port mapping lives in the student's constraint file, not in the board's naming
   convention.** U21 board-native mode matches *names*; this course names ports freely and lets the
   `.qsf` (Basys 3: `.xdc`) bind them to pins. The general mechanism is a **pin map**: parse the
   constraint file, look each pin up in the board JSON, generate the wrapper from the result. The
   repo already has the parsers (`scripts/port_convention_parsers/{qsf,xdc,pcf,cst,lpf,ucf,ccf,
   boardstore_xml}.py`) and the pins (every board JSON's `leds[].pins`, `switches[].pins`,
   `buttons[].pins`, `clocks[].pin`). This is the arc's centerpiece, **U53**.
2. **Synopsys packages are the course's dialect.** They are non-standard and generally discouraged
   in favor of `ieee.numeric_std`, but the instructor's own examples use them, so the tool accepts
   them and says so once, gently (D-10).
3. **The divider is a generic (or a big constant).** The course teaches `CNTR_LEN` as a generic and
   overrides it in the testbench; the simulator should offer the same lever, explicitly and opt-in
   (D-9), and explain the arithmetic when a board looks frozen (U48).
4. **Lab folders hold testbenches and sub-entities.** A picked design must run regardless of what
   else is in the folder (F19); multi-file itself is deferred (D-5), with the one-file rule
   documented.
5. **Students will not copy files under this repository** (Rick). Loading from an arbitrary
   location must be first-class: `--vhdl PATH` from any directory, drag-and-drop onto the window, and
   a picker that stays in the student's folder after a failed attempt (F10, F20).
6. **Time has two meanings and the tool must never blur them** (Rick): *simulated* (hardware) time
   vs *wall-clock* time. A student who "simulates 100 ms" must be told what that costs in wall-clock
   seconds and in waveform megabytes on *their* machine (D-15).

---

## 2. Decisions locked — do not relitigate

| # | Question | Decision |
|---|---|---|
| D-1 | Timeline | **~3 weeks** to the first lab (≈ 2026-09-26) |
| D-2 | Target boards | **DE10-Standard and Basys 3 first**, then DE10-Lite, DE0-CV, DE1-SoC, DE2-115, iCEstick, Tang Nano 9K, ULX3S (revised 2026-09-05 in review; v1 excluded Digilent) |
| D-3 | Where lab material lives | **Outside this project** — no `labs/`, no exercises, no verbatim solutions. **Refined 2026-09-05:** *lab-shaped* reference designs (same skills as Labs 1–3, different specifics) and a tool tutorial written in the labs' shape **are** in scope; they double as Gate A's soak material |
| D-4 | Install path | **Both** lab machines and students' own laptops |
| D-5 | Multi-file designs | **Reversed 2026-09-06 — U51 is back in this arc.** v2 deferred it to v0.24.0, traded for D-6, with U51 named the first item to pull back in. The trigger arrived: a *second* course (BI-PNO, Basys 3 + Vivado) whose student projects are multi-file to the core — nine sources plus five testbenches in one, six plus one in the other — and which is organized around testbenches rather than board I/O. The one-file rule ("paste sub-entities above your top level") does not survive contact with that material, and D-16 below makes the sibling set explicit anyway |
| D-6 | `sim_bridge.py` split | **Do the full split now**, PR 2 (reaffirmed 2026-09-05 with the trade above) |
| D-7 | The two `.adoc` talk decks | **Leave untouched this arc** |
| D-8 | How the pin map finds the constraint file | **Auto-detect** the single `.qsf`/`.xdc`/`.pcf`/`.cst`/`.lpf` beside the picked `.vhd`, show it on the preview, **plus `--pinmap PATH`** for the explicit case; fall back to the existing name matching when none is present |
| D-9 | Frozen-board lever | **Opt-in generic override:** a [Generics…] dialog on the preview listing the top level's generics with their defaults, plus `--generic NAME=VALUE`; folded into U48. Never automatic |
| D-10 | Synopsys packages | **Accept** (`-fsynopsys` on GHDL) **and show a one-line non-blocking note** recommending `ieee.numeric_std` |
| D-11 | Testbench runner ("run the course testbench, open the waveform") | **Card now (U54), build later.** Document the manual two-line GHDL/NVC recipe in `first_design.md` so students can do it today |
| D-12 | Plan documents | Move to **`docs/plans/`** (PR 0b), kept as the project's history; `docs/README.md` indexes both directories |
| D-13 | Spelling | **US English everywhere**, identifiers included; extend the guard's word list as new forms appear |
| D-14 | Waveform format | **FST is the default whenever capture is enabled**; VCD stays selectable; docs state sizes per simulated millisecond and where files go |
| D-15 | Time vocabulary | Every number the UI or docs show is labeled **simulated time** or **wall-clock time**; the stall advisory and the tutorial explain the ratio, measured on this machine |
| D-16 | Where the simulator reads a project from | **Our own folder contract — *one folder = one project* — instead of learning each EDA suite's layout.** Copy the design files and the `.qsf`/`.xdc` into one directory, pick the top level, and everything beside it is available to it. Rick's reasoning, and it is decisive: Vivado's layout is user-configurable and version-dependent, so chasing it is a losing game that we would lose again on the next release. The Vivado-specific discovery path drafted on 2026-09-06 is **withdrawn**. This is already what `discover_pinmap` does; the work is *documenting* it, plus saying so when a constraint file exists **nearby but not in the folder** — a teaching moment, never a guess |
| D-17 | Two more course boards | **DE2-115 and VEEK-MT2** join D-2's list (Rick, 2026-09-06). **VEEK-MT2 is electrically a DE2-115** — same EP4CE115, same Y2 clock, same LED/switch/button pins, eight digits — so one cited HEX source covers both. Both need `seven_seg.segment_pins` hand-authored before the pin map can target them |
| D-18 | The BI-PNO course's projects | **Not a gap to close in this arc.** Neither project was ever wired to a board: no source declares an LED, switch or segment port, no `.runs/` directory exists, and project 1's `.xdc` is untouched Digilent boilerplate binding names that appear in no design file. They need a student to write a board top level — a design exercise, not a tool feature. What they *do* need from us is **U51** (D-5) and, later, **U54**. Project 2 additionally wants PS/2, which is unmodelled |
| D-19 | How the install docs get verified | **A scheduled CI workflow, not a clean-machine rehearsal** (Rick, 2026-09-06). `.github/workflows/install-docs.yml` runs the *documented* commands verbatim on all three operating systems — including the F23 unknown, whether `winget install ghdl.ghdl.ucrt64.mcode` still resolves, which `ci.yml`'s pinned-zip job deliberately sidesteps. Non-blocking by design and never a required check. **This un-gates PR 10 (`--doctor`).** Known limit: a hosted runner is a clean *machine*, not a messy student's machine, and has no display — the troubleshooting half of `docs/install.md` stays a human job |

> **`D-n` is a decision in this table; `Dn` is a roadmap card.** The hyphen is the whole
> difference, and D-16/D-17 above now sit beside cards **D16** (simulator sandbox → v0.25.0) and
> **D17** (the `sim_bridge.py` split, shipped as PR 2). Read the hyphen.

D-3 (refined) and D-8/D-9 are the consequential ones: they are why this plan has a pin map and a
generics dialog instead of a curriculum, and why the example work (PR 11) is lab-*shaped* rather
than a teaching ladder.

---

## 3. Baseline — what is already good

Stated first because it sets how much budget goes to "code cleanup". Measured 2026-09-05 on `main`
at `3213b39`:

- `uv run ruff check .` → **All checks passed**; `uv run mypy .` (strict) → **Success, 174 files**
- **2,479 tests** across 90+ files; non-slow suite **green in 17 s**; zero `xfail`s; all 16 skips are
  environment gates; `pytest-randomly` enforces order independence
- **Zero** `TODO` / `FIXME` / `HACK` / `XXX`; zero commented-out code; zero bare `except`; zero
  mutable default arguments; test:source ratio **1.8:1**
- Docstrings complete by construction (`D` enabled repo-wide, only `D203`/`D213` off)
- CI: 4 platforms × 3 Pythons × 5 simulator jobs + board-data drift, all green
- A **US-spelling guard** already exists (`tests/test_us_spelling.py`, suite-level, whole-word list)

**A sharp student browsing this repo will be impressed, not dismissive.** The cleanup ask is a short
list (§4 F13–F16), so most of the budget goes to the student experience.

**The ruff/mypy exception audit Rick asked for** ("we shouldn't turn off what could be fixed").
Inventory from `pyproject.toml:82-153`, with the disposition:

| Exception | Verdict |
|---|---|
| `D203` / `D213` ignored | Keep — each conflicts with its enabled sibling (`D211` / `D212`) |
| `"tests/*" = ["ANN", "D"]` | Keep the docstring relaxation; **try** enabling `ANN` on one test module to measure the cost |
| Per-file `ANN` on the ten `sim/test_*.py` cocotb files, each listed by hand | **Collapse to one glob** (`"sim/test_*.py"`); try annotating one file — if the dynamic `dut` handles make it noise, keep the ignore with that reason recorded |
| `E501` on three fixture-bearing parser tests | Keep — verbatim constraint-file excerpts |
| mypy `ignore_missing_imports = true` (global) | **Narrow** to a per-module override list (pygame, cocotb, …) so a typo'd import is caught again |
| mypy override listing the same ten cocotb modules by hand | **Glob**, same as ruff |
| rumdl `MD013`/`MD036` | Keep — documented rationale in the file |

Lands in the post-release housekeeping PR (§7, PR H) unless week 3 has room; nothing stays off that
could be fixed.

---

## 4. Evidence map (verified findings)

Every line was checked directly on 2026-09-05. Re-verify before starting.

### Student-blocking

**F1 — The file picker's first seven entries are deliberately-broken fixtures.** `hdl/` contains
`bad_contract_7seg_extra_seg.vhdl`, `bad_contract_7seg_missing_seg.vhdl`, `bad_contract_blinky.vhdl`,
`bad_contract_fixed_width.vhdl`, `bad_contract_wrong_direction.vhdl`, `bad_encoding_blinky.vhdl`,
`bad_semantic_blinky.vhdl`, and `sorted()` puts all seven above `blinky.vhd`. `VHDLFilePicker._scan`
(`ui/vhdl_picker.py:48-63`) filters only dotfiles and non-`.vhd*` suffixes; a fresh profile has no
preselection (`controller.py:436-443` preselects only a previously-used file). README's own "Try it"
step 4 (`README.md:92-101`) walks a new user straight into this. Referenced from
`tests/test_vhdl_validation.py`, `tests/test_sim_bridge_errors.py`, `tests/test_nvc.py`, and one line
each of `docs/u35_simulator_picker_plan.md`, `docs/7seg_display_plan_v2.md`, `docs/roadmap_delivered.md`.
Rick: move or rename them so they never appear — a **move**, not a filter (PR 4).

**F2 — A real lab design renders a dead board with no message.** `build_generics`
(`controller.py:88-120`) floors `COUNTER_BITS` at **17** bits (**20** on NVC, `controller.py:84-85`)
precisely because a 24-bit divider is unwatchable at simulator throughput. **Board-native designs get
no such override** (`_render_native_wrapper` is generic-map-less by design, `sim_bridge.py:1846-1900`),
and a pin-map design will not either. The course's Lab 2a divides by 2²⁴ (`CNTR_LEN := 24`): 16.8 M
cycles per step, i.e. **minutes per LED step** on GHDL and still tens of seconds on NVC (~8× faster:
`_COUNTER_BITS_FLOOR = {"nvc": 20}`). Lab 3c's 50 MHz → 1 Hz divider is 50 M cycles per tick.
**Neither existing lever rescues it:** the speed slider is a *throttle* (`_SPEED_MIN`/`_SPEED_MAX` =
0.001–10× of *real time*, `ui/sim_panel.py:57-58`) and the virtual-clock preset changes only how much
*simulated time* an edge represents, not edges per wall-second. **Two things Rick flagged:** (a)
`COUNTER_BITS` and the generated wrapper are "mystery VHDL" to a student whose design has no such
generic — so the advisory must speak in the student's own terms (their generic's name, their
divider's size) and the docs must show what the simulator wraps around their file and where to find
it; (b) the course's own idiom *is* a generic override (`generic map (4, …)` in the testbench), so the
tool should offer exactly that lever, explicitly (D-9).

**F3 — Only one file can be compiled; folders hold more.** `analyze_vhdl` (`sim_bridge.py:2315-2365`)
runs exactly one `analyze_cmd(vhdl_path, …)`. Multiple design *units within one file* already work —
the contract checks `stem in [all entities found]` (`sim_bridge.py:1587` onward). Lab 3 ships
`counter.vhd` as a separate unit; every lab folder holds a `testbench.vhd`. This arc documents the
one-file rule (D-5) and keeps the pin-map/native paths indifferent to neighbors; U51 records the
full design (sibling analysis to a fixpoint, non-fatal siblings, `analyze_cmd` in a loop, [Reload]
re-analyzes the set) and its acceptance test: split `hdl/t80_walking_counter_7seg.vhd` at its ten
design-unit boundaries (package `T80_Pack` + nine entities, matching the six vendored files under
`scripts/embedded_core/cores/t80/` plus `cpu_rom`/`cpu_ram`/`cpu_io`/top) and run the walking-counter
suite by picking the top — Rick's suggestion, harder than anything a student will bring.

**F4 — Compiler errors are mostly unhinted.** `add_error_hints` (`sim_bridge.py:1682-1768`)
recognizes four patterns. Verified misses: missing `use ieee.numeric_std` / undefined `unsigned`
(the repo's own `bad_semantic_blinky.vhdl`; the sibling `std_logic` regex at `:1694` is one word
away), every syntax error, undeclared identifier, entity-not-found-in-`work`, and the course
testbenches' **"too many actuals for component instance"** / NVC "found at least 7 positional
actuals but … has only 6 ports". Rick: if a message can be useful, emit it — raw compiler output
stays, hints are added.

**F5 — GHDL's caret/column marker is destroyed.** `ErrorDialog._draw` (`ui/error_dialog.py:113-124`)
word-wraps with `raw_line.split(" ")` and `.strip()`, collapsing leading whitespace, so GHDL's `^`
lands alone at column 0. The font is already monospace (`ui/constants.py:54-61`). No
copy-to-clipboard either.

**F6 — Board selector defects.** `_filtered()` (`ui/board_selector.py:131-177`) has sort branches for
vendor / leds / switches / buttons / 7seg / total but **no `"name"` branch**, so the default "Name"
sort returns discovery order (source directory, then filename). The filter text matches only
`b.name` and `b.class_name` (`:134-136`), so `terasic` returns zero. `hovered = -1` on construction
(`:49`) with `K_RETURN` requiring `0 <= self.hovered` (`:266`), so **Enter is inert on first run**.

**F7 — Sixteen board display names are mangled, two in target families.** `_prettify_class_name`
(`scripts/amaranth_parser.py:584-591`) splits digit-then-capital and turns a trailing `_` into a
dangling `-`: `DE1SoCPlatform` → **`"DE1 So C"`** (the file is even named `de1_so_c.json`);
`ULX3S_45F_Platform` → **`"ULX3 S-45 F-"`** (four variants). Also `AX7325 B`, `Cora Z7-07 S`,
`Colorlight-5 A75 B-R70`, `Logicbone85 F`, `Orange Crab R0-2-25 F`, `Orange Crab R0-2-85 F`,
`TE0714-03-50-2 I`, `Genesys ZU-3EG-D`, `Genesys ZU-5EV-D`, `Sitlinv A E115fb`;
`scripts/litex_parser.py:467` is a second copy. Fixing the parsers means a re-sync that the CI drift
job (`scripts/check_board_drift.py`) must agree with — HIGH risk mid-arc; this arc takes the cheap
path (PR 13: a load-time override table).

**F8 — No health check; the documented smoke test is the whole suite.** `__main__.py:49-100` defines
eight flags, none a `--doctor` or `--version`. `README.md:81-86` and `docs/install.md:212-217`
prescribe `uv run pytest` (2,479 tests, `addopts = "-v"`, ~68 simulator subprocess tests) as the
install check. `docs/install.md:209` says `uv sync` installs runtime deps only and "contributors want
`--group dev`", while pytest *is* dev-only (`pyproject.toml:33-56`) — it works only because uv installs
`dev` by default. Rick: `--doctor` should also **say how to fix** each deficiency.

**F9 — `--board` / `--vhdl` are benchmark-mode only.** `ScreenController.run()`
(`controller.py:322-331`) always starts at `NextScreen.SELECTOR`; `_inapplicable_flags`
(`__main__.py:115-141`) merely warns. `on_board_selected(board)` (`:355`) and
`on_vhdl_loaded(vhdl_path, work_dir)` (`:493`) are already the entry points a seeded start needs.

**F10 — The picker forgets the student's directory on a validation retry.** `controller.py:451`
re-opens `VHDLFilePicker(self.screen, start_dir=_HDL_DIR)` on the non-first pick, so after *any*
error, [Try Another File] throws the student back to bundled `hdl/` — worst exactly when they are
iterating on a failing file.

**F11 — No lab-shaped example; native references cover one target board.** `hdl/native/` holds
`arty_litex`, `arty_rgb`, `basys3_scan`, `de0`, **`de10_standard`** (a target board — correction to
v1), `de25_standard`, `nexys4ddr_scan`; nothing for DE10-Lite, DE0-CV, DE1-SoC, DE2-115, Tang Nano,
iCEstick, ULX3S. **Every** `hdl/*.vhd` contains `rising_edge`: no `led <= sw`, no gates, no mux, no
`case`-statement 7-segment decoder, no labeled-states FSM — i.e. nothing shaped like Lab 1 or Lab 3a/b.
The ladder is 62 lines (`blinky.vhd`, already carrying four generics, `minimum()`, `mod`, a variable
and two processes) → 314 → 1,382 (generated soft CPU).

**F12 — No tutorial, no troubleshooting doc.** `docs/writing_designs.md` (356 lines) is a *reference*
opening at "three ways to write a design"; `docs/user_guide.md` (382 lines) is a feature reference.
Neither has a "your first design" walkthrough or a section on student errors. `hdl/blinky_survey.md`
(466 lines, twelve categorized blinky idioms, a blink-rate formula table, a column headed "Teaching
goal") is linked from **nothing**.

**F17 — GHDL rejects the course's Synopsys packages.** `_GHDLBackend.analyze_cmd` /
`elaborate_cmd` / `run_cmd` (`sim_bridge.py:232-278`) pass `--std=08` with no `-fsynopsys`; verified
error text in §1.1. NVC (`:312-353`) accepts them. GHDL mcode elaborates inside `-r`, so all three
commands need the flag; on the compiled backends it is harmless at `-r`.

**F18 — The port mapping is in the constraint file; the board data almost has what it needs.**
Verified pin-for-pin against the course `.qsf` (§1.1): `boards/custom/de10_standard.json` records the
clock (`clocks[0].pin = "AF14"`), all ten LED pins, ten switch pins, four button pins with
`inverted: true`. The same shape holds for `amaranth-boards/de10_lite.json` (`A8`/`C10`/`B8`, buttons
inverted), `digilent-xdc/basys_3.json` (`U16`/`V17`/`U18`…, clock `W5`, five named buttons
active-high). **Gap:** `seven_seg` carries only `num_digits / has_dp / is_multiplexed / inverted /
select_inverted` (`boards/schema/board.schema.json` `$defs.seven_seg`; `board_loader.py:28-35`) —
**no segment pins** — yet the course's `hex(27 downto 0)` is 28 segment pins. The sync parsers
already *see* the pins upstream and drop them: amaranth `_display7seg_resource` /
`_extract_sevenseg` (`scripts/amaranth_parser.py:234-269, 546-575`), litex `_build_seven_seg_def`
(`scripts/litex_parser.py:363`), Digilent `seg[i]`/`an[i]` parsing (`scripts/digilent_parser.py:468-503`).
The QSF `set_global_assignment -name DEVICE 5CSXFC6D6F31C6` line versus the JSON's `device` field
gives a precise "this project is for another board" check. The parsers live under `scripts/` and are
importable only through `tests/conftest.py:22` (`sys.path` insert) — the runtime package cannot use
them where they are.

**F19 — Broken neighbors.** Two of three course testbenches fail analysis as shipped (§1.1); Lab 3's
`counter.vhd` analyzes with a GHDL `-Whide` warning only. Whatever reads a folder must not let a
neighbor's failure block the picked design.

**F20 — No way in from an arbitrary location except browsing.** No `DROPFILE` handling anywhere in
`src/`; the picker (`ui/vhdl_picker.py`) has no path entry; `--vhdl` is benchmark-only (F9); the retry
resets to `hdl/` (F10). Rick: students will be reluctant to place files under the project directory.

**F21 — Time is shown without its meaning.** The stats panel shows **Sim time** (simulated), **Eff.
rate** (cycles per wall-second) and a speed slider labeled in multiples of real time
(`docs/user_guide.md:190-222`, `ui/sim_panel.py:4-12`), but nothing explains the two clocks, the
ratio on this machine, or what "simulate 100 ms" costs in seconds and megabytes.

**F22 — Waveform capture: FST exists, VCD is the fat one, retention is unbounded.** `WaveFormat =
Literal["vcd", "fst"]` (`sim_bridge.py:47-51`), Settings cycles off → VCD → FST
(`ui/settings_dialog.py:47-50`), default **off** (`session_config.py:27-28`), dumps accumulate under
`~/.fpga_simulator/waveforms/` with no sweep (`sim_bridge.py:2497-2558`). P13's numbers: 1–2 s runs
produced **42–119 MB** VCDs; FST is ~10–20× leaner (2–5 MB). P14: GHDL + VCD + Memories silently
dumps nothing. Rick: mention formats and sizes in the docs, default to the smallest.

**F23 — What Windows/macOS CI proves, and what it does not** (Rick's question). CI installs GHDL on
`windows-latest` from the **GitHub Releases zip** (`ci.yml:331-333`, `test-windows-ghdl`), on macOS
from **pinned release tarballs** (`ci.yml:240-284`) and NVC via **`brew install nvc`** (`:291-317`),
on Linux from pinned tarballs and `nickg/setup-nvc`. So the *toolchain* is proven on all three
OSes. **Not** proven: the `winget install ghdl.ghdl.ucrt64.mcode` path README and `install.md:316`
lead with (the package's presence "is not guaranteed"), the MSYS2 fallback, `brew install ghdl`, or
a student-shaped clean profile. Gate A rehearses exactly those; `--doctor` and `install.md` should
prefer the CI-proven paths (a versioned zip/tarball is also what a doctor can verify).

### Code quality (what a code-reading student would notice)

**F13 — `sim_bridge.py` is 3,067 lines and nine unrelated concerns.** 2.5× the next-largest source
file (`ui/board_display.py`, 1,222) and 22% of `src/`. It already carries `# ── section ──` banners
that *are* the split lines: config (`:41-150`) · backends (`:150-367`) · discovery (`:367-599`) ·
venv/libpython (`:599-674`) · VHDL interface + contract (`:674-1043`) · **board-native convention
matcher (`:1043-1771`, 728 lines)** · wrapper rendering + `analyze_vhdl` (`:1771-2497`) · waveform
(`:2497-2765`) · runner (`:2765-3067`). 46 import statements across 35 files. **Landmine:** four
`Path(__file__).parent.parent.parent` constants — `_DUTY_FRAGMENT_DIR:81`, `_WRAPPER_TEMPLATE:1773`,
the venv default `:2443`, `_root:2459` — two on the exact path a student's file travels
(`analyze_vhdl` → `_generate_wrapper`). Moving the module one directory deeper would silently break
all four. Four more live in `board_loader.py:383`, `controller.py:64`, `__main__.py:197`,
`generate_board_images.py:823` (`ui/icons.py:30` uses the correct `.resolve().parent` form). Rick:
the architecture/developer docs must stay accurate through this change (PR 2 lists them).

**F14 — Three renderers for the same widgets, already drifted.** `ui/components.py` (pygame),
`generate_board_images.py:299-561` (SVG) and `sim/capture_frames.py` (binary LEDs) re-implement
LED/switch/button/7-seg independently; commit `2746c37` touched two of them. → P34.

**F15 — Duplication.** `sanitize_filename` / `unique_name` are verbatim copies
(`generate_board_images.py:76,99` vs `scripts/sync_common.py:23,34`). `_page_rows` / `_ensure_visible`
/ `_move_cursor` are byte-identical between `ui/vhdl_picker.py:147-176` and
`ui/board_selector.py:277-300`, as is the wheel-scroll step. Five screens hand-roll the same modal
`while running:` loop.

**F16 — Presentation trivia.** `docs/` holds 23 Markdown files of which 13 are *completed or live*
delivery plans, burying the handful a student wants (Rick: give them their own subdirectory, keep
them as history → D-12). **224** opaque `(U37)` / `(D6b)` / `(#386)` markers appear in source
comments with no legend outside `docs/roadmap_delivered.md`. Plus: 16 dead `# noqa` directives; the
ten cocotb files listed twice in `pyproject.toml`; an unused `ui` pytest marker; a no-op `sys.path`
insert in the root `conftest.py`; no `py.typed`; an unsorted `__all__` with `RGBLED` unexported
(`ui/__init__.py:25-48`); one unreferenced public method `get_switch_state` (`ui/board_display.py:382`).

### Icebox triggers that fire

| ID | Item | Disposition |
|---|---|---|
| **P17** | Board-native frozen-divider warning | **Graduates → U48**, as runtime observation + the generics lever, *not* the static lint the card describes |
| **P11** | Traffic-light FSM teaching design | **Graduates → U52** in spirit: the course's Lab 2b makes a **code-lock FSM** the more relevant labeled-states example; decide the exact design in PR 11 |
| **P13** / **P14** | Unbounded waveform size; GHDL+VCD+Memories dead end | **Resolved in PR 12** (D-14): FST default when enabling capture, an end-of-run size line, docs; the retention sweep only if the day has room |
| **P6** | External boards directory | Not scheduled |

---

## 4.1 Gate A soak findings (2026-09-06)

**These supersede §4 where they disagree.**

Gate A's first half ran on 2026-09-05 by reading the course's own files (§1.1). Its second half ran
on 2026-09-06: a **thirteen-case corpus** in the course's shape — five lab-shaped solutions (the
Lab-1 combinational display, the Lab-2a `CNTR_LEN` running light, and Tasks 3a/3b/3c) and eight
student-style wrong ones (off-by-one LED width, a missing `use` clause, an `integer` top-level port,
inverted segment polarity, a reserved-word signal, an entity/filename mismatch, a testbench picked
as the design, and a `.qsf` naming another board) — pushed through **the app's own three stages**,
`check_vhdl_encoding` → `check_vhdl_contract` → `analyze_vhdl`, on DE10-Standard and Basys 3.

The corpus lives at `/tmp/arc/gate_a/`, with a durable copy plus its generator and the soak
harness staged at **`~/.claude/arc/`** (`mkcorpus.py`, `soak.py`, `gate_a_corpus/`) — `/tmp` is
tmpfs and does not survive a reboot. It is *lab-shaped*, never a copy of the course's own
solutions; **PR 6 promotes the parts it needs into `tests/fixtures/pinmap/`** as **tool** fixtures,
which is where it should live permanently. Gate B re-runs exactly these files.

**G6 — the headline, and it is a measurement rather than an opinion.** Twelve of the thirteen cases
fail at the *same* wall with the *same* words: `Missing required port(s) in 'test_entity.vhd': clk,
btn, led`, followed by the generic contract. A correct Lab-1 design, a correct combinational
Task 3a, an off-by-one LED width, a missing `numeric_std`, an illegal `integer` port, inverted
segment polarity, a `.qsf` for another board, and a *testbench picked by mistake* are today
**indistinguishable to the student**. Only the entity/filename mismatch produces a specific,
actionable message (and that one is genuinely good). Nothing in the tool can currently tell a
student whether they have the wrong file, the wrong board, or the wrong tool. This confirms the §9
never-cut set rather than changing it.

**G5 — why, exactly; and the near-miss path is *right* to stay silent.** `_best_convention_attempt`
scores every course file at **one** matched role — `sw` happens to be the Terasic bank's name too —
and `check_vhdl_contract` requires `>= 2` matched roles before it reports a convention near-miss, so
each file falls back to the generic-contract message. That threshold is correct: telling a student
"you nearly wrote a Terasic-native design" would be false. It is precisely why nothing short of
**U53** fixes this, and it means the pin map must produce its *own* diagnostics — falling back to
this message when a pin map is present but incomplete would waste the mechanism.

### Changes to U53's specification (PR 6)

**G1 — a real course file has an input port with no pin assignment at all.** Lab 1 declares
`button : in std_logic_vector(2 downto 0)` with no default, and **none of the three course `.qsf`
files assigns `BUTTON`** — they assign `KEY[0..2]`, which is what Lab 2a renamed the port to.
Quartus places an unassigned pin automatically, so the project still builds and the student never
finds out. Under §7 PR 6's rule as written — *"an unassigned input without a default → error naming
it"* — **the pin map would reject the first file of the first lab.** Revised rule: tie an unassigned
input **off** and keep the design running, with one non-blocking line saying so (the shape U31 ✅
already uses for an absent bank, and closer to the truth than either rejecting or silence). An
unassigned *output* is still left `open`, as planned.

**G2 — the constraint file is the vendor's entire pin file, not the design's.** The course `.qsf`
carries **422** `set_location_assignment` lines: SDRAM, VGA, TV decoder, audio, HPS, both the
golden-top names (`KEY[0..2]`, `HEX4`/`HEX5`, `LEDR[0]`, `CLOCK2_50`…) *and* the instructor's. The
design declares six ports. So the map is built **from the design's ports outward**, and every
assignment no declared port claims is ignored — in particular, "a pin the board does not know" may
only be an error for a pin some *declared* port claims, or `DRAM_ADDR[0]` alone would sink every
project.

**G3 — a pin-mapped design may legitimately drive only part of the display.** DE10-Standard has
**six** digits; the course's `hex(27 downto 0)` is four digits of seven segments, **with no decimal
point**. U22's rule that declaring a strict subset of a board's display ports is a near-miss must
**not** apply on the pin-map path: there the constraint file *is* the declaration, and digits 4–5
stay dark exactly as they do on the student's own board.

### New work for U50 (PR 9), found by soaking rather than by reading

**G4 — a picked testbench is a distinct, trivially-detectable case.** `_parse_toplevel_interface`
returns **`ports = []`** for a testbench, so a zero-port entity is unambiguous — yet the student
gets the same "Missing required port(s)" message as everything else. It deserves its own: *"this
file declares an entity with no ports, which is what a testbench looks like — pick the design it
tests; the simulator supplies the stimulus itself."*

**G7 — `units` is a VHDL reserved word, and GHDL will not say so.** Writing
`signal units : integer range 0 to 9` for a countdown's ones digit — the obvious name in Task 3c,
and the author of this corpus did it without thinking — fails with *"an identifier is expected
instead of 'units'"*. `units` is reserved for physical type declarations (`type time is range …
units … end units`), which is nowhere in a student's mental model. A hint naming the reserved word
costs one pattern.

**G8 — what a broken testbench actually says *first*.** Analyzed on its own, which is the state a
student is in, the course's seven-actuals testbench fails with
`unit "test_entity" not found in library "work"` — **not** "too many actuals", which appears only
once the design has been analyzed into the same library. So of §4 F4's two candidates the
entity-not-found hint is the *more* common, and both belong in PR 9. The "too many actuals"
diagnostic also demonstrates F5 exactly: its caret sits at **column 45**, under `open`, and the
error dialog strips it to column 0.

### Still outstanding — the half that needed hardware

**Resolved 2026-09-06 by D-19: CI does it instead.** The original plan was a clean-machine
rehearsal on a Windows laptop and a macOS laptop, following `docs/install.md` verbatim, with the
`winget install ghdl.ghdl.ucrt64.mcode` pre-flight (F23) — and **PR 10 (`--doctor`) was gated on
it**. Rick's observation is that a hosted runner already *is* a clean machine, and unlike a laptop
it re-runs every week and catches the rot as it happens. `.github/workflows/install-docs.yml`
covers it; **PR 10 is un-gated**.

What the substitution does not buy: a runner has no display, no prior Python, no Store Python, no
half-installed MSYS2 and no group policy, so it exercises the install matrix and not the
troubleshooting section. Those paths stay unrehearsed until someone runs them on a real profile.

---

## 5. Cards to file

Standing rules: an arc does not start without a card; **an ID is taken the moment it is used
anywhere** (2026-09-04 corollary). Next free before this arc is **U48 · D17 · P34**:

| ID | Card | Tier | Status after this arc |
|---|---|---|---|
| **U48** | "It looks frozen" — runtime stall advisory **+ opt-in generic override** (graduates **P17**) | 1 | shipped (PRs 7, 8) |
| **U49** | Self-service first run — direct launch, picker/selector defects, drag-and-drop, board-name repair | 1 | shipped (PRs 1, 4, 5, 13) |
| **U50** | Student-error diagnostics — Synopsys acceptance + note, hint coverage, caret preservation, `--doctor` | 1 | shipped (PRs 3, 9, 10) |
| **U51** | Multi-file designs — sibling analysis to a fixpoint, non-fatal neighbors; acceptance test = the split T80 system (F3) | 2 | **pulled back into this arc 2026-09-06** (D-5 reversed); the folder contract (D-16) is its other half |
| **U52** | Learn-by-example — lab-shaped references + target-board native references (graduates **P11**) | 3 | shipped (PR 11) |
| **U53** | **Project pin map** — run a design through its own `.qsf`/`.xdc`/… constraint file; 7-segment pin data for the target boards | 1 | shipped (PR 6) — the centerpiece |
| **U54** | Testbench runner — analyze the folder, elaborate the testbench, capture FST, open the viewer | 2 | **carded → v0.24.0** (D-11); manual recipe documented in PR 12 |
| **D17** | `sim_bridge.py` decomposition + `fpga_sim/paths.py` | 1 | shipped (PR 2) |
| **P34** | Three-way renderer convergence (pygame / SVG / capture) | Icebox | no trigger yet |

PR 0 also **renumbers the queue — peripherals → v0.24.0, D16 sandbox → v0.25.0 — across all ~8
sites**, refreshes *Current focus*, and adds this file to the *Plan documents index*. **Next free
afterwards: U55 · D18 · P35.**

---

## 6. Schedule

Honest capacity: three weeks *with teaching in them* is **~9–11 focused days**. The work in §7 sums
to **~16**. The must-have core — Gate A, PR 0/0b, PR 1, PR 2, PR 3, PR 4, PR 6, PR 8, PR 14, plus
`first_design.md` and `troubleshooting.md` from PR 12 — is **~11**. Everything else rides on slack in
the §9 order. This is stated plainly so nobody discovers it in week 3.

```text
Day 0     Gate A½   course files analyzed (done 2026-09-05, §1.1)
Day 1     Gate A    lab-shaped solutions + wrong solutions through the app · clean-machine installs
Week 1    PR 0-5    cards+renumber · docs/plans/ move · direct launch · the split · -fsynopsys · hdl/ + picker · selector
Week 2    PR 6-8    PIN MAP (3 d) · generics override · frozen-board advisory                    Gate B
Week 3    PR 9-14   hints/caret · doctor · examples · docs · board-name table · release
```

Ordering choices worth stating:

- **Gate A finishes before code.** Half of it happened during review (§1.1); the other half — real
  student-shaped files through the interactive app, and clean installs — is the only source of
  unknown-unknowns and produces the install matrix `--doctor` must encode.
- **The split is PR 2, before the pin map.** The pin map extends the convention matcher and the
  wrapper renderer; landing it *after* the split means it is written into the new, smaller modules
  and never bloats `sim_bridge.py`.
- **PR 3 (`-fsynopsys`) is tiny and early** because every soak of a course file needs it.
- **PR 6 is the centerpiece and the largest risk**; it gets the middle of the arc, the whole test
  net, and Gate B immediately after.

**Tag the release ≥ 4 days before lab 1.** The tag is what surfaces the last problems.

### Gate A — soak-0 and install rehearsal (day 0–1, no PR)

> **Status 2026-09-06: the soak half is done — findings in [§4.1](#41-gate-a-soak-findings-2026-09-06),
> which supersedes §4 where they disagree. The clean-machine install half has not run and
> needs hardware; PR 10 stays gated on it.**

1. **Real files (half done).** The three course projects were run through both backends on
   2026-09-05 (§1.1). Remaining: write **lab-shaped solutions** to Tasks 1, 2, 3a, 3b, 3c *and*
   **student-style wrong solutions** (Rick: "see how our project reacts") — off-by-one vector
   widths, a missing `use` clause, an `integer` port on the top level, an active-low mistake, a
   testbench picked as the design, a design named differently from its file — in a staging directory
   **outside the repo** (Rick's `/tmp/arc/`; `/tmp` is tmpfs and is wiped on reboot, so copy anything
   worth keeping into `tests/fixtures/` as *tool* fixtures, never as lab solutions). Run them through
   the interactive app on DE10-Standard and Basys 3 (once PR 3 and PR 6 exist, re-run — that is Gate
   B); until then the run records *how the failure is reported*, which is itself a finding.
   Mechanical half: `uv run fpga-sim --benchmark N --board DE10StandardPlatform --vhdl … --screenshots DIR`.
2. **Clean machines.** Install from a clean clone on a Windows laptop and a macOS laptop following
   `docs/install.md` verbatim, recording every step's outcome. Pre-flight `winget install
   ghdl.ghdl.ucrt64.mcode` (F23) **now, not the week of the lab**; if it is absent or stale, the
   documented primary path becomes the CI-proven release zip.

**Output:** a ranked defect list that *supersedes* §4 where they disagree, plus the install matrix.
Re-order PRs 4–13 against it before starting them.

### Gate B — soak-1 confirmation (end of week 2, 0.5 d)

Re-run Gate A's files, now with PRs 3, 6, 7, 8 in place: every course-shaped file must load, run,
and either animate or raise the advisory with correct arithmetic. New findings are **triaged, not
automatically fixed**; anything M+ goes to the post-semester queue rather than into week 3.

---

## 7. The PRs

Each: feature branch (never commit to `main`), CHANGELOG `[Unreleased]` entry, **a "docs touched"
line in the PR description**, and
`uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`
before every commit (with `pipefail` when piping). UI/render PRs additionally get screenshots and
Rick's visual review before merge (the standing carve-out from merge-on-green).

---

**PR 0 — arc cards + version renumber.** ✅ **landed 2026-09-05** · 0.5 d · low risk
Commit this document (the agreed v2 only; v1 rides along marked superseded); file U48–U54, D17, P34;
update *Current focus* and *Next — in order*; renumber peripherals → v0.24.0 and D16 → v0.25.0
everywhere; record the ID allocation (next free U55 · D18 · P35); add the *Plan documents index* row.
*Files:* `docs/improvement_roadmap.md`, this file, `docs/u48_classroom_arc_plan.md` (banner only).
*Docs touched:* the roadmap is the doc.
*Done when:* the roadmap describes the arc about to run and `grep -rn "v0.23.0" docs/` refers only
to this arc.

**PR 0b — plan documents → `docs/plans/`.** ✅ **landed 2026-09-06** · 0.25 d → 0.5 d · low risk (D-12)
`git mv` the 13 completed/live plans (`7seg_display_plan_v2`, `board_native_release_plan`,
`docs_assets_improvement_plan`, `docs_assets_improvement_plan_v2`, `embedded_core_improvement_plan`,
`embedded_core_system_plan`, `u9_led_complete_plan`, `u21_board_native_vhdl_plan`,
`u22_7seg_scan_plan`, `u34_single_window_plan`, `u35_simulator_picker_plan`, `u39_peripherals_plan`,
`u44_multi_input_plan_v1`) plus both u48 files into `docs/plans/`; keep `u25_ghdl_perf_profile.md`
and `embedded_core_build_notes.md` in `docs/` (reports and notes, not plans). Add `docs/README.md`
indexing both directories. Fix inbound links: `CHANGELOG.md` (links only, no history rewrite),
`CLAUDE.md`, `CONTRIBUTING.md`, `docs/architecture.md`, `docs/install.md`,
`docs/improvement_roadmap.md` (plan index), `docs/roadmap_delivered.md`,
`docs/port_convention_sources/README.md` + `waves.toml`, `docs/embedded_core_system_guide.md`, the
`sim_bridge.py` docstring, six `systems/*.toml` comments, two test docstrings.
*Done when:* `ls docs/*.md` shows ≤ 12 entries, every moved file is reachable from `docs/README.md`,
and `uv run rumdl check .` is clean.

---

**PR 1 (U49) — direct launch into the interactive app.** 0.5 d · medium risk
Drop "benchmark mode only" from `--board` / `--vhdl` (`__main__.py:64-75, 115-141`); reserve
`--pinmap PATH` and `--generic NAME=VALUE` (repeatable) here so the flag set is stable, wiring them
in PRs 6 and 7; seed `ScreenController.run()` (`controller.py:322-331`) through the existing
`on_board_selected()` / `on_vhdl_loaded()` entry points (F9). Relative paths resolve against the
student's cwd. **First in the arc** because it makes every later soak iteration ~10× faster and gives
lab machines a one-click desktop shortcut (D-4).
*Risk:* the launcher state machine. A test **must** assert the no-flag path still enters
`NextScreen.SELECTOR`.
*Docs touched:* `docs/user_guide.md` (launch flags), README "Quick start".
*Done when:* `uv run fpga-sim --board DE10StandardPlatform --vhdl ~/lab1/test_entity.vhd` opens on
the preview with the file loaded and validated; the no-flag path is unchanged in behavior.

---

**PR 2 (D17) — `sim_bridge.py` decomposition.** 1.5–2 d · medium risk, de-risked as follows

1. **Split into sibling modules in `fpga_sim/`, not a subpackage.** A `fpga_sim/sim/` package would
   change every module's depth and silently break the four `parent.parent.parent` constants in F13.
   Flat siblings keep the depth. (A subpackage would also collide conceptually with the top-level
   `sim/` directory on the child's `PYTHONPATH`.) Proposed: `sim_backends.py` · `sim_discovery.py` ·
   `vhdl_contract.py` · `conventions.py` · `wrapper.py` · `waveform.py` · `sim_runner.py`, with
   `sim_bridge.py` left as a **re-export shim** carrying a section map, so all 46 import sites keep
   working.
2. **Land `fpga_sim/paths.py` first, in the same PR.** One `REPO_ROOT` (plus `HDL_DIR`, `BOARDS_DIR`,
   `SIM_DIR`) replaces the eight fragile chains across five files.

*Docs touched (Rick's question — yes):* `docs/architecture.md` ("Simulator backends" and "How
board-native works" sections), the CLAUDE.md file table, CONTRIBUTING → "Backend dispatch design
(`sim_bridge.py`)".
*Done when:* no module exceeds ~800 lines; ruff, mypy and the **full** pytest — including the slow
GHDL and NVC jobs, which are what exercise `_WRAPPER_TEMPLATE` and `_DUTY_FRAGMENT_DIR` — are green;
CI green on all platforms.

---

**PR 3 (U50) — accept the Synopsys packages, say so once.** 0.25 d · low risk (D-10)
Add `-fsynopsys` to `_GHDLBackend.analyze_cmd`, `elaborate_cmd` and `run_cmd`
(`sim_bridge.py:232-278`; after PR 2, `sim_backends.py`). Add a `uses_synopsys_packages(text)`
detector over the design's `use` clauses; when true, show one non-blocking line on the preview in the
slot the board-native badge uses — *"Uses the non-standard Synopsys packages `std_logic_arith` /
`std_logic_unsigned`; they work here and in Quartus, but modern VHDL prefers `ieee.numeric_std`"* —
and record it in the session log.
*Tests:* a fixture using both packages analyzes, elaborates and runs on GHDL **and** NVC; the note
appears; a `numeric_std` design shows nothing.
*Docs touched:* `docs/writing_designs.md` (a short "Synopsys packages" note), `troubleshooting.md`
(PR 12 cross-reference), CHANGELOG.
*Done when:* all three course files pass analysis on GHDL unmodified.

---

**PR 4 (U49) — `hdl/` hygiene + picker + drag-and-drop.** 0.75 d · low risk
`git mv hdl/bad_*.vhdl tests/fixtures/hdl/` (F1) and repoint the three test modules and three docs
lines. Preselect `example_vhdl_for(board)` (`controller.py:67-74`) on a fresh profile. Stop resetting
the picker to `_HDL_DIR` on a retry (`controller.py:451`, F10). Add the existing `draw_help_button`
(`ui/help_dialog.py:282`) to the VHDL picker and the simulation screen. **Handle `pygame.DROPFILE`**
on the picker and the preview: dropping a `.vhd` runs the same encoding → contract → analysis chain
as picking it (F20; a native OS file dialog stays a Gate A option, see §8).
*Watch:* the encoding guard (`scripts/check_encoding.py`, `tests/test_encoding_guard.py`) picking up
the BOM fixture at its new home.
*Docs touched:* `docs/user_guide.md` ("Select a VHDL file": drag-and-drop, where the picker starts),
README "Try it" step 4, in-app help text.
*Done when:* `ls hdl/` shows only teaching designs; a fresh-profile launch lands with `blinky.vhd`
selected; a failed validation re-opens the picker in the student's own directory; a dropped file
loads.

---

**PR 5 (U49) — board selector.** 0.5 d · low risk
Add the `"name"` sort branch; match `b.vendor` in the filter text; default `hovered = 0`, guarding an
empty `_filtered()` (F6). Ride along: extract the byte-identical scroll helpers from
`board_selector.py:277-300` and `vhdl_picker.py:147-176` into `ui/_scroll.py` (F15).
*Docs touched:* `docs/user_guide.md` ("Select a board").
*Done when:* the default list is alphabetical; typing `terasic` returns the Terasic boards; Enter
selects on a fresh profile; both list screens scroll from one implementation.

---

**PR 6 (U53) — project pin map.** 3 d · **medium-high risk · the centerpiece**
*The single item that decides whether the course's files run at all.* The student picks their top
level exactly as today; the simulator finds the project's constraint file beside it, maps every port
bit to a board resource by **pin**, and generates the wrapper from that map — the student's own
declared truth, never a name heuristic.

1. **Relocate the parsers.** `git mv scripts/port_convention_parsers src/fpga_sim/constraints`
   (the package is self-contained: eight dialect modules + `types.py` + `classify.py`); fix the ~10
   imports in `scripts/sync_port_conventions.py`, the eight `tests/test_port_convention_parser_*.py`
   modules and `tests/test_port_convention_parsers_golden.py`. Scripts already import `fpga_sim`
   one-way (`scripts/amaranth_parser.py`), so the dependency direction is unchanged.
2. **`fpga_sim/pinmap.py`.**
   - `discover_pinmap(vhdl_path) -> Path | None`: exactly one file with a known constraint suffix
     (`.qsf .xdc .pcf .cst .lpf .ucf .ccf`) beside the design → use it; two or more → an error naming
     them all, resolved by `--pinmap`; none → `None` (the existing name-based paths run).
   - `board_pin_index(board) -> dict[str, PinRole]`: clocks (`clocks[].pin`), `leds[i].pins[0]` →
     LED channel *i* (RGB sites follow the existing channel layout), `switches[i].pins[0]`,
     `buttons[i].pins[0]` with `inverted`, and — new data, item 5 — 7-segment pins → (digit, segment
     | dp) for `individual` displays or (shared segment | digit-enable | dp) for `scan` displays.
     Pin strings are normalized (`PIN_AF14` ≡ `AF14`, case-insensitive).
   - `build_pin_map(interface, table, board) -> PinMapMatch | PinMapProblem`, over
     `_parse_toplevel_interface()` (`sim_bridge.py:836`) **bit by bit**: the clock port must map to a
     clock pin (a design with no clock port is combinational — allowed; the wrapper still ticks);
     input bits → switch or button pins (several ports may share one bank: `button(2:0)` + `reset`
     both land in KEY); output bits → LED or segment pins; an unassigned **input with a default** is
     fine, without a default → error naming it; an unassigned **output** → left `open`; a pin the
     board does not know → error naming the port bit and pin *and* whether the QSF's `DEVICE` matches
     the board's `device` ("`test_entity.qsf` targets 5CSXFC6D6F31C6, but DE10-Lite is 10M50DAF484C7G —
     did you select the wrong board?"). **Never coerce silently.**
3. **`_render_pinmap_wrapper`** (in `wrapper.py` after PR 2): same entity, generics, top ports and
   clock process as the native wrapper (`sim_bridge.py:1846-1900`), then bit-level assignments —
   `uut_sw(2) <= sw(2)`, `uut_reset <= not btn(3)` (polarity from the board JSON `inverted` flags,
   exactly what a design written for the real board expects), `led(4) <= uut_led_r(4)`,
   `seg(8*1 + 2) <= not uut_hex(9)` with the `{dp, g..a}` byte packing per digit; scan displays reuse
   the U22 combinational demux at bit level. Design generics pass through (PR 7). The wrapper embeds
   the constraint file's **sha256 as a comment**, so `wrapper_is_stale` (`controller.py:167-199`,
   `sim_bridge.py:2204`) re-analyzes after the student edits their `.qsf` — for free.
4. **Integration.** `check_vhdl_contract(path, board_def, pinmap=…)`: when a constraint file is
   present, the pin map is tried **first**, then the convention matcher, then the generic contract;
   the result names which mechanism matched. `ContractResult.match` becomes
   `ConventionMatch | PinMapMatch`; `SessionState.convention` likewise; the preview badge reads
   "Pin map: `test_entity.qsf` → DE10-Standard"; the `.gtkw` writer lists the design's own ports
   (`_native_gtkw_signals` pattern, `sim_bridge.py:2571-2615`); the session log gains a `pinmap`
   field; `--pinmap` from PR 1 is wired.
5. **7-segment pin data** (F18). Extend the schema and `SevenSegDef` with optional pins —
   `individual`: per-digit segment lists (+ dp); `scan`: shared segment list + digit-enable list +
   dp. Make the three parsers retain what they already see (amaranth `_extract_sevenseg`, litex
   `_build_seven_seg_def`, Digilent `_build_seven_seg`). **Pre-flight first:** run
   `scripts/check_board_drift.py` unmodified and prove a byte-identical no-op re-sync (needs
   `GITHUB_TOKEN`); only then re-sync each source **in place at its recorded `source_commit`**
   (`boards/*/_sync_metadata.json`; pass `--ref <sha>` to dodge the API rate limit that reads as false
   drift), so the drift job stays green. Hand-author `boards/custom/de10_standard.json` and
   `custom/de2_115.json` (cite the user manuals' HEX pin tables in `docs/port_convention_sources/`
   style; the course QSF corroborates DE10-Standard's HEX0..3 = `W17 V18 AG17 AG16 AH17 AG18 AH18`,
   …). Only the target boards *need* the data; a pin-less board gets a clear error ("DE0-Nano's
   7-segment pins are not in the board data — see docs/writing_designs.md#pin-map").
6. **Tests.** Relocated parser tests unchanged; `board_pin_index` for each target board; matcher
   rules without a simulator (shared bank, default-less input, unknown pin, wrong `DEVICE`, two
   constraint files); a wrapper golden test; **slow end-to-end on GHDL + NVC with the repo's own
   course-shaped fixtures** under `tests/fixtures/pinmap/` — a DE10-Standard-shaped `top.vhd` +
   `top.qsf` whose test asserts each `hex` nibble lands on the right digit and `reset` on KEY[3]; a
   Basys 3-shaped design with renamed ports + `.xdc` on the scan display; a Lab 2a-shaped design with
   `CNTR_LEN` (PR 7 reuses it).
*Files:* new `fpga_sim/pinmap.py`, `fpga_sim/constraints/`; `vhdl_contract.py`, `wrapper.py`,
`controller.py`, `board_loader.py`, `boards/schema/board.schema.json`, the three parsers, target
board JSONs, `ui/board_display.py` (badge), `sim_session_log.py`.
*Docs touched:* `docs/writing_designs.md` (new section "Your own port names: the pin map", the
error catalog), `docs/user_guide.md`, `docs/troubleshooting.md` (PR 12), `docs/architecture.md`,
CLAUDE.md, the schema, `docs/port_convention_sources/README.md` (7-seg pin citations).
*Done when:* every course-shaped fixture runs on DE10-Standard and Basys 3 on both backends with
the display digits and KEY polarity correct; a `.qsf` for another board is rejected naming the
device; `check_board_drift.py` is green after the re-sync; the badge and session log say "pin map".

---

**PR 7 (U48) — opt-in generic override.** 1 d · medium risk (D-9)
`fpga_sim/generics.py`: read the top level's generics from `_parse_toplevel_interface()`; editable
kinds are `integer`/`positive`/`natural`, `boolean`, `std_logic`/`bit` literals; anything else is
shown read-only. Wrapper pass-through on **all three** wrapper kinds (generic-contract, native, pin
map): each design generic becomes a wrapper generic with the design's default and is forwarded in the
`generic map`; the run then passes `-gNAME=VALUE` (GHDL, at `-r`) or elaborates with it (NVC,
`_prepare_simulation`), the path the contract generics already use. UI: a **[Generics…]** dialog on
the preview (the Settings-dialog pattern), values persisted per (board, file) in the session, the
badge showing "CNTR_LEN=4 (overridden)"; CLI `--generic NAME=VALUE` (repeatable). The generic-contract
`COUNTER_BITS` override stays as it is and is listed in the dialog so it stops being a mystery.
*Tests:* the Lab 2a-shaped fixture animates within seconds with `CNTR_LEN=4`; a non-integer generic
is rejected with a message; the wrapper diff makes a changed default re-analyze.
*Docs touched:* `docs/user_guide.md` (the dialog), `docs/writing_designs.md` ("divider as a
generic" pattern — the hardware default stays, the simulator passes less), `first_design.md` (PR 12).
*Done when:* the course's running-light shape runs unmodified and visibly animates after one dialog
change or one flag.

---

**PR 8 (U48) — "it looks frozen."** 1–1.5 d · medium risk · **the most important UX change**
Runtime observation, not a static lint and not an automatic override:

1. **Detect.** No boundary LED/segment bit has changed for T wall-seconds **while simulated time is
   advancing** (the second clause separates a slow divider from a hung child). `visual_signature()`
   (`ui/board_display.py:1003`) already runs every frame for U23's redraw gate; it needs an
   *output-only* variant so a switch flip does not reset the timer.
2. **Say it with measured arithmetic, in the student's terms** (D-15): *"No LED or digit has changed
   in 10 s of wall-clock time. In that time this machine simulated ~1.9 M clock cycles = 38 ms of
   the board's 50 MHz. Your design's `CNTR_LEN = 24` means 16.8 M cycles per step ≈ 88 s here (≈ 11 s
   on NVC); on the real board it is 0.34 s."* Every number comes from the live throughput counter,
   never a constant.
3. **Offer the levers that exist:** **[Generics…]** when the top level has an integer generic
   (PR 7); **[Switch to NVC]** when NVC is installed (U35 picker); **[Why?]** → the two-clocks help
   text. Dismissible per run.

*Files:* `ui/simulation_screen.py`, `ui/sim_panel.py`, `ui/board_display.py`, `controller.py`, tests.
*Risk:* touches the live run loop; the "sim advancing" clause must not fire on a hung child.
*Docs touched:* `docs/user_guide.md` (the advisory), `troubleshooting.md` ("my board is dead"),
in-app help.
*Done when:* a 2³⁰-divider fixture raises the banner within ~10 s with correct arithmetic on both
backends; the mid-bit-tapping `hdl/native/*.vhd` and every `hdl/*.vhd` example never do; both
actions work.

---

**PR 9 (U50) — error hints + caret preservation.** 0.5 d · low risk
Widen the `std_logic` regex (`sim_bridge.py:1694`) to `unsigned|signed|to_unsigned|to_integer` →
"add `use ieee.numeric_std.all;`"; add hints for a syntax error ("check the end of the previous
line"), an undeclared identifier, entity-not-found-in-`work`, and the course testbenches' **"too many
actuals" / positional port map** (F4). Stop `.strip()`ing leading whitespace in `ErrorDialog._draw`
so GHDL's `^` lands under the offending column, and add copy-to-clipboard (F5). Purely additive; the
raw compiler text always stays.
*Docs touched:* `troubleshooting.md` entries mirror each hint.
*Done when:* `tests/fixtures/hdl/bad_semantic_blinky.vhdl` produces a `numeric_std` hint on **both**
backends, a caret-bearing diagnostic renders aligned, and the Lab 1-shaped broken testbench yields
the positional-map hint.

---

**PR 10 (U50) — `fpga-sim --doctor`.** 0.5 d · low risk · **gated on Gate A**
Reuse `discover_simulators()` (`sim_bridge.py:507`); print Python / uv / pygame-ce / cocotb versions,
every discovered simulator (label, backend, version, path), the board count, write access to
`~/.fpga_simulator/`, and one real headless analyze of a bundled design against a bundled board; exit
non-zero on failure — and **print a fix-it line per failing check** (Rick): the CI-proven install
command for this OS, the PATH fix, the pygame/pygame-ce collision repair. Then replace the "run
`uv run pytest`" install check in `README.md:81-86` and `docs/install.md:212-217`, and fix the
`install.md:209` dev-deps contradiction (F8). Looks XS; is really "encode the install matrix across
3 OSes × 4 GHDL backends + NVC" — hence the gate.
*Docs touched:* README Quick start, `docs/install.md` (primary Windows path per F23/Gate A).
*Done when:* `uv run fpga-sim --doctor` prints a pass/fail matrix with fix-its on all three OSes and
both docs point at it instead of the test suite.

---

**PR 11 (U52) — lab-shaped references + target-board natives.** 1–1.5 d · low risk (D-3 refined)
On the generic contract, so they run on every board and serve as the tutorial's material:
`gates_mux.vhd` (two control + two data inputs → one LED: the function-selector shape),
`hex_decoder_7seg.vhd` (the archetypal `case` decoder; a byte on the switches → two digits),
`running_light.vhd` (with **`DIVIDER_BITS` as a generic defaulting to the hardware value** — the
pattern PRs 7/8 teach), `code_lock_fsm.vhd` (labeled-states FSM driven by buttons — the P11 slot,
more course-relevant than a traffic light), `countdown_7seg.vhd` (99 → 0 at ~1 Hz from a generic
divider). Different specifics from the course tasks; no verbatim solutions. Plus a **DE10-Lite**
native reference (`MAX10_CLK1_50` / `SW` / `KEY` / `LEDR` / `HEX0..5`, mid-bit taps) and a **Tang
Nano 9K** one (`sys_clk` + six active-low LEDs, no inputs — exercises the U31 tie-off). Register them
in `writing_designs.md`'s example table and **link `hdl/blinky_survey.md`** from README and
`writing_designs.md` (F12).
*Tests:* each analyzes, elaborates and animates on its own board under **both** backends; short
cocotb behavior tests for the decoder and the FSM.
*Docs touched:* `docs/writing_designs.md`, README, `first_design.md` (PR 12).
*Done when:* the table lists them, the tests pass, and each has a screenshot from
`--benchmark --screenshots` in the PR.

---

**PR 12 — documentation.** 2 d · low risk · **the highest-ROI docs work in the arc**

- **`docs/first_design.md`** — the tutorial that does not exist, written in the labs' shape for the
  take-home student: install → launch → pick the board → *"your Quartus/Vivado folder: the simulator
  reads your `.qsf`/`.xdc`"* → run → **the two clocks** (simulated vs wall-clock, what "Sim time" and
  "Eff. rate" mean, why the board looks slow and how the advisory helps) → **[Generics…]** → change
  one line → reload → read an error → **what the simulator wraps around your file** (the wrapper,
  where it lives in the work dir, why `COUNTER_BITS` exists) → **the manual testbench recipe**
  (`ghdl -a -fsynopsys --std=08 *.vhd && ghdl -r --std=08 -fsynopsys testbench --fst=tb.fst`, NVC
  equivalent; note the course testbenches end with `severity failure` on purpose) → the one-file rule
  for sub-entities. Source material: the `.adoc` decks' "Blinky, Line by Line"
  (`virtual-fpga-boards.adoc:779-830`) and `hdl/blinky_survey.md`.
- **`docs/troubleshooting.md`** — entity/filename mismatch; "needs -fsynopsys" (should no longer
  occur; the note); missing `numeric_std`; a syntax error; "too many actuals"; **"my board is dead"**
  (the advisory's arithmetic, the generic pattern, the real-hardware default); **"this project is for
  another board"** (the pin-map `DEVICE` near-miss and the convention near-miss); active-low
  surprises (KEY, HEX); "my file is in a folder with other files"; **where waveforms go, which format,
  how large** (D-14: FST default, ~MB per simulated ms measured on the examples, `FPGA_SIM_WAVEFORM_DIR`).
- **Waveform defaults (P13/P14):** FST is the first non-off choice in Settings; an end-of-run line
  reports the dump's size; optionally a retention sweep with a documented cap.
- **Which simulator, said once, where a newcomer meets it.** `first_design.md` must name the
  backend choice at the point it first matters — *"if this feels slow, and NVC is installed, the
  `SIM:` toggle re-runs on it"* — with the ratios linked, not repeated
  ([choosing a simulator](../install.md#choosing-a-simulator) is the single source). The
  information was always correct and always two documents away from the person who needed it: it
  lived only in `install.md`, which is read once, before any of it means anything. **Done already
  (2026-09-07):** the README's install step carries the ratio table and the macOS
  `brew install ghdl` correction, and the stall advisory names a faster *installed* engine and
  points at the toggle. What is left for this PR is the tutorial's own mention — the one a reader
  meets while their first design sits there looking dead.
- **README re-aim:** one line above the fold pointing a newcomer at `first_design.md`; move the
  CI-matrix paragraph (`README.md:11-14`) below the value proposition; "Try it" reflects PR 4.
- **Legend and map:** one sentence in `docs/architecture.md` saying `(U##)` / `(D##)` markers cite
  `docs/roadmap_delivered.md`; the section map atop the `sim_bridge.py` shim (PR 2).
- **`docs/install.md`:** the primary Windows path per Gate A, `--doctor` as the check, the
  `--group dev` sentence corrected.

Per D-7, the two `.adoc` decks stay untouched.
*Done when:* a reader who has never seen the repo goes from clone to a running course-shaped file
using only `first_design.md`; `tests/test_docs_board_counts.py` and the spelling guard are green.

---

**PR 13 (U49) — board display names, the cheap path.** 0.25 d · low risk
A curated display-name override table applied at load time in `board_loader.py` for the sixteen
mangled names (F7), plus a data-level guard test over every board JSON (no standalone single capital
as a word, no leading/trailing separator) that fires on any *new* mangling. No parser change, no
re-sync, no drift risk. The parser fix and re-sync stay carded for a between-arc slot.
*Done when:* `DE1-SoC` and `ULX3S-45F` read correctly in the selector and the guard passes.

---

**PR 14 — release v0.23.0, "the classroom release."** 0.5 d · low risk
Version bump in `pyproject.toml`; **`uv.lock` re-sync after the bump**; CHANGELOG `[Unreleased]` →
`[0.23.0]` (it already carries U47 and the render-cache entries); card closeouts; confirm PR 0's
renumber still holds at all ~8 sites; short GitHub release notes (highlights + one-liners, linking
the CHANGELOG). Tag ≥ 4 days before lab 1.

---

**PR H — housekeeping (post-release, or week-3 slack).** 0.5 d · low risk
The ruff/mypy audit (§3) and the F16 trivia: dead `# noqa`s, the duplicated `pyproject.toml` lists →
globs, the unused `ui` marker, the no-op `conftest.py` insert, `py.typed`, `__all__` ordering,
`get_switch_state`.

---

## 8. Explicitly out of scope, and why

- **U39–U41 peripherals → v0.24.0.** Nine phases, one L-risk phase, serving the *in-lab* experience
  the courses already have in hardware. Plan stays approved and unstarted at
  [u39_peripherals_plan.md](u39_peripherals_plan.md).
- **U51 multi-file → v0.24.0** (D-5) and **U54 testbench runner → v0.24.0** (D-11). Both carded with
  their acceptance tests written down (§4 F3, §5). U51 is the first pull-back if time appears.
- **A native OS file dialog** (tkinter `askopenfilename`) — the most familiar way to load from
  anywhere, but tkinter's presence in uv-managed and lab-machine Pythons is unproven; Gate A checks
  it, and it rides along only if PR 4's drag-and-drop proves insufficient.
- **Docs & Assets round 2 PRs 3–6 → with peripherals.** Not needed here (stills exist today).
- **#354 GHDL-Cosim doc offer.** Gated on the full asset refresh; stays gated.
- **D16 sandbox → v0.25.0.** The interim warning shipped 2026-08-05; these students run files they
  wrote themselves.
- **Renderer convergence → P34** (F14). Students look at board images, not renderers.
- **Relaxing the generic contract** (optional `clk`/`btn`/`sw`). With the pin map, a combinational
  course file already runs as written; the churn is not worth it.
- **Parser-side board-name fix + re-sync** (F7) — carded; PR 13's table covers the semester.
- **Other carded quick wins — U15, U16, U17, U19, D5, D12, D13.** Correct findings, no semester value.

---

## 9. Cut order if three weeks becomes two

Cut in this order; nothing below the line changes.

1. **PR 13** (board-name table) — cosmetic.
2. **PR 11** reduced to `gates_mux.vhd` + `hex_decoder_7seg.vhd` + `running_light.vhd`; no natives.
3. **PR 12** reduced to `first_design.md` + `troubleshooting.md`; no README re-aim, no sweep.
4. **PR 10** (`--doctor`) reduced to the minimum matrix — *unless* Gate A shows the install is broken
   on Windows or macOS, in which case it is promoted and PR 9 slips instead.
5. **PR 7** reduced to `--generic` on the CLI only; the dialog follows post-semester.
6. **PR 5** reduced to the `"name"` sort + vendor filter.
7. **PR 9** (hints/caret).

**Never cut:** PR 0/0b, **Gate A**, PR 1, **PR 2** (Rick's call, D-6), PR 3, PR 4, **PR 6**, **PR 8**,
PR 14.

**Pull-back order if time appears:** U51 multi-file (siblings non-fatal, fixpoint ordering, the
T80 acceptance test) → the OS file dialog → U54 testbench runner.

That never-cut set still delivers the thesis: *a student alone at 11 pm drops their own Quartus
top level onto the window, the simulator reads their `.qsf`, the board lights up — and when it does
not, the tool tells them, with numbers measured on their machine, why.*

---

## 10. Verification

Per PR: `uv run ruff check . && uv run ruff format --check . && uv run mypy . && uv run pytest`.

Arc-level, end to end:

1. **Course-shaped files end to end.** The repo's own fixtures in the shapes of Lab 1, Lab 2a, Lab 2b
   and a Basys 3 renamed-port design (`tests/fixtures/pinmap/`) load through their constraint files
   on DE10-Standard / Basys 3 on **both** GHDL and NVC; Lab 2a's shape animates within 10 s after a
   `CNTR_LEN` override; Lab 2b's shape unlocks by KEY presses (active-low honored); the Lab 1 shape
   shows the right digit for each `hex` nibble.
2. **The frozen board.** A 2³⁰-divider fixture raises the banner within ~10 s with measured
   arithmetic and the [Generics…] / [Switch to NVC] actions work; no bundled example ever triggers it.
3. **Fresh-profile walkthrough.** With `~/.fpga_simulator/` removed: launch, select DE10-Standard by
   keyboard alone, drop a file, run it, hit an error deliberately, recover. No `bad_*` file visible;
   Enter works; the picker stays in the student's directory.
4. **Fleet sweep.** `--benchmark N --screenshots DIR` green across the nine target boards on both
   backends, reviewed as a contact sheet.
5. **Install rehearsal, repeated.** Re-run `docs/install.md` verbatim on clean Windows and macOS
   profiles after PR 10, ending at `fpga-sim --doctor`.
6. **Board data.** `scripts/check_board_drift.py` clean after the 7-segment pin re-sync;
   `tests/test_docs_board_counts.py` green after the doc edits.
7. **Language and lint.** `tests/test_us_spelling.py` green; `uv run rumdl check .` clean.
8. **CI.** All 25 checks green per PR across 4 platforms × 3 Pythons × 5 simulator jobs.

---

## 11. Open at execution time

- **The stall threshold T** (10 s? 15 s?), per-run vs per-session dismissal, and whether a change on
  a single segment resets the timer. Decide against Gate A's observations.
- **Pin-map precedence** when a folder holds a constraint file *and* the design already uses the
  board's canonical names (both match): pin map first is the plan; confirm the message makes the
  choice visible.
- **FST-default migration** for sessions that already persisted `waveform = "vcd"`: leave them, or
  nudge once?
- **7-segment pins for non-target boards:** stop at the target boards, or let the re-sync populate
  every board the parsers can see (more diff, same risk class)?
- **tkinter availability** on uv-managed Python and the lab image, for the OS file dialog option.
- ~~**Whether `--doctor` should attempt the analyze step on every discovered simulator** or only
  the default one.~~ **Resolved in PR 10: every one.** Measured on the dev machine, `hdl/blinky.vhd`
  analyzes + elaborates in 0.02 s (GHDL mcode), 0.05 s (NVC), 0.05 s (GHDL LLVM-JIT) and 0.26 s
  (GHDL LLVM AOT) — 0.4 s for all four, against a diagnostic that otherwise cannot distinguish "GHDL
  answers `--version`" from "GHDL can compile", which is the failure students actually have.

---

## 12. Revision log

- **PR 12 (documentation) — 2026-09-07. P13 / P14 resolved.** The two documents were written by
  *running* everything they quote rather than recalling it, and that is what made them worth the
  day: the sample `--doctor` report, the stall advisory, both compiler errors, the pin-map badge
  ("10 output bit(s) and 13 input bit(s)"), the wrong-board refusal and the waveform sizes are all
  captured output. Three claims died on contact with the code. (1) A failed **[Reload VHDL]** does
  *not* leave the old run going — `_revalidate_for_reload` calls `clear_analysis()` and hands the
  next screen to an ErrorDialog — so the draft's reassurance was backwards. (2) `gates_mux.vhd`
  selects AND/OR/XOR/**NOT**, not NAND. (3) The advisory's own suggested divider width (17, computed
  from the measured rate) differs from the design header's "try 15", which now reads as the point it
  is rather than as a contradiction. A fourth was a false alarm worth recording: constructing
  `Divider(declared="24")` with a **string** made `overridden` true and produced the nonsense line
  *"running at 24, not the 24 in your file"* — the field is `int | None` and the product passes an
  int, so the bug was in the repro, not the code.
  Two guards were extended rather than trusted. `test_docs_simulator_ratios` now covers both new
  documents: each had been drafted quoting a machine-measured ratio (8.5x) that install.md's table
  does not contain, which is exactly the drift the guard exists to stop — so they quote **absolute
  measured rates plus the command that reproduces them** and link install.md for the comparison.
  `test_docs_board_counts` gained the sample `--doctor` report in *both* files that print one:
  "285 definitions in 4 sources" is a live count in a shape the existing three-digit sweep cannot
  see, so `install.md`'s copy had been unguarded since PR 10 — a new `sources` key in the fleet
  fixture covers the second number too, and the guard was checked for teeth by breaking it.
  **The retention sweep (P13) was deliberately not taken**: the per-run size line puts the decision
  in front of the only person who knows whether a dump still matters.
  Also closed **P11**'s Icebox marker, which U52 graduated but never ticked.
- **PR 10 (`--doctor`) — 2026-09-07. U50 closed.** Two checks the card did not list were added,
  both for failures *discovery cannot see*. (1) The **cocotb VPI/VHPI plugin and libpython** handed
  to the simulator child are verified to exist, asked through `sim_runner._build_sim_env` itself —
  that half of the pipeline an `analyze` never touches, and precisely the Windows DLL failure
  `docs/install.md` already documents a manual workaround for. (2) The analyze runs on **every
  discovered install** (§11 resolved above). One structural constraint drove the module's shape:
  the pygame/pygame-ce pip collision the doctor reports is exactly the state in which
  `import pygame` raises, and `fpga-sim` imports pygame before argparse sees the flag — so nothing
  in `doctor.py` imports pygame at module scope, cocotb is read through distribution metadata
  rather than imported, and `python -m fpga_sim.doctor` is a supported entry point. A health check
  that cannot run in the environment it diagnoses is not one. The install commands it prints are
  asserted by test to appear verbatim in `docs/install.md`, so D-19's workflow is what proves them;
  and the report is asserted ASCII, because a legacy Windows console turns a stray dash into a
  `UnicodeEncodeError` in place of the diagnostic. F8's dev-dependency contradiction is fixed the
  other way round from the plan's reading: `uv sync` installs the `dev` group *by default*, so the
  docs now say that rather than telling contributors to ask for it.
- **Stack merge + four decisions — 2026-09-06.** PRs 1–6c merged (U50 Synopsys acceptance, U49
  first run + board selector, D17 split, U53 pin map). Rick then supplied material that moved four
  things, recorded as **D-16…D-19** and a reversal of **D-5**. The reversal is the substantive one:
  a second course (BI-PNO — Basys 3, Vivado, Czech) whose student projects are multi-file and
  testbench-organized makes the one-file rule untenable, so **U51 comes back into this arc**. D-16
  replaces "teach the tool each EDA layout" with our own *one folder = one project* contract, after
  Rick pointed out that Vivado's layout is user-configurable and version-dependent — a Vivado
  discovery path had been drafted and is withdrawn. D-19 replaces the clean-machine install
  rehearsal with a weekly CI workflow and **un-gates PR 10**. D-18 records what the BI-PNO projects
  actually are, so the question is not reopened: never wired to a board, never synthesized, and
  blocked on a design exercise rather than on us.
  Two mechanical lessons from the merge itself, both worth carrying: GitHub **closes** a stacked PR
  rather than retargeting it when its base branch is deleted by a merge, and the PR cannot be
  reopened until that branch exists again — so merge **without** `--delete-branch`, rebase and
  retarget the next PR, and delete the branches at the end. And a squash merge makes every
  descendant branch need `git rebase --onto main <old-base>` before its diff means anything.
- **PRs 7 and 8 (U48) — 2026-09-06.** Built in the order the cut list implies rather than the one
  §7 numbers: **PR 7 in §9's reduced form** (`--generic` on the CLI, dialog deferred), because PR 8
  is never-cut and needs a lever to point at, and the reduced lever exists sooner. Four findings.
  (1) The plan's `-gNAME=VALUE` sketch was replaced by writing the override as a **literal into the
  generated wrapper**: the design's generics are not the wrapper's, GHDL applies `-g` at `-r` while
  NVC bakes it at elaboration, and a literal makes `wrapper_is_stale` re-analyze for free *and*
  turns a bad value into an **analysis** error the user sees while still looking at what they typed.
  (2) The advisory needed an output-only signature, which §7 named but did not motivate: a student
  who cannot tell a slow design from a dead one flips switches to find out, and `visual_signature()`
  would have reset the timer that was about to explain it. (3) The first banner render sat across
  the top of the board, on the 7-segment digits, while saying "no digit has changed" — caught by
  looking at the still, not by a test, and moved to the empty strip above the toolbar. (4) The third
  lever, **[Switch to NVC]**, is *not* wired: the picker lives on the preview and switching engines
  mid-run means tearing down and relaunching the child, which is its own PR.
- **U51 — 2026-09-06, and the measurement lesson in it.** Shipped eagerly (sweep the folder, then
  analyze) on the strength of two numbers: 0.22 s on GHDL mcode and 0.38 s on NVC over `hdl/`,
  18 files and 29.7k lines. Both true, both unrepresentative — on GHDL's **AOT LLVM** backend an
  analyze *compiles*, and CI put the job at **139 s → 663 s** (macOS 133 → 730). Rewritten to sweep
  only after the design fails, which returned the job to 124 s. Two lessons worth the words: *two
  green measurements on the cheap backends are not evidence about the expensive one*, and the
  laziness has to hang off **both** failure paths — `entity work.x` fails at analysis, but a
  `component` with default binding analyzes fine alone and only fails to bind at elaboration.
- **v1 — 2026-09-05 (draft).** Framed the arc around U21 board-native mode ("Terasic lab files are
  board-native"), a runtime frozen-board advisory, multi-file in-arc, and a docs refresh; excluded
  Digilent boards.
- **Gate A (soak half) — 2026-09-06.** Thirteen course-shaped files through the app's own three
  stages on both target boards; findings recorded as §4.1, which supersedes §4 where they disagree.
  Three of them change **U53**'s specification (an unassigned input with no default is real and must
  tie off, not reject; the constraint file is the vendor's whole 422-line pin file so the map runs
  design-outward; a pin-mapped design may drive only part of the display), two add work to **U50**
  (a picked testbench is a zero-port entity and deserves its own message; `units` is a reserved
  word), and one measures the thesis: twelve of thirteen files, right and wrong alike, fail with the
  same sentence. The install half still needs a Windows and a macOS machine.
- **PR 0b — 2026-09-06.** The move cost 0.5 d rather than 0.25, for one reason worth carrying
  forward: `docs/embedded_core_system_plan.md` is cited from **seven generated `hdl/*.vhd`
  designs** (through six `systems/*.toml` descriptions), the **vendored** `cores/mx65.vhd`
  provenance header, and a test docstring — none of which §7's file list named. Chasing a moved
  plan through generated files is the wrong fix, so those pointers now name
  `docs/embedded_core_system_guide.md`, the reader-facing doc that stays in `docs/` — one
  `regen_embedded_cores.py --write` pass, ten comment lines across eight designs. The rule applied:
  a reference to a *plan concept* ("Stage 0", "Decision 3", "§2") still points at the plan, now
  under `docs/plans/`; a generic "learn more" pointer points at the guide. Two link targets in
  `docs_assets_improvement_plan.md` were already broken before the move and are fixed. Contrary to
  §7, `docs/install.md` and the `sim_bridge.py` docstring cite no plan at all.
- **PR 0 — 2026-09-05.** Executed as written, with three things worth recording. (1) The
  roadmap's *Next — in order* dropped its completed item 1 (Docs & Assets PRs 1–2) rather than
  keeping a struck-through row — the fact lives in *Loose threads* and in item 3's text. (2) Two
  interconnections the §7 file list did not name turned up while filing: the Tier-3 **U18** note
  claimed the picker's retry-start-dir papercut, which is PR 4's work, so it moved to **U49**; and
  **D7** / **D16** both name a spawn seam that **D17** relocates to `sim_runner.py`, so both cards
  now say to order after it. (3) A British `-ise` spelling in D13's card was corrected to
  `Parameterize`, and that verb's three `-ise` forms were added to `tests/test_us_spelling.py`, per
  standing rule 1 — the guard gets extended, never worked around. (It then caught this very entry
  for quoting the banned word, which is the guard behaving correctly: the fix is to not write it.)
- **v2 — 2026-09-05 (this document).** After Rick's review (22 embedded comments, three follow-up
  messages) and inspection of the B251 course material: the central assumption replaced by the
  **pin map** (U53) after the course `.qsf` showed instructor-named ports; **`-fsynopsys`**, the
  **generic override**, and **broken-neighbor tolerance** added from the same files; DE10-Standard and
  Basys 3 promoted to first-priority boards; D-3 refined (lab-shaped references in), D-5 revised
  (multi-file out, traded for keeping the split), D-8…D-15 recorded; U53/U54 carded; the plan
  documents move to `docs/plans/`; the budget restated honestly (≈16 d vs 9–11) with the never-cut
  core (≈11 d) named; US spelling applied throughout.
