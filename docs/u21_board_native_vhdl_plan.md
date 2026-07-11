# U21 — Board-native VHDL: arc plan (conventions population + matcher + wrapper)

**Status:** IN PROGRESS — A0 in review (PR #209). Update the [status ledger](#status-ledger) as phases land.
**Decided 2026-07-12 (Rick):** the port-conventions population pipeline is **folded into the
U21 arc** as its opening phases (Part A), rather than run as a separate arc.
**Source data:** [`docs/port_convention_sources/`](port_convention_sources/) (PR #198) — ranked,
fetch-verified pointers for all 278 board files; see its README for schema and status semantics.
**Roadmap card:** U21 in [`improvement_roadmap.md`](improvement_roadmap.md) (strategy stays there;
this doc is the execution plan, per the hybrid backlog model).

This plan is written to be executed phase-by-phase by a capable model (Sonnet/Opus class)
without additional context. Every phase has **Do**, **Verify**, and **Quality gates**. Do not
start a phase until the previous phase's Verify steps pass. One PR per phase (repo precedent:
embedded-core arc #140–#154); never commit to `main` directly; branch each phase off
post-merge `main`.

---

## Locked decisions (do not relitigate; recorded 2026-07-11/12)

1. **Registry is the source of truth** for where convention data comes from. Code writes the
   board JSONs; humans maintain a small cited overlay; no model hand-edits board files.
2. **Names are the product.** The simulator never uses pin locations. Only sources whose
   *port names* are canonical (vendor/official-org) may populate `port_conventions`.
   Project-renamed sources (registry notes say so, e.g. EGO1) are excluded until a canonical
   source or an overlay entry exists.
3. **7-seg scope for U21:** direct-driven styles only — per-digit ports (Terasic `HEX0..n`)
   and per-segment scalars (Nandland Go `o_Segment1_A..G`). **Scan-mux** (Basys3 `seg`+`an`,
   Nexys4-DDR `CA..CG`, Mimas A7 `SevenSegment`+`Enable`) is recorded in data but consumed
   only by **U22**. **Serial** (Sword) is out of scope entirely.
4. **Native mode port parity:** a native design must declare the full `clk`+switches+buttons+LEDs
   set (per the board's convention) in U21's first cut. Partial-interface support is a follow-up.
5. **Width policy:** native ports must match the convention widths exactly; mismatch is a clear
   validation error, not a silent pad.
6. **Frozen-divider problem** (native designs have no `COUNTER_BITS` to override; a real
   50 MHz divider looks frozen at sim speed): handled by documentation in this arc; a
   literal-constant warning heuristic is parked (add to Icebox at closeout).

## Open questions (answer during B1 design review, before coding B2)

- Where the matched convention surfaces in UX. *Recommendation:* analysis-spinner text +
  `sim_session_log` field; no new dialog.
- Whether `check_vhdl_contract`'s return grows a typed result object now or a third tuple
  element. *Recommendation:* small frozen dataclass `ContractResult` (repo precedent: typed
  results, D6a/U7).

---

## Part A — populate `port_conventions` from the registry

### A0. Schema deltas (`boards/schema/board.schema.json`)

**Do:**

- Extend `$defs/seg_port_mapping.style` enum: keep `individual` (= per-digit ports) and
  `packed_vector`; add `per_segment_scalars`, `scan`, `serial`.
- Add optional `digit_enable` (a `port_mapping`: name/width/active_low) — used by `scan`.
- Add to `$defs/port_convention`: optional `source` object
  (`url`, `retrieved` (date), `registry_board` (string)), and optional `naming` enum
  `["canonical", "project-derived"]` (absent = canonical, for the existing hand-authored blocks).
- Formalize the already-used ad-hoc key `leds_green` (see `boards/custom/de2_115.json`) as an
  optional `port_mapping`.

**Verify:**

- `uv run pytest` — the board-loading/validation suite passes with zero board edits.
- All 278 board JSONs still validate against the updated schema (the existing schema test
  covers this; if none exists for *all* files, add one in this phase).
- Add a fixture JSON (in `tests/`) exercising every new field (incl. a `scan` block with
  `digit_enable`) and assert it validates; assert an invalid `style` value fails.

**Quality gates:** `uv run ruff check`, `uv run ruff format --check`, `uv run mypy .` (CI runs
mypy repo-wide — tests must stay clean), CHANGELOG entry (Unreleased/Changed), schema change
called out in the PR body.

### A1. Re-sync preservation guard (`scripts/sync_common.py`)

**Do:**

- In the shared JSON writer: before writing a board file, read the existing file (if any) and
  preserve top-level keys the calling sync script did not generate — at minimum
  `port_conventions` and `peripherals`.
- Digilent nuance: `sync_digilent_xdc.py` *generates* `port_conventions["digilent"]`; merge
  per-key — the generated `digilent` key wins, any other convention keys are preserved.

**Verify:**

- Unit tests: (a) inject a fake `port_conventions.custom` block into a board JSON fixture,
  run the writer, assert the block survives and generated keys updated; (b) digilent per-key
  semantics test; (c) file without conventions round-trips unchanged.
- Live check: run one real sync (`uv run python scripts/sync_amaranth_boards.py`) and confirm
  `git diff boards/` shows only expected sync changes; then hand-add a dummy convention to one
  amaranth board, re-run, confirm survival, revert.

**Quality gates:** as A0. This phase **must merge before A4** (population without the guard is
wiped by the next re-sync).

### A2. Constraint-dialect parsers (`scripts/port_convention_parsers/`)

**Do:** one pure module per dialect, `parse(text) -> PortTable` where `PortTable` lists
`(port_name, pin)` pairs plus any `FREQUENCY`/clock metadata the dialect exposes. Dialects and
**empirically confirmed gotchas** (from the registry work — encode each as a test fixture):

| Dialect | Match | Gotchas proven in the wild |
|---|---|---|
| QSF | `set_location_assignment PIN_x -to name[idx]` | device line = `set_global_assignment -name DEVICE …`; course files may rename ports |
| XDC | `set_property PACKAGE_PIN x [get_ports {name}]` | **`-dict { PACKAGE_PIN "x" … } [get_ports { Name }]` form** (Mimas A7); `create_clock` lines also contain `get_ports`; bracket-less `[get_ports clk]` |
| UCF | `NET "name" LOC = "pin"` | vector syntax `name<0>` **and** `name(0)`; PULLUP/PULLDOWN attrs |
| PCF | `set_io [-nowarn] name pin` | comments carry polarity hints (fomu-hacker) |
| LPF | `LOCATE COMP "name" SITE "pin"` | `FREQUENCY PORT "clk" nn MHz` gives the clock rate; `IOBUF PORT` lines |
| CST | `IO_LOC "name" pin;` | `IO_PORT` attribute lines; names vary per example project |
| CCF | `Pin_in/Pin_out "name" Loc = "x"` | GateMate; attributes after `\|` |
| BoardStore XML | `<pin index=… name ="X" loc=…/>` | **space before `=` in `name ="`**; repo default branch is a version (`2022.2`); Apache-2.0 |

- Derive vector widths from max index + 1; detect 7-seg structure (per-digit groups vs
  per-segment scalars vs shared-segment + enable ⇒ scan) by name-shape rules; classify
  clk/leds/buttons/switches with an interest/exclude filter (start from the proven regexes in
  the #198 research tooling; rewrite as tested code, not copy-paste).

**Verify:**

- pytest per dialect with committed fixture snippets **taken from the registry's fetched
  sources** (each gotcha row above gets at least one fixture). Repo convention: parser modules
  ship with their own test files (see `scripts/*_parser.py` + `tests/`).
- Golden test: parse the Digilent Basys3 master XDC fixture and reproduce the widths/names in
  `boards/digilent-xdc/basys_3.json`'s existing convention.

**Quality gates:** as A0; parsers must be network-free (pure text in, dict out).

### A3. Generator (`scripts/sync_port_conventions.py`) + curated overlay

**Do:**

- Row gate: registry `status == "verified"` **and** rank-1 `kind ∈ {vendor-official,
  official-repo}` **and** the registry row/notes do not mark naming as project-renamed
  **and** the board is listed in the current wave file.
- Wave file `docs/port_convention_sources/waves.toml`: explicit board-name lists per wave
  (reviewable data, not code).
- Overlay `docs/port_convention_sources/overlay.toml`: cited, hand-maintained facts the
  constraint files cannot state — polarity (`active_low`), canonical-clock choice on
  multi-clock boards, canonical clk names where the fetched source renamed them (e.g. Terasic
  `CLOCK_50` / `MAX10_CLK1_50` — citations exist as verification stamps in the registry rows),
  7-seg style overrides. Every overlay entry carries a `cite` string. Overlay wins over parsed.
- Pipeline per board: resolve source URL → download (reuse `sync_common` download + cache;
  resolve branch to a commit SHA via the GitHub API and record it) → parse (A2) → classify →
  cross-check widths against the board JSON's resource counts (**mismatch ⇒ warn + skip, never
  write**) → apply overlay → build convention block with `source` stamp + `naming` →
  schema-validate → shallow-merge into every `files[]` target under a maker-slug key.
- Modes: default write; `--check` (regenerate in memory, diff, exit non-zero on drift);
  `--board <name>` for single-board runs.

**Verify (the trust-establishing regressions — all four must pass before any A4 write):**

1. **Digilent regression:** generator output for the 26 digilent boards is dict-identical to
   the blocks the existing `sync_digilent_xdc.py` pipeline produces.
2. **Hand-authored regression:** regenerated Terasic blocks match Rick's 6 `boards/custom/`
   blocks field-for-field, or every difference is listed and adjudicated in the PR body.
3. **Idempotency:** running twice produces zero diff.
4. **Schema:** all touched files validate; `uv run pytest` green.

**Quality gates:** as A0, plus unit tests for the row gate, overlay precedence, and
mismatch-skip behavior.

### A4. Population waves (data PRs)

**Do:**

- **Wave 1 (teaching / 7-seg first):** DE0, DE0-CV, DE10-Lite, DE1-SoC, DE0-Nano, DE10-Nano
  (amaranth-boards); Nandland Go; RZ-EasyFPGA (both files); Runber. Terasic clk names come from
  the overlay (citations = the direct-fetch stamps in `terasic.toml`). STEP-MXO2 stays out
  (registry: candidate, gated docs). EGO1 stays out (project-renamed names).
- **Wave 2 (clean official-org families):** machdyne (8), iCE40 hobbyist verified set
  (ICEBreaker/Bitsy, Fomu PVT+Hacker, iCESugar+Nano, UPduino v3, TinyFPGA BX, HX8K-EVN),
  ULX3S + ULX4M, Trellisboard, Icepi Zero, Hadbadge, OrangeCrab, ECPIX-5, iCESugar-Pro,
  Alchitry Au, Mimas A7 (LED/switch/scan-seg recorded; scan consumed only by U22),
  miniSpartan6+, Pipistrello, CYC1000, MAX1000, Xilinx kits (KC705/KCU105/KCU116/ZCU102/ZCU216),
  PYNQ-Z2, Red Pitaya, EBAZ4205, LimeSDR Mini v2 + XTRX, Pano G2, TimeCard, LiteFury/NiteFury-II,
  Acorn, FK33, Lattice EVN set (community-canon PDC/LPF — mark `naming` accordingly if names
  look example-specific).
- Run the generator per wave; review the diff board-by-board before commit (the PR body lists
  each board with its source URL).

**Verify:**

- `uv run pytest` (loader still loads all 278 boards; conventions are inert data until Part B).
- `scripts/sync_port_conventions.py --check` clean after each wave commit.
- Re-run one upstream sync script and confirm the guard (A1) preserves every populated block.
- Spot-check three boards per wave by opening the recorded source URL and comparing names.

**Quality gates:** as A0; CHANGELOG entry per wave PR.

---

## Part B — the simulator feature (U21 proper)

### B1. Thread conventions into the runtime (`board_loader.py`)

**Do:** add `port_conventions` to `BoardDef` (typed: a small dataclass mirror of the schema,
or `dict` in the first cut — decide in-phase, mypy-strict either way), populate it in the
loader, include it in `BoardDef` JSON serialization (it rides `FPGA_SIM_BOARD_JSON`
harmlessly; wrapper generation happens launcher-side so the subprocess never needs it).

**Verify:** loader unit tests — a board with conventions exposes them; a board without gets
an empty mapping; serialization round-trips; all 278 boards still load
(`project_board_loading_facts`: the count is 278, not 281).

### B2. Convention matcher (`sim_bridge.check_vhdl_contract`)

**Do:**

- New branch after the generic-contract check fails (generic contract keeps priority): try each
  of the selected board's conventions with `naming` = canonical; match parsed ports
  (`_parse_toplevel_interface` output — names are already lowercased; VHDL case-insensitivity
  is free) against convention names; exact widths per decision 5; polarity/structure recorded
  into the returned `ContractResult`.
- Native mode inverts one rule: fixed widths equal to convention widths are *expected*
  (the generic contract rejects fixed widths — keep that behavior on the generic path).
- Near-miss errors: if ≥2 convention ports match but others are missing/mis-sized, the error
  message names the convention and lists what's missing (wire into `add_error_hints` wording
  style).

**Verify:** unit tests: DE10-Standard-style entity matches `terasic`; wrong widths produce the
clear error; a generic-contract file is untouched by the new branch; a board without
conventions short-circuits. Test file naming/entity rules unchanged (entity = filename stem).

### B3. Native wrapper generation (`sim_bridge._generate_wrapper` + template)

**Do:** for a convention match, generate the uut instantiation from the parsed interface +
convention: port renames, button/LED polarity inversion (`KEY_i <= not btn`), no generic map
on the uut (native designs have none), early elaboration at **board-real widths** (the
defaults dance is generic-path-only), 7-seg adapters for the two in-scope styles:
per-digit (`seg[8i+k] <= not HEXi(k)`, dp tied) and per-segment scalars (same, scalar-wise).
cocotb testbench unchanged (wrapper still exposes `sw/btn/led/seg`); `.gtkw` writer (U28)
unchanged for the same reason.

**Verify:**

- New example files under `hdl/native/`: a DE10-Standard-style `golden_blinky` (CLOCK_50/KEY/
  LEDR/SW/HEX0-5, small divider constants — the frozen-divider doc note explains why) and a
  Nandland-Go-style per-segment example.
- Headless e2e on **both GHDL and NVC** via the recipe in
  `reference_headless_sim_testing` memory / existing test patterns: native file analyzes,
  elaborates, simulates; LEDs respond to switches; HEX digits read back correctly inverted.
- Full `uv run pytest`; benchmark unaffected (native path only activates on convention match).

### B4. Docs + done-when

**Do:** README/docs section for board-native mode (which boards, what's supported, the
frozen-divider expectation note); roadmap U21 card updates.

**Done when (arc):** a DE10-Standard-style file with native port names simulates unmodified
(the U21 card's criterion), the Nandland per-segment example passes on both simulators, all
sim-supported 7-seg boards except the scan/serial set have populated conventions, and
`--check` + full test suite are green in CI.

---

## Cross-cutting quality gates (every phase PR)

- `uv run ruff check` + `uv run ruff format --check` + `uv run mypy .` + `uv run pytest`
  locally before every commit (CI mypy is repo-wide; tests must stay typed-clean).
- CHANGELOG entry per PR (house rule since the v0.9.0 arc); never predict PR numbers in docs.
- Before each PR: explicitly consider doc updates and test additions (standing checklist).
- US spelling everywhere. VHDL examples plain ASCII.
- Typed-identifier changes follow the value's full round-trip (loader → controller → launch),
  not just the card's function list.

## Status ledger

| Phase | Scope | PR | Status |
|---|---|---|---|
| A0 | Schema deltas | #209 | in review |
| A1 | Re-sync guard | — | not started |
| A2 | Dialect parsers | — | not started |
| A3 | Generator + overlay | — | not started |
| A4 | Wave 1 + Wave 2 population | — | not started |
| B1 | BoardDef threading | — | not started |
| B2 | Convention matcher | — | not started |
| B3 | Native wrapper + e2e | — | not started |
| B4 | Docs + closeout | — | not started |

## Closeout checklist (do not skip — explicit step per the planning-lessons memory)

- [ ] Roadmap: U21 card marked shipped with PR list; downstream refs updated (U22 note about
      scan data being ready; Icebox: add frozen-divider heuristic; P2 subset note resolved).
- [ ] Registry README: add the "how population consumes this" section pointing at the
      generator; statuses of enriched rows updated.
- [ ] This doc: status ledger complete; lessons-learned section appended.
- [ ] Memory: arc memory updated (plan → shipped), release-plan memory updated.
- [ ] CHANGELOG entries verified across all phase PRs before the release that ships U21.

## Risk register

| Risk | Mitigation |
|---|---|
| Upstream constraint files drift/vanish | generator records resolved commit SHA at fetch; registry keeps alternates; cache |
| Re-sync wipes populated blocks | A1 ordering is mandatory before A4 |
| Overlay asserts wrong polarity | every entry cited; wave-1 spot-checks against manuals |
| Schema churn between A0 and U22 | style enum is additive; scan fields land now, consumed later |
| Sipeed-style per-example naming instability | those families need `naming` review before population; hold if unclear |
| Course-QSF renamed clocks (Terasic) | clk names come from the overlay with citations, never from course files |
