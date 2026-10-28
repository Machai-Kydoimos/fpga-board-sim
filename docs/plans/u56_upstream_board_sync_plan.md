# U56 — Upstream board-sync repair: arc plan (faithful parsers, stable identity, orphaned boards)

**Status:** **DRAFT — for Rick's review** (drafted 2026-10-28; nothing executed, nothing committed
to `main`). Not approved; no milestone, no issues. On approval, PR 0 commits this file and the
roadmap card; issues open just-in-time per phase. Once execution starts, the phase ledger in §12 is
the status source of truth.

**Card ID:** **U56**, claimed 2026-10-28 in [`improvement_roadmap.md`](../improvement_roadmap.md)
(ID allocation → next free **U57 · D18 · P38**). Card: Part 1 / Tier 2. This arc **absorbs Icebox
P35** (the display-name parser fix — its trigger, "a board-data re-sync is happening anyway",
fired 2026-10-28) and names **Icebox P15** as the follow-up for cross-source twins (§14).

**Decided 2026-10-28 (Rick) — do not relitigate:**

1. **Fidelity.** Keep every board definition, within and between upstream sources, and simulate
   whatever upstream defined — "perhaps they were special boards (poorly named) or different
   versions or even bad board definitions." We fix only *our parsers' misreadings* of upstream;
   we never correct upstream data with outside knowledge.
2. **Upstream bugs are upstream's.** No local overrides. The Acorn baseboard's 506 Hz clock
   (`default_clk_period = 1e9/506` in `litex_acorn_baseboard.py`) is reported as
   [litex-hub/litex-boards#934](https://github.com/litex-hub/litex-boards/issues/934) (filed by
   Rick); we wait. ("We're not broken, they're broken.")
3. **Orphans are kept and marked.** A board that later disappears upstream stays, so a user's
   native VHDL still has something to run on, and is marked "orphaned upstream" so the user knows
   to consider migrating.
4. **Cross-source duplicates stay separate.** They are not merged or hidden, and no entry receives
   another entry's canonical conventions without a citation for that specific entry.

**Open decisions (for review — §3):** D-1 alias model · D-2 DIP switches · D-3 multi-pin
resources · D-4 identical versions · D-5 release slot.

**Audience contract:** written to be executed phase by phase by a capable model without additional
context. Every phase has **Do**, **Verify**, **Quality gates**. Do not start a phase until the
previous phase's Verify passes. One PR per phase; branch each phase off post-merge `main`; never
commit to `main`. UI- or render-affecting phases (2, 3, 4, 6; the selector part of 5) need PNGs and
Rick's visual review **before** merge.

**Evidence:** every number below was measured on 2026-10-28 against the pinned and then-current
upstream commits (§2.1). The audit scripts lived in a session scratchpad and are not retained;
Appendix A describes them closely enough to rebuild, and every phase re-proves its own effect with
in-place re-syncs and tests. **Upstream keeps moving — re-measure before relying on a number.**

---

## 1. Why

Three classes of problem, none of which is visible today:

- **A. Silent misreadings.** The LiteX and Amaranth parsers mock-exec upstream Python and swallow
  every failure (`scripts/litex_parser.py:500`, `:536`; `scripts/amaranth_parser.py:614`) — a file
  that fails to exec is reported as "no simulatable resources" (`scripts/sync_litex_boards.py:80`)
  and a platform that fails to instantiate silently falls back to a module-level `_io` list
  (`scripts/litex_parser.py:541`). Result: **54 LiteX boards and 4 Amaranth boards upstream defines
  have never been synced**, and shipped boards are mis-modeled (Zybo Z7 ships with 0 buttons;
  Red Pitaya with no clock; 84 boards with an empty `device`; 20 boards draw one upstream pin as
  two LEDs).
- **B. Unsafe identity and silent staleness.** A board's file name *is* its sanitized display name
  (`sync_common.sanitize_filename`, 277/277 synced files), with `_2`, `_3` appended in processing
  order on a collision (`sync_common.unique_name`). And the sync **never deletes** a file
  (`write_outputs` only writes). So a board that stops being produced lingers, frozen and
  unmarked; a display-name fix (P35) would rename ~20 files; and a new same-named upstream board
  could take over an existing board's file.
- **C. Upstream drift breaks the parser.** LiteX is 397 commits past our pin and refactored its
  PMOD/dock helpers into `litex_boards/extensions/`. Re-syncing at LiteX head with today's parser
  produces **149 boards instead of 171**; the other 31 files would stay on disk, frozen at the old
  commit, missing from `_sync_metadata.json` and invisible to the drift check.

**Nothing is broken today:** the drift job (`scripts/check_board_drift.py`) re-syncs at the
recorded pins. Every problem above bites at the next pin bump or is already a quiet inaccuracy.

**What success looks like:** every board upstream defines is either synced or listed with a
reason; every shipped board is read the way upstream defines it; no board is ever renamed or lost
by a sync; boards that vanish upstream are kept and marked; and the in-repo VHDL (9 native, 24
generic designs) and the CPU firmware behave exactly as before (§2.5 proves this is achievable).

---

## 2. Evidence (audit of 2026-10-28)

### 2.1 Pins and drift

| Source | Recorded pin (`_sync_metadata.json`) | Upstream head 2026-10-28 | Ahead |
|---|---|---|---|
| amaranth-boards | `be069dfd490b31df215337afac35711994a52418` | `f270d210e36b0787d62db77176c7b0e8032178d3` | 5 commits (3 board files) |
| litex-boards | `8bf5de766fed9b89fdb265b17d2becc08039e9d1` | `c7056065097338bd943f54195dbe27a7548ef4d2` | 397 commits |
| digilent-xdc | `00a3404901f35aa9567b01ecb3f2c233b6efe9f4` | `c8644a9fe31cc803789643124545d56b3bef4600` | 1 commit (`SECURITY.md` only) |

Today: **285 boards** = 80 amaranth + 171 litex + 26 digilent + 8 custom. Digilent at head is
content-identical to what we ship (field by field, only `source` differs).

### 2.2 Projected board counts

| Source | Today | Unfixed parser @ head | Phase 1b @ pins | + Phase 2 @ pins | All fixes @ heads (Phase 7) |
|---|---|---|---|---|---|
| amaranth | 80 | 82 | 83 | 83 | 86 |
| litex | 171 | 149 produced (31 left frozen) | 223 | 226 | 233 produced + 5 orphans kept = 238 files |
| digilent | 26 | 26 | 27 (ZedBoard — **unmeasured**) | 27 | 27 |
| custom | 8 | 8 | 8 | 8 | 8 |
| **files** | **285** | — | **341** | **344** | **359** (before Phase 5 versions) |

The LiteX figures include Wukong revision 1 as a new file beside today's revision-2 file (§4.1);
the audit harness measured one fewer (222 / 225 / 232) because it overwrote Wukong instead. Of the
73 new board files at heads: 53 are boards we do not have from any source, 14 are second sources
for boards we already ship (Appendix B.6), 5 are the upstream Efinix renames, 1 is Wukong revision 1.

### 2.3 Defect inventory

| # | Defect | Anchor | Effect | Phase |
|---|---|---|---|---|
| 1 | Exec/instantiate failures swallowed; skip reason never printed | `litex_parser.py:500,536`; `sync_litex_boards.py:80`; `amaranth_parser.py:614`; `sync_amaranth_boards.py:67` | boards vanish silently | 1a |
| 2 | File name = display name; collision suffix by order; sync never deletes | `sync_common.py:23,34,268` | renames, silent staleness, takeover risk | 1a |
| 3 | `_Pins` mock accepts one string; upstream passes several; no `.identifiers` | `litex_parser.py:21` | ~31 files never synced (DE1-SoC, DE10-Lite, ZedBoard, KC705…) | 1b |
| 4 | Vendor key typo `LatticeICE40Platform` (upstream: `LatticeiCE40Platform`) | `litex_parser.py:109` | all LiteX iCE40 boards never synced | 1b |
| 5 | No Microsemi / Anlogic / QuickLogic / `LatticePlatform` mocks | `litex_parser.py:99` | those boards never synced | 1b |
| 6 | Mock platform lacks `toolchain`, `add_platform_command` (78 files), `add_connector`, … | `litex_parser.py:124-160` | ~95 platforms never instantiate → module `_io` fallback, empty `device` | 1b |
| 7 | New upstream module-level helpers (`deprecated_pmod_helpers`, `warn_deprecated`, `Pmod*`, Tang docks) undefined after imports are blanked | `litex_parser.py:486-501` | 22-board net loss at head | 1b |
| 8 | Amaranth: no `DDR4Resource`, `DiffPairsN`; base classes imported from sibling files | `amaranth_parser.py:293-345` | RFSoC 4x2, UPduino v2, Versa ECP5-5G, Supercon badge dropped | 1b |
| 9 | Amaranth classifier: `n.startswith("sw")` matches `swd` | `amaranth_parser.py:431` | QuickFeather's 2-pin debug port drawn as a switch | 1b |
| 10 | Digilent parser classifies only by section headings; Avnet's ZedBoard XDC has none | `digilent_parser.py:206,261` | ZedBoard (8 LEDs/8 SW/5 BTN) skipped | 1b |
| 11 | Display names mangled from class/file names (P35) | `amaranth_parser.py` `_prettify_class_name`; `litex_parser.py:467` | override table grows (`board_loader.py:54`) | 1c |
| 12 | `add_extension` is a no-op; upstream extension objects not read | `litex_parser.py:149` | Zybo Z7 0 buttons; Tang dock I/O lost; Red Pitaya no clock | 2 |
| 13 | Default clock read only from class attributes | `litex_parser.py:526-527` | Red Pitaya keeps a 12 MHz default (real `clk125` set in `__init__`) | 2 |
| 14 | Multi-pin non-RGB resources collapsed into one LED/switch/button | `litex_parser.py:289`; `amaranth_parser.py:436` | 12 shipped boards (Appendix B.4) | 3 |
| 15 | `user_dip_btn` classified as button (name match on `btn`, from the first LiteX commit `d9c3caa`) | `litex_parser.py:239,312` | 9 shipped / 16 at head (Appendix B.3) | 3 (if D-2) |
| 16 | Upstream aliases emitted as separate LEDs; only one alias group becomes a native bank | parsers + `framework_conventions.py:86-166` | 20 shipped / 29 at head draw one pin twice (Appendix B.2) | 4 (if D-1) |
| 17 | One board per platform file (default constructor only) | `litex_parser.py:649` | 59 upstream files define selectable versions | 5 (D-4) |

### 2.4 Instantiation audit (LiteX)

With the Phase 1b mock fixes applied (Appendix A), platform instantiation succeeds for **245/248**
files at the pin and **251/256** at head. The remainder are not boards (`enclustra_st1`,
`qmtech_daughterboard`, `qmtech_rp2040_daughterboard` — no platform class) plus, at head, the two
Machdyne ML1 carriers (`machdyne_mozart_ml1`, `machdyne_vivaldi_ml1`: `type object 'MachdyneML1'
has no attribute 'revisions'` — class-level access on a stub; their sources contain no LED,
switch or button resources). With only the partial fixes (varargs `Pins`, vendor mocks, a
`toolchain` attribute, helper stubs) and before the permissive platform mock, the failure classes
were: `add_platform_command`
76 (pin) / 78 (head), `toolchain` item assignment 10/15, `add_connector` 5/1, `+=` on a stub 1/1,
`Pins.identifiers` 1/1.

### 2.5 Impact on our VHDL and firmware (measured)

- **Native and generic designs.** `check_vhdl_contract` for all 9 `hdl/native/*.vhd` and all 24
  `hdl/*.vhd` designs × every board, today vs the projected post-fix fleet at heads (Phases 1–2 +
  7, canonical sub-keys carried forward and polarity reconciled as `write_outputs` does): **zero
  outcome changes on any existing board** — same boards matched, same clock/bank names, widths,
  polarity. Every generic design also passes on all 72 new board files.
- **Canonical conventions.** 74 boards carry a canonical (non-framework) `port_conventions`
  sub-key; **none** of them is touched by any phase's board-data change (LED alias set, DIP set,
  extension/rename/upstream-change set). No in-repo native design targets a board in those sets.
- **Embedded CPU designs (`firmware/`, `hdl/mx65_*`, `hdl/t80_*`).** No static coupling: the
  syncers write only `boards/<source>/`; the generator, regen script, `systems/` and `firmware/`
  never read board data; CPU tests use the synthetic `tests/conftest.py:212` board. Runtime
  coupling only, through `build_generics` (`controller.py:130`) and the 8-bit config registers
  (`scripts/embedded_core/templates/cpu_io.vhd.tmpl:54-57`; firmware limits: 8-digit BCD buffer,
  16-bit `sw`/`btn` windows, 16 reachable LEDs). Projected generics stay inside today's ranges
  (Appendix B.8). Four existing boards change, all gaining real I/O: Zybo Z7 (`NUM_LEDS` 4→10,
  `NUM_BUTTONS` 1→4), Tang Console / Mega 138K / Mega 138K Pro (`NUM_BUTTONS` 1→2–4). Phase 3/4
  effects: Appendix B.2 / B.3.
- **Course boards.** DE10-Standard (`boards/custom/`) and Basys 3 (`boards/digilent-xdc/`) are in
  sources this arc does not change; neither has aliased pins, so pin maps (U53) are unaffected.

### 2.6 Identity facts the design depends on

- File name = `sanitize_filename(name)` for **277/277** synced files; **0** collision suffixes in
  use today.
- The cited registries key boards by **file path** (`docs/port_convention_sources/*.toml`
  `files = ["litex-boards/ego1.json"]`; `docs/led_color_sources/*.toml` likewise) → existing file
  names must never change.
- User state keys boards by **`(class_name, source folder)`**: `session_config.push_recent`
  (`session_config.py:129`, called at `controller.py:830,925`) and the session's
  `board_class`/`board_source` (`controller.py:649-651`) → existing `class_name`s must never change.
- `find_board` (`board_loader.py:566`) resolves `--board` by `class_name` or display name, case-
  and separator-insensitive; display-name overrides are keyed by `class_name` (`board_loader.py:54`,
  applied at `:502`).
- LiteX `name` and `class_name` derive from the upstream **file** name (`litex_parser.py:467-478`);
  Amaranth `class_name` is the upstream class name.

---

## 3. Open decisions (recommendations)

All recommendations follow decision 1: be faithful to what upstream's own definition says.

**D-1 — Aliased LEDs (Phase 4).** Upstream deliberately aliases (Amaranth iCEBreaker:
`# Semantic aliases` for `led_r`/`led_g`; LiteX Numato Tagus: `# … aliased here also`; OrangeCrab
`user_led` tagged `# rgb_led.r/.g/.b`).
*Recommend:* merge entries **only where upstream maps them to the identical pin**, and accept
**every** upstream name as a native port. The evidence is upstream's own pin assignment, not
hardware knowledge: their definition says `user_led0` and `rgb_led.r` are both pin K4, so drawing
two lamps simulates an output their definition does not contain. Every alias stays usable — more
than today, where only one alias group is a native bank. Colors carried by alias names (`led_r0`
red) move onto the merged LED. A design that declares two aliases of the same LED is a near-miss
naming the shared pin (two drivers on one pin). *Alternative:* leave aliases as separate LEDs.

**D-2 — DIP switches (Phase 3).** *Recommend:* classify `user_dip_btn` as **switches**. Upstream's
own name contains "dip"; Amaranth defines the same Versa ECP5 parts as switches; a widget has to be
chosen either way and today's choice is an unexplained substring match from the first commit. Cost
to the CPU examples (Appendix B.3): Versa ECP5 and Antmicro SDI-MIPI lose reverse / lamp test /
dice roll (0 real buttons); ECP5 EVN, ECP5 VIP, CertusPro-NX Versa lose the lamp test (1 button).
Native designs are unaffected (`user_dip_btn` keeps its name and width; the bank moves from
`buttons` to `switches`). *Alternative:* read "btn" as upstream's intent and keep buttons.

**D-3 — Multi-pin resources (Phase 3).** *Recommend:* a plain multi-pin input or output resource
becomes one component per pin (Trenz `gpio_leds`, 8 pins → 8 LEDs; Versa `alnum_led`, 15 pins →
15 LEDs); a resource whose sub-signals are named `r`/`g`/`b` becomes one RGB site regardless of its
name; bidirectional or multiplexed shapes (`rgb_leds_muxed`, `led_cathodes`, `swd`) keep today's
representation in the board model but are listed in the sync ledger as "unsupported shape" (no
silent change). *Alternative:* leave all multi-pin resources collapsed.

**D-4 — Versions that would simulate identically (Phase 5).** *Recommend:* emit one board per
upstream-listed version, but collapse versions whose simulated content (LEDs, switches, buttons,
7-seg, clocks) is identical — most FPGA-size `device=` choices — since they are indistinguishable
in the simulator. *Alternative:* emit every version.

**D-5 — Release slot.** *Recommend:* its own MINOR before peripherals (this arc → v0.24.0,
peripherals → v0.25.0, D16 → v0.26.0), after the classroom release's open tail (doc review,
§10.2/§10.3). Note: an unplanned MINOR renumbers the roadmap in ~8 places (see the v0.22.0
precedent). *Alternative:* ship Phases 1a–1c as maintenance inside the peripherals release and the
rest after it — the peripherals plan makes no sync-tooling changes
([u39_peripherals_plan.md](u39_peripherals_plan.md) "no sync-tooling changes"), so either order works.

---

## 4. Design

### 4.1 Board identity

Each synced board carries an identity in its `source` block:

| Field | Meaning | LiteX | Amaranth | Digilent |
|---|---|---|---|---|
| `origin` (exists) | source name | `litex-boards` | `amaranth-boards` | `digilent-xdc` |
| `upstream_file` (exists) | file in the archive | `digilent_arty.py` | `de10_lite.py` | `Basys-3-Master.xdc` |
| `upstream_class` (new) | platform class in that file | the class `parse_litex_board` selects (usually `Platform`) | the class name | omitted |
| `upstream_args` (new) | effective values of the **version-selecting** constructor parameters | e.g. `{"variant": "z7-20"}` | omitted | omitted |

Identity key = `(origin, upstream_file, upstream_class, upstream_args)`.

- **Version-selecting parameters** (Phase 5 enumerates them; Phase 1a records their effective
  values for the default construction): `variant`, `revision`, `board_version`, `version`, `dock`,
  `expansion`, `baseboard`, `som`, `board`. Not `device`, `toolchain`, `speedgrade` (D-4 governs
  `device`). Effective value = the `inspect.signature(cls.__init__)` default when not passed, so
  the default construction and an explicit `revision=1` are one identity.
- **File-name assignment.** An identity that already has a file keeps it forever. A new identity
  gets `<sanitized upstream file stem>`, plus `_<sanitized class minus "Platform">` when the file
  defines more than one board, plus `_<param>-<value>` per non-default version parameter (e.g.
  `qmtech_wukong_revision-1.json`). If that name is taken by a *different* identity, the sync
  **fails** naming both — never a silent `_2`. `unique_name` is retired from the write path.
- **`class_name` and display name for a new versioned identity** append the version
  (`QmtechWukongRevision1Platform`, "Qmtech Wukong (revision 1)") so `(class_name, source)` stays
  unique for recents and `--board`.
- **Backfill (Phase 1a).** Existing files get identity fields from a re-sync at their recorded pin;
  today's file ↔ board pairing is exact (277/277). **One exception:** `litex-boards/qmtech_wukong.json`
  holds **revision 2** data (the module-`_io` fallback tries `_io_v2` before `_io_v1`,
  `litex_parser.py:541`) while LiteX's default is `revision=1`; a one-time migration entry records
  `{"revision": 2}` for it, and the default (revision 1: LEDs J6/H6, clock M22, button H7) arrives
  as a new board in Phase 1b. Delete the migration entry once applied.

### 4.2 The sync ledger (loud skips)

Every upstream file yields exactly one outcome, printed by the sync and written (sorted) into
`_sync_metadata.json`:

| Outcome | Meaning | Sync exit |
|---|---|---|
| `boards: [<file names>]` | produced one or more boards | 0 |
| `skipped: not_a_board` | no platform class / no resources section | 0 |
| `skipped: no_simulatable_io` | clean exec + instantiate, zero LED/switch/button | 0 |
| `skipped: unsupported_shape: <resource>` | (Phase 3) a resource kept as today but flagged | 0 |
| `error: <ExceptionType>: <normalized detail>` | our parser failed | **non-zero** from Phase 1b (reported only in 1a, where errors are today's baseline) |

- **Normalize details** to stay byte-stable across Python versions (CI's drift job runs Python 3.12,
  #449; local runs may be 3.13): for `NameError` record only the missing name, for `AttributeError`
  only the attribute name, otherwise only the exception type. Never the full message.
- Because `_sync_metadata.json` is committed, the existing drift check (zero `git diff` after an
  in-place re-sync) automatically fails on any change in the ledger, and every PR shows ledger
  changes in its diff.
- Parsers stop returning `[]` on exceptions: they return a structured outcome (add a
  `ParseOutcome` dataclass — boards, status, detail — in `sync_common.py`; keep thin compatibility
  wrappers only if a test needs them, otherwise update the tests).
- The module-`_io` fallback (`litex_parser.py:538-545`) is recorded as a ledger warning in 1a
  (content must not change in 1a) and removed in 1b (instantiation failure → `error`).

### 4.3 Orphans

After generating, for each existing file whose identity was **not** produced:

| Situation | Action |
|---|---|
| its `upstream_file` had an `error` outcome | **sync fails**: "would orphan X because our parser failed on Y"; files untouched |
| `upstream_file` absent from the archive | mark orphaned, reason `file_removed` |
| file parsed cleanly but no longer defines this identity | mark orphaned, reason `no_longer_defined` |
| file parsed cleanly with zero simulatable I/O | mark orphaned, reason `no_simulatable_io` |

- **Mark** = add to `source`: `upstream_status: "orphaned"`, `orphaned_at_commit: <commit being
  synced>`, `orphaned_reason`, optional `successor: "<source>/<file>.json"`. Everything else in
  the file stays frozen, including `sync_commit` (the last good sync).
- **Stable:** a re-sync at the same pin re-derives the same mark (keep `orphaned_at_commit` from the
  existing file if already set), so the drift check stays byte-identical.
- **Successor** (a hint, never an automatic migration): among identities *new in this run*, (a) one
  from the same `upstream_file`, else (b) the unique one whose normalized content (`leds`,
  `switches`, `buttons`, `seven_seg`, `clocks`, `device`) equals the orphan's. The 5 Efinix renames
  match by (b) (verified identical).
- **Un-orphan:** when an orphaned identity is produced again, the sync overwrites the file and the
  mark disappears.
- `_sync_metadata.json` gains an `orphans` list.
- Orphans keep working everywhere: the loader reads them, native designs match their frozen
  conventions, recents (keyed by `class_name`) still resolve.

### 4.4 Mock namespace principles

- **Import-aware resolution** (replaces blind blanking): before blanking `import`/`from` lines, walk
  the AST for every `Import`/`ImportFrom` (module level and inside functions). For each imported
  name the mock namespace does not provide: if the module is inside the same upstream archive
  (`litex_boards.*`, Amaranth relative imports such as `from .upduino_v1 import …`) → exec that
  module (cleaned the same way, recursively, cycle-guarded) and bind the name; otherwise bind a
  permissive stub. Star imports (`from litex.build.generic_platform import *`) are what our mocks
  cover. A `NameError` for a name that is **not imported anywhere** is a genuine gap → ledger
  `error`.
- **Permissive stub:** callable; any attribute (instance **and class level** — use a metaclass, so
  `MachdyneML1.revisions` works); `__getitem__`/`__setitem__`; `__iadd__`; iterates as empty.
- **Mock platform:** keep explicit `add_resources` / `add_extension` / `request`; add
  `toolchain = <stub>` and a `__getattr__` returning a no-op callable for every other platform method
  (`add_platform_command`, `add_connector`, `add_period_constraint`, `lookup_request`, …).
- Phase 1b stubs LiteX extension names so files parse; Phase 2 resolves `litex_boards.extensions.*`
  for real.
- Trust model unchanged: we already exec upstream platform files; extension modules come from the
  same archive.

### 4.5 Schema

`boards/schema/board.schema.json` has `additionalProperties: false` at the top level and in
`$defs/source`, and `write_outputs` validates before writing (`sync_common.py:293-296`). Every new
field lands in the schema first, in the same PR (the #346 rule): Phase 1a (`upstream_class`,
`upstream_args`, `upstream_status` enum `["orphaned"]`, `orphaned_at_commit`, `orphaned_reason` enum
`["file_removed", "no_longer_defined", "no_simulatable_io"]`, `successor`); Phase 4 (`leds[].aliases`,
convention alias banks). Update `tests/test_board_schema.py`.

### 4.6 Alias model (Phase 4, if D-1)

- **Board model:** merge LED entries that upstream maps to the identical pin(s): mono+mono on one
  pin → one mono entry; a mono entry whose single pin equals one channel of a 3-pin `rgb_led` → that
  channel of the RGB site. Never merge across different pins; any other overlap shape → keep
  separate + ledger warning. The merged entry keeps the first-declared upstream entry as primary and
  lists the rest in a new `aliases: [{name, number, channel?}]`. Color: from an alias name via
  `led_metadata.color_from_name` unless the cited registry sets one.
- **Conventions:** `framework_conventions.build_convention` currently keeps one primary LED group
  (`framework_conventions.py:99`). Emit every alias group as an accepted bank, each carrying its
  boundary-channel map. `ConventionMatch` (`conventions.py:105`) gains a general list of matched
  LED banks with channel maps (the fixed `leds` / `leds_green` / `leds_rgb` slots stay for existing
  conventions).
- **Matcher:** a design may declare any subset of banks; two declared banks that reach the same
  channel → near-miss naming the shared pin.
- **Wrapper:** generalize the per-site RGB packing in `wrapper.py` (`leds_rgb`, around lines
  171-218) into an explicit per-bit channel map.
- **Pin maps:** `pinmap.py:112-145` indexes physical entries; aliases resolve to the same channel.

### 4.7 Versions (Phase 5, D-4)

Detect versions only where upstream's own code lists them: in `__init__`, a subscript whose index
is a version-selecting parameter and whose value is a dict literal or a module-level name bound to
a dict literal (Wukong `{1: _io_v1, 2: _io_v2}[revision]`; Tang `docks[dock]`; Zybo
`{"z7-10": …, "z7-20": …, "original": …}[variant]`); plus `if param == "<literal>"` comparisons
(ZTEX `expansion == "debug"` / `"sbus"`). Construct each version through the identity machinery
(§4.1); the default version keeps the existing file.

### 4.8 Orphans in the UI (Phase 6)

- Selector row tag "orphaned upstream".
- Preview info line: "No longer in \<source\> since \<date\> (\<short commit\>). Your design
  still runs on this saved copy; it will not receive upstream fixes." plus "Possible successor:
  \<display name\>" when set.
- `--board` resolution prints the same note to stderr.
- Session log field `board_upstream_status` (+ `board_successor`).
- Never blocks a run.
- Register new UI elements with inspect mode (`ui/inspect.py`) and regenerate `docs/ui_map.md`
  (`scripts/gen_ui_map.py`; `tests/test_ui_map.py` enforces it).

---

## 5. PR 0 — Plan, card, ID claim

**Do:** commit this file; the roadmap card U56 (Part 1 / Tier 2); ID allocation → next free U57;
plan-index rows in `docs/improvement_roadmap.md` and `docs/README.md`; Icebox P35 note
("absorbed into U56 Phase 1c"); Icebox P15 note (follow-up for twins); a "Proposed" or ordered entry
in *Current focus* per D-5. Record D-1…D-5 outcomes in this file's header.
**Verify:** `uv run rumdl check docs/`; `uv run pytest tests/test_docs_*.py`.
**Quality gates:** documentation only.

## 6. Phase 1a — Identity, ledger, orphan detection (no board content change)

**Do:**

1. Schema fields of §4.5 (Phase 1a set); `tests/test_board_schema.py`.
2. Parsers return `ParseOutcome` (§4.2) and the identity fields (§4.1); the LiteX parser records
   `upstream_class` and effective `upstream_args` (`inspect.signature` defaults); keep the module-`_io`
   fallback but report it as a ledger warning.
3. Restructure the write path (`sync_common.write_outputs`, `:268`): index existing files by
   identity; assign file names per §4.1; detect and mark orphans per §4.3; write the ledger and
   `orphans` into `_sync_metadata.json`. Preserve `_fold_forward_unmanaged_keys` (`:160` — U39 relies
   on it for `peripherals`), `_carry_forward_sync_stamp` (`:240`), framework polarity reconciliation
   (`:223`), LED color stamping and schema validation.
4. The one-time Wukong migration entry (§4.1).
5. Loader: `BoardDef` gains `upstream_status`, `orphaned_at_commit`, `successor` read from `source`
   (no UI yet); `tests/test_serialization.py` round-trip.
6. Docs: `docs/architecture.md` (sync section: identity, ledger, orphans), `CLAUDE.md` rows for
   `sync_common.py` and the parsers, `CONTRIBUTING.md` if it describes syncing.

**Verify:**

- `export GITHUB_TOKEN=$(gh auth token)`; re-sync each source **in place at its recorded pin**
  (`uv run python scripts/sync_<source>.py --ref <source_commit>` — never a fresh directory, the A1
  trap).
- `git diff boards/` shows **only** the new `source` identity fields and the `_sync_metadata.json`
  ledger. Zero orphans, zero new boards, zero changed LEDs/switches/buttons/clocks/conventions.
- Ledger lists exactly today's skips: LiteX 77 of 248 platform files (24 `not_a_board` or
  `no_simulatable_io` + 53 errors in the classes of §2.3/§2.4); Amaranth 10 (`microzed_z010`,
  `microzed_z020`, `sk_xc6slx9`, `tinyfpga_ax1`, `tinyfpga_ax2`, `zturn_lite_z007s` → no
  simulatable I/O; `supercon19badge` `DiffPairsN`, `upduino_v2` `UpduinoV1Platform`,
  `versa_ecp5_5g` `VersaECP5Platform`, `zturn_lite_z010` `ZTurnLiteZ007SPlatform` → errors);
  Digilent 1 (`Zedboard-Master.xdc`, no simulatable I/O). In 1a, `error` outcomes are reported
  but do not fail the sync: they are today's baseline, recorded in the committed ledger and so
  guarded by the drift check. Phase 1b removes them and makes `error` fatal.
- Unit tests for identity assignment (collision → failure), every orphan situation of §4.3
  (synthetic archives), successor matching, ledger normalization, un-orphaning, re-sync stability.
- `uv run python scripts/check_board_drift.py` green; full `pytest`.

**Quality gates:** board content byte-identical apart from the new fields; `ruff check`,
`ruff format --check`, `mypy` (CI scope: `UV_PROJECT_ENVIRONMENT=/tmp/venv312 uv run --python 3.12
--group dev mypy .`); `set -o pipefail` on any piped test gate.

**Effort:** M.

## 7. Phase 1b — Fix the parsers' misreadings (at the current pins)

**Do:** items 3–10 of §2.3, using the §4.4 principles:

- `_Pins.__init__(self, *identifiers, dir="io", conn=None, assert_width=None)`; names = each string
  split on whitespace; set `self.identifiers`.
- `_PLATFORM_VENDORS`: `LatticeiCE40Platform`, `LatticePlatform` (Lattice), `MicrosemiPlatform`,
  `AnlogicPlatform`, `QuickLogicPlatform`; drop the misspelled key; add a regression test.
- Permissive mock platform and stub (§4.4), import-aware resolution (LiteX: stub
  `litex_boards.extensions.*` for now; Amaranth: exec sibling modules), remove the module-`_io`
  fallback.
- Amaranth: `DDR4Resource` → `_stub_single`; `DiffPairsN` → `_DiffPairs`; `_classify` (`:431`):
  match `sw`/`switch` as a whole token (e.g. `^(sw|switch)(_|\d|$)`), with a `swd` test.
- Digilent: when no section heading classifies a port, fall back to port-name patterns
  `^LD\d+$` (LED), `^SW\d+$` (switch), `^BTN[CDLRU]$` (button), alongside the existing
  `_RE_LED_WORD` / channel patterns (`digilent_parser.py:206-213`). ZedBoard's clock `GCLK` (Y9) has
  no `create_clock` period in the file: follow the parser's existing no-period behavior and do not
  invent a frequency (decision 1) — record what happens.
- New boards take stem-based file names (§4.1), e.g. Amaranth `versa_ecp5_5g.json`,
  `supercon19badge.json`, `upduino_v2.json`.
- Add display-name overrides for any new name `tests/test_board_display_names.py` flags (or do 1c
  first).

**Verify (in place at recorded pins):**

- LiteX 171 → **223**: the 51 boards of Appendix B.1 plus `qmtech_wukong_revision-1.json`
  (2L/0S/1B; LEDs J6/H6, clock M22, button H7). The audit harness counted 222 because it rebuilt
  Wukong in place instead of keeping the revision-2 file. **84** existing LiteX boards change only `device` (`""` → part number); no other
  existing board changes LEDs/switches/buttons/clocks/conventions. `qmtech_wukong.json` (revision 2
  identity) is now built from the instance: diff it against the committed file and review — expect
  equal or additions only.
- Amaranth 80 → **83** (Appendix B.1). Digilent 26 → **27** (ZedBoard: measure and record its
  LED/switch/button counts and conventions).
- Ledger: LiteX errors = 0; remaining skips are `not_a_board` (3) and `no_simulatable_io`.
- Native/generic matrix (Appendix A.3): zero outcome changes on existing boards.
- `tests/test_litex_parser.py`, `tests/test_digilent_parser.py`, `tests/test_sync_amaranth_boards.py`
  gain a test per fix (each with a minimal upstream-shaped fixture); `tests/test_docs_board_counts.py`
  → update the documented counts it names; drift check green; full `pytest`.

**Quality gates:** as 1a. New boards inherit framework conventions automatically; run
`uv run python scripts/sync_port_conventions.py --check` and `uv run python scripts/sync_led_colors.py --check`.

**Effort:** M.

## 8. Phase 1c — Display names from the parsers (absorbs P35)

**Do:** fix `_prettify_class_name` (`amaranth_parser.py:584`) and the LiteX file-name prettifier
(`litex_parser.py:467`) per the P35 card (`DE1SoC` → "DE1-SoC", no dangling hyphens; keep the vendor
spellings `Genesys ZU-3EG-D` / `-5EV-D`). Re-sync in place at the pins. Delete every override in
`board_loader._DISPLAY_NAME_OVERRIDES` that the parsers now emit on their own
(`test_every_override_actually_changes_the_name` names them).
**Verify:** `git diff boards/` changes only `name` fields — **no file renames** (Phase 1a's frozen
identity is what makes P35 safe now); `tests/test_board_display_names.py` (including
`test_a_renamed_board_still_answers_to_its_old_name`); drift check; full `pytest`.
**Effort:** S.

## 9. Phase 2 — Extensions, docks, default clock from the instance

**Do:**

- Resolve `litex_boards.extensions.*` imports by exec'ing the upstream modules (§4.4).
- Mock `add_extension(ext)`: list/tuple → extend `_captured_io`; object → `ext.define_io(self)` if it
  returns a list (dynamic docks such as `TangMegaNeoDock`), else `ext.io`.
- After construction, read `default_clk_name` / `default_clk_period` from the instance, falling back
  to class attributes (`litex_parser.py:526-527`).
- List every LED/switch/button that arrives via an extension in the PR description for review.

**Verify (in place at recorded pins):**

- LiteX 223 → **226**: new `sipeed_tang_primer_20k` 7L/0S/5B, `sipeed_tang_primer_25k` 2L/0S/2B,
  `ztex213` 30L/0S/0B (LiteX's default `expansion="debug"`).
- Changed: `digilent_zybo_z7` 4L/4S/0B → 4L+2rgb/4S/4B (default `variant="z7-20"`: `_io_z7` +
  `_io_z7_20`); `sipeed_tang_console` → 2L/0S/3B; `sipeed_tang_mega_138k` → 2L/0S/3B;
  `sipeed_tang_mega_138k_pro` 8L → 9L/0S/4B; `redpitaya` clocks `[]` → `clk125` @ 125 MHz — **measure
  `default_clock_hz`** (12 MHz today; the audit did not read instance clock attributes).
- No other existing board changes; native/generic matrix zero changes.
- PNGs (product renderer: `uv run fpga-sim --benchmark … --screenshots DIR`) for Zybo Z7, Tang Mega
  138K Pro, ZTEX 2.13, Tang Primer 20K, Red Pitaya → **Rick's visual review before merge**.

**Effort:** S/M.

## 10. Phase 3 — Multi-pin resources (D-3) and DIP switches (D-2)

**Do:**

- Multi-pin rule of D-3 in `_parse_io_as_component` (`litex_parser.py:289`) and `_to_component`
  (`amaranth_parser.py:436`); ledger `unsupported_shape` entries.
- Before coding, classify the 12 boards of Appendix B.4 by shape (plain multi-pin vs r/g/b
  sub-signals vs muxed/bidirectional) and put the table in the PR.
- If D-2 approved: in `_classify_resource` (`:239`) test `dip` before the `btn` substring and return
  `switch`; naming at `:312` → `switch`. The framework convention bank keeps name and width and moves
  from `buttons` to `switches` (verified on `lattice_versa_ecp5`, `lattice_ecp5_evn`,
  `lattice_certuspro_nx_evn`).

**Verify:** in-place re-sync; the diff touches only boards in Appendix B.3/B.4; generics stay within
Appendix B.8 ranges; native/generic matrix zero changes for in-repo designs; PNGs (Versa ECP5,
Trenz C10LP RefKit, Siglent SDS1104X-E, Hackaday badge) → **visual review**.
**Effort:** S.

## 11. Phases 4–8

**Phase 4 — Aliases (D-1), §4.6.**

- **Do, first:** a regression test that freezes every native match possible today: for every board
  and every convention block and LED bank, synthesize a minimal design (clock + that bank, reusing
  the helpers in `tests/test_native_convention.py` such as `_synth_board` at `:535`) and assert
  `match_convention` still matches with the same widths and polarity.
- **Then:** the board-model merge, the `aliases` schema field, alias banks in
  `framework_conventions`, the matcher and wrapper channel maps, the two-aliases near-miss, alias
  colors, pin-map indexing.
- **Verify:** the 29 boards of Appendix B.2 reach the "pin-merged" column; every frozen match still
  matches; GHDL + NVC e2e for one alias board per shape (mono+mono: iCEBreaker; mono+RGB channel:
  OrangeCrab; triple: LiteX `lattice_ice40up5k_evn`); PNGs → **visual review**.
- **Effort:** L.

**Phase 5 — Versions (D-4), §4.7.**

- **Do:** implement detection, then **report first** (per file: versions found, which simulate
  differently, proposed names) and stop for Rick's go-ahead; then emit.
- **Verify:** default versions keep their files and `class_name`s; new versions follow §4.1 naming;
  native/generic matrix zero changes on existing boards; selector PNG → **visual review**.
- **Effort:** M.

**Phase 6 — Orphans in the UI, §4.8.**

- **Do:** use a synthetic orphan fixture; assert on what is rendered (tag text, info line,
  successor); add the CLI note and the session-log field; inspect registration; `docs/ui_map.md`
  regeneration; `docs/user_guide.md` (selector + preview sections).
- **Verify:** PNGs → **visual review**; full `pytest`.
- **Effort:** S/M.

**Phase 7 — Bump to the upstream heads.**

- **Do:** resolve each source's current default-branch head and re-sync in place at it (the
  2026-10-28 heads are in §2.1; upstream will have moved — **re-run the audit** and review anything
  not listed here); update `_sync_metadata.json` pins.
- **Expected** (vs 2026-10-28 heads): LiteX produces 233 boards — +12 new (Appendix B.5); the 5 Efinix renames →
  old files **kept, marked orphaned, successor = new file** (identical I/O and device, verified);
  `sipeed_tang_console` 3 → 2 buttons (upstream made `EX_KEY.0` the reset); `alinx_ax7010` buttons 2/3
  swap pins R17/T17 (upstream edit); `modretro_chromatic` device `GW5A-LV25PG256C1/I0` →
  `GW5A-EV25UG256CC1/I0` (upstream). Amaranth +3 (`butterstick`, `icesugar_pro`, `rfsoc4x2`).
  Digilent unchanged. Acorn keeps 506 Hz unless upstream has fixed #934.
- **Verify:** drift check green at the new pins; ledger reviewed; `sync_port_conventions --check`,
  `sync_led_colors --check`; native/generic matrix zero changes on existing boards (measured for
  the 2026-10-28 heads); `tests/test_docs_board_counts.py`; full `pytest`.
- **Effort:** S/M.

**Phase 8 — Closeout.** `CHANGELOG.md`; `README.md` / `docs/user_guide.md` / `docs/architecture.md`
/ `CLAUDE.md` counts and sync description; roadmap card → delivered (+ `docs/roadmap_delivered.md`
entry); Icebox P35 closed as absorbed; this file's status → executed; release per D-5.

---

## 12. Phase ledger

| Phase | Scope | Visual review | Status |
|---|---|---|---|
| PR 0 | plan + card + ID | no | not started |
| 1a | identity, ledger, orphan detection | no | not started |
| 1b | parser misreadings at pins | no (data only; spot-check PNGs optional) | not started |
| 1c | display names (P35) | no | not started |
| 2 | extensions, docks, instance clock | **yes** | not started |
| 3 | multi-pin, DIP | **yes** | not started |
| 4 | aliases | **yes** | not started |
| 5 | versions | **yes** (selector) | not started |
| 6 | orphan UI | **yes** | not started |
| 7 | bump to heads | no | not started |
| 8 | closeout + release | no | not started |

---

## 13. Traps checklist (read before every phase)

- **Re-sync in place at the recorded `source_commit`** — a fresh directory drops canonical
  conventions (the U21 A1 trap). `GITHUB_TOKEN` is required; an unauthenticated rate limit reads as
  false drift.
- **Never hand-edit generated board JSON** — change a parser or a registry, then re-sync.
- **Never rename an existing board file or change an existing `class_name`** (§2.6: registries key
  by path, recents by `class_name` + source; `tests/test_native_convention.py` reads
  `boards/amaranth-boards/tiny_fpgabx.json`, `boards/litex-boards/digilent_arty.json`,
  `boards/digilent-xdc/arty_a7-100.json`, `nexys_4_ddr.json`, `basys_3.json`,
  `boards/custom/de25_standard.json`).
- **The sync never deletes** — by design now (orphans). Do not add deletion.
- **Ledger text must be Python-version-stable** (§4.2).
- **Schema first** (`additionalProperties: false`); the sync validates before writing.
- **Keep** `_fold_forward_unmanaged_keys`, `_carry_forward_sync_stamp`, polarity reconciliation and
  LED-color stamping working through the write-path refactor.
- **Upstream data bugs are not ours to fix** (decision 2) — if one surfaces, offer Rick a drafted
  upstream issue; no override.
- **Visual review before merge** for phases 2–6. `--benchmark` exits before the session restores.
- Tests: `set -o pipefail` around piped gates; CI mypy runs on Python 3.12 (#449).
- Prove a projection before trusting it: rebuild the Appendix A baseline (no-fix harness reproduces
  the committed boards exactly) before reading any "after" number.

## 14. Out of scope / follow-ups

- **Icebox P15** — "this design matches board X" for a native file chosen against the other twin of
  a cross-source pair (e.g. Terasic `de10_lite.vhd` on LiteX "Terasic De10lite"). Recommended
  follow-up; it improves the message without changing data (decision 4).
- Multiplexed LED matrices (ButterStick `rgb_leds_muxed`, Supercon badge `led_cathodes`) as a scan
  model — a new card if wanted.
- Acorn clock — upstream #934.
- 18-switch custom boards (DE2-115, VEEK-MT2) exceed the CPU designs' 16-bit switch window; the
  firmware reads only `sw(7:0)`; pre-existing and unrelated.
- Cross-source disagreements (Appendix B.7) — kept per decision 1.

---

## Appendix A — Audit method (to rebuild the evidence)

**A.1 Harness.** Shallow-clone each upstream at the pin and at head. In a script run from the repo
root with `scripts/` and `src/` on `sys.path`, monkeypatch the parser modules
(`litex_parser._Pins.__init__`, `_PLATFORM_VENDORS`, `_make_mock_platform`,
`_make_litex_namespace`; `amaranth_parser._make_namespace`), then call the sync's **own**
generators — `sync_litex_boards.generate_all_json(board_files, sha)` /
`sync_amaranth_boards.generate_board_json(board_files, sha)` with
`board_files = {path.name: text for every *.py in the platforms dir}` — and write
`{output file: board dict}`. The audit resolved undefined names by exec-retry (catch `NameError`,
bind a stub, retry; for Amaranth bind a class from the sibling file that defines it) — Phase 1b
replaces that with import-aware resolution (§4.4).

**A.2 Comparison and baseline.** Diff harness output against `boards/<source>/` after normalizing:
drop `$schema` and `source`; drop LED `color` (stamped at write time); keep only the parser's own
`port_conventions` sub-key, **merged with the committed canonical sub-keys and passed through
`framework_conventions.reconcile_framework_polarity`** (as `sync_common.py:223` does). With **no**
fixes at the pins this reproduced **171/171 LiteX and 80/80 Amaranth** boards exactly — prove that
baseline before trusting any "after" diff. Report LEDs as sites, mono + RGB, by the loader's rule
(`name == "rgb_led"` and 3 pins); never as channels.

**A.3 Impact matrix.** For every `hdl/native/*.vhd` and `hdl/*.vhd`, run
`vhdl_contract.check_vhdl_contract(path, board_def=BoardDef.from_json(raw))` against every board
today and in the projected fleet; compare `(ok, ConventionMatch minus board_name)`. Generics: run
`controller.build_generics(BoardDef.from_json(raw))` for every board; `NUM_SEGS` = the board's digit
count when it has a display, else the CPU designs' default 4.

**A.4 Instantiation audit.** For each platform file: exec (with the fixes), find the platform class,
call it with no arguments, and tabulate exception type + message.

## Appendix B — Lists (2026-10-28)

### B.1 Boards recovered by Phase 1b at the pins

LiteX (51): `alchitry_cu` 8L · `alibaba_vu13p` 9L/3S · `antmicro_datacenter_ddr4_test_board`
5L/4B · `avalanche` 4L/2B · `colorlight_i5` 1L · `digilent_netfpga_sume` 6L/2B ·
`digilent_pynq_z1` 10L/2S/4B · `digilent_zedboard` 8L/8S/5B · `enclustra_mercury_kx2` 4L ·
`fpgawars_alhambra2` 8L · `ice_v_wireless` 3L/1B · `icebreaker` 4L/1B · `icebreaker_bitsy`
4L+1rgb/1B · `kosagi_fomu_evt` 1L+1rgb/2B · `kosagi_fomu_hacker` 1L+1rgb · `kosagi_fomu_pvt`
1L+1rgb · `lattice_ice40up5k_evn` 4L+1rgb/4S · `lattice_machxo3` 8L/4B · `machdyne_krote` 1L ·
`mlkpai_fs01_dr1v90m` 8L/3B · `muselab_icesugar` 3L+1rgb/4S · `numato_nereid` 1rgb ·
`quicklogic_quickfeather` 3L+1rgb/1B · `qwertyembedded_beaglewire` 1L/1B · `signaloid_c0_microsd`
2L · `sipeed_tang_primer` 3L/1B · `sitlinv_stlv7325_v1` 8L/2B · `sitlinv_stlv7325_v2` 8L/2B ·
`sitlinv_xc7k420t` 8L/1B · `sqrl_xcu1525` 3L · `terasic_de0nano` 8L/4S/2B · `terasic_de10lite`
10L/10S/2B/7seg6 · `terasic_de1soc` 10L/10S/4B/7seg6 · `terasic_deca` 8L/2S/3B · `tinyfpga_bx` 1L ·
`trenz_mf_c10lp_001` 1L · `trenz_smf2000` 9L/1B · `trenz_tem0006` 1L/1B · `xilinx_ac701`
4L/4S/5B · `xilinx_alveo_u200` 3L/4S · `xilinx_alveo_u250` 3L/4S · `xilinx_alveo_u280` 3L ·
`xilinx_kc705` 8L/9B · `xilinx_kcu105` 8L/9B · `xilinx_vc707` 8L/13B · `xilinx_vcu118` 8L/9B ·
`xilinx_vcu128` 8L · `xilinx_zc706` 4L/7B · `xilinx_zcu104` 4L/4B · `xilinx_zcu106` 8L/5B ·
`ypcb_00338_1p1` 3L. (Counts before Phases 3–4; the DIP boards' buttons include DIPs.)

Amaranth (3): `supercon19badge.py` 12L/8B · `upduino_v2.py` 3L+1rgb · `versa_ecp5_5g.py` 9L/8S.

Phase 2 adds (LiteX): `sipeed_tang_primer_20k` 7L/5B · `sipeed_tang_primer_25k` 2L/2B · `ztex213`
30L.

### B.2 Boards listing one pin under several names (D-1, Phase 4) — at head, fixed parser

| Board | As listed (LED bits) | Pin-merged (LED bits) |
|---|---|---|
| litex `gsd_orangecrab` | 3L+1rgb (6) | 1rgb (3) |
| litex `icebreaker` | 4L (4) | 2L (2) |
| litex `icebreaker_bitsy` | 4L+1rgb (7) | 2L+1rgb (5) |
| litex `kosagi_fomu_evt` / `_hacker` / `_pvt` | 1L+1rgb (4) | 1rgb (3) |
| litex `lattice_ice40up5k_evn` | 4L+1rgb (7) | 1rgb (3) |
| litex `machdyne_konfekt` / `_kopflos` / `_noir` / `_schoko` | 3L+1rgb (6) | 1rgb (3) |
| litex `muselab_icesugar` / `_icesugar_pro` | 3L+1rgb (6) | 1rgb (3) |
| litex `numato_aller` / `_tagus` | 3L+1rgb (6) | 1rgb (3) |
| litex `quicklogic_quickfeather` | 3L+1rgb (6) | 1rgb (3) |
| litex `sipeed_tang_nano` | 3L+1rgb (6) | 1rgb (3) |
| litex `trenz_tel0025` | 3L+1rgb (6) | 1rgb (3) |
| litex `xilinx_zcu216` | 8L+8rgb (32) | 8rgb (24) |
| amaranth `black_ice` / `black_ice_ii` | 8L (8) | 4L (4) |
| amaranth `fomu_hacker` / `fomu_pvt` | 1L+1rgb (4) | 1rgb (3) |
| amaranth `ice40_up5_kbevn` / `icesugar` / `upduino_v1` / `upduino_v2` | 3L+1rgb (6) | 1rgb (3) |
| amaranth `icebreaker` | 4L (4) | 2L (2) |
| amaranth `icebreaker_bitsy` | 4L+1rgb (7) | 2L+1rgb (5) |

29 boards (19 LiteX + 10 Amaranth); 20 of them are shipped today. None carries a canonical
convention; no in-repo native design targets one. CPU examples: on a board whose only LED becomes
one RGB site, the walking light cycles that LED's channels.

### B.3 DIP boards (D-2, Phase 3) — LiteX `user_dip_btn`

| Board | Shipped | Buttons now | of which DIP | Real buttons after | Switches after |
|---|---|---|---|---|---|
| `antmicro_sdi_mipi_video_converter` | yes | 2 | 2 | **0** | 2 |
| `lattice_certus_nx_versa` | new | 7 | 4 | 3 | 4 |
| `lattice_certuspro_nx_evn` | yes | 11 | 8 | 3 | 8 |
| `lattice_certuspro_nx_versa` | yes | 6 | 5 | **1** | 5 |
| `lattice_certuspro_nx_vvml` | yes | 6 | 4 | 2 | 4 |
| `lattice_crosslink_nx_evn` | yes | 10 | 8 | 2 | 8 |
| `lattice_crosslink_nx_vip` | yes | 6 | 4 | 2 | 4 |
| `lattice_ecp5_evn` | yes | 9 | 8 | **1** | 8 |
| `lattice_ecp5_vip` | yes | 9 | 8 | **1** | 8 |
| `lattice_machxo3` | new | 4 | 4 | **0** | 4 |
| `lattice_versa_ecp5` | yes | 8 | 8 | **0** | 8 |
| `xilinx_kc705` / `xilinx_kcu105` / `xilinx_vcu118` | new | 9 | 4 | 5 | 4 |
| `xilinx_vc707` | new | 13 | 8 | 5 | 8 |
| `xilinx_zc706` | new | 7 | 4 | 3 | 4 |

CPU firmware: `btn(0)` reverses the walk / rolls the die, `btn(1)` held is the lamp test, each
active switch in `sw(7:0)` doubles the walk rate (`firmware/README.md`).

### B.4 Shipped boards with multi-pin non-RGB resources (D-3, Phase 3)

amaranth `quickfeather` `swd`(2 pins, io) · amaranth `tang_primer20k_dock` `mic_led`(2) · amaranth
`versa_ecp5` `alnum_led`(15) · litex `alibaba_xcku3p` `led`(3) · litex
`efinix_titanium_ti60_f225_dev_kit` `led`(3) ×2 · litex `fairwaves_xtrx` `led`(3), `switch`(3) ·
litex `gsd_butterstick` `led`(3) · litex `hackaday_hadbadge` `led`(11), `led`(3) · litex
`lattice_versa_ecp5` `alnum_led`(15) · litex `limesdr_xtrx` `led`(3), `switch`(3) · litex
`siglent_sds1104xe` `led_frontpanel`(4), `button`(3) · litex `trenz_c10lprefkit` `gpio_leds`(8).
(Shapes not yet classified — first task of Phase 3. Example: `fairwaves_xtrx` declares
`("user_led2", 0, Pins("G3 M2 G2"))  # GPIO LED`.)

### B.5 Upstream changes between the pins and the 2026-10-28 heads

- LiteX new (12): `aliexpress_rk_xcku5p` 4L/4B · `alinx_ax7035` 4L/4B/7seg1 ·
  `digilent_eclypse_z7` 2rgb/2B · `efinix_t120_f576_dev_kit` 8L/4S/4B · `efinix_t20_f256_dev_kit`
  8L/3S/3B · `efinix_t20_mipi_dev_kit` 2L/2B · `efinix_t8_f81_dev_kit` 5L/2B ·
  `efinix_ti60_f225_dev_kit` 2L/2S/4B · `lattice_certus_nx_versa` 8L/7B · `microsoft_storey_peak`
  8L · `mlk_cu07_ku15p` 7L/3B · `sipeed_tang_mega_60k` 8L/2B.
- LiteX renamed (5, identical I/O and device): `efinix_t8f81_dev_kit` → `efinix_t8_f81_dev_kit` ·
  `efinix_titanium_ti60_f225_dev_kit` → `efinix_ti60_f225_dev_kit` ·
  `efinix_trion_t120_bga576_dev_kit` → `efinix_t120_f576_dev_kit` ·
  `efinix_trion_t20_bga256_dev_kit` → `efinix_t20_f256_dev_kit` · `efinix_trion_t20_mipi_dev_kit` →
  `efinix_t20_mipi_dev_kit`.
- LiteX content changes on shared files: `sipeed_tang_console` buttons 3 → 2; `alinx_ax7010`
  buttons 2/3 pin swap; `modretro_chromatic` device string.
- Amaranth new (3): `butterstick.py` 1L/2B (its 7 RGB LEDs are `rgb_leds_muxed`, see D-3) ·
  `icesugar_pro.py` 1rgb · `rfsoc4x2.py` 4L+2rgb/4S/4B.
- Digilent: `SECURITY.md` only.

### B.6 Second-source twins at heads (kept as-is, decision 4)

LiteX `terasic_de10lite` ↔ amaranth `de10_lite` (Terasic canonical) · LiteX `terasic_de1soc` ↔
amaranth `de1_so_c` (Terasic canonical) · LiteX `terasic_de0nano` ↔ amaranth `de0_nano` (Terasic
canonical) · LiteX `digilent_eclypse_z7` ↔ digilent `eclypse_z7` (Digilent canonical) · LiteX
`xilinx_kc705` ↔ amaranth `kc705` · LiteX `xilinx_kcu105` ↔ amaranth `kcu105` · LiteX `icebreaker`
↔ amaranth `icebreaker` · LiteX `icebreaker_bitsy` ↔ amaranth `icebreaker_bitsy` · LiteX
`kosagi_fomu_hacker` ↔ amaranth `fomu_hacker` · LiteX `kosagi_fomu_pvt` ↔ amaranth `fomu_pvt` ·
LiteX `muselab_icesugar` ↔ amaranth `icesugar` · LiteX `quicklogic_quickfeather` ↔ amaranth
`quickfeather` · amaranth `butterstick` ↔ LiteX `gsd_butterstick` · amaranth `icesugar_pro` ↔ LiteX
`muselab_icesugar_pro`. A Terasic- or Digilent-native design matches only the entry carrying the
canonical block (follow-up: P15).

### B.7 Cross-source disagreements (informational; each source simulated as defined)

Genesys 2 / Nexys 4 / Nexys 4 DDR: 6 buttons (Digilent XDC counts CPU reset) vs 5 (LiteX
`cpu_reset` is separate) · Cmod A7: 2 vs 1 (same reason) · DE2-115: LiteX 18L vs custom
27L/18S/4B · Versa ECP5: LiteX 8 DIP-as-buttons vs Amaranth 8 switches (D-2) · KC705 / KCU105:
LiteX 9 buttons vs Amaranth 0 (Amaranth declares none) · ButterStick: LiteX 8L vs Amaranth 1L ·
iCESugar Pro / QuickFeather / Tang Nano: LiteX aliases (D-1) vs Amaranth single RGB.

### B.8 Runtime generic ranges (`build_generics`), today vs projected at heads

| Generic | Today | Projected | New values |
|---|---|---|---|
| `NUM_LEDS` | 1..32 | 1..32 | 30 (`ztex213`) |
| `NUM_SWITCHES` | 1..18 | 1..18 | — |
| `NUM_BUTTONS` | 1..13 | 1..13 | — |
| `NUM_SEGS` | 1..8 | 1..8 | — |
| `CLK_HALF_NS_INIT` | 1..988142 | 1..988142 | 6 |

(988142 ns is the Acorn baseboard's upstream 506 Hz clock — decision 2.)

## Appendix C — Code anchors (verified 2026-10-28)

| Concern | Anchor |
|---|---|
| LiteX mocks | `scripts/litex_parser.py:21` `_Pins` · `:99` `_PLATFORM_VENDORS` (`:109` iCE40 key) · `:124` `_make_mock_platform` (`:146` `add_connectors`, `:149` `add_extension`) · `:166` `_make_litex_namespace` |
| LiteX classify/parse | `:226` `_classify_resource` (`:239` DIP) · `:289` `_parse_io_as_component` (`:312` DIP name) · `:439` `_build_litex_convention` · `:467` `_prettify_filename` · `:474` `_make_class_name` · `:486` `parse_litex_board` (`:500` exec except · `:526-527` class-level default clock · `:536` instantiate except · `:541` `_io` fallback · `:649` one board) |
| Amaranth | `scripts/amaranth_parser.py:293` `_make_namespace` · `:422` `_classify` (`:431` `sw`) · `:436` `_to_component` · `:584` `_prettify_class_name` · `:599` `load_board_from_source` (`:614` except) |
| Digilent | `scripts/digilent_parser.py:206` `_RE_LED_WORD` · `:213` RGB channel pattern · `:261` heading classification · `:278` `parse_xdc` |
| Sync scripts | `scripts/sync_litex_boards.py:60` `generate_all_json` (`:80` silent skip, `:93` file name) · `scripts/sync_amaranth_boards.py:48` `generate_board_json` (`:67`, `:80`) · `scripts/sync_digilent_xdc.py:103,106` |
| Sync common | `scripts/sync_common.py:23` `sanitize_filename` · `:34` `unique_name` · `:160` `_fold_forward_unmanaged_keys` · `:223` polarity reconcile · `:240` `_carry_forward_sync_stamp` · `:268` `write_outputs` |
| Conventions | `scripts/framework_conventions.py:86` `build_bank` · `:99` primary-group rule · `:166` `build_convention` · `:225` `reconcile_framework_polarity` |
| Drift | `scripts/check_board_drift.py:64` `main` |
| Loader | `src/fpga_sim/board_loader.py:54` overrides · `:242` `is_rgb` · `:285` `BoardDef` · `:352` `num_led_channels` · `:366` `led_channel_targets` · `:473` `from_json` · `:566` `find_board` |
| Matcher/wrapper | `src/fpga_sim/conventions.py:105` `ConventionMatch` · `:478` `_convention_precedence` · `:521` `match_convention` · `src/fpga_sim/wrapper.py` `leds_rgb` packing (~`:171-218`) |
| Runtime | `src/fpga_sim/controller.py:130` `build_generics` · `src/fpga_sim/pinmap.py:112-145` pin index · `src/fpga_sim/session_config.py:129` `push_recent` |
| CPU IO | `scripts/embedded_core/templates/cpu_io.vhd.tmpl:37` `LED_REG_WIDTH` · `:43-57` read mux and config registers |
| Tests | `tests/test_litex_parser.py` · `tests/test_digilent_parser.py` · `tests/test_sync_amaranth_boards.py` · `tests/test_sync_common.py` · `tests/test_check_board_drift.py` · `tests/test_board_schema.py` · `tests/test_serialization.py` · `tests/test_board_display_names.py` · `tests/test_docs_board_counts.py` · `tests/test_native_convention.py` · `tests/test_ui_map.py` · `tests/conftest.py:212` |
