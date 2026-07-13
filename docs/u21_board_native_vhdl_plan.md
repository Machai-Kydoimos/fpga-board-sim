# U21 — Board-native VHDL: arc plan (conventions population + matcher + wrapper)

**Status:** ✅ COMPLETE (2026-07-13). Part A: A0 (#209), A1 (#210), A2 (#211), A3 (#212) merged; schema-symmetry follow-up (#213) and `boards/custom/`-trust gate follow-up (#214) merged; A4 Wave 1 (#215) + DE10-Lite (#218) and DE0 (#219) rescues merged. Part B: B1 (#216), B2 (#217), B3a (#220), B3b (#221) merged; B4 (docs + closeout) is the PR carrying this update. See the [status ledger](#status-ledger) and [lessons learned](#lessons-learned). The board-native done-when is met: a Terasic-native file (`CLOCK_50` / `KEY` / `LEDR` / `SW` / `HEX0`-`HEX5`) simulates unmodified.
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

## Open questions (resolved) — both recommendations adopted

- Where the matched convention surfaces in UX. *Recommendation:* analysis-spinner text +
  `sim_session_log` field; no new dialog. **✅ Adopted** (B3b): spinner reads "Analyzing
  board-native …", the session log gained `mode`/`convention`, plus an info-strip mode tag and a
  stats-panel active-low note — no new dialog.
- Whether `check_vhdl_contract`'s return grows a typed result object now or a third tuple
  element. *Recommendation:* small frozen dataclass `ContractResult` (repo precedent: typed
  results, D6a/U7). **✅ Adopted** (B2): frozen `ContractResult(ok, message, match)` +
  `ConventionMatch`.

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
  - *Refined after A3, since `kind` labels where a file is hosted, not whether its port
    names are canonical:* the `kind` check (only that check — never `status`/wave) is also
    satisfied by (a) a `files[]` target under `boards/custom/` (#214: a human already verified
    it against vendor docs), or (b) a rank-1 source explicitly vouched `naming = "canonical"`
    with a `naming_cite` (A4 #204: `_rank1_vouched_canonical`). (b) is *how* the "exclude
    project-renamed naming" rule above is actually enforced — a renamed course file simply
    never earns the cited vouch.
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

**Realized — Wave 1 (A4, closes #204).** The pedagogical Wave-1 list above and the A3 row gate
were composed independently and don't fully intersect (root cause of the "0/10 populate" pause):
Terasic ships no vendor-official per-board QSF repo, so its teaching-board constraint files in
the wild are community-hosted, and the un-refined `kind` gate rejected all of them. Resolved by
the cited canonical-naming trust signal (see the A3 row-gate refinement note). **3 boards ship**,
each verified by direct fetch to use vendor-canonical Terasic names, with cited `overlay.toml`
polarity (and DE1-SoC's canonical clock):

- **DE0-CV** (`amaranth-boards/de0_cv.json`) — LEDR/SW/KEY/HEX0..5/CLOCK_50.
- **DE1-SoC** (`amaranth-boards/de1_so_c.json`) — same; clk pinned to CLOCK_50 via overlay
  (the QSF's CLOCK2/3/4_50 + ADC_SCLK otherwise mislead classify()).
- **DE0-Nano** (`amaranth-boards/de0_nano.json`) — LED(8)/SW(4)/KEY(2)/CLOCK_50, no 7-seg.

The other seven Wave-1 rows stay listed in `waves.toml` (they self-include once fixed) but are
held back, each with a recorded reason:

- **DE0** — **RESCUED** (System-CD follow-up, PR below): the A2 classifier learned the split
  `HEXn_D[6:0]` + `HEXn_DP` per-digit style (→ `individual`) and now routes a green-only LED bank
  (`LEDG`) to `leds`; clk pinned to `CLOCK_50` via overlay. Names are golden-top-confirmed
  canonical, so it uses the standard naming vouch. Now populated in Wave 1.
- **DE10-Lite** — **RESCUED** (System-CD follow-up, PR below): its rank-1 course QSF renames
  `LEDR`→`LED` and `MAX10_CLK1_50`→`Clk`; a cited overlay resource-name override (verified against
  the DE10-Lite System CD v2.2.0 golden top) restores both to canonical, admitted by the new
  `_overlay_supplies_cited_canonical_names` gate bypass. Now populated in Wave 1.
- **DE10-Nano** — registry `candidate` (+ sparse source); populate once upgraded to `verified`.
- **Nandland Go** — board JSON has 0 switches vs the PCF's 4; needs a resource supplement (not a
  hand-edit — A1's guard doesn't preserve resource-count edits across re-sync). Also `personal` kind.
- **RZ-EasyFPGA (both files)** — rank-1 QSF has 5 buttons (`KEY[0..4]`) vs the board JSON's 4
  (pin 25 / `KEY[4]` missing upstream); same resource-supplement caveat.
- **Runber** — rank-1 is `MD` (no parser); the CST alternates are incomplete → partial convention
  only (Decision #4 defers partial-interface support).

**Verify:**

- `uv run pytest` (loader still loads all 278 boards; conventions are inert data until Part B).
- `scripts/sync_port_conventions.py --check` clean after each wave commit.
- Re-run one upstream sync script and confirm the guard (A1) preserves every populated block.
- Spot-check three boards per wave by opening the recorded source URL and comparing names.

**Quality gates:** as A0; CHANGELOG entry per wave PR.

### A4 follow-up ✅ — Terasic System-CD wave via overlay name-override

Discovered during A4: Rick provided the official Terasic System CDs / Resource Packages
(DE0-CV, DE0-Nano, DE10-Lite, DE10-Standard, DE23-Lite, DE25-Standard, VEEK-MT2, VEEK-MT-SoCKit).
Their `golden_top` / `Default` QSFs are the **vendor-official** canonical source; they validated
the three A4 boards and the hand-authored `custom/` DE10-Standard block field-for-field, and they
unlock boards the registry can't currently populate:

- **DE10-Lite** — **DONE (this follow-up's first PR).** Official golden top confirms canonical
  `LEDR`/`SW`/`KEY`/`HEX0..5` + `MAX10_CLK1_50`; the community rank-1 renames only `LEDR`→`LED`
  and the clk (confirmed by direct fetch — the registry's normalized `leds = "LEDR[0..9]"` masked
  the literal `LED`). A cited overlay `[board.leds] name` + `clk` override restore both to
  canonical, and the new `_overlay_supplies_cited_canonical_names` gate bypass admits the board.
  HEX ships 7-bit (segments only, per the source), matching DE0-CV/DE1-SoC.
- **DE0** (original Cyclone III — a *different* board from DE0-CV: EP3C16 vs 5CEBA4, 3 buttons vs 4,
  4 digits vs 6) — **DONE (this follow-up's second PR).** Official DE0 CD-ROM v1.1 golden top
  (`DE0_Default.qsf`) confirms canonical `LEDG`(10) / `SW`(10) / `BUTTON`(3) / `CLOCK_50` + four
  7-seg digits `HEXn_D[6:0]` **plus a separate `HEXn_DP` scalar**. Two `classify.py` additions
  landed it: a split `<name>_D[k]`+`_DP` per-digit branch (→ `individual` over the `_D` ports, the
  DP recognized-but-unlisted → the sim's 8th bit stays unused, as on the bare-`HEXn` boards) and
  green-only-bank → `leds` routing. Names are canonical verbatim in the source, so standard naming
  vouch + a clk overlay (classify mis-picks `GPIO0_CLKIN`). Reusable older-Terasic convention.
- **DE23-Lite, DE25-Standard, VEEK-MT2** — registry `candidate`/PDF-gated (no machine-parseable
  source today); their Resource-Package golden tops carry clean canonical `LEDR`/`SW`/`KEY`/`HEX`
  (VEEK-MT2: 27 LEDs = LEDR18 + LEDG9, 8 digits). Authoritative source for validating/completing
  the hand-authored `custom/` candidate blocks and for a future wave.

**Mechanism:** extend `overlay.toml` (+ `apply_overlay`) to override a `port_mapping`'s `name`
(today it overrides only `clk` name + `active_low`), each carrying a `cite` to the System-CD
version + file. **Licensing: cite-not-copy** — the CDs are Terasic-copyrighted, so record the
*fact* (the canonical name) with a versioned citation and do **not** commit the QSFs (respects
Locked Decision #1). This also addresses the model gap that Terasic's best source is a downloaded
ZIP, not a raw URL. A **second, independent mechanism** is needed for DE0: teach the A2 classifier
the `<name>_D[k]` + `<name>_DP` per-digit 7-seg style (see the DE0 bullet). **Scope:** small
additive `apply_overlay` name-override + the A2 classifier extension + tests, then a data wave;
its own PR(s), not folded into A4. **Status: ✅ done.** PR 1 (#218) shipped the `apply_overlay`
name-override + the `_overlay_supplies_cited_canonical_names` gate bypass + DE10-Lite; PR 2 (#219)
shipped the A2 `<name>_D`/`_DP` classifier extension + green-only-LED routing + DE0. DE25-Standard's
candidate `terasic` block was then exercised end-to-end as B3a's active-low-LED example
(`hdl/native/de25_standard.vhd`, GHDL + NVC), validating it against a real native design. DE23-Lite
and VEEK-MT2 remain read-only-validation candidates for a future data wave (no machine-parseable
source today) — not blockers for U21's done-when.

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

**Realized (B2, this PR):** `check_vhdl_contract` now returns a frozen
`ContractResult(ok, message, match)`; `match_convention()` + `ConventionMatch`/`NativePort`/
`NativeSeg` are the pure detector. Deltas from the sketch above, all toward correctness:

- **`naming`:** the schema documents *absent = canonical*, and every hand-authored Terasic
  block (incl. the flagship DE10-Standard) omits it — so the matcher skips only an explicit
  `project-derived`, not "== canonical" (which would have excluded every custom board).
- **7-seg scope:** only `individual` (the sole style in canonical board data) is matched;
  `packed_vector`/`scan`/`serial`/`per_segment_scalars` decline (→ generic path / U22 / a B3
  extension once a real example pins the `per_segment_scalars` port layout).
- **`leds_green`** is an optional secondary bank (captured if the design declares it, never
  required); LED/switch/button banks accept both the `name`+`width` vector form and the
  `names` scalar-bank form (Nandland-style).
- **Native-detection guard:** a design that declares the simulator's own sizing generics
  (`NUM_SWITCHES/BUTTONS/LEDS/SEGS`) is a broken *generic* design, not board-native.
- **`ok` stays False for a native match** (the message names the board + native ports and
  points at B3); `match` rides on the result for B3 to consume. **5 call sites** updated, not
  4 — `scripts/gen_embedded_core.py` was the missed one (it mixed the tuple unpack with
  `check_vhdl_encoding`).
- Tests: new `tests/test_convention_matcher.py` (27 cases); the generic-contract suites keep a
  local `_contract()` → `(ok, message)` shim so their assertions are untouched.

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
| A0 | Schema deltas | #209 | merged |
| A1 | Re-sync guard | #210 | merged |
| A2 | Dialect parsers | #211 | merged |
| A3 | Generator + overlay | #212 | merged |
| A4 | Wave 1 population (3 boards) + DE10-Lite / DE0 rescues | #215, #218, #219 | merged |
| B1 | BoardDef threading | #216 | merged |
| B2 | Convention matcher + typed `ContractResult` | #217 | merged |
| B3a | Native wrapper + GHDL/NVC e2e + `hdl/native/` examples | #220 | merged |
| B3b | Run affordances (info tag, stats note, session log, spinner) | #221 | merged |
| B4 | Docs + closeout | this PR | merged |

## Closeout checklist (do not skip — explicit step per the planning-lessons memory)

- [x] Roadmap: U21 card condensed to a shipped ✅ stub with the PR list; downstream refs updated
      (U22 dependency note now past-tense "landed"; Icebox **P15** cross-board ambiguity + **P16**
      Surfer preselection + **P17** frozen-divider heuristic added; P2 subset note resolved to
      "shipped as A1 ✅ (#210)"). *(B4)*
- [x] Registry README: "How population consumes this" section added pointing at
      `sync_port_conventions.py` + the A2 parsers; the stale "(planned)" pipeline wording fixed.
      Row-level `status`/enrichment updates are maintained per population PR (A3 #212 / A4 #215).
      *(B4)*
- [x] This doc: status ledger complete (all phases merged); lessons-learned section appended;
      CLAUDE.md gained a board-native VHDL subsection + `hdl/native/` file-table row. *(B4)*
- [x] Memory: `project_u21_arc_progress` flipped to arc-complete; index hook updated. *(B4)*
- [x] CHANGELOG: per-phase [Unreleased] entries present for A0–A4, B1, B2, B3a, B3b + a B4
      closeout entry (all under one release bucket when U21 ships).

## Lessons learned

- **Bake the board widths as the native wrapper's generic *defaults*.** Because `analyze_vhdl`'s
  early elaboration calls `elaborate_cmd("sim_wrapper", {}, …)` with *no* generics, emitting
  `NUM_LEDS := 10` (etc.) as the wrapper entity's defaults makes the top ports line up with the
  native uut's fixed widths with zero changes to the launch/run path or the cocotb testbench — the
  key move that kept B3a localized to `sim_bridge.py` + a thin `match` thread. Avoid a "defaults
  dance" (re-elaborating with explicit generics just for the early check).
- **Cross-board safety is data-dependent — make it a regression *invariant*, not detection.** No
  silent polarity flip is possible with today's data (the only cross-board full match, DE23↔DE25,
  agrees on polarity), but that hinges on names/widths/polarity differing. A sweep-all-pairs test
  that asserts no cross-board full match diverges on polarity turns an incidental safety property
  into one that **fails loudly** if a future board breaks it — better than speculative global
  ambiguity detection (parked P15).
- **GHDL and NVC both emit lowercase identifiers in the VCD/FST.** Verified against a real native
  dump; the `.gtkw` native preselection lowercases the `sim_wrapper.uut.<native>` names accordingly.
  Don't assume the source-case `LEDR`/`HEX0` survives into the dump.
- **Split by review surface, not just by layer.** Rick's B3a (core execution: `ok=True` flip +
  native wrapper + e2e) / B3b (UX: mode tag, stats note, session log, spinner) split kept each PR
  independently reviewable; B3b consumed the `FPGA_SIM_NATIVE_CONVENTION` env B3a already exported,
  so it added *no* new detection logic.
- **Fit new overlays into fixed panel geometry.** The stats-panel active-low note is one small-font
  line in the ~13 px of slack below the existing INFO rows, so the panel height (and therefore the
  board size) is unchanged — verified with headless screenshots before merge. "Don't let the stats
  overlay shrink the board into obscurity" was an explicit constraint.
- **Inspect source *names*, not just widths, when vouching a board.** (Carried from A4.) The "5
  clean boards" count was a width-only over-count; boards whose community QSF renamed resources
  (DE10-Lite `LEDR`→`LED`, DE0 `HEXn_D`) needed a cited overlay name-override, not a straight ship.

## Risk register

| Risk | Mitigation |
|---|---|
| Upstream constraint files drift/vanish | generator records resolved commit SHA at fetch; registry keeps alternates; cache |
| Re-sync wipes populated blocks | A1 ordering is mandatory before A4 |
| Overlay asserts wrong polarity | every entry cited; wave-1 spot-checks against manuals |
| Schema churn between A0 and U22 | style enum is additive; scan fields land now, consumed later |
| Sipeed-style per-example naming instability | those families need `naming` review before population; hold if unclear |
| Course-QSF renamed clocks (Terasic) | clk names come from the overlay with citations, never from course files |
| Community QSF renamed *resources* (not just clk), admitted via the canonical-naming vouch | vouch is per-source, cited, and width-cross-checked; the overlay corrects the clk name but *not* resource names, so a board whose course QSF renames LEDs/switches/buttons is held back with a recorded reason (DE10-Lite: `LEDR`→`LED`), never shipped with non-canonical names |
| ~~`port_mapping` (leds/switches/buttons) had no `names` list like `seg_port_mapping` got in A0~~ | **RESOLVED, PR #213** (pre-A4-Wave-1): added optional `names: string[]` to `$defs/port_mapping`; `classify.py` now populates it for distinct un-bracketed scalar groups (Nandland Go's `o_LED_1..4`) instead of declining |
