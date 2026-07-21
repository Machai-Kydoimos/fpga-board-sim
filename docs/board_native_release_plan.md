# Board-native release (v0.14.0) — execution plan

**Status:** ✅ COMPLETE — **v0.14.0 released 2026-07-16** (all phases merged; see the Status ledger at the end).
**Goal:** ship the board-native VHDL arc (U21 + U31 + U32 + U33, unreleased on `main`
since v0.13.0, 25 commits) as **v0.14.0**, after (a) fixing every finding from the
2026-07-15 full-arc review and (b) restructuring the documentation so the README serves
newcomers and four focused `docs/` files carry the depth.
**Executor:** a capable model (Opus class), phase-by-phase, no additional context needed
beyond this plan + `CLAUDE.md` + `CONTRIBUTING.md`. Do not start a phase until the
previous phase's Verify steps pass. **One PR per phase** (repo precedent: the U21 arc,
PRs #209–#222); never commit to `main` directly; branch each phase off post-merge `main`.
**Milestone:** use the existing empty milestone **#4 "v0.14.0"** (retitle to
"v0.14.0 — board-native release"); file one issue per phase into it at execution start
(hybrid backlog model). The UX cards previously penciled for v0.14.0 (U8/U9/U23/U27)
move to a new v0.15.0 milestone — milestone re-slots are established precedent.
**Review evidence:** every finding below was verified against live behavior on
`main` @ `db49065` (probes, fleet sweeps, a full GHDL+cocotb native run), not just read
from code. Line numbers reference that commit and may drift a little — anchor on the
named functions.

---

## Locked decisions (do not relitigate; recorded 2026-07-15 with Rick)

1. **README target: ~250 lines, newcomer-only.** Story: hook (badges + the two
   existing GIFs) → happy-path install → two guided demos → "write your own VHDL"
   (generic contract *and* an inline board-native example — the release headline) →
   features-at-a-glance (one line each, linked) → docs index / dependencies /
   contributing pointer / talks / acknowledgements / license.
2. **Four focused docs, one audience each** (all under `docs/`):
   `install.md` (full install matrix + ALL troubleshooting), `user_guide.md` (the app
   reference: screens, shortcuts, settings, waveforms, persistence),
   `writing_designs.md` (the VHDL author's contract reference incl. board-native in
   full), `architecture.md` (project tree, pipeline, backends, native-mode internals).
3. **Install depth in README: happy path only.** One GHDL command per OS
   (winget/apt/dnf/brew) + a two-line NVC mention; everything else (from-source, MSYS2,
   AUR/Gentoo/FreeBSD, Windows PATH surgery) lives in `docs/install.md`.
4. **README demos: snake + 6502 + native.** Walk through `hdl/snake_7seg.vhd` (matches
   the hero GIF) and `hdl/mx65_walking_counter_7seg.vhd` (soft-CPU wow); the
   "your own VHDL" section shows the generic contract snippet **and** a ~10-line
   board-native `CLOCK_50`/`LEDR` example.
5. **Architecture has exactly one home.** `docs/architecture.md` absorbs
   CONTRIBUTING.md's "Architecture overview" section; CONTRIBUTING keeps a 2-line
   pointer.
6. **All eight review findings get fixed** (Phases 1–2 below). None are optional.
7. **`sync_port_conventions.py --check` stays a manual, checklist-enforced step**, not
   a CI job (it needs live network + GitHub API). It is added to the release checklist;
   a scheduled-CI variant is parked in the Icebox (Phase 4 adds **P19**).
8. **Code fixes land before docs** (Phases 1–2 before 3), so the new docs describe
   post-fix behavior — e.g. "a one-LED board accepts `led : out std_logic`" must be
   true when written.

---

## Review findings — the evidence base

Summary of the 2026-07-15 review findings this plan resolves. F-numbers are used
throughout the phases.

| # | Finding | Verified how |
|---|---------|--------------|
| F1 | Width-1 LED banks reject a natural scalar port (`led : out std_logic`); user gets the **generic-contract** error (misleading). 42 convention blocks fleet-wide advertise `{"name": …, "width": 1}` | Live probe on TinyFPGA BX: scalar spelling → "Missing required port(s): clk, sw, btn"; `std_logic_vector(0 downto 0)` spelling → full match |
| F2 | Canonical and framework blocks disagree on LED polarity for the same physical LEDs on 4 boards: `de0_cv` (terasic high vs amaranth low), `litefury` + `nitefury_ii` (rhs_research low vs amaranth high), `sipeed_tang_nano_9k` (sipeed low vs litex high). In all 4 the cited canonical block is physically right. Upstream `amaranth-boards/de0_cv.py` has `invert=True` on LEDs — apparent upstream bug (DE0-CV LEDR are active-high per the user manual) | Fleet sweep script + upstream fetch of `de0_cv.py` |
| F3 | Native matcher rejects extra inputs **with defaults** (near-miss), while the generic path accepts them; an unassociated `in` with a default is legal VHDL in both simulators | Live probe: `UART_RX : in std_logic := '1'` added to a full DE10-Standard native match → near-miss |
| F4 | Stale user-facing near-miss message: "(U21 B3) … until then" implies the feature is unshipped; internal ticket ID in user text; message doesn't name which convention block near-missed. Also stale *internal* text: the B2 comment block above the matcher and the `check_vhdl_contract` docstring still say `ok` stays False / "the native wrapper … lands in B3" | Live probe of the message; code read |
| F5 | `classify.py` (A2/A3 pipeline) still classifies LEDs by bare `led` substring — the U33 Wave-4 token hardening went to the litex/amaranth parsers and the digilent section classifier, not here. A future golden-top QSF with `oled_d[15:0]` would win the LED bank (then fail-safe skip on width, needing hand-diagnosis) | Code read; `_LED_INTEREST = re.compile(r"led", IGNORECASE)` at classify.py:54 |
| F6 | Scalar-bank (`names[]`) matcher members aren't width-checked: a member declared `std_logic_vector(7 downto 0)` "matches", then dies at elaboration with a cryptic association error | Code read: `_match_native_port` names branch checks existence+mode only |
| F7 | README drift: native section omits `arty_litex.vhd`, never mentions framework-derived coverage (~273/278 boards with conventions), sources bullet still says "~26 Digilent boards with port_conventions" | README read |
| F8 | No automated **native cocotb-loop** test (suite covers native analyze on both sims + one standalone NVC run). A manual GHDL+cocotb run of `arty_litex.vhd` on the Arty passed (zero-extend + sw→led XOR verified) | Live run 2026-07-15 |

Additional review notes folded into phases: `rgb_led` width-1 framework banks are
fictional port names (Phase 2); `_native_port_map` maps a **single-entry** `names[]`
bank as a whole vector, which is wrong for scalar ports (fixed by F1's flag design).

Explicitly **parked** (do not do in this arc): CI job for `--check` (P19, Phase 4),
proper RGB-subsignal native banks (P20, Phase 4), A1 stale-sub-key deletion semantics,
`digit_enable` consumption (U22), native matching for files whose interface the parser
can't parse (legacy fallback path).

---

## Phase 1 — matcher/wrapper correctness + ergonomics (F1, F3, F4, F6, F8)

All changes in `src/fpga_sim/sim_bridge.py` + tests. Pure behavior changes with tests
landing in the same PR.

### Do

**F1 — accept a scalar port for a width-1 vector bank.**

- Add a field to `NativePort`: `scalar_ports: bool = False` — "each entry in `names`
  is a scalar port". Set it `True` in `_match_native_port` for (a) the existing
  `names[]` scalar-bank branch, and (b) a **new acceptance**: vector-form mapping with
  `width == 1` where the design declares the port with `literal_width is None`
  (a scalar such as `std_logic`). Keep accepting `std_logic_vector(0 downto 0)`
  (`literal_width == 1`) as a non-scalar match, so both spellings work.
- `_native_port_map` (sim_bridge.py:1267): key the whole-vector vs per-bit choice off
  `scalar_ports`, **not** `len(port.names) == 1`. This also fixes the latent
  single-entry-`names[]` bug (a one-member scalar cluster currently gets a
  whole-vector association).
- `_native_gtkw_signals` (sim_bridge.py:1700): a `scalar_ports` bank emits per-name
  **unranged** paths (`sim_wrapper.uut.led`, no `[0:0]`), matching how GHDL/NVC dump
  scalar signals.
- The wrapper's internal signal stays a `(width - 1 downto 0)` vector in both cases;
  per-bit association `name => sig(0)` is legal VHDL (scalar formal ← element actual).

**F3 — allow extra inputs that carry defaults.**

- In `_attempt_convention`'s unmapped-input check (sim_bridge.py:949), skip decls with
  `has_default`: `mode == "in" and not decl.has_default`. Leave `inout` handling as is
  (unbound non-`in` ports elaborate; verified in U31). This makes the native path
  consistent with the generic path (`_check_parsed_contract` line ~664), and with the
  LRM: an unassociated `in` **with** a default expression is legal in GHDL and NVC.

**F6 — width-check scalar-bank members.**

- In `_match_native_port`'s `names[]` branch, require `decl.literal_width is None` for
  every member (they are scalar ports by definition). A vector-typed member becomes a
  clean near-miss instead of a cryptic elaboration failure.

**F4 — fix stale text, internal and user-facing.**

- `_near_miss_convention_message` (sim_bridge.py:1074): remove "(U21 B3)" and
  "until then"; name the convention. Target wording (adjust for flow, keep the parts):

  > `'{filename}' is close to {board_name}'s board-native '{maker}' interface but
  > does not fully match it (missing/mismatched: {problems}).`
  > `Fix those ports to run it board-native, or use the generic clk/sw/btn/led
  > contract (see hdl/blinky.vhd).`

  This needs the maker on the near-miss path: `check_vhdl_contract` already holds the
  `_ConventionAttempt` — pass `attempt` (which has `.maker`) into the message helper.
- Rewrite the stale **B2 comment block** above the matcher (sim_bridge.py:723–736,
  "B2 only *detects* … does not yet accept it") and the stale paragraph in
  `check_vhdl_contract`'s docstring (sim_bridge.py:1095–1099, "``ok`` stays False —
  running a native design needs the B3 wrapper") to describe shipped reality: a full
  native match returns `ok=True` and runs via the native wrapper.

**F8 — add the native cocotb-loop test.**

- New `@pytest.mark.slow` test in `tests/test_native_convention.py`: run
  `hdl/native/arty_litex.vhd` on `boards/litex-boards/digilent_arty.json` through
  `check_vhdl_contract` → `analyze_vhdl(match=…)` → the **real GHDL run command with
  cocotb loaded**, driving a minimal cocotb module (inject its directory via
  `PYTHONPATH`, mirroring `_testbench_native_helpers`). Assertions (all verified
  manually 2026-07-15): `dut.led` upper 4 bits stay 0 (zero-extend); setting
  `dut.sw = 0b0101` flips `led`'s low nibble by exactly `0b0101` (the design XORs
  switches onto mid counter bits, which are stable over a few µs).

### Verify

- New unit tests, all in the same PR:
  - width-1 vector bank matches a scalar decl **and** a `(0 downto 0)` decl; a
    width-≥2 bank still rejects a scalar.
  - wrapper render for a scalar-matched bank associates per-bit; `.gtkw` writer emits
    the unranged path.
  - full match with a defaulted extra input; near-miss retained for a default-less
    extra input (update `test_partial_extra_input_near_miss_message` accordingly).
  - `names[]` member with a vector type → near-miss.
  - near-miss message: asserts the maker appears and "U21 B3"/"until then" do not.
    Update the wording-pinned tests: `tests/test_convention_matcher.py`
    (`test_contract_near_miss_names_the_convention`) and
    `tests/test_native_convention.py` (`test_partial_match_message_lists_only_declared_roles`,
    `test_partial_extra_input_near_miss_message`).
- Extend the fleet self-match invariant
  (`test_every_canonical_board_matches_its_own_synthesized_interface`): for boards
  whose primary bank has width 1, synthesize **both** spellings (scalar and
  `(0 downto 0)`) and assert both match.
- e2e: GHDL + NVC `analyze_vhdl` of a scalar-led design on a real width-1 board
  (e.g. `boards/amaranth-boards/tiny_fpgabx.json`) and of a full-match design carrying
  a defaulted extra input — proves the wrapper elaborates in both cases.
- Full suite green (`uv run pytest`): 1678 tests pre-phase; expect net growth.

### Quality gates

`uv run ruff check` + `uv run ruff format --check` + `uv run mypy .` +
`uv run pytest` locally before every commit; CHANGELOG `[Unreleased]` entry (Fixed +
Added); PR body lists each finding fixed with its one-line evidence.

---

## Phase 2 — data fidelity (F2, F5, rgb width-1 survey) + fleet polarity test

Changes in `scripts/framework_conventions.py`, `scripts/sync_common.py`,
`scripts/sync_port_conventions.py` (call site only), `scripts/port_convention_parsers/classify.py`,
the two framework parsers if the rgb survey requires, regenerated `boards/` data, and tests.

### Do

**F2 — polarity reconciliation (canonical is the physical truth).**

- New **pure** helper in `scripts/framework_conventions.py`:
  `reconcile_framework_polarity(port_conventions: dict) -> dict`. Rule: for each
  `naming == "framework-derived"` block, for each of `leds` / `switches` / `buttons`
  (and `leds_green` when both sides have it): if a canonical block (`naming` absent or
  `"canonical"`) on the same board maps the **same role at the same width** (join on
  role + width; shape may differ — canonical `names[]` of width 4 reconciles a
  framework vector of width 4), set/clear the framework bank's `active_low` to the
  canonical bank's effective value (absent = active-high, which for curated canonical
  blocks is a deliberate claim). Document the rule in the module docstring: *polarity
  is a physical fact; cited canonical data wins; framework blocks keep their names but
  inherit truth.*
- Call it from **both** writers so re-syncs converge from either direction:
  `sync_common._fold_forward_unmanaged_keys` (after the per-sub-key merge) and
  `sync_port_conventions.write_results` (after merging new canonical blocks in).
- **Fleet consistency test** (new, `tests/test_native_convention.py` or a new data-
  invariants file): sweep all committed board JSONs; assert no framework block
  disagrees with a same-board canonical block on same-width primary-bank polarity.
  This is the review's sweep, made permanent — it currently fails on exactly 4 boards
  and must pass after the regen.
- Regenerate: `uv run python scripts/sync_litex_boards.py` and
  `…/sync_amaranth_boards.py` (and digilent for completeness). Expected diff: exactly
  the 4 boards' framework banks change polarity; if upstream moved since the U33
  full-sync-at-HEAD, land clean upstream drift as a **separate commit** in the same PR
  so the reconciliation diff stays reviewable.
- **Upstream issue (draft only — Rick approves before anything is posted):** prepare
  the text for an `amaranth-lang/amaranth-boards` issue: `de0_cv.py` marks LEDs
  `invert=True`, but DE0-CV LEDR are active-high (cite the DE0-CV user manual section
  and the System-CD golden-top citation already recorded in
  `docs/port_convention_sources/overlay.toml`). Re-verify both citations before
  drafting. Park the draft in the PR body or a gist reference — **do not file it
  autonomously**.

**F5 — token-harden `classify.py`.**

- Replace the bare-substring LED interest (classify.py:54) with the token-boundary
  approach already proven in `scripts/amaranth_parser.py` (`_LED_TOKEN =
  re.compile(r"(?:^|[_\-0-9])led")`, see its comment for the rationale: `m2led` and
  `led0` count; `oled*` does not). Apply the same boundary to the `ledg` secondary-bank
  interest so the pair stays consistent. Port the U33 fixture set into
  `tests/test_port_convention_parsers_classify.py`: `oled`/`oled_d[15:0]` alongside a
  real `ledr[9:0]` bank (the OLED group must not win the bank), `segled_*` routed away
  from LEDs, `m2led` kept.
- Then run `uv run python scripts/sync_port_conventions.py --check` (needs network +
  `GITHUB_TOKEN`) and confirm **zero drift** — the hardening must not change any
  shipped canonical block.

**rgb width-1 survey — stop advertising ports that don't exist.**

- Affected candidates found in review (amaranth blocks whose primary `leds` is
  `rgb_led` width 1): `orange_crab_r0-1`, `orange_crab_r0-2` (+ `-25_f`, `-85_f`),
  `quickfeather`, `tang_nano`, `upduino_v3`. (`arrow_axe5000`'s litex `user_led`
  width 1 is a *real* single LED — that is F1's case, keep it.)
- For each: check the upstream resource shape. An RGB resource with r/g/b subsignals
  has **no** declarable `rgb_led` scalar port — the emitted convention is fiction.
  Detector available to the parsers: the flattened component carries multiple pins for
  one bit. Implement the exclusion at the adapter or `build_bank` level (an
  `RoleEntry` whose resource aggregates >1 pin per bit is not emittable), so an
  rgb-primary board simply fails the clk+LEDs floor and ships **no** framework block —
  truth over coverage. If any candidate turns out to be a genuine 1-pin port named
  `rgb_led`, keep it and note it in the PR body.
- Regen; **recompute the fleet coverage number** (boards with ≥1 convention block /
  278) and record it in the PR body — Phase 3 docs must use this number, not 273.
- Check ICEBreaker Bitsy against the U33 note ("framework conv already correct") and
  state the outcome in the PR body.

### Verify

- Unit tests for `reconcile_framework_polarity` (inherits set + clear; width mismatch
  → no-op; names[]-vs-vector shape join; non-framework blocks untouched).
- Fleet polarity test passes on the regenerated data (and demonstrably failed before —
  include the pre-fix failure output in the PR body).
- classify fixtures pass; `--check` clean; full `uv run pytest` green.
- Re-run each modified sync script **twice**; second run produces zero diff
  (idempotency, the A1/A3 standing bar).
- `git diff boards/` reviewed board-by-board in the PR body: 4 polarity inheritances +
  the rgb exclusions + (separate commit) any upstream drift, nothing else.

### Quality gates

As Phase 1, plus: no hand-edits to `boards/` JSON (everything flows through the
parsers/generator — hand edits are wiped by the next sync); every data change traceable
to a code change in the same PR.

---

## Phase 3 — documentation restructure

Two PRs, ordered so the README never points at a file that doesn't exist yet and
nothing vanishes before its new home lands.

### The quality bar (applies to every file both PRs touch)

- **Accuracy is verified, not assumed.** Every command is executed once before it is
  written down. Every number (board count, conventions coverage, test count, supported
  7-seg boards list) is recomputed from the repo at writing time — use the Phase-2
  coverage number. Every behavioral claim about board-native mode reflects the
  **post-Phase-1/2** code.
- **No internal ticket IDs** (U21/B3/F1…) in README, install, user-guide, or
  writing-designs prose. They are fine in `architecture.md`'s "history" pointers and
  in plan documents.
- Each new doc opens with a 2–3 line "who this is for / what it covers" preamble and
  a link back to README's docs index.
- US spelling; ASCII VHDL snippets; relative links; stable heading anchors (these
  become link targets — pick names once). `uv run rumdl check .` passes.
- **Anchor hygiene:** before moving content, `grep -rn "README.md#"` and
  `grep -rn "#windows-"` etc. across the repo (docs/, CONTRIBUTING.md, help text,
  issue templates) and update every cross-reference to the new locations.
- Tone matches the existing docs: direct, concrete, no filler.

### Phase 3a — create `docs/install.md`, `docs/user_guide.md`, `docs/architecture.md`; trim CONTRIBUTING

**Do:**

- **`docs/install.md` (~220 lines).** Moves in: README 49–133 (full GHDL/NVC install
  matrix incl. from-source and AUR/Gentoo/FreeBSD), 135–141 (uv setup, referenced from
  README's short form), 158–167 (Windows run notes), 530–648 (all four Troubleshooting
  sections + the MSYS2 guide), plus the pygame-ce note (528). Organize: per-OS happy
  path first (mirroring README), then per-simulator detail, then Windows specifics,
  then troubleshooting. Keep the "NVC on Windows untested — report results" caveat.
- **`docs/user_guide.md` (~250 lines).** Moves in: README 169–234 (the four screens,
  shortcuts, stats panel tables, speed slider, virtual clock). **Break the line-234
  persistence blob into real subsections:** Session persistence · Recent files ·
  Settings dialog · Themes · Waveform capture (formats, timestamped paths,
  `FPGA_SIM_WAVEFORM_DIR`) · `.gtkw` save files · Auto-open + `FPGA_SIM_WAVEFORM_VIEWER`
  template · Headless/CI env vars (`FPGA_SIM_WAVEFORM`, `_OPEN`, `_MEMORIES`) · Session
  logs. **New content:** a "Board-native runs" subsection documenting the B3b
  affordances that are currently documented nowhere — the "Board-native (maker)" info
  tag, the stats-panel active-low note (which roles it lists and why), the spinner
  wording, and the session-log `mode`/`convention` fields.
- **`docs/architecture.md` (~230 lines).** Moves in: README 236–306 (Project Structure
  tree), 308–426 (How It Works: board loading + sources + sync commands, pygame UI
  internals, the simulation-pipeline diagram, the blinky anatomy, the backend table +
  VPI/VHPI note), and CONTRIBUTING.md's "Architecture overview" section (~505–598) —
  reconcile overlaps rather than duplicating. **New content:** a "How board-native
  works" internals section (currently only in the U21 plan doc and CLAUDE.md): contract
  check → convention matcher (canonical-before-framework precedence, near-miss
  scoring) → native wrapper generation (polarity inversion, zero-extend, 7-seg
  packing, board-width generic defaults) → unchanged cocotb boundary; link
  `docs/u21_board_native_vhdl_plan.md` and the registry README for history.
- **CONTRIBUTING.md:** replace the absorbed Architecture overview with a 2-line
  pointer to `docs/architecture.md`. Add `sync_port_conventions.py --check` and
  `regen_embedded_cores.py` (check mode) to the **release checklist** pre-flight
  (locked decision 7).
- **README is untouched in 3a** (it still carries the old sections; they get cut in
  3b). `CLAUDE.md`: add the three new docs to the key-files table.

**Verify:** rumdl clean; every moved command re-executed once; anchor-hygiene grep
shows no dangling references; `uv run pytest` green (docs PRs still run the suite);
each new file renders correctly (preview locally or in the PR).

### Phase 3b — `docs/writing_designs.md` + the README rewrite

**Do:**

- **`docs/writing_designs.md` (~280 lines).** The VHDL author's reference:
  - Moves in: README 447–514 (generic contract, 7-seg contract + byte layout and
    active-high normalization, embedded-CPU section with its GIF, the board-native
    paragraph) and the `hdl/` example catalog from README 193 + 269–280.
  - Contract details: `COUNTER_BITS` runtime-override semantics (floor 17, why),
    entity-name = filename-stem rule, extra-ports-need-defaults rule, the
    clock (board frequency, 12 MHz fallback). Verify the 7-seg board list in the
    heading against current board data before writing it.
  - **Board-native mode, written properly (the release headline — replaces the single
    dense paragraph, resolves F7):**
    - what it is: the board's own port names + fixed widths, no `NUM_*` generics;
    - where names come from: vendor-canonical conventions (cited constraint files;
      Terasic `CLOCK_50/SW/KEY/LEDR/HEX0..n` etc.) **and** framework-derived
      conventions (litex `clk100/user_led/user_sw/user_btn`, amaranth
      `clk100/led/switch/button`) — state the coverage number from Phase 2 and that
      canonical data wins when both exist;
    - polarity: the board's convention supplies it (active-low LEDs/KEYs inverted by
      the simulator; the stats panel notes which roles) — pin-level semantics: your
      ports are the pins;
    - partial interfaces: clk + LEDs minimum; switches/buttons only if the board's
      convention declares them; extra **outputs** are left open; extra inputs need a
      default (post-F3 behavior); one-LED boards accept `led : out std_logic`
      (post-F1);
    - wrong-board files: the near-miss rejection with the mismatch named (post-F4
      wording) — show one example message;
    - the four `hdl/native/` examples incl. `arty_litex.vhd`, each mapped to its
      board; the frozen-divider note (no `COUNTER_BITS` override → tap mid counter
      bits) with the reason;
    - 7-seg scope: per-digit (`individual`) style adapted; scan/serial boards stay on
      the generic contract until U22.
- **README rewrite to the locked ~250-line skeleton** (decision 1). Content notes:
  - Install section: locked decision 3's shape; keep `uv run pytest` as the
    "is it working?" step; link `docs/install.md` prominently.
  - Demos section: locked decision 4 — step-by-step (launch → filter to DE10-Lite →
    pick `hdl/snake_7seg.vhd` → press BTN0/BTN1/SW0, mirroring the hero GIF caption),
    then the 6502 demo with its existing GIF.
  - "Write your own VHDL": the generic entity snippet (keep it compilable), one
    sentence + link for 7-seg, then the board-native subsection with a ~10-line
    `CLOCK_50`/`LEDR` example (derive from `hdl/native/de10_standard.vhd`, mid-bit
    tap) and the coverage claim, linking `docs/writing_designs.md`.
  - Features at a glance: one line each — waveforms + auto-`.gtkw`, themes, tooltips,
    help overlay (F1/?), session persistence, speed slider + virtual clock, stats
    panel — each linking into `docs/user_guide.md`.
  - Docs index: the four new docs + embedded-core guide + CONTRIBUTING.
  - Keep: badges, CI-matrix line, both GIFs + captions, Dependencies table (update the
    digilent "~26 boards with port_conventions" line to the real story), Talks,
    Acknowledgements, License (incl. the boards-license paragraph).
- Update `CLAUDE.md`'s board-native sections if any behavioral wording changed in
  Phases 1–2 (scalar width-1, defaulted extras, polarity reconciliation).
- Skim `src/fpga_sim/ui/help_dialog.py`'s contract summary: if it states "extra ports
  need defaults" style rules, confirm they're still worded correctly post-F1/F3; a
  one-line board-native mention is welcome but keep the overlay short (it has fixed
  geometry — verify with a headless screenshot if touched).

**Verify:** README line count in the ~230–270 band; every link resolves (run a link
check over the repo's markdown); rumdl clean; the two GIF paths untouched; anchor
grep clean again; `uv run pytest` green; read the README top-to-bottom once as a
newcomer — install → demo → own VHDL must work verbatim on a clean clone (actually
execute the sequence).

### Quality gates (both PRs)

As Phase 1, plus: PR body includes the disposition ("moved README §X → file#anchor")
so review is diff-plus-map; CHANGELOG entry under `[Unreleased]` → Changed
("documentation restructure: …").

---

## Phase 4 — release v0.14.0

### Do

1. Pre-flight (all must pass on post-Phase-3 `main`):
   - `uv run pytest` on a machine with **both** GHDL and NVC installed.
   - `uv run ruff check` + `format --check` + `mypy .` + `rumdl check .`.
   - `GITHUB_TOKEN=… uv run python scripts/sync_port_conventions.py --check` → "No drift."
   - `uv run python scripts/regen_embedded_cores.py` (check mode) → no drift.
   - Re-run one upstream sync script; `git diff boards/` empty (A1 guard + Phase-2
     reconciliation stable).
   - CI green on `main`.
2. Roadmap + Icebox bookkeeping (`docs/improvement_roadmap.md`): U33 card gets its
   shipped ✅ stub if not already; the "Board-native VHDL coverage" section updates to
   the Phase-2 number; add Icebox **P19** (scheduled-CI `--check` job) and **P20**
   (model RGB subsignal banks as native-mappable), each with a one-line rationale
   pointing at this plan.
3. Milestone hygiene: retitle milestone #4 → "v0.14.0 — board-native release"; confirm
   the four phase issues are closed into it; create milestone "v0.15.0" and note the
   UX cards (U8/U9/U23/U27) target it.
4. Follow **CONTRIBUTING.md → Releasing** steps 1–6 verbatim (release branch →
   CHANGELOG `[Unreleased]` → `[0.14.0] - <date>` + comparison links → version bump in
   `pyproject.toml` → PR → tag `v0.14.0` on the merge → GitHub Release).
   - The release body leads with the board-native story: one paragraph, the coverage
     number, the two contract styles side-by-side, links to `docs/writing_designs.md`
     and the new docs set; then the standard CHANGELOG section.
   - Note in the PR body that this release deliberately batched one arc
     (board-native) — acknowledging the "avoid release gravity" guideline rather than
     silently exceeding it.
5. Post-release: verify the release page renders, badges update, and
   `git describe --tags` on `main` reports v0.14.0.

### Verify

Tag exists and matches the merge commit; GitHub Release published with the CHANGELOG
body; milestone #4 closed; roadmap/Icebox updated; memory/bookkeeping per the repo's
release habits.

---

## Cross-cutting quality gates (every phase PR)

- `uv run ruff check` + `uv run ruff format --check` + `uv run mypy .` +
  `uv run pytest` locally before every commit (CI mypy is repo-wide; tests must stay
  typed-clean). `uv run rumdl check .` for any PR touching markdown.
- CHANGELOG entry per PR, under `[Unreleased]`, written for users not maintainers.
- Never predict PR numbers in docs; reference issues.
- Before each PR: explicitly consider doc updates and test additions (standing
  checklist). US spelling everywhere. VHDL examples plain ASCII.
- One PR per phase; branch off post-merge `main`; PR bodies carry the
  evidence/disposition tables described above.

## Status ledger

| Phase | Scope | PR | Status |
|---|---|---|---|
| 1 | Matcher/wrapper fixes (F1, F3, F4, F6) + native cocotb-loop test (F8) | #245 | ✅ merged |
| 2 | Polarity reconciliation + fleet test (F2), classify hardening (F5), rgb survey, regens | #246 | ✅ merged |
| 3a | `docs/install.md` + `docs/user_guide.md` + `docs/architecture.md` + CONTRIBUTING trim | #247 | ✅ merged |
| 3b | `docs/writing_designs.md` + README rewrite (F7) | #248 | ✅ merged |
| 4 | Release v0.14.0 | #249 | ✅ released 2026-07-16 |

## Appendix A — README disposition map (from 672-line README @ db49065)

| README lines | Content | Destination |
|---|---|---|
| 1–25 | Badges, pitch, hero + selector GIFs | README (keep) |
| 26–48 | Prereqs, clone | README (keep, tightened) |
| 49–133 | Full GHDL/NVC install matrix | `docs/install.md`; happy-path one-liners stay in README |
| 135–141 | uv setup | README (keep) |
| 143–167 | Run commands + Windows notes | README keeps the 3-line run; Windows detail → `docs/install.md` |
| 169–210 | Usage: 4 screens + shortcuts | Condensed demo narrative in README; full reference → `docs/user_guide.md` |
| 211–234 | Stats panel + persistence blob | `docs/user_guide.md` (restructured into subsections) |
| 236–306 | Project Structure tree | `docs/architecture.md` |
| 308–426 | How It Works | `docs/architecture.md` |
| 428–445 | Running Tests | README keeps `uv run pytest` as install check; the rest → CONTRIBUTING already covers |
| 447–493 | Generic + 7-seg contracts | Snippet stays in README; full reference → `docs/writing_designs.md` |
| 494–511 | Embedded CPU systems + GIF | Pointer in README; section → `docs/writing_designs.md` (guide link unchanged) |
| 512–514 | Board-native paragraph | Rewritten: README subsection + full treatment in `docs/writing_designs.md` |
| 516–528 | Dependencies table + pygame-ce note | Table stays in README; pygame-ce note → `docs/install.md` |
| 530–648 | Troubleshooting + MSYS2 | `docs/install.md` |
| 650–672 | Contributing/Talks/Acknowledgements/License | README (keep) |

## Appendix B — polarity disagreement table (Phase 2 oracle)

Found 2026-07-15; the fleet test must fail on exactly these before the regen and pass
after:

| Board file | Canonical block | Framework block | Truth |
|---|---|---|---|
| `amaranth-boards/de0_cv.json` | terasic: active-high | amaranth: active-low | active-high (upstream `invert=True` is the bug) |
| `amaranth-boards/litefury.json` | rhs_research: active-low (cited `LED_ON=1'b0`) | amaranth: active-high | active-low |
| `amaranth-boards/nitefury_ii.json` | rhs_research: active-low | amaranth: active-high | active-low |
| `litex-boards/sipeed_tang_nano_9k.json` | sipeed: active-low (cited) | litex: active-high | active-low |
