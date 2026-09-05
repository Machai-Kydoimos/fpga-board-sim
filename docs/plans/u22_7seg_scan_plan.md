# U22 — 7-Segment v2: Physical Scan Interface (Board-Native)

*Status: approved 2026-07-23 (§3.2 decision: relax + guard). Roadmap card: U22 "7-segment v2 — physical mux mode".*
*Companion history: `7seg_display_plan_v2.md` (v1, shipped v0.3.0 — reserved mux mode for v2),
`u21_board_native_vhdl_plan.md` (the matcher/wrapper machinery this plan extends).*

---

## 1. Reframe: what "physical mux mode" means in 2026-07

The U22 roadmap card predates U21/U31/U9/U34 and imagined three mechanisms this plan
**retires**, each with rationale:

| Card bullet (2026-07-02) | Verdict | Why |
|---|---|---|
| "New conditional placeholders in the unified wrapper template" | **Retired** | The generic template serves the *logical* packed-`seg` contract, which stays the design-side default (the card's own carried-forward constraint — every 7-seg example and generated embedded-core design assumes it). The physical interface arrives on the **board-native** path instead, where `_render_native_wrapper()` already emits bespoke architectures; no template placeholders are involved. |
| "Updated testbench readback" | **Retired** | The native wrapper adapts scan → the same `seg : out std_logic_vector(8*NUM_SEGS-1 downto 0)` boundary the testbench already reads. `sim/sim_testbench.py`, `sim_link`, the UI, and the waveform tooling are untouched below the wrapper. |
| "New `physical_mux: bool` toggle per board" | **Retired** | Superseded by data that already exists: `port_conventions.seven_seg.style == "scan"` (schema landed in U21 Part A0, with `digit_enable`). Scan adaptation activates when a native design matches a scan-style convention — no per-board toggle, no mode switch. |

What remains is exactly the U9 head-start note's claim: **v2 is wiring, not measurement.**
The duty engine (default mode `full`, `sim_bridge.py:63`) measures the boundary `seg`
*after* the wrapper's adaptation (8 channels/digit, `_duty_channels`), so a combinationally
gated demux gets physically honest 1/N-duty brightness for free — verified in U9 ("a one-hot
walker's per-window duties sum to exactly 100%").

**Done-when (unchanged from the card):** a muxed 7-seg board (Nexys 4 DDR) shows correct
digits when a design drives the physical scan interface (`CA..CG` + `AN` + `DP`).

## 2. Ground truth from recon (2026-07-23, all at current `main`)

### 2.1 The data defect (the card's prerequisite)

`scripts/digilent_parser.py::_build_port_conventions` (lines ~680–708) has **no `scan`
branch**: indexed segments → `packed_vector`, anything else → `individual`. The `an`
digit-enable entries and the `dp` scalar are parsed (they set the *board-level*
`seven_seg` def correctly: `is_multiplexed: true`, 8/4 digits) and then **dropped** from
the convention. Result, per committed JSON:

| Board(s) | Today's block | Reality (pinned XDC `00a3404`) | Correct block |
|---|---|---|---|
| Nexys 4 DDR, Nexys A7-100T, Nexys A7-50T | `individual`, `names: [CA..CG]`, `width_per_digit: 7` | 7 shared segment **scalars** `CA..CG` + `DP` scalar + `AN[7:0]`, all active-low | `scan` (scalar-segment idiom) |
| Basys 3, Nexys 4 (original) | `packed_vector`, `name: seg`, `width_per_digit: 7` | shared vector `seg[6:0]` + `dp` scalar + `an[3:0]`/`an[7:0]`, all active-low | `scan` (vector-segment idiom) |
| Sword | `individual`, `names: [sseg_clk, sseg_en, sseg_sdo]` | serial shift-register interface (board-level `seven_seg` is `null`) | `serial` (documenting; matcher declines it) |

Consequences today:

- The three Nexys-DDR-family boards **falsely full-match** a nonsense design declaring
  `CA..CG` as seven 7-bit vectors; a physically faithful scan design near-misses.
- The U38 sibling transplant (`sync_port_conventions.py::digilent_sibling_results`)
  **refuses** those blocks — `cross_check_widths` computes 7 "digits" vs the boards' 8
  (line ~382) — so `boards/amaranth-boards/nexys4_ddr.json` and
  `boards/litex-boards/digilent_nexys4ddr.json` carry no `digilent` block at all.
- On **every** scan-display board, *no* real native design can run: the matcher requires
  a seg match whenever the board has a display (`_attempt_convention`, sim_bridge.py:1266),
  and `_match_native_seg` declines every non-`individual` style (sim_bridge.py:1190) —
  so even a clk+LED-only native design near-misses on Basys 3 / the Nexys family.

The roadmap card points at `scripts/port_convention_parsers/classify.py`; recon shows the
actual emitter for `boards/digilent-xdc/` is `digilent_parser.py` (classify.py cannot even
see `CA..CG` — its `_SEG_INTEREST` is `seg|hex`, and the digilent registry rows are not in
`waves.toml`, so the classify pipeline never runs for these boards). classify.py's own
scan upgrade (packed vector + `an`/`enable` → `scan`, lines 310–324) is already correct.

### 2.2 What U21 already left in place (consume, don't rebuild)

- **Schema** (`boards/schema/board.schema.json`): `seg_port_mapping.style` enum includes
  `scan`/`serial`; `digit_enable` is a `port_mapping` ($ref) with `name`/`width`/`names`/
  `active_low`. Only gap: no field for the shared **decimal-point scalar** (§3.1).
- **Matcher datatypes**: `NativeSeg.digit_enable: NativePort | None` exists (sim_bridge.py:1076,
  "it belongs to the `scan` style, which B2 declines"), and `_attempt_convention` already
  adds `digit_enable.names` to the consumed-port set (line 1297).
- **Registry**: `docs/port_convention_sources/digilent.toml` rows are pinned + fetched
  (verify-or-omit) — their `seven_seg` prose fields describe the *current wrong* blocks and
  must be refreshed in Phase D.
- **Polarity**: segment cathodes and anode enables active-low on all five scan boards —
  already stamped (`active_low: true`, `select_inverted: true`) and consistent with the
  Digilent RM 7-seg sections (common-anode digits, transistor-driven anodes); Phase D adds
  the citations to the registry rows while touching them (the U38 ALL-PROSE lesson).

### 2.3 Fixed spellings at the pin (`00a3404901f3`)

- Basys 3: `seg[0..6]`, `dp`, `an[0..3]` (all lowercase). Nexys 4: same idiom, `an[7:0]`.
- Nexys 4 DDR / A7-100T / A7-50T: `CA CB CC CD CE CF CG`, `DP`, `AN[7:0]` (uppercase).
- VHDL is case-insensitive; conventions carry the XDC's original case as today.

## 3. Design decisions

### 3.1 Scan convention shape (Phase D emits, schema gains `dp`)

```jsonc
// Nexys 4 DDR (scalar-segment idiom)
"seven_seg": {
  "style": "scan",
  "names": ["CA", "CB", "CC", "CD", "CE", "CF", "CG"],  // per-SEGMENT scalars (shared lines)
  "width_per_digit": 7,                                  // == len(names)
  "active_low": true,                                    // segment (and dp) drive polarity
  "dp": "DP",                                            // shared decimal-point scalar (NEW field)
  "digit_enable": { "name": "AN", "width": 8, "active_low": true }
}
// Basys 3 (vector-segment idiom)
"seven_seg": {
  "style": "scan",
  "name": "seg", "width_per_digit": 7,                   // one shared 7-bit vector
  "active_low": true, "dp": "dp",
  "digit_enable": { "name": "an", "width": 4, "active_low": true }
}
```

- **Semantics shift to document in the schema description:** for `scan`, `names`/`name`
  describe the *segment* side (shared lines), and the digit count is
  `digit_enable.width` — unlike `individual`, where `names` are per-digit ports. This is
  precisely the confusion that produced the 7-vs-8 transplant refusal.
- **`dp` is a new optional `seg_port_mapping` property** (string; the shared decimal-point
  scalar, same polarity as the segments). Chosen over folding dp into `names`/width 8
  because both XDC idioms ship dp as a *separate scalar* even when the segments are a
  vector — the convention should state what the source states. `individual`-style blocks
  keep ignoring dp (bare-`HEXn` boards ship 7-bit there; DE0's `HEXn_DP` scalars stay
  unmapped-open).
- Sword becomes `style: "serial", "names": ["sseg_clk", "sseg_en", "sseg_sdo"]` — honest
  data the matcher (and `cross_check_widths`' digit check) explicitly skips. Sword's
  board-level `seven_seg` stays `null`; serial driving remains out of scope (Icebox).

### 3.2 Matcher: scan matching + the seg-requiredness question

`_match_native_seg` gains the `scan` arm:

- Segment side: vector (`name`, `literal_width == width_per_digit`, mode `out`) **or**
  scalar bank (`names[]`, each a scalar `out`) — mirroring `_match_native_port`'s two
  shapes; sets `scalar_ports`-like handling for the port map.
- `digit_enable` matched via `_match_native_port(…, "out")` (it is a design *output*).
- `dp`: matched when **both** the convention and the design declare it; a design omitting
  `dp` still matches (its dp bits stay dark) — mirroring `leds_green`'s leniency. A
  declared-but-unmapped `dp` on the design side is an ordinary open output.
- `NativeSeg` gains `dp: str | None = None` and a `scalar_segments: bool` flag;
  `style` distinguishes the wrapper paths.

**DECISION — resolved 2026-07-23: (a) relax + guard (Rick).** With scan matchable, what
about native designs that *don't* drive the display on a display board?

- **(a) Relax + guard (adopted).** Seg becomes matched-when-declared, like switches/
  buttons post-U31: if the design declares **none** of the convention's seg-role ports
  (segments, digit_enable, dp), the match proceeds and the digits stay dark (exactly how
  an unused `leds_green`/`leds_rgb` bank behaves). If it declares a **strict subset**,
  that is forced to a near-miss naming the missing ports — the guard that keeps a typo'd
  scan interface from running silently dark (outputs are otherwise open-and-silent; the
  default-less-input rule doesn't cover them). Unlocks clk+LED native demos on Basys 3 /
  Nexys family — boards where **no** native design can run today — and applies uniformly
  to `individual` boards (a HEX-less native design runs on DE10-Lite with dark digits).
- **(b) Keep required.** Scan designs must drive the full interface; display boards still
  refuse display-less native designs. No behavior change beyond scan; smaller test
  surface; leaves Basys-3-style boards native-usable only via full scan designs.

### 3.3 Wrapper: combinational demux (no latch, no generate)

For a scan match, `_render_native_wrapper` emits (polarity shown for the all-active-low
Digilent case):

```vhdl
signal scanseg_uut : std_logic_vector(6 downto 0);   -- or per-scalar signals CA..CG
signal scandp_uut  : std_logic;                      -- when matched
signal scanen_uut  : std_logic_vector(7 downto 0);
...
-- digit i, segment k (unrolled from Python; <= 8*8 = 64 lines):
seg_int(8*i + k) <= (not scanseg_uut(k)) and (not scanen_uut(i));
seg_int(8*i + 7) <= (not scandp_uut)    and (not scanen_uut(i));  -- else '0'
```

- **Combinational gating, deliberately unlatched:** the boundary `seg` is the *instantaneous*
  lit state, and the duty engine integrates it into exact per-window duty — a 1/8 scan
  renders as steady digits at 1/8 brightness (honest display physics; the U9 rendering
  pipeline needs zero changes). A latched reconstruction would fake full brightness and
  misreport a stopped scan (real hardware shows one lit digit; so do we — including in
  the U38 pause-instant sample).
- **Unrolled concurrent assignments, not a generate:** matches the existing per-digit
  emission style (sim_bridge.py:1822-1832) and stays clear of the mcode
  generate/override trap by construction.
- **`NUM_SEGS` default flips meaning — the easy-to-miss line:** today it is
  `len(seg.names)` (sim_bridge.py:1853); for scan that is the *segment* count. It must be
  the digit count (`digit_enable.width`), keeping the baked default equal to the
  `build_generics` runtime value (the analyze/run consistency invariant).
- Duty splice: unchanged — `seg_int` is already the measured channel in `full` mode.
- `.gtkw` writer (`_write_gtkw`, sim_bridge.py:2323): list the native scan ports
  (segments + `AN` + `dp`) under the uut group, as the individual style lists `HEXn`.

### 3.4 What deliberately does not change

- Generic-contract designs (`counter_7seg.vhd`, embedded cores): logical packed `seg`,
  byte per digit — untouched, on every board including scan boards.
- `sim/sim_testbench.py`, `sim_link`, `SimulationScreen`, `sim_duty.py`, board renderer.
- `per_segment_scalars` (Nandland Go) and `serial` (Sword) stay generic-only.
- Board-level `SevenSegDef` (all five scan boards already carry correct
  `num_digits`/`is_multiplexed`/`select_inverted`).

## 4. Phases

### Phase D — data: correct scan classification end-to-end (1 PR)

Files: `scripts/digilent_parser.py`, `boards/schema/board.schema.json`,
`scripts/sync_port_conventions.py` (`cross_check_widths` + transplant),
`docs/port_convention_sources/digilent.toml` (prose refresh + polarity citations),
regenerated `boards/digilent-xdc/*.json` + transplanted sibling JSONs,
`tests/test_digilent_parser.py`, `tests/test_sync_port_conventions.py`,
`tests/test_board_schema.py`.

1. `_build_port_conventions`: stop discarding `an`/`dp`; emit the §3.1 shapes
   (anodes present → `scan` in both idioms; no anodes → today's behavior unchanged);
   Sword's `sseg_*` → `serial`. Reuse the section entries `_build_seven_seg` already
   parses rather than re-deriving.
2. Schema: add `dp` to `seg_port_mapping`; update the `style` description to state the
   scan segment-side semantics (§3.1).
3. `cross_check_widths`: scan digits = `digit_enable.width` (validate segment side:
   `len(names) == width_per_digit` / vector width); `serial` skips the digit check.
4. Re-sync digilent at the recorded pin (`00a3404`, needs `GITHUB_TOKEN`), run
   `sync_port_conventions` write mode (the transplant now **fires** for the Nexys/Basys
   siblings — amaranth `nexys4_ddr`, litex `digilent_nexys4ddr`, etc. gain `digilent`
   blocks: new capability, larger diff, called out in the PR body), then
   `sync_led_colors`; `check_board_drift` must pass on the result.
5. Tests: both scan idioms + dp capture + Sword serial + non-mux boards byte-identical;
   scan-aware cross-check accept/refuse cases; schema validation of the new field.

Interim behavior after D alone: the three false-match boards become honest near-misses
("7-segment display" problem) until Phase MW lands — acceptable inside the arc.

### Phase MW — matcher + wrapper together (1 PR; splitting them would let a scan match generate a broken wrapper)

Files: `src/fpga_sim/sim_bridge.py` (`NativeSeg`, `_match_native_seg`,
`_attempt_convention` if §3.2(a), `_render_native_wrapper`, `_native_convention_message`,
`_near_miss_convention_message`, `_write_gtkw`), `tests/test_convention_matcher.py`,
`tests/test_native_convention.py`.

1. §3.2 matching (both idioms; dp-lenient; consumed-set includes dp).
2. §3.2 decision as adopted: (a) relax + subset-guard.
3. §3.3 wrapper demux + `NUM_SEGS`-default fix + gtkw listing; native info message names
   the scan interface (e.g. `CA..CG+AN`).
4. Hermetic tests: matcher accept/near-miss matrices (incl. subset-guard cases and
   wrong-board name mismatches resolving safely); wrapper-gen golden assertions
   (polarity `not`s, gating lines, dp-absent `'0'` fill, defaults = board counts).

### Phase E — examples, end-to-end proof, docs, closeout (1 PR)

Files: `hdl/native/nexys4ddr_scan.vhd`, `hdl/native/basys3_scan.vhd`,
`sim/test_native_scan.py`, `tests/` runner glue mirroring the existing native-design
tests, `docs/user_guide.md`, `docs/architecture.md`, `docs/u21_board_native_vhdl_plan.md`
(pointer), `CLAUDE.md`, `docs/improvement_roadmap.md` (closeout per the checklist),
`docs/roadmap_delivered.md`, `CHANGELOG.md`.

1. Two reference designs (picker-hidden like all `hdl/native/`): Nexys 4 DDR scalar idiom
   (`CA..CG`/`DP`/`AN[7:0]`, digit counter + `btnC` lamp test) and Basys 3 vector idiom
   (`seg`/`dp`/`an[3:0]`). Both scan **fast** (low-mid counter bits, digit period ~1–10 µs
   sim time): the duty window (~60 Hz wall ≈ tens of µs sim at sub-real-time speed) must
   contain many whole scan periods for steady 1/N duty — a real-hardware ~1 kHz scan
   looks like a rolling single digit at sim throughput. This is the scan-rate cousin of
   the existing "tap mid counter bits" rule; document both together.
2. Cocotb: duty-based digit reconstruction against known glyphs (lit segment ≈ 1/N duty,
   unlit ≈ 0), digit_enable one-hot check, dp behavior; headless screenshot pass per the
   verification recipe.
3. Docs: user guide (scan boards natively targetable; 1/N brightness is honest physics;
   Off/Color duty modes show instantaneous single-digit sampling — use Full, the
   default; pause shows the actually-active digit), architecture ("How board-native
   works" scan paragraph), CLAUDE.md board-native section (scan joins `individual` as
   adapted; serial/per-segment-scalars still generic → the U22 line comes out),
   roadmap completion sweep (all interconnected sections, per the checklist memory).

### Phase F — deferred (separate card if wanted; not required for done-when)

Amaranth scan boards (RZ-EasyFPGA-A2/2, StepMXO2) via framework-derived seg banks in
`scripts/framework_conventions.py` (the parsers already capture `display_7seg` +
`display_7seg_ctrl` shapes and polarity). StepMXO2 is a hybrid (two independent digit
resources + 2-pin ctrl) needing its own thought. Mimas A7 has registry-verified scan data
but is not in the fleet (source URL 404, `waves.toml` note). Park unless Rick pulls it in.

## 5. Quality gates (every PR)

Ruff + `ruff format --check` + `mypy .` (repo-wide, incl. tests) before commit;
`pipefail` on test pipelines; full pytest; GHDL + NVC cocotb suites where touched;
`check_board_drift` green on data changes; benchmark only if a perf-adjacent path moves
(none expected). Feature branches throughout; UI-visible changes (Phase E screenshots)
get Rick's visual review before merge.

## 6. Risk register

| Risk | Mitigation |
|---|---|
| Transplant diff surprises reviewers (siblings gain blocks) | Called out in Phase D PR body; cross-check gates every target; drift tripwire proves idempotence |
| Scan design scans at real-hardware rate → rolling digit | Documented rate guidance + fast-scanning reference designs (§4-E1); duty math itself stays exact |
| Off/Color duty modes show one digit per sample | Documented; `full` is the default; not a regression (same trade PWM LEDs make today) |
| Typo'd partial scan interface runs silently dark (only under §3.2(a)) | Subset-guard forces a near-miss naming the missing ports |
| `NUM_SEGS` default emitted as segment count for scan | Explicit step + wrapper-gen golden test pins default == digit count |
| mcode generate/override trap | No generates: unrolled assignments |
| Un-tokened re-sync reads as false drift | Phase D regen run with `GITHUB_TOKEN` (the U38 lesson, already baked into the tripwire) |
| Registry prose rows go stale vs. regenerated blocks | Phase D updates `digilent.toml` rows + citations in the same PR |

## 7. Estimates

Phase D ~M (parser branch + cross-check + regen + tests), Phase MW ~M-L (matcher matrix +
wrapper emission + goldens), Phase E ~M (two designs + cocotb + docs sweep). Arc ≈ 3 PRs,
comfortably a one-milestone sprint.
