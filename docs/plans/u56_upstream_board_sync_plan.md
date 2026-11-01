# U56 — Upstream board-sync repair: arc plan (faithful parsers, stable identity, orphaned boards)

**Status:** **APPROVED 2026-10-31 (Rick)** — drafted 2026-10-28, revised twice on 2026-10-31, and
amended the same day at the start of execution. **Executing → v0.24.0, the whole arc** (D-5,
revised: next, ahead of U39–U41 → v0.25.0 and D16 → v0.26.0; Phases 5–7 included). **No upstream
code is ever executed** (D-7): Phase 0 replaces the Amaranth and LiteX parsers' `exec()` with a
reader that only parses. The early `--board` item shipped in [#466](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/466); the no-scope sync-token
recipe was dropped (D-7). PR 0 ([#465](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/465))
committed this file and the roadmap card; issues open just-in-time per phase. From here on, the
phase ledger in §12 is the status source of truth.

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

**Decided 2026-10-31 (Rick) — every recommendation in §3 approved:** D-1 merge LEDs that upstream
maps to the same pin, and accept every upstream name as a native port · D-2 DIP switches are
switches · D-3 one component per pin, behind two prerequisites (defect 21; a split group never
displaces today's bank) · D-4 emit every upstream-listed version · D-5 v0.26.0, after D16, with a
stop point after Phase 4 · D-6 read every frequency upstream defines (defects 13, 22, 23), and mark
the remaining four boards' clocks as assumed.

**Decided 2026-10-31, at the start of execution (Rick) — amends the above:**

- **D-7 (new): never execute upstream code.** "I consider executing upstream code a potential
  vulnerability. Let's not do that." Phase 0 replaces `exec()` with a parse-only reader (§3 D-7,
  §4.4, §5a).
- **D-5 revised: next, as v0.24.0, and the whole arc.** "U56 should come next, and we need the full
  arc." U39–U41 → v0.25.0, D16 → v0.26.0. Phase 4 stays a checkpoint, not a release point.
- **No separate sync token.** "Locally, `gh` can do everything we need." Once nothing executes
  upstream code, `gh`'s own token is fine for the one step that needs a token (§4.4).
- **Also folded in (recommended 2026-10-31):** the external review's R2 — mono and RGB LEDs
  interleaved on 19 LiteX boards — is a parser misreading of upstream's order, so it joins Phase 1c
  as defect 24.

**Revised 2026-10-31** after a review pass that checked this draft against the code, the saved
audit data and a re-run of today's parser at the LiteX pin:

- **Identity (§4.1).** The sync constructs every identity already on disk, not only the default,
  and matching tolerates version keys added later. As first drafted, Phase 1a's own in-place
  re-sync would have orphaned Wukong's revision-2 file.
- **Ledger and orphans (§4.2–4.3).** One outcome plus any warnings per upstream file; a committed
  accept-list for upstream files that are genuinely broken (decision 2) and for orphans that could
  be our misreading; a board whose file stops yielding I/O fails the sync instead of quietly
  becoming an orphan.
- **Credentials (§4.4).** Syncs use a token with no scopes, and the step that executes upstream
  code runs with no credential in its environment.
- **Phase 1a** also makes `--board` source-qualified (14 boards cannot be selected from the
  command line today, §2.6) and commits a design × board impact matrix that later phases diff.
- **Order (§12).** Display names before the parser fixes; the bump right after the orphan UI;
  multi-pin/DIP, aliases and versions after the bump, with a stop point there (D-5). Phases are
  renumbered to match the order.
- **Visual review** now covers every phase that adds boards or changes what a board draws —
  including the parser fixes, which put a part number on 91 chips.
- **Decisions.** D-4 now recommends emitting every version; D-6 is new.
- **Evidence.** Six more cross-source twins, found by comparing pins (47 physically new boards,
  not 53); 74 new files, not 73; 86 LiteX boards ship an empty `device`, not 84; new defects 18–20.

**Revised again 2026-10-31, at approval**, after checking the evidence behind each decision:

- **D-3 (§3, Phase 5).** LiteX's classifier reads any name containing "switch" as a user switch, so
  both XTRX boards ship upstream's RF-path switch controls (`rf_switches`) as one (defect 21, fixed
  in 1c). And the bank builder picks the widest group, so splitting the XTRX boards' 3-pin
  `user_led2` would replace their `user_led` bank: a split group must never displace today's bank.
- **D-6 (§3).** 13 boards show a default clock we invented, but upstream defines a frequency for 11
  of them: on-chip oscillators the Amaranth parser ignores (defect 22), a Digilent frequency stated
  only in a comment (defect 23), and LiteX clocks set in the constructor (defect 13, now two
  boards). Four boards remain whose clock is marked as assumed.
- **Phase 1a** now freezes every native port bank in the impact matrix (moved from Phase 6), since
  Phase 5 can change one.
- **D-5** now places the arc after D16, instead of before the peripherals.
- **Wording.** D-2: `user_dip_btn` is an explicit button entry, not a substring accident. D-4: how
  many versions §4.7's rules find.

**Amended 2026-10-31, at the start of execution** (the decisions above):

- **D-7 and Phase 0 (§5a).** The parsers stop executing upstream files. §4.4 is rewritten as the
  reader's design. Phase 1a loses its credential items, since nothing executes. Phase 1c's
  import-aware resolution and Phase 2's extension modules are *read*, not executed. Phase 4 reads
  unreviewed heads and runs none of them, and §14's sandbox question is moot.
- **D-5.** Next, v0.24.0, the whole arc; the roadmap is renumbered in the PR that records this.
  Phase 8 releases after Phase 7.
- **Defect 24 (§2.3, Phase 1c):** the external review's R2.
- **The 2026-10-28 audit harness executed upstream files** (Appendix A). It must not be run again:
  rebuild evidence with the Phase 0 reader or the static scans in `~/.claude/u56-audit/`.

**Audience contract:** written to be executed phase by phase by a capable model without additional
context. Every phase has **Do**, **Verify**, **Quality gates**. Do not start a phase until the
previous phase's Verify passes. One PR per phase; branch each phase off post-merge `main`; never
commit to `main`. **Never execute, import or instantiate an upstream file** (D-7): not in a sync, a
test, an audit or a one-off measurement. A phase that adds boards or changes what a board draws (phases 1c and 2–7)
attaches PNGs and waits for Rick's visual review **before** merge. Name boards as
**`<source>/<file>.json`** in Verify steps and PR text: display names and class names repeat
across sources, and an unqualified `--board` can pick the other source's twin (§2.6).

**Evidence:** every number below was measured on 2026-10-28 against the pinned and then-current
upstream commits (§2.1); numbers marked *2026-10-31* were measured in the review pass. The audit
scripts and their raw results are saved outside the repository on the drafting machine
(`~/.claude/u56-audit/`, with a README; the scripts there that execute upstream files must not be
run again, D-7). Appendix A describes them closely enough to rebuild, and
Phase 1a commits the design × board impact matrix, so no later phase depends on them. Every phase
re-proves its own effect with in-place re-syncs and tests. **Upstream keeps moving — re-measure
before relying on a number.**

---

## 1. Why

Three classes of problem, none of which is visible today:

- **A. Silent misreadings.** The LiteX and Amaranth parsers mock-exec upstream Python and swallow
  every failure (`scripts/litex_parser.py:500`, `:536`; `scripts/amaranth_parser.py:614`) — a file
  that fails to exec is reported as "no simulatable resources" (`scripts/sync_litex_boards.py:80`)
  and a platform that fails to instantiate silently falls back to a module-level `_io` list
  (`scripts/litex_parser.py:541`). Result: **54 LiteX boards and 4 Amaranth boards upstream defines
  have never been synced**, and shipped boards are mis-modeled (Zybo Z7 ships with 0 buttons;
  91 boards with an empty `device` — 86 LiteX boards built from the fallback and 5 Amaranth Gowin
  boards; 11 boards simulate a default clock other than the one upstream defines, Red Pitaya's
  among them; 20 boards draw one upstream pin as two LEDs; two XTRX boards draw an RF switch
  control as a user switch).
- **B. Unsafe identity and silent staleness.** A board's file name *is* its sanitized display name
  (`sync_common.sanitize_filename`, 277/277 synced files), with `_2`, `_3` appended in processing
  order on a collision (`sync_common.unique_name`). And the sync **never deletes** a file
  (`write_outputs` only writes). So a board that stops being produced lingers, frozen and
  unmarked; a display-name fix (P35) would rename ~20 files; and a new same-named upstream board
  could take over an existing board's file. The command line shares the weakness: `--board`
  ignores the source folder, so 14 boards cannot be selected with it at all (§2.6).
- **C. Upstream drift breaks the parser.** LiteX is 397 commits past our pin and refactored its
  PMOD/dock helpers into `litex_boards/extensions/`. Re-syncing at LiteX head with today's parser
  produces **149 boards instead of 171**; the other 31 files would stay on disk, frozen at the old
  commit, missing from `_sync_metadata.json` and invisible to the drift check.

**Nothing in the board data is broken today:** the drift job (`scripts/check_board_drift.py`)
re-syncs at the recorded pins. Every problem above bites at the next pin bump or is already a quiet
inaccuracy.

**What success looks like:** every board upstream defines is either synced or listed with a
reason; every shipped board is read the way upstream defines it; no board is ever renamed or lost
by a sync; boards that vanish upstream are kept and marked; every board can be named on the
command line; and the in-repo VHDL (9 native, 24 generic designs) and the CPU firmware behave
exactly as before (§2.5 proves this is achievable).

---

## 2. Evidence (audit of 2026-10-28, review pass of 2026-10-31)

### 2.1 Pins and drift

| Source | Recorded pin (`_sync_metadata.json`) | Upstream head 2026-10-28 | Ahead |
|---|---|---|---|
| amaranth-boards | `be069dfd490b31df215337afac35711994a52418` | `f270d210e36b0787d62db77176c7b0e8032178d3` | 5 commits (3 board files) |
| litex-boards | `8bf5de766fed9b89fdb265b17d2becc08039e9d1` | `c7056065097338bd943f54195dbe27a7548ef4d2` | 397 commits |
| digilent-xdc | `00a3404901f35aa9567b01ecb3f2c233b6efe9f4` | `c8644a9fe31cc803789643124545d56b3bef4600` | 1 commit (`SECURITY.md` only) |

Today: **285 boards** = 80 amaranth + 171 litex + 26 digilent + 8 custom. Digilent at head is
content-identical to what we ship (field by field, only `source` differs).

### 2.2 Projected board counts

| Source | Today | Unfixed parser @ head | Phase 1c @ pins | + Phase 2 @ pins | After the bump (Phase 4) |
|---|---|---|---|---|---|
| amaranth | 80 | 82 | 83 | 83 | 86 |
| litex | 171 | 149 produced (31 left frozen) | 223 | 226 | 233 produced + 5 orphans kept = 238 files |
| digilent | 26 | 26 | 27 (ZedBoard — **unmeasured**) | 27 | 27 |
| custom | 8 | 8 | 8 | 8 | 8 |
| **files** | **285** | — | **341** | **344** | **359** (before Phase 7 versions) |

The LiteX figures include Wukong revision 1 as a new file beside today's revision-2 file (§4.1);
the audit harness measured one fewer (222 / 225 / 232) because it overwrote Wukong instead. Of the
**74** new board files after the bump: **47** are physical boards we do not have from any source;
**20** are second sources for boards we already ship (Appendix B.6 — found by comparing pins, not
names); **1** is the Digilent ZedBoard, a second source for the new LiteX ZedBoard; **5** are the
upstream Efinix renames; **1** is Wukong revision 1. *(2026-10-31: the first draft said 73 / 53 /
14 — it left out the Digilent ZedBoard, and it matched twins by name, which misses mangled names
such as `tiny_fpgabx` ↔ `tinyfpga_bx`.)*

### 2.3 Defect inventory

| # | Defect | Anchor | Effect | Phase |
|---|---|---|---|---|
| 1 | Exec/instantiate failures swallowed; skip reason never printed | `litex_parser.py:500,536`; `sync_litex_boards.py:80`; `amaranth_parser.py:614`; `sync_amaranth_boards.py:67` | boards vanish silently | 1a |
| 2 | File name = display name; collision suffix by order; sync never deletes | `sync_common.py:23,34,268` | renames, silent staleness, takeover risk | 1a |
| 3 | `_Pins` mock accepts one string; upstream passes several; no `.identifiers` | `litex_parser.py:21` | ~31 files never synced (DE1-SoC, DE10-Lite, ZedBoard, KC705…) | 1c |
| 4 | Vendor key typo `LatticeICE40Platform` (upstream: `LatticeiCE40Platform`) | `litex_parser.py:109` | all LiteX iCE40 boards never synced | 1c |
| 5 | No Microsemi / Anlogic / QuickLogic / `LatticePlatform` mocks | `litex_parser.py:99` | those boards never synced | 1c |
| 6 | Mock platform lacks `toolchain`, `add_platform_command` (78 files), `add_connector`, … | `litex_parser.py:124-160` | ~95 platforms never instantiate; **86** shipped boards are built from the module `_io` fallback, with an empty `device` (*2026-10-31*) | 1c |
| 7 | New upstream module-level helpers (`deprecated_pmod_helpers`, `warn_deprecated`, `Pmod*`, Tang docks) undefined after imports are blanked | `litex_parser.py:486-501` | 22-board net loss at head | 1c |
| 8 | Amaranth: no `DDR4Resource`, `DiffPairsN`; base classes imported from sibling files | `amaranth_parser.py:293-345` | RFSoC 4x2, UPduino v2, Versa ECP5-5G, Supercon badge dropped | 1c |
| 9 | Amaranth classifier: `n.startswith("sw")` matches `swd` | `amaranth_parser.py:431` | QuickFeather's 2-pin debug port drawn as a switch | 1c |
| 10 | Digilent parser classifies only by section headings; Avnet's ZedBoard XDC has none | `digilent_parser.py:206,261` | ZedBoard (8 LEDs/8 SW/5 BTN) skipped | 1c |
| 11 | Display names mangled from class/file names (P35) | `amaranth_parser.py` `_prettify_class_name`; `litex_parser.py:467` | override table grows (`board_loader.py:54`) | 1b |
| 12 | `add_extension` is a no-op; upstream extension objects not read | `litex_parser.py:149` | Zybo Z7 0 buttons; Tang dock I/O lost; Red Pitaya no clock | 2 |
| 13 | Default clock read only from class attributes | `litex_parser.py:526-527` | Red Pitaya (`clk125`, set in `__init__`) and Snickerdoodle (`default_clk_freq = 100e6`, applied in `__init__`) keep a 12 MHz default (*Snickerdoodle 2026-10-31*) | 2 |
| 14 | Multi-pin non-RGB resources collapsed into one LED/switch/button | `litex_parser.py:289`; `amaranth_parser.py:436` | 12 shipped boards (Appendix B.4) | 5 |
| 15 | `user_dip_btn` classified as button (an explicit, uncommented entry in the button list since the first LiteX commit `d9c3caa`) | `litex_parser.py:239,312` | 9 shipped / 16 at head (Appendix B.3) | 5 (D-2) |
| 16 | Upstream aliases emitted as separate LEDs; only one alias group becomes a native bank | parsers + `framework_conventions.py:86-166` | 20 shipped / 29 at head draw one pin twice (Appendix B.2) | 6 (D-1) |
| 17 | One board per platform file (default constructor only) | `litex_parser.py:649` | 59 upstream files define selectable versions | 7 (D-4) |
| 18 | Amaranth reads the part only from `device`; its Gowin platforms name it `part` (`TangNano9kPlatform.part = "GW1NR-LV9QN88PC6/I5"`) | `amaranth_parser.py:662` | 5 shipped Gowin boards with an empty `device` (*2026-10-31*) | 1c |
| 19 | `--board` matches class or display name, ignoring the source folder; the first match in load order wins | `board_loader.py:566` | 14 boards unreachable from the command line today, 18 after the bump (§2.6) (*2026-10-31*) | 1a |
| 20 | A board whose default clock frequency the parser cannot read gets an invented one, which the chip draws as if upstream had stated it | `litex_parser.py:641` and `amaranth_parser.py:383` (12 MHz); `digilent_parser.py:864` (100 MHz) | 13 shipped boards; upstream defines a frequency for 11 of them (defects 13, 22, 23), so 2 shipped and 2 new boards truly state none (D-6) (*2026-10-31*) | 2 (D-6) |
| 21 | LiteX classifier treats any name containing "switch" as a user switch | `litex_parser.py:241` | `fairwaves_xtrx` and `limesdr_xtrx` draw `rf_switches` — upstream's control lines for the board's SKY13330/SKY13384 RF-path switches — as a user switch; the only such name at the pin (*2026-10-31*) | 1c |
| 22 | Amaranth default clock ignores on-chip oscillators: it looks only for a `Clock` resource named by `default_clk` | `amaranth_parser.py:375` | 6 boards at 12 MHz whose frequency the board file and Amaranth's vendor platform define: Chameleon96 100 MHz (`cyclonev_oscillator`), both MachXO2 breakouts 2.08 MHz (`OSCH`, `osch_frequency`), QuickFeather 5 MHz (`osc_freq / osc_div`), UPduino v1 48 MHz (`SB_HFOSC`, `hfosc_div = 0`), Tang Nano 24 MHz (`OSC`, `osc_frequency`) (*2026-10-31*) | 1c |
| 23 | Digilent reads a frequency only from `create_clock`, and a clock only under a clock heading | `digilent_parser.py:227`, `:825` | the three Genesys ZU boards have neither, but their comment above `sysclk` says "Sysclk is a 25 MHz PL reference clock"; they ship with no clock, at 100 MHz (*2026-10-31*) | 1c |
| 24 | LiteX sorts all LEDs by their upstream index across resource names, so `user_led` *n* and `rgb_led` *n* interleave | `litex_parser.py:642` | 19 boards draw mono and RGB LEDs alternately (ZCU216: 16 captioned banks for 16 LEDs); `led(i)` is unaffected, because `BoardDef.led_channels` already puts every mono channel before the RGB ones (external review R2, 2026-09-22) | 1c |

### 2.4 Instantiation audit (LiteX)

With the Phase 1c mock fixes applied (Appendix A), platform instantiation succeeds for **245/248**
files at the pin and **251/256** at head. The remainder are not boards (`enclustra_st1`,
`qmtech_daughterboard`, `qmtech_rp2040_daughterboard` — no platform class) plus, at head, the two
Machdyne ML1 carriers (`machdyne_mozart_ml1`, `machdyne_vivaldi_ml1`: `type object 'MachdyneML1'
has no attribute 'revisions'` — class-level access on a stub; their sources contain no LED,
switch or button resources). With only the partial fixes (varargs `Pins`, vendor mocks, a
`toolchain` attribute, helper stubs) and before the permissive platform mock, the failure classes
were: `add_platform_command`
76 (pin) / 78 (head), `toolchain` item assignment 10/15, `add_connector` 5/1, `+=` on a stub 1/1,
`Pins.identifiers` 1/1.

Today's parser at the pin (*2026-10-31*, a re-run of `parse_litex_board`'s own logic with no
credential in the environment): **86** of the 171 shipped LiteX boards are built from the
module-level fallback — every one after an `AttributeError` at instantiation — and only
`qmtech_wukong.py` falls back to a variable other than `_io` (`_io_v2`), although its constructor
defaults to revision 1 (`__init__(self, revision=1, speedgrade=-2, toolchain='vivado')`).

### 2.5 Impact on our VHDL and firmware (measured)

- **Native and generic designs.** `check_vhdl_contract` for all 9 `hdl/native/*.vhd` and all 24
  `hdl/*.vhd` designs × every board, today vs the projected post-fix fleet at heads (Phases 1–2 +
  4, canonical sub-keys carried forward and polarity reconciled as `write_outputs` does): **zero
  outcome changes on any existing board** — same boards matched, same clock/bank names, widths,
  polarity. Every generic design also passes on the 72 new board files the harness produced;
  Wukong revision 1 and the Digilent ZedBoard were not run through the matrix, so Phase 1c's
  regenerated matrix covers them.
- **Pin maps (U53).** The board's `device` feeds the pin map's wrong-board hint (`pinmap.py:576`;
  an empty device counts as a match, `:450`). The hint is only appended to a pin map that already
  fails, so no outcome changes, but its text does: today the DE10-Standard fixture's `.qsf`
  (`tests/fixtures/pinmap/de10_standard/`) draws the hint on 192 boards (*2026-10-31*), and Phase
  1c gives 91 more boards a device. The Phase 1a matrix includes both pin-map fixtures, so its diff
  shows every such change.
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
  `NUM_BUTTONS` 1→4), Tang Console / Mega 138K / Mega 138K Pro (`NUM_BUTTONS` 1→2–4). The clock
  fixes (defects 13, 22, 23) move `CLK_HALF_NS_INIT` on 11 boards, inside today's range. Phase 5/6
  effects: Appendix B.3 / B.2.
- **Course boards.** DE10-Standard (`boards/custom/`) and Basys 3 (`boards/digilent-xdc/`) are
  boards this arc does not change: `custom/` is not synced, and Phase 1c's Digilent fallback may
  only reach ports that no section heading classifies — its Verify requires the 26 existing
  Digilent boards to stay byte-identical. Neither board has aliased pins, so pin maps (U53) are
  unaffected.

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
  and separator-insensitive, and returns the **first** match in load order (source folders
  sorted: `amaranth-boards` < `custom` < `digilent-xdc` < `litex-boards`). The source folder plays
  no part, so a board whose key an earlier source already uses cannot be selected with `--board`
  at all — **14 today** (*2026-10-31*): Digilent `nexys_4_ddr` (class `Nexys4DDRPlatform`, the
  same as Amaranth's), `arty_a7-35`, `arty_a7-100`, `arty_s7-25`, `arty_s7-50`, `arty_z7-20`,
  `cora_z7-07s`, `cora_z7-10`, `genesys_2`; LiteX `alchitry_au`, `alchitry_pt_v2`, `ebaz4205`,
  `logicbone`, `mist`. The projected fleet adds 4: LiteX `icebreaker`, `icebreaker_bitsy`,
  `tinyfpga_bx`, and the orphaned `efinix_t8f81_dev_kit`, behind its own successor. A
  `--benchmark --board` run of a cross-source twin can therefore show the other source's board.
  Display-name overrides are keyed by `class_name` (`board_loader.py:54`, applied at `:502`).
- The loader skips a board file it cannot read without saying so (`board_loader.py:543`), so a
  board that stops loading simply disappears; the Phase 1a matrix makes that visible.
- LiteX `name` and `class_name` derive from the upstream **file** name (`litex_parser.py:467-478`);
  Amaranth `class_name` is the upstream class name.

---

## 3. Decisions (approved 2026-10-31)

All recommendations follow decision 1: be faithful to what upstream's own definition says. **Rick
approved every recommendation below on 2026-10-31.** Each *Alternative* stays as the record of what
was weighed.

**D-1 — Aliased LEDs (Phase 6). Decided: as recommended.** Upstream deliberately aliases (Amaranth iCEBreaker:
`# Semantic aliases` for `led_r`/`led_g`; LiteX Numato Tagus: `# … aliased here also`; OrangeCrab
`user_led` tagged `# rgb_led.r/.g/.b`).
*Recommend:* merge entries **only where upstream maps them to the identical pin**, and accept
**every** upstream name as a native port. The evidence is upstream's own pin assignment, not
hardware knowledge: their definition says `user_led0` and `rgb_led.r` are both pin K4, so drawing
two lamps simulates an output their definition does not contain. Every alias stays usable — more
than today, where only one alias group is a native bank. Colors carried by alias names (`led_r0`
red) move onto the merged LED. A design that declares two aliases of the same LED is a near-miss
naming the shared pin (two drivers on one pin). No shipped board shares a pin between an LED and a
switch or button (*2026-10-31*), so merging LED entries covers the fleet. *Alternative:* leave
aliases as separate LEDs.

**D-2 — DIP switches (Phase 5). Decided: as recommended.** *Recommend:* classify `user_dip_btn` as
**switches**. Upstream's own name contains "dip"; Amaranth defines the same Versa ECP5 parts as
switches; LiteX's own target files never use `user_dip_btn` (*2026-10-31*), so no upstream usage
points the other way. A widget has to be chosen either way, and today's choice is an explicit,
uncommented entry in the parser's button list (`litex_parser.py:239`) from the first LiteX commit.
Cost
to the CPU examples (Appendix B.3): Versa ECP5 and Antmicro SDI-MIPI lose reverse / lamp test /
dice roll (0 real buttons); ECP5 EVN, ECP5 VIP, CertusPro-NX Versa lose the lamp test (1 button).
Native designs are unaffected (`user_dip_btn` keeps its name and width; the bank moves from
`buttons` to `switches`). *Alternative:* read "btn" as upstream's intent and keep buttons.

**D-3 — Multi-pin resources (Phase 5). Decided: as recommended, with two prerequisites.**
*Recommend:* a plain multi-pin input or output resource becomes one component per pin (Trenz
`gpio_leds`, 8 pins → 8 LEDs; Versa `alnum_led`, 15 pins → 15 LEDs); a resource whose sub-signals
are named `r`/`g`/`b` becomes one RGB site regardless of its name; bidirectional or multiplexed
shapes (`rgb_leds_muxed`, `led_cathodes`, `swd`) keep today's representation in the board model but
are listed in the sync ledger as "unsupported shape" (no silent change). *Prerequisites, found on
approval (2026-10-31):* (1) defect 21 is fixed first (Phase 1c), or the split turns the XTRX boards'
misread `rf_switches` into three user switches; (2) a group produced by splitting never displaces
the bank chosen today. `framework_conventions.build_bank` picks the widest indexed group, so
splitting the XTRX boards' 3-pin `user_led2` would replace their `user_led` bank (width 1 on
`fairwaves_xtrx`, 2 on `limesdr_xtrx`) and break a design written to it — measured with the real
builder on `fairwaves_xtrx`. Split groups stay out of bank selection until Phase 6 accepts every
group as a bank, and the Phase 1a matrix's per-bank rows show any bank that changes.
*Alternative:* leave all multi-pin resources collapsed.

**D-4 — Versions (Phase 7). Decided: as recommended.** *Recommend:* emit **one board per
upstream-listed version**, including versions that differ only in FPGA part. The first draft
recommended collapsing those as "indistinguishable in the simulator", but they are not: the chip
draws `device` (`ui/components.py:67`) and the pin map's wrong-board hint compares it
(`pinmap.py:576`). The other sources already ship part variants as separate boards — Amaranth turns
13 upstream files into 29 boards this way (ULX3S 12F/25F/45F/85F, Arty A7-35/-100, OrangeCrab r0.2
25F/85F…), and Digilent ships separate Arty A7-35 and A7-100 files — so collapsing only LiteX's
would treat the sources differently and drop definitions upstream wrote (decision 1). *Scale
(2026-10-31):* a static scan of the LiteX pin by §4.7's rules finds 35 files listing about 48 extra
versions. 58 files take a version-selecting parameter; the rest list a single value or choose in
ways §4.7 does not read (dynamic docks, a free-form `device=`). That is roughly 13% more selector
rows, which the selector's filter and facets absorb. *Alternative:* collapse versions whose LEDs,
switches, buttons, 7-seg and clocks are identical, keeping the default version's part: fewer
near-duplicate selector rows, at the cost of that inconsistency.

**D-5 — Release slot. Decided: v0.26.0, after U39–U41 (v0.24.0) and D16 (v0.25.0).** This
reverses the first recommendation (its own MINOR before the peripherals), for three reasons. The arc
changes nothing on the course boards (§2.5: DE10-Standard and Basys 3 are untouched), while the
peripherals serve the classroom directly, were approved first (2026-08-05) and had already moved
back once, and D16 is the security release. Waiting costs little: Phases 1a–2 run at the recorded
pins, which do not move, and Phase 4 audits whatever upstream heads exist when it runs. And the
queue keeps the order already set, with no renumbering. The two items that cost something today
land early, outside the slot: Phase 1a item 6 (`--board` by source) and the no-scope sync-token
recipe in `CONTRIBUTING.md` (§4.4; the credential-free child stays in 1a). The arc has a **stop
point after Phase 4**, the bump: identity, loud skips, orphans, the parser fixes and the new boards
are then all in place, and Phases 5–7 are refinements that each wait on a visual review. If they
are not ready, run Phase 8 at the stop point, ship, and re-card Phases 5–7 as a follow-up whose
spec is this plan. Either order works technically: the peripherals plan makes no sync-tooling
changes ([u39_peripherals_plan.md](u39_peripherals_plan.md) "no sync-tooling changes").
*Alternatives (not taken):* its own MINOR before the peripherals, renumbering the roadmap in ~8
places (the v0.22.0 precedent); or Phases 1a–1c as maintenance inside the peripherals release.

**D-5 revised (2026-10-31, at the start of execution): next, as v0.24.0, and the whole arc.** Rick:
"U56 should come next, and we need the full arc. We really need to stop executing upstream code,
but we also want a thorough and accurate upstream sync." The first alternative above is now the
decision: U39–U41 → v0.25.0 (their second slip) and D16 → v0.26.0, renumbered in the PR that
records this. What changed: D-7 makes the arc a security fix as well, since the sync tooling
executes third-party code on contributors' machines and in CI on every PR, and the arc answers two
findings of the external review (defect 24; D-1). Phases 5–7 ship in the same release, so Phase 4
is a checkpoint, not a release point. The course boards stay untouched (§2.5).

**D-6 — Boards with no upstream clock (Phases 1c and 2). Decided: read every frequency upstream
defines, then mark the rest as assumed.** 13 shipped boards show a default clock we invented —
12 MHz from `amaranth_parser.py:383` and `litex_parser.py:641`, 100 MHz from
`digilent_parser.py:864` — and the chip draws it as if upstream had stated it. The first draft
counted the 11 with `clocks: []` and proposed marking them all as assumed, but upstream defines a
frequency for 11 of the 13 (*2026-10-31*). Those are parser misreadings, fixed as defects: six
Amaranth boards on on-chip oscillators (defect 22, Phase 1c), the three Genesys ZU boards whose
comment states 25 MHz (defect 23, Phase 1c), and Red Pitaya and Snickerdoodle, whose constructors
set the clock (defect 13, Phase 2). That leaves **four boards with no upstream frequency**:
Digilent `genesys_2` (a differential `sysclk` with no period), LiteX `newae_cw305` (an SMA clock
input), and two that arrive in Phase 1c — the Digilent ZedBoard (`GCLK`, no period) and LiteX
`quicklogic_quickfeather` (no default clock). The simulator still needs a clock for them, so keep
the fallback but record it as assumed: the parsers write `default_clock_assumed: true`, and the
chip marks the number ("100 MHz, assumed"). The fallback values stay as they are — both are
guesses, and changing one would change simulated timing for nothing. *Alternative (not taken):*
mark all 13 as assumed, which would label our own misreadings as assumptions.

**D-7 — Never execute upstream code (decided 2026-10-31, Rick).** "I consider executing upstream
code a potential vulnerability. Let's not do that." The Amaranth and LiteX parsers load every
upstream file with `exec()` against mock classes (`amaranth_parser.py:613`, `litex_parser.py:499`;
the LiteX parser then instantiates `Platform()`, `:533`), and the namespace carries the real `os`,
`subprocess` and builtins (`amaranth_parser.py:340-345`, `litex_parser.py:199-203`). A compromised
upstream file would run as the user, on a contributor's machine and in CI. It buys nothing: at the
2026-10-31 heads, 81 of 83 Amaranth files and 206 of 256 LiteX files are pure data in the code that
runs, where every call is one of our own mock constructors, and no executed path uses `os` or
`subprocess`. The rest call LiteX's extension helpers or need a constructor's default arguments.
**Rule:** no sync, drift check, test, audit or one-off measurement executes, imports or
instantiates an upstream file. Phase 0 replaces `exec()` with a reader that parses each file and
interprets an allowlisted subset of Python (§4.4); a construct outside it is reported, never run.
**Consequences:** the old §4.4 credential rules go, since nothing executes, so `gh`'s own token is
fine for `sync_port_conventions.py`, the one step that needs a token; the source syncs need none at
a pinned commit; §14's sandbox question is moot; Phase 2 reads extension modules; Phase 4 reads
unreviewed heads instead of running them. **Nothing was harmed before the rule:** a static scan of
the code the parsers execute (module and class bodies, LiteX `__init__`, and the calls they make)
found no environment, process, network or obfuscation construct in any upstream revision run since
2026-07-14, when a token could first have been present (`~/.claude/u56-audit/exec_scope_scan.py`;
it catches a planted file in 9 of 9 ways).

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

- **Version-selecting parameters** (Phase 7 enumerates their values; Phase 1a records their
  effective values for the default construction): `variant`, `revision`, `board_version`,
  `version`, `dock`, `expansion`, `baseboard`, `som`, `board`. Not `device`, `toolchain`,
  `speedgrade` (D-4 governs part variants). Effective value = the `inspect.signature(cls.__init__)`
  default when not passed, so the default construction and an explicit `revision=1` are one
  identity. The list may grow — Phase 7 can meet a parameter it lacks, and upstream adds new
  ones — so matching must not depend on it (below).
- **What a sync constructs.** For each upstream file: the default construction, **every identity
  already on disk for that file** (constructed with its recorded `upstream_args`), and from Phase
  7 every enumerated version. The second keeps a file's meaning when upstream changes a default:
  after `revision=1` → `2`, the existing file goes on building revision 1, and the new default
  gets a new file. If the default construction succeeds but a recorded identity's construction
  raises, that identity is `no_longer_defined` (§4.3) with a `version_failed` warning (§4.2):
  upstream no longer accepts that version, which is not a parser error.
- **Matching.** A file and a produced board pair up when `origin`, `upstream_file` and
  `upstream_class` are equal **and every key the file records in `upstream_args` has the same
  effective value in the board**. A key the board has and the file lacks is no obstacle, and is
  written on the rewrite. Pair the most specific files first (most recorded keys), prefer the
  default construction on a tie, and use each file and each board once. Growing the parameter
  list therefore never orphans a file.
- **File-name assignment.** An identity that already has a file keeps it forever. A new identity
  gets `<sanitized upstream file stem>` (Digilent drops the `-Master` every XDC file name ends in,
  so a new ZedBoard is `zedboard.json`; decided 2026-11-01, Rick), plus `_<sanitized class minus "Platform">` when the file
  defines more than one board, plus `_<param>-<value>` for each version parameter whose value is
  not the default. If that name is held by another identity of the same upstream file and class,
  append `_<param>-<value>` for every version parameter instead: the default revision 1 of Wukong
  arrives after the revision-2 identity holds `qmtech_wukong.json`, so it becomes
  `qmtech_wukong_revision-1.json`. Any other clash **fails** the sync, naming both — never a silent
  `_2`. `unique_name` is retired from the write path.
- **`class_name` and display name for a new versioned identity** append the version
  (`QmtechWukongRevision1Platform`, "Qmtech Wukong (revision 1)") so `(class_name, source)` stays
  unique for recents.
- **Backfill and the fallback (Phases 1a–1b).** Existing files get identity fields from a re-sync
  at their recorded pin; today's file ↔ board pairing is exact (277/277), so the first run pairs by
  today's file names. While the module-`_io` fallback exists (until Phase 1c), a file whose
  default construction fails yields just its one fallback board, with the default's effective args
  as its identity; nothing else is constructed for that file. **One exception:**
  `litex-boards/qmtech_wukong.json` holds **revision 2** data — the fallback tries `_io_v2` before
  `_io_v1` (`litex_parser.py:541`) — while LiteX's default is revision 1 (§2.4). A migration entry
  gives that one fallback-built board the identity `{"revision": 2}`, and it stays as long as the
  fallback does: without it, every in-place re-sync in Phases 1a and 1b (the drift job included)
  would compute revision 1, orphan `qmtech_wukong.json` and write its revision-2 content to a new
  file. Phase 1c removes the fallback and the migration together. From then on the sync builds
  `revision=2` from the on-disk identity, and the default (revision 1: LEDs J6/H6, clock M22,
  button H7) arrives as a new board.

### 4.2 The sync ledger (loud skips)

Every upstream file yields exactly one **outcome** and any number of **warnings**, printed by the
sync and written (sorted) into `_sync_metadata.json`:

| Outcome | Meaning | Sync exit |
|---|---|---|
| `boards: [<file names>]` | produced one or more boards | 0 |
| `skipped: not_a_board` | no platform class / no resources section | 0 |
| `skipped: no_simulatable_io` | clean exec + instantiate, zero LED/switch/button | 0 (a file that used to produce a board: §4.3) |
| `error: <ExceptionType>: <normalized detail>` | our parser failed | **non-zero** from Phase 1c unless accepted (reported only in 1a–1b, where errors are today's baseline) |

| Warning | Meaning | Phases |
|---|---|---|
| `io_fallback: <variable>` | built from a module-level list, not an instance | 1a–1b (gone in 1c) |
| `version_failed: <args>: <ExceptionType>` | a recorded identity no longer constructs | from 1c |
| `unsupported_shape: <resource>` | a resource kept as today but flagged (D-3) | from 5 |
| `alias_overlap: <pins>` | an overlap shape the alias merge does not handle | from 6 |

- **Normalize details** to stay byte-stable across Python versions (CI's drift job runs Python 3.12,
  #449; local runs may be 3.13): for `NameError` record only the missing name, for `AttributeError`
  only the attribute name, otherwise only the exception type. Never the full message.
- Because `_sync_metadata.json` is committed, the existing drift check (zero `git diff` after an
  in-place re-sync) automatically fails on any change in the ledger, and every PR shows ledger
  changes in its diff.
- Parsers stop returning `[]` on exceptions: they return a structured outcome (add a
  `ParseOutcome` dataclass — boards, outcome, detail, warnings — in `sync_common.py`; keep thin
  compatibility wrappers only if a test needs them, otherwise update the tests).
- The module-`_io` fallback (`litex_parser.py:538-545`) is recorded as an `io_fallback` warning
  in 1a and 1b (content must not change there; expect **86** at the LiteX pin, §2.4) and removed
  in 1c (instantiation failure → `error`).
- **Accept-list.** Decision 2 says a genuinely broken upstream file is upstream's to fix while we
  wait; a fatal `error` would then block every bump of that source until upstream acts. So a
  committed accept-list, `scripts/board_sync_accepted.toml` (with a JSON schema beside it,
  validated in tests like the registries, #346), records what a person has looked at: per entry
  the source, the upstream file (and the identity, for an orphan), the expected outcome, a reason,
  and the upstream issue URL when there is one. An accepted `error` leaves that file's existing
  boards on disk untouched and unmarked — upstream still has them; we cannot read the current
  version — and the ledger shows the acceptance. An acceptance that no longer matches anything
  fails the sync, so the list cannot rot.

### 4.3 Orphans

After generating, for each existing file whose identity was **not** produced:

| Situation | Action |
|---|---|
| its `upstream_file` had an `error` outcome | **sync fails**: "would orphan X because our parser failed on Y"; files untouched. If that error is accepted (§4.2): files untouched and unmarked |
| `upstream_file` absent from the archive | mark orphaned, reason `file_removed` |
| file parsed cleanly but no longer defines this identity | mark orphaned, reason `no_longer_defined` — **only if accepted**, otherwise the sync fails naming it: a renamed class is upstream's doing, our class selection picking a different class is a misreading, and only a person can tell which |
| file parsed cleanly with zero simulatable I/O | mark orphaned, reason `no_simulatable_io` — **only if accepted**, otherwise the sync fails naming it: a board that loses all its I/O is what a parser misreading looks like (class A, §1) |

- **Mark** = add to `source`: `upstream_status: "orphaned"`, `orphaned_at_commit: <commit being
  synced>`, `orphaned_reason`, optional `successor: "<source>/<file>.json"`. Everything else in
  the file stays frozen, including `sync_commit` (the last good sync).
- **Stable:** a re-sync at the same pin re-derives the same mark (keep `orphaned_at_commit` from the
  existing file if already set), so the drift check stays byte-identical.
- **Successor** (a hint, never an automatic migration): among identities *new in this run*, the
  unique one whose normalized content (`leds`, `switches`, `buttons`, `seven_seg`, `clocks`,
  `device`) equals the orphan's. Among several identical ones, the one from the orphan's own
  `upstream_file` breaks the tie; otherwise none is named. *Amended 2026-11-01 (Rick: "we should
  be fairly confident about the possible successor or it may cause confusion"):* a new identity
  from the same file used to qualify on that alone. With other I/O it is another version, and
  naming it would send someone to a different board. The 5 Efinix renames match on identical
  content (verified at the 2026-11-01 heads, each from a renamed file).
- **Un-orphan:** when an orphaned identity is produced again, the sync overwrites the file and the
  mark disappears.
- `_sync_metadata.json` gains an `orphans` list.
- Orphans keep working everywhere: the loader reads them, native designs match their frozen
  conventions, recents (keyed by `class_name` + source) still resolve, and `--board` reaches them
  by their qualified name (an unqualified name can be shadowed by the successor's — the Efinix T8
  case, §2.6).

### 4.4 Reading upstream files without executing them (D-7)

- **Parse, then interpret an allowlist.** `scripts/upstream_reader.py` parses each upstream file
  with `ast.parse` and walks it with a small interpreter that implements only the Python the board
  files use: literals; names; arithmetic and `+`/`*` on lists and strings; starred unpacking;
  subscripts and slices; comprehensions; f-strings; `if`, `for` and `while` under a step budget;
  assignment, augmented assignment and tuple unpacking; `def` and `lambda`, interpreted when
  called and never compiled; class definitions with in-file inheritance; keyword, default and
  `*args`/`**kwargs` arguments; and `raise`, which fails the file as `exec` would have.
- **The only native calls are ours.** The interpreter calls into Python only for our mock
  constructors and mock platform methods (today's `_make_namespace` / `_make_litex_namespace`
  vocabulary) and attributes of our own mock objects; a fixed set of pure builtins (`range`,
  `enumerate`, `zip`, `len`, `str`, `int`, `float`, `bool`, `list`, `tuple`, `dict`, `set`,
  `sorted`, `reversed`, `min`, `max`, `abs`, `round`, `sum`, `any`, `all`, `isinstance`, `chr`,
  `ord`); and allowlisted methods of `str`, `list` and `dict`. Upstream functions and classes are
  data the interpreter walks, never Python callables. A dunder attribute, a name nothing defines,
  `str.format` with an attribute or index field (it reads attributes without a call), and any
  construct outside the list raise `UnsupportedConstructError` with file, line and construct. Budgets
  cap steps, list length and string length.
- **Classes stay classes.** A class definition becomes a real Python class built with `type()`: its
  bases are our mock classes or other classes from the same file, its attributes are the evaluated
  class-body values, and each method is an interpreter-backed descriptor. The parsers' extraction
  (`__mro__`, `getattr`, `Platform()`) keeps working unchanged, and a method body still runs only
  inside the interpreter.
- **Equivalence first.** Phase 0 reproduces today's output byte for byte at the pins, defects
  included: a name the mocks lack fails as `exec` failed, and LiteX's instantiation fallback is
  reproduced. Each later fix is then its own visible diff. The reference is the committed JSON, so
  proving it executes nothing.
- **Imports.** Phase 0 keeps today's behavior: import lines are not resolved. From Phase 1c, for
  every `Import`/`ImportFrom` (module level and inside functions), a module inside the same
  upstream archive (`litex_boards.*`, Amaranth relative imports such as `from .upduino_v1 import …`)
  is **read** with the same interpreter, recursively and cycle-guarded, and the name is bound; any
  other module binds a permissive stub. Phase 1c reads Amaranth's sibling modules and stubs
  `litex_boards.extensions.*`; Phase 2 reads those too. Star imports
  (`from litex.build.generic_platform import *`) are what our mocks cover. A `NameError` for a name
  imported nowhere is a genuine gap → ledger `error`.
- **Permissive stub:** callable; any attribute (instance **and class level**, so
  `MachdyneML1.revisions` works); `__getitem__`/`__setitem__`; `__iadd__`; iterates as empty. It is
  our object, so the interpreter may call it.
- **Mock platform:** keep explicit `add_resources` / `add_extension` / `request`; add
  `toolchain = <stub>` and a `__getattr__` returning a no-op callable for every other platform method
  (`add_platform_command`, `add_connector`, `add_period_constraint`, `lookup_request`, …).
- **Known growth (measured 2026-11-01).** The code that runs today needs nothing beyond the list.
  At the pins, the 2026-10-28 heads and today's heads the reader refused nothing, and at the
  2026-10-28 heads its output equals the old `exec` path's on every board (149 LiteX, 82 Amaranth),
  so every skip there is a mock gap the later phases close. They also reach further. **Phase 1c:**
  one LiteX platform calls `copy.deepcopy`, so the few standard-library calls board code makes need
  safe stand-ins: a permissive stub would hand back the wrong data rather than fail. **Phase 2:**
  LiteX's extension modules use a generator (`_pmod_indexes`, `extensions/pmod.py`) and
  `type(self).__name__` (the deprecated `io`/`connectors` accessors, `extensions/qmtech.py:109,115`),
  so add eager generators and a one-argument `type()` with a read-only `__name__`, or call the
  non-deprecated API. Amaranth's programmer methods use `with` (68) and `.encode` (5), but the
  parsers never call them. Grow the reader on this kind of evidence, in the phase that first needs
  a construct, never ahead of it.
- **Tokens.** Only `sync_port_conventions.py` needs one: it resolves a path-scoped pin per cited
  file, far past the 60 requests an hour the API allows without a token. It reads text and runs
  only our code, so `GITHUB_TOKEN="$(gh auth token)"` is fine. The source syncs make one API call
  each and work without a token at a pinned commit; Phase 4 resolves heads with `git ls-remote`.

### 4.5 Schema

`boards/schema/board.schema.json` has `additionalProperties: false` at the top level and in
`$defs/source`, and `write_outputs` validates before writing (`sync_common.py:293-296`). Every new
field lands in the schema first, in the same PR (the #346 rule): Phase 1a (`upstream_class`,
`upstream_args`, `upstream_status` enum `["orphaned"]`, `orphaned_at_commit`, `orphaned_reason` enum
`["file_removed", "no_longer_defined", "no_simulatable_io"]`, `successor`); Phase 2
(`default_clock_assumed`, D-6); Phase 3 (`orphaned_at_date`); Phase 6 (`leds[].aliases`, convention alias banks). The
accept-list gets a schema of its own (§4.2). Update `tests/test_board_schema.py`.

### 4.6 Alias model (Phase 6, D-1)

- **Board model:** merge LED entries that upstream maps to the identical pin(s): mono+mono on one
  pin → one mono entry; a mono entry whose single pin equals one channel of a 3-pin `rgb_led` → that
  channel of the RGB site. Never merge across different pins; any other overlap shape → keep
  separate + an `alias_overlap` warning. The merged entry keeps the first-declared upstream entry as
  primary and lists the rest in a new `aliases: [{name, number, channel?}]`. Color: from an alias
  name via `led_metadata.color_from_name` unless the cited registry sets one.
- **Conventions:** `framework_conventions.build_convention` currently keeps one primary LED group
  (`framework_conventions.py:99`). Emit every alias group — and every group Phase 5 split from a
  multi-pin resource, which Phase 5 keeps out of bank selection (D-3) — as an accepted bank, each
  carrying its boundary-channel map. `ConventionMatch` (`conventions.py:105`) gains a general list of matched
  LED banks with channel maps (the fixed `leds` / `leds_green` / `leds_rgb` slots stay for existing
  conventions).
- **Matcher:** a design may declare any subset of banks; two declared banks that reach the same
  channel → near-miss naming the shared pin.
- **Wrapper:** generalize the per-site RGB packing in `wrapper.py` (`leds_rgb`, around lines
  171-218) into an explicit per-bit channel map.
- **Pin maps:** `pinmap.py:112-145` indexes physical entries; aliases resolve to the same channel.

### 4.7 Versions (Phase 7, D-4)

Detect versions only where upstream's own code lists them: in `__init__`, a subscript whose index
is a version-selecting parameter and whose value is a dict literal or a module-level name bound to
a dict literal (Wukong `{1: _io_v1, 2: _io_v2}[revision]`; Tang `docks[dock]`; Zybo
`{"z7-10": …, "z7-20": …, "original": …}[variant]`); plus `if param == "<literal>"` comparisons
(ZTEX `expansion == "debug"` / `"sbus"`). Construct each version through the identity machinery
(§4.1); the default version keeps the existing file. D-4 is decided: every version is emitted,
including versions that differ only in FPGA part.

### 4.8 Orphans in the UI (Phase 3)

- Selector row tag "orphaned upstream".
- Preview info line, by reason: `file_removed` — "No longer in \<source\> since \<date\> (\<short
  commit\>)."; `no_longer_defined` — "\<source\> no longer defines this version since \<date\>
  (\<short commit\>)."; `no_simulatable_io` — "\<source\> lists no LED, switch or button for this
  board since \<date\> (\<short commit\>)." Each continues: "Your design still runs on this saved
  copy; it will not receive upstream fixes." With a successor, two aligned rows follow, so the
  names can be compared: "This board: \<source\>/\<file\>" and "Successor: \<source\>/\<file\>
  (same FPGA, clocks and I/O)". Both use the file spelling, because display names repeat across
  sources (*amended 2026-11-01*: Rick asked for the loaded board's file beside the successor's).
- `--board` resolution prints the same note to stderr.
- Session log field `board_upstream_status` (+ `board_successor`).
- Never blocks a run.
- Register new UI elements with inspect mode (`ui/inspect.py`) and regenerate `docs/ui_map.md`
  (`scripts/gen_ui_map.py`; `tests/test_ui_map.py` enforces it).

---

## 5. PR 0 — Plan, card, ID claim

**Do:** commit this file; the roadmap card U56 (Part 1 / Tier 2); ID allocation → next free U57;
plan-index rows in `docs/improvement_roadmap.md` and `docs/README.md`; Icebox P35 note
("absorbed into U56 Phase 1b"); Icebox P15 note (follow-up for twins); an ordered entry in
*Current focus* per D-5 (queue item 5 → v0.26.0). Record D-1…D-6 outcomes in this file's header.
**Done 2026-10-31** in #465, which carries the approval.
**Verify:** `uv run rumdl check docs/`; `uv run pytest tests/test_docs_*.py`.
**Quality gates:** documentation only.

## 5a. Phase 0 — Stop executing upstream code (D-7)

**Do:**

1. `scripts/upstream_reader.py`: the reader of §4.4, standalone (no `fpga_sim` import), with
   `UnsupportedConstructError`.
2. `amaranth_parser.load_board_from_source` and the LiteX parser read through it instead of
   `exec(compile(…))` (`amaranth_parser.py:613`, `litex_parser.py:499`), and LiteX's
   `platform_class()` (`:533`) runs the interpreted constructor. Delete the real `os`,
   `subprocess`, `unittest` and `__builtins__` entries from both namespaces; the mock vocabulary
   stays, as the reader's allowlist. The seven Amaranth files that declare
   `class TestCase(unittest.TestCase)` need a stub base, not the module.
3. A file the reader cannot evaluate prints one line naming file, line and construct (loud from
   here on, until Phase 1a's ledger records it) and yields what `exec` yielded: a file `exec`
   dropped is still dropped, and a LiteX board built from the module-level fallback prints a
   warning.
4. A guard test, an AST rule in the style of `tests/test_no_input_polling.py`: nothing under
   `scripts/` calls `exec`, `eval`, `compile`, `__import__` or `importlib`. Unit tests for the
   reader: the allowlist, refused dunders, refused `str.format` fields, budgets, an unsupported
   construct's message, and planted upstream files that read the environment, run a command or open
   a connection, which are refused and never run.
5. Docs: `CONTRIBUTING.md` ("Syncs that run upstream code" becomes "the syncs read upstream files
   and never execute them"; the drift check runs locally again, with
   `GITHUB_TOKEN="$(gh auth token)"` for its port-convention step, and the release pre-flight runs
   it again); `CLAUDE.md` (the parser rows and the "Amaranth Parser Mock Namespace" section);
   `docs/architecture.md` (the sync pipeline).

**Verify:**

- In place at the recorded pins, `sync_amaranth_boards.py --ref <pin>` and
  `sync_litex_boards.py --ref <pin>` leave `git status boards/` empty: byte-identical to what
  `exec` produced, with nothing executed to get there. Run it twice.
- The files the reader reports are exactly the files whose `exec` failed, each with its construct:
  the 53 LiteX and 4 Amaranth errors in §6's Verify list. The 86 fallback-built LiteX boards print
  their warning.
- `check_board_drift.py` green locally and in CI; the guard and reader tests; full `pytest`;
  `ruff check`, `ruff format --check`, `mypy` at CI scope.

**Visual review:** no — board content does not change. **Effort:** M/L.

## 6. Phase 1a — Identity, ledger, orphan detection, `--board`, impact matrix (no board content change)

**Do:**

1. Schema fields of §4.5 (Phase 1a set) and the accept-list's schema; `tests/test_board_schema.py`.
2. Parsers return `ParseOutcome` (§4.2: an outcome plus warnings) and the identity fields (§4.1);
   the LiteX parser records `upstream_class` and effective `upstream_args` (the constructor's
   defaults, which the reader evaluates, §4.4); keep the module-`_io` fallback, reported as an `io_fallback` warning.
3. Restructure the write path (`sync_common.write_outputs`, `:268`): index existing files by
   identity; construct and match per §4.1; assign file names per §4.1; detect orphans and apply
   the accept-list per §4.2–4.3; write the ledger and `orphans` into `_sync_metadata.json`.
   Preserve `_fold_forward_unmanaged_keys` (`:160` — U39 relies on it for `peripherals`),
   `_carry_forward_sync_stamp` (`:240`), framework polarity reconciliation (`:223`), LED color
   stamping and schema validation.
4. The Wukong migration entry (§4.1), kept until Phase 1c.
5. ~~Credentials~~ — dropped by D-7: nothing executes upstream code (Phase 0), so there is nothing
   to shield, and the no-scope token recipe was withdrawn before it was needed.
6. **`--board` by source** (defect 19). `find_board` accepts `<source>/<stem>` (e.g.
   `litex-boards/icebreaker`; `.json` optional) and resolves it exactly; the loader records each
   board's file stem (runtime only, not serialized — keep `tests/test_serialization.py` green). An
   unqualified `--board` keeps today's first-match answer, but when other boards share its key it
   names their qualified spellings on stderr. Tests: every board on disk resolves by its qualified
   name; a snapshot of unqualified collisions, so a new one shows up in review. Docs:
   `docs/user_guide.md` (the `--board` row) and `CONTRIBUTING.md` ("Smoke-testing a board"). The
   bug predates this arc, so this item **lands early, on its own** (D-5); Phase 1a only re-checks it.
   **Done 2026-10-31 in [#466](https://github.com/Machai-Kydoimos/fpga-board-sim/pull/466).**
7. **The impact matrix, committed.** `scripts/gen_board_design_matrix.py` writes
   `tests/fixtures/board_design_matrix.json`: for every design in `hdl/native/*.vhd`, `hdl/*.vhd`
   and `tests/fixtures/pinmap/*/*.vhd` × every board on disk, `check_vhdl_contract`'s verdict and,
   when it passes, the `ConventionMatch` minus `board_name`; whether the pin map's wrong-board hint
   fired; and `build_generics` per board (Appendix B.8). **Plus one row per native bank** (moved
   here from Phase 6 on 2026-10-31): for every board, every convention block and every LED,
   switch and button bank in it, a synthesized minimal design (its clock + that bank, reusing the
   helpers in `tests/test_native_convention.py` such as `_synth_board` at `:535`) and whether
   `match_convention` matches it, with widths and polarity. The in-repo designs target few boards;
   these rows freeze every native match a design could make today, so a phase that changes any
   bank shows it (D-3's split would otherwise slip through: no in-repo design targets the XTRX
   boards). Keep it compact — for example, per design the boards it runs on, with an "all except"
   form for the generic designs.
   `tests/test_board_design_matrix.py` fails when the file and the product disagree, as
   `tests/test_ui_map.py` does. Every later phase that changes board data or matching regenerates
   it, and **its diff is that phase's impact evidence** (it replaces rebuilding Appendix A.3). It
   also shows a board the loader stops reading. Measured 2026-10-31: 35 designs × 285 boards =
   9,975 checks in about 12 s.
8. Loader: `BoardDef` gains `upstream_status`, `orphaned_at_commit`, `successor` read from `source`
   (no UI yet); `tests/test_serialization.py` round-trip.
9. Docs: `docs/architecture.md` (sync section: identity, ledger, accept-list, orphans), `CLAUDE.md`
   rows for `sync_common.py`, the parsers and the matrix script, `CONTRIBUTING.md` (it describes
   syncing and `--board`).

**Verify:**

- Re-sync each source **in place at its recorded pin** (`uv run python
  scripts/sync_<source>.py --ref <source_commit>` — never a fresh directory, the A1 trap; no token
  needed, §4.4).
- `git diff boards/` shows **only**: the new `source` identity fields; on every synced file, a fresh
  `sync_commit` (the pin) and `sync_timestamp` — adding fields is a content change, so
  `_carry_forward_sync_stamp` re-stamps every file; and the `_sync_metadata.json` ledger. Zero
  orphans, zero new boards, zero changed LEDs/switches/buttons/clocks/conventions; the impact
  matrix generated before and after the re-sync is identical.
- **Re-sync in place a second time: byte-identical.** The drift job does exactly this on the PR,
  and it is the check that catches a self-orphaning identity such as Wukong's.
- Ledger lists exactly today's skips: LiteX 77 of 248 platform files (24 `not_a_board` or
  `no_simulatable_io` + 53 errors in the classes of §2.3/§2.4), plus **86** `io_fallback`
  warnings, one of them `_io_v2` (Wukong); Amaranth 10 (`not_a_board` for the five whose class
  declares `resources = []` — `microzed_z010`, `microzed_z020`, `tinyfpga_ax1`, `tinyfpga_ax2`,
  `zturn_lite_z007s` — and `no_simulatable_io` for `sk_xc6slx9`, whose three resources are none we
  simulate (measured 2026-11-01);
  `supercon19badge` `DiffPairsN`, `upduino_v2` `UpduinoV1Platform`, `versa_ecp5_5g`
  `VersaECP5Platform`, `zturn_lite_z010` `ZTurnLiteZ007SPlatform` → errors); Digilent 1
  (`Zedboard-Master.xdc`, no simulatable I/O). In 1a and 1b, `error` outcomes are reported but do
  not fail the sync: they are today's baseline, recorded in the committed ledger and so guarded by
  the drift check. Phase 1c removes them and makes `error` fatal.
- Unit tests: identity assignment (a clash → failure; the same-file suffix rule), matching (a key
  added later still matches; most specific first), constructing on-disk identities (a changed
  upstream default keeps the old file's meaning; a version upstream dropped → `no_longer_defined`,
  which needs an acceptance), every orphan situation of §4.3 including the accept-list paths and a
  stale acceptance (synthetic archives), successor matching, ledger normalization, un-orphaning,
  re-sync stability.
- `--board`: every board resolves by `<source>/<stem>`; `--board "Nexys 4 DDR"` still opens the
  Amaranth board, as today, and names `digilent-xdc/nexys_4_ddr` on stderr.
- `uv run python scripts/check_board_drift.py` green; full `pytest`.

**Quality gates:** board content byte-identical apart from the new fields and stamps; `ruff check`,
`ruff format --check`, `mypy` (CI scope: `UV_PROJECT_ENVIRONMENT=/tmp/venv312 uv run --python 3.12
--group dev mypy .`); `set -o pipefail` on any piped test gate.

**Effort:** M/L (item 6 may land separately).

## 7. Phase 1b — Display names from the parsers (absorbs P35)

**Do:** fix `_prettify_class_name` (`amaranth_parser.py:584`) and the LiteX file-name prettifier
(`litex_parser.py:467`) per the P35 card (`DE1SoC` → "DE1-SoC", no dangling hyphens; keep the vendor
spellings `Genesys ZU-3EG-D` / `-5EV-D`). Re-sync in place at the pins. Delete every override in
`board_loader._DISPLAY_NAME_OVERRIDES` that the parsers now emit on their own
(`test_every_override_actually_changes_the_name` names them). This runs **before** the parser
fixes, so the boards Phase 1c adds arrive with corrected names and no override is written only to
be deleted.
**Verify:** `git diff boards/` changes only `name` fields — **no file renames** (Phase 1a's frozen
identity is what makes P35 safe now); a before → after name table in the PR;
`tests/test_board_display_names.py` (including
`test_a_renamed_board_still_answers_to_its_old_name`); the Phase 1a collision snapshot gains no
entry (a corrected name can collide with another source's); the impact matrix is unchanged; drift
check; full `pytest`.
**Effort:** S.

## 8. Phase 1c — Fix the parsers' misreadings (at the current pins)

**Do:** items 3–10, 18 and 21–24 of §2.3, using the §4.4 reader:

- `_Pins.__init__(self, *identifiers, dir="io", conn=None, assert_width=None)`; names = each string
  split on whitespace; set `self.identifiers`.
- `_PLATFORM_VENDORS`: `LatticeiCE40Platform`, `LatticePlatform` (Lattice), `MicrosemiPlatform`,
  `AnlogicPlatform`, `QuickLogicPlatform`; drop the misspelled key; add a regression test.
- Permissive mock platform and stub (§4.4), import-aware reading (LiteX: stub
  `litex_boards.extensions.*` for now; Amaranth: read sibling modules with the reader), and safe
  stand-ins for the standard-library calls board code makes (`copy.deepcopy`; §4.4, Known growth). Remove the module-`_io`
  fallback **and the Wukong migration entry** together; from here on the sync builds `revision=2`
  from the on-disk identity (§4.1).
- Amaranth: `DDR4Resource` → `_stub_single`; `DiffPairsN` → `_DiffPairs`; `_classify` (`:431`):
  match `sw`/`switch` as a whole token (e.g. `^(sw|switch)(_|\d|$)`), with a `swd` test; read the
  part from `part` when a class has no `device` (its Gowin platforms; `:662`), with a
  `GowinPlatform` fixture test.
- LiteX `_classify_resource` (`:241`, defect 21): match `sw`/`switch` only as the leading token,
  optionally after `user_` or `dip_` (e.g. `^(user_)?(dip_)?(sw|switch|switches)(_|\d|$)`), as the
  Amaranth fix above does; an `rf_switches` test. Re-run the classifier over every resource name at
  the pin and at head: `rf_switches` must be the only name that changes class.
- Amaranth default clock (`_find_default_clock_hz`, `:375`, defect 22): when `default_clk` names no
  `Clock` resource, apply the vendor platform's own rule, as Amaranth's `default_clk_constraint`
  states it: `OSCH` → `osch_frequency` MHz; `OSCG` → 310 / `oscg_div` MHz; `OSCA` → 450 / `osca_div`
  MHz; `SB_HFOSC` → 48 / 2^`hfosc_div` MHz; `SB_LFOSC` → 10 kHz; `cyclonev_oscillator` → 100 MHz;
  QuickLogic `sys_clk0` → `osc_freq / osc_div`; Gowin `OSC` → `osc_frequency`. An on-chip oscillator
  has no pin, so `clocks` stays as it is. A `default_clk` matching neither a resource nor a rule
  keeps the fallback, which D-6 marks in Phase 2. A fixture test per rule.
- Digilent (defect 23): when a file has no `create_clock`, a `<number> MHz` in the comment block
  directly above a port, in a sentence naming that port (`# Sysclk is a 25 MHz PL reference clock …`
  above `sysclk`), makes that port the board's clock at that frequency, even outside a clock-headed
  section. A fixture test in the Genesys ZU shape.
- Digilent: when no section heading classifies a port, fall back to port-name patterns
  `^LD\d+$` (LED), `^SW\d+$` (switch), `^BTN[CDLRU]$` (button), alongside the existing
  `_RE_LED_WORD` / channel patterns (`digilent_parser.py:206-213`). ZedBoard's clock `GCLK` (Y9) has
  no `create_clock` period in the file. Today's no-period behavior is itself a fallback, not
  upstream data — `default_clock_hz: 100e6` with `clocks: []` (`digilent_parser.py:864`), which the
  chip shows as "100 MHz". Keep it here; D-6 (Phase 2) decides how such boards are shown. Record
  what the ZedBoard JSON contains.
- LiteX LED order (defect 24, `:642`): stable-partition today's sorted list into mono LEDs, then
  3-pin `rgb_led` sites — the partition `BoardDef.led_channels` already applies to channels — so
  the display shows upstream's blocks and no `led(i)` moves. Order within the mono group must not
  change, because a reorder there *does* move `led(i)`: LimeSDR Mini V2's alternating green and red
  LEDs are real bi-color hardware, and the 1-pin and 4-pin "RGB" resources (`colorlight_i9plus`,
  `sipeed_tang_nano_20k`, `modretro_chromatic`) are mono by the loader's rule and stay put.
- New boards take stem-based file names (§4.1), e.g. Digilent `zedboard.json` (from
  `Zedboard-Master.xdc`), Amaranth `versa_ecp5_5g.json`,
  `supercon19badge.json`, `upduino_v2.json`.
- Phase 1b already fixed the prettifiers; add a display-name override only for a new name that
  `tests/test_board_display_names.py` still flags.

**Verify (in place at recorded pins):**

- LiteX 171 → **223**: the 51 boards of Appendix B.1 plus `qmtech_wukong_revision-1.json`
  (2L/0S/1B; LEDs J6/H6, clock M22, button H7). The audit harness counted 222 because it rebuilt
  Wukong in place instead of keeping the revision-2 file. **86** existing LiteX boards gain a
  `device` (`""` → part number): **83** change nothing else (*2026-10-31*);
  `litex-boards/fairwaves_xtrx.json` and `litex-boards/limesdr_xtrx.json` also lose the
  `rf_switches` switch (defect 21 — no convention advertised it, and `NUM_SWITCHES` stays at its
  floor of 1); and `qmtech_wukong.json` (revision 2 identity) is now built from the instance — diff
  it against the committed file and review, expecting equal or additions only. No other existing
  LiteX board changes LEDs/switches/buttons/clocks/conventions, except the order of `leds` on the 19
  boards of defect 24: mono first, then RGB, with the same sites and an unchanged channel layout
  (some of them also gain a `device`; re-count the overlap when the phase runs).
- Amaranth 80 → **83** (Appendix B.1). The 5 Gowin boards gain a `device` from `part`; the six
  boards of defect 22 change `default_clock_hz` (Chameleon96 100 MHz, both MachXO2 breakouts
  2.08 MHz, QuickFeather 5 MHz, UPduino v1 48 MHz, Tang Nano 24 MHz — Tang Nano is in both sets);
  nothing else changes. Digilent 26 → **27** (ZedBoard: measure and record its LED/switch/button
  counts, conventions and clock). The three Genesys ZU boards (defect 23) gain `sysclk` at 25 MHz,
  the matching `default_clock_hz` and a `clk` in their convention, and nothing else; the other
  **23 existing Digilent boards are byte-identical**. `CLK_HALF_NS_INIT` moves on the nine boards
  of defects 22–23, inside today's range (Appendix B.8).
- Ledger: LiteX errors = 0 and no `io_fallback` warnings; the remaining skips are `not_a_board` (3)
  and `no_simulatable_io` (23 by subtraction: 248 files − 222 that produce boards − 3).
- The regenerated impact matrix: zero outcome changes on existing boards; rows for the new boards,
  including Wukong revision 1 and the ZedBoard, which the 2026-10-28 audit never ran; wrong-board
  hint changes only on boards that gained a `device`; per-bank rows change only where the Genesys
  ZU boards gained a clock.
- `tests/test_litex_parser.py`, `tests/test_digilent_parser.py`, `tests/test_sync_amaranth_boards.py`
  gain a test per fix (each with a minimal upstream-shaped fixture); `tests/test_docs_board_counts.py`
  → update the documented counts it names; drift check green; full `pytest`.
- **Contact sheet → Rick's visual review before merge.** Copy the new and changed board JSONs into
  a scratch `<dir>/<source>/` tree and run
  `uv run generate-board-images --boards-dir <dir> --formats png --output-dir <out>` — the
  product's own renderer, one command for any number of boards. The chip now prints a part number
  on 91 boards (`ui/components.py:67`; the longest, `GW5AST-LV138PG484AC1/I0` on the Tang Mega
  138K, fits at 1024×700, checked 2026-10-31), a different clock on nine (defects 22–23), the
  LED order of 19 boards (defect 24), and 56 board files are new.

**Quality gates:** as 1a. New boards inherit framework conventions automatically; run
`uv run python scripts/sync_port_conventions.py --check` and `uv run python scripts/sync_led_colors.py --check`.

**Effort:** M.

**Measured when Phase 1c ran (2026-11-01).** Every number above held, with five differences.

- **Seven Amaranth clocks change, not six:** UPduino v3 inherits v1's `SB_HFOSC`.
- **LiteX's switch rule is narrower than the example regex above.** It keeps today's rule and
  anchors only `"switch"` to the leading word. The example would also have made `sw1`, `sw2_pd`,
  `sw_en` and `sw_sel` user switches, and `rf_switches` is the one name that may change class.
- **Imports and stand-ins.** Names that a file imports from modules we do not model bind inert
  stand-ins. A name used after an unmocked `from migen import *` gets a stand-in on a re-read.
  `copy` and `math` keep their real, pure functions.
- **Versioned identities** carry the version in `class_name` and display name
  (`QmtechWukongRevision1Platform`, "Qmtech Wukong (revision 1)"). A paired board keeps the
  names its file holds, and the sync fails if two live boards in a source would share a
  `class_name`.
- **The ZedBoard** has 8 LEDs, 8 switches and 5 buttons, and keeps the no-period 100 MHz
  fallback with `clocks: []`. D-6 marks it as assumed in Phase 2.

The matrix shows no contract outcome change on any existing board. On all 19 reordered boards,
every `led(k)` drives the same LED and color.

**Rick's visual review found one defect,** in the renderer rather than the data: 19 of the part
numbers were wider than the chip at the default 1024×700 window and ran past its edges.
`FPGAChip.fit_label` now breaks such a line at a dash, slash or space. It shrinks the font only
where no break fits (three boards, by 1 px), and clips only in a window too small for either.
The SVG export lays the label out the same way. Boards whose label already fit are drawn as
before.

## 9. Phase 2 — Extensions, docks, default clock from the instance (and D-6)

**Do:**

- Resolve `litex_boards.extensions.*` imports by reading the upstream modules with the reader
  (§4.4): their `Pmod*` and dock classes become interpreted classes, so `add_extension(ext)` gets
  data and no upstream code runs. Teach the reader what those modules need first: eager generators
  and a read-only one-argument `type()`/`__name__` (§4.4, Known growth).
- Mock `add_extension(ext)`: list/tuple → extend `_captured_io`; object → `ext.define_io(self)` if it
  returns a list (dynamic docks such as `TangMegaNeoDock`), else `ext.io`.
- After construction, read `default_clk_name` / `default_clk_period` from the instance, falling back
  to class attributes (`litex_parser.py:526-527`).
- List every LED/switch/button that arrives via an extension in the PR description for review.
- D-6: the three parsers write `default_clock_assumed: true` whenever upstream states no
  frequency — after defects 13, 22 and 23, four boards (§3) — schema first (§4.5); the loader reads
  it, and the chip marks the number (`ui/components.py`, e.g. "100 MHz, assumed").

**Verify (in place at recorded pins):**

- LiteX 223 → **226**: new `sipeed_tang_primer_20k` 7L/0S/5B, `sipeed_tang_primer_25k` 2L/0S/2B,
  `ztex213` 30L/0S/0B (LiteX's default `expansion="debug"`).
- Changed: `digilent_zybo_z7` 4L/4S/0B → 4L+2rgb/4S/4B (default `variant="z7-20"`: `_io_z7` +
  `_io_z7_20`); `sipeed_tang_console` → 2L/0S/3B; `sipeed_tang_mega_138k` → 2L/0S/3B;
  `sipeed_tang_mega_138k_pro` 8L → 9L/0S/4B; `redpitaya` clocks `[]` → `clk125` @ 125 MHz — **measure
  `default_clock_hz`** (12 MHz today; the audit did not read instance clock attributes);
  `krtkl_snickerdoodle` `default_clock_hz` 12 → 100 MHz (`default_clk_freq`; its `clocks` already
  lists 100 MHz) (*2026-10-31*).
- No other existing board changes; the impact matrix shows zero outcome changes. D-6: exactly four
  boards gain the field — `digilent-xdc/genesys_2.json`, `litex-boards/newae_cw305.json`, the
  Digilent ZedBoard and `litex-boards/quicklogic_quickfeather.json`.
- Contact sheet (the Phase 1c recipe) for `litex-boards/digilent_zybo_z7.json`,
  `litex-boards/sipeed_tang_mega_138k_pro.json`, `litex-boards/ztex213.json`,
  `litex-boards/sipeed_tang_primer_20k.json`, `litex-boards/redpitaya.json`, plus
  `digilent-xdc/genesys_2.json` for the assumed-clock mark → **Rick's visual review before merge**.

**Effort:** S/M.

## 10. Phase 3 — Orphans in the UI, §4.8

**Do:** use synthetic orphan fixtures, one per reason; assert on what is rendered (tag text, the
info line for each reason, successor); add the CLI note and the session-log field; inspect
registration; `docs/ui_map.md` regeneration; `docs/user_guide.md` (selector + preview sections).
It comes before the bump because the bump creates the first real orphans (the five Efinix renames).
**Verify:** PNGs → **visual review**; full `pytest`.
**Effort:** S/M.

**Measured when Phase 3 ran (2026-11-01).** Built as §4.8 describes, with three refinements:

- **A date the note can show.** §4.8's "since \<date\>" had no field to read: an orphan recorded
  only `orphaned_at_commit`. The sync now also writes `orphaned_at_date`, the UTC date of the sync
  that found the board orphaned. Both are kept by later re-syncs, so the mark stays stable, and
  the schema gains the field first. No board is orphaned yet, so nothing needed migrating.
- **The successor is named by its file** (`litex-boards/efinix_trion_t8f81_dev_kit`), not its
  display name. That is the spelling `--board` takes and the one that names exactly one board;
  display names repeat across sources (§2.6). It also needs no lookup of another board's file.
- **Where the note goes.** The preview draws it in amber across the top, below the help and
  settings icons, and the board starts below it. Only an orphan has one, so every other board
  lays out exactly as before. The simulation screen shows it too, since it draws the same board.
  The selector tags the row "orphaned upstream" on its name line. `BoardDef.orphan_note()` is
  the one source of the text, used by the banner, `--board` (the launcher and the benchmark)
  and the tests. `gen_ui_map.py` renders a synthetic orphan, so both new regions are in the
  map: `preview.board.orphan-note` and `select.list.row[i].orphaned`.

## 11. Phases 4–8

**Phase 4 — Bump to the upstream heads.**

- **Do:** resolve each source's current default-branch head with `git ls-remote` and re-sync in
  place at it. The reader parses code nobody has reviewed and executes none of it (D-7); run
  `exec_scope_scan.py` over the heads anyway and list anything it flags in the PR, as a candidate
  upstream report. Update the
  `_sync_metadata.json` pins. The 2026-10-28 heads are in §2.1; upstream will have moved. The sync
  is now its own audit: read its ledger, its orphan list and the impact-matrix diff, and review
  anything not listed here. Add an accept-list entry only for an outcome a person has checked.
- **Expected** (vs 2026-10-28 heads): LiteX produces 233 boards — 12 new files (Appendix B.5: 7 new
  boards and the 5 Efinix rename targets); the 5 old Efinix files → **kept, marked orphaned
  (`file_removed`), successor = the new file** (identical I/O and device, verified);
  `sipeed_tang_console` 3 → 2 buttons (upstream made `EX_KEY.0` the reset); `alinx_ax7010` buttons
  2/3 swap pins R17/T17 (upstream edit); `modretro_chromatic` device `GW5A-LV25PG256C1/I0` →
  `GW5A-EV25UG256CC1/I0` (upstream). Amaranth +3 (`butterstick`, `icesugar_pro`, `rfsoc4x2`).
  Digilent unchanged. Acorn keeps 506 Hz unless upstream has fixed #934.
- **Verify:** drift check green at the new pins; ledger and orphans reviewed;
  `sync_port_conventions --check`, `sync_led_colors --check`; the impact matrix shows zero outcome
  changes on existing boards (measured for the 2026-10-28 heads); `tests/test_docs_board_counts.py`;
  full `pytest`; contact sheet of the new and changed boards → **visual review**.
- **Effort:** S/M.
- **Checkpoint, not a release point** (D-5, revised): the arc's freshness goal is met here, and
  Phases 5–7 ship in the same release.

**Phase 5 — Multi-pin resources (D-3) and DIP switches (D-2).**

- **Do:** the multi-pin rule of D-3 in `_parse_io_as_component` (`litex_parser.py:289`) and
  `_to_component` (`amaranth_parser.py:436`), with `unsupported_shape` warnings. **A group produced
  by splitting never displaces the bank chosen today** (D-3): keep split groups out of
  `build_bank`'s selection until Phase 6 accepts every group as a bank (defect 21, fixed in 1c,
  already keeps `rf_switches` out). Before coding,
  list the boards with multi-pin non-RGB resources at the pin now in force (Appendix B.4 is from
  the old pins; the orphaned old Efinix Ti60 file stays frozen as it is, and its successor gets the
  rule), classify them by shape (plain multi-pin vs r/g/b sub-signals vs muxed/bidirectional) and
  put the table in the PR. D-2: in `_classify_resource` (`:239`) test `dip` before
  the `btn` substring and return `switch`; naming at `:312` → `switch`. The framework convention
  bank keeps name and width and moves from `buttons` to `switches` (verified on
  `lattice_versa_ecp5`, `lattice_ecp5_evn`, `lattice_certuspro_nx_evn`).
- **Verify:** in-place re-sync; the diff touches only the listed multi-pin boards and the Appendix
  B.3 DIP boards; the impact matrix shows zero outcome changes for in-repo designs and generics
  within the Appendix B.8 ranges; its per-bank rows change only on the B.3 DIP boards — the
  `user_dip_btn` bank moves from buttons to switches with the same name, width and polarity, and a
  `user_btn` bank appears where the wider DIP group hid it — and on no multi-pin board; contact
  sheet for `litex-boards/lattice_versa_ecp5.json`,
  `amaranth-boards/versa_ecp5.json`, `litex-boards/trenz_c10lprefkit.json`,
  `litex-boards/siglent_sds1104xe.json`, `litex-boards/hackaday_hadbadge.json` → **visual review**.
- **Effort:** S.

**Phase 6 — Aliases (D-1), §4.6.**

- **Do, first:** confirm that the Phase 1a matrix's per-bank rows (moved there from this phase on
  2026-10-31) still cover every bank a design could target, Phase 5's split groups included. They
  freeze every native match possible before this phase.
- **Then:** the board-model merge, the `aliases` schema field, alias banks in
  `framework_conventions`, the matcher and wrapper channel maps, the two-aliases near-miss, alias
  colors, pin-map indexing.
- **Verify:** the 29 boards of Appendix B.2 reach the "pin-merged" column; every per-bank row that
  matched before still matches, with the same widths and polarity; GHDL + NVC e2e for one alias board per shape (mono+mono: `amaranth-boards/icebreaker.json`;
  mono+RGB channel: `litex-boards/gsd_orangecrab.json`; triple:
  `litex-boards/lattice_ice40up5k_evn.json`); PNGs → **visual review**.
- **Effort:** L.

**Phase 7 — Versions (D-4), §4.7.**

- **Do:** implement detection, then **report first** (per file: versions found, which simulate
  differently, proposed names) and stop for Rick's go-ahead; then emit.
- **Verify:** default versions keep their files and `class_name`s; new versions follow §4.1 naming;
  the impact matrix shows zero outcome changes on existing boards; selector PNG → **visual review**.
- **Effort:** M.

**Phase 8 — Closeout.** `CHANGELOG.md`; `README.md` / `docs/user_guide.md` / `docs/architecture.md`
/ `CLAUDE.md` counts and sync description; roadmap card → delivered (+ `docs/roadmap_delivered.md`
entry); Icebox P35 closed as absorbed; this file's status → executed; release as v0.24.0 (D-5,
revised: the whole arc, with no release at the Phase 4 checkpoint).

---

## 12. Phase ledger

| Phase | Scope | Visual review | Status |
|---|---|---|---|
| PR 0 | plan + card + ID + decisions | no | done 2026-10-31 (#465) |
| early | `--board` by source (1a item 6); the no-scope sync-token recipe (§4.4) | no | `--board`: done 2026-10-31 (#466), ahead of the arc. Token recipe: **dropped** 2026-10-31 — Rick decided no upstream code is executed, so `gh`'s own token is fine for our code; until the parse-only reader lands, the syncs that execute upstream files run only in CI (amendment to follow) |
| 0 | parse-only reader: no upstream code executed (D-7, §5a) | no | done 2026-11-01 (#469) |
| 1a | identity, ledger, accept-list, orphan detection, impact matrix with per-bank rows (`--board` re-checked) | no | done 2026-11-01 (#470) |
| 1b | display names (P35) | no (a before → after name table) | done 2026-11-01 (#471) |
| 1c | parser misreadings at pins | **yes** (contact sheet: 56 new board files, part numbers on 91 chips, clocks on nine, LED order on 19) | done 2026-11-01 (#472); the review found long part numbers running past the chip, fixed in the PR |
| 2 | extensions, docks, instance clock (+ D-6) | **yes** | not started |
| 3 | orphan UI | **yes** | PR #475, awaiting visual review (2026-11-01) |
| 4 | bump to heads (read, never executed) — checkpoint | **yes** (contact sheet of new and changed boards) | not started |
| 5 | multi-pin, DIP | **yes** | not started |
| 6 | aliases | **yes** | not started |
| 7 | versions | **yes** (selector) | not started |
| 8 | closeout + release v0.24.0 | no | not started |

---

## 13. Traps checklist (read before every phase)

- **Never execute, import or instantiate an upstream file** (D-7) — not in a sync, a test, an
  audit or a one-off measurement. The exec-based scripts in `~/.claude/u56-audit/` must not be run;
  read with the Phase 0 reader or the static scans.
- **Re-sync in place at the recorded `source_commit`** — a fresh directory drops canonical
  conventions (the U21 A1 trap). The drift check's port-convention step needs a token, and
  `GITHUB_TOKEN="$(gh auth token)"` is fine (§4.4); an unauthenticated rate limit reads as false
  drift.
- **Re-sync in place a second time before opening the PR** and require a byte-identical result;
  the drift job will do the same.
- **Never hand-edit generated board JSON** — change a parser or a registry, then re-sync.
- **Never rename an existing board file or change an existing `class_name`** (§2.6: registries key
  by path, recents by `class_name` + source; `tests/test_native_convention.py` reads
  `boards/amaranth-boards/tiny_fpgabx.json`, `boards/litex-boards/digilent_arty.json`,
  `boards/digilent-xdc/arty_a7-100.json`, `nexys_4_ddr.json`, `basys_3.json`,
  `boards/custom/de25_standard.json`).
- **Name boards as `<source>/<file>.json`**, and once Phase 1a lands use the qualified `--board`:
  an unqualified one returns the first match in load order and can silently pick the other
  source's twin (§2.6).
- **The sync never deletes** — by design now (orphans). Do not add deletion.
- **Ledger text must be Python-version-stable** (§4.2).
- **Schema first** (`additionalProperties: false`); the sync validates before writing.
- **Keep** `_fold_forward_unmanaged_keys`, `_carry_forward_sync_stamp`, polarity reconciliation and
  LED-color stamping working through the write-path refactor.
- **Regenerate the impact matrix** in every phase that changes board data or matching; its diff is
  the evidence.
- **Upstream data bugs are not ours to fix** (decision 2) — if one surfaces, offer Rick a drafted
  upstream issue and an accept-list entry; no override.
- **Visual review before merge** for phases 1c and 2–7. `--benchmark` exits before the session
  restores.
- Tests: `set -o pipefail` around piped gates; CI mypy runs on Python 3.12 (#449).
- Prove a projection before trusting it: the reader at the pins must reproduce the committed boards
  exactly before any "after" number counts (Appendix A's harness executed upstream files and must
  not be rebuilt, D-7).

## 14. Out of scope / follow-ups

- **Icebox P15** — "this design matches board X" for a native file chosen against the other twin of
  a cross-source pair (e.g. Terasic `de10_lite.vhd` on LiteX "Terasic De10lite"). Recommended
  follow-up; it improves the message without changing data (decision 4). Appendix B.6 now lists 20
  twins; none of the six added on 2026-10-31 carries a canonical block.
- Multiplexed LED matrices (ButterStick `rgb_leds_muxed`, Supercon badge `led_cathodes`) as a scan
  model — a new card if wanted.
- Acorn clock — upstream #934.
- 18-switch custom boards (DE2-115, VEEK-MT2) exceed the CPU designs' 16-bit switch window; the
  firmware reads only `sw(7:0)`; pre-existing and unrelated.
- Cross-source disagreements (Appendix B.7) — kept per decision 1.
- ~~Full isolation of upstream code during syncs~~ — moot: nothing executes upstream code (D-7).

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
bind a stub, retry; for Amaranth bind a class from the sibling file that defines it) — Phase 1c
replaces that with import-aware reading (§4.4). **Superseded by D-7 (2026-10-31):** this harness
executes upstream files and must not be run again; rebuild any evidence with the Phase 0 reader,
which produces the same outputs without executing anything.

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
count when it has a display, else the CPU designs' default 4. From Phase 1a this is committed
(`scripts/gen_board_design_matrix.py`, adding the two pin-map fixtures and the wrong-board hint),
so later phases diff it instead of rebuilding it.

**A.4 Instantiation audit.** For each platform file: exec (with the fixes), find the platform class,
call it with no arguments, and tabulate exception type + message.

**A.5 Twins by pins.** For each new board, compare its set of LED, switch and button pins with
every board of another source (Jaccard ≥ 0.5 over at least 2 pins), then confirm each hit by its
device. Names miss mangled pairs (`tiny_fpgabx` ↔ `tinyfpga_bx`, `ice40_up5_kbevn` ↔
`lattice_ice40up5k_evn`), and the tiny pin sets of iCE40UP5K boards coincide across different
boards (the RGB driver pins are fixed by the silicon), so every hit needs that confirmation.

## Appendix B — Lists (2026-10-28; B.6–B.7 extended 2026-10-31)

### B.1 Boards recovered by Phase 1c at the pins

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
`ypcb_00338_1p1` 3L. (Counts before Phases 5–6; the DIP boards' buttons include DIPs.)

Amaranth (3): `supercon19badge.py` 12L/8B · `upduino_v2.py` 3L+1rgb · `versa_ecp5_5g.py` 9L/8S.

Phase 2 adds (LiteX): `sipeed_tang_primer_20k` 7L/5B · `sipeed_tang_primer_25k` 2L/2B · `ztex213`
30L.

### B.2 Boards listing one pin under several names (D-1, Phase 6) — at head, fixed parser

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

### B.3 DIP boards (D-2, Phase 5) — LiteX `user_dip_btn`

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

### B.4 Shipped boards with multi-pin non-RGB resources (D-3, Phase 5) — at the old pins

amaranth `quickfeather` `swd`(2 pins, io) · amaranth `tang_primer20k_dock` `mic_led`(2) · amaranth
`versa_ecp5` `alnum_led`(15) · litex `alibaba_xcku3p` `led`(3) · litex
`efinix_titanium_ti60_f225_dev_kit` `led`(3) ×2 · litex `fairwaves_xtrx` `led`(3), `switch`(3) ·
litex `gsd_butterstick` `led`(3) · litex `hackaday_hadbadge` `led`(11), `led`(3) · litex
`lattice_versa_ecp5` `alnum_led`(15) · litex `limesdr_xtrx` `led`(3), `switch`(3) · litex
`siglent_sds1104xe` `led_frontpanel`(4), `button`(3) · litex `trenz_c10lprefkit` `gpio_leds`(8).
(Shapes not yet classified — first task of Phase 5, which re-lists them at the pin then in force.
Example: `fairwaves_xtrx` declares `("user_led2", 0, Pins("G3 M2 G2"))  # GPIO LED`. The XTRX
boards' `switch`(3) is `rf_switches`, which defect 21 removes in Phase 1c, so Phase 5 never splits
it; splitting their `user_led2` must not displace the `user_led` bank, D-3.)

### B.5 Upstream changes between the pins and the 2026-10-28 heads

- LiteX new files (12 — 7 new boards plus the 5 Efinix rename targets listed below):
  `aliexpress_rk_xcku5p` 4L/4B · `alinx_ax7035` 4L/4B/7seg1 ·
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

### B.6 Second-source twins at heads (kept as-is, decision 4) — matched by pins (A.5)

LiteX `terasic_de10lite` ↔ amaranth `de10_lite` (Terasic canonical) · LiteX `terasic_de1soc` ↔
amaranth `de1_so_c` (Terasic canonical) · LiteX `terasic_de0nano` ↔ amaranth `de0_nano` (Terasic
canonical) · LiteX `digilent_eclypse_z7` ↔ digilent `eclypse_z7` (Digilent canonical) · LiteX
`xilinx_kc705` ↔ amaranth `kc705` · LiteX `xilinx_kcu105` ↔ amaranth `kcu105` · LiteX `icebreaker`
↔ amaranth `icebreaker` · LiteX `icebreaker_bitsy` ↔ amaranth `icebreaker_bitsy` · LiteX
`kosagi_fomu_hacker` ↔ amaranth `fomu_hacker` · LiteX `kosagi_fomu_pvt` ↔ amaranth `fomu_pvt` ·
LiteX `muselab_icesugar` ↔ amaranth `icesugar` · LiteX `quicklogic_quickfeather` ↔ amaranth
`quickfeather` · amaranth `butterstick` ↔ LiteX `gsd_butterstick` · amaranth `icesugar_pro` ↔ LiteX
`muselab_icesugar_pro`.

**Added 2026-10-31**, which the name match missed: LiteX `tinyfpga_bx` ↔ amaranth `tiny_fpgabx`
(the same LED pin, B3; iCE40LP8K) · LiteX `lattice_ice40up5k_evn` ↔ amaranth `ice40_up5_kbevn`
(all 7 pins) · LiteX `terasic_deca` ↔ amaranth `arrow_deca` (12 of 13 pins; 10M50DA) · LiteX
`lattice_machxo3` ↔ amaranth `mach_xo3_lsk` (12 of 13 pins; the same `LCMXO3L-6900C`, and
equally close to `mach_xo3_lfsk`, the LF variant) · amaranth `supercon19badge` ↔ LiteX `hackaday_hadbadge` (the
2019 Supercon badge; 14 shared pins, LFE5U-45F) · amaranth `versa_ecp5_5g` ↔ LiteX
`lattice_versa_ecp5` (all 31 pins, the same `LFE5UM5G-45F`; also pin-identical to amaranth
`versa_ecp5`, the `LFE5UM-45F` sibling).

**New on both sides:** LiteX `digilent_zedboard` ↔ digilent `Zedboard-Master.xdc`.

That makes 20 second sources for boards we already ship. A Terasic- or Digilent-native design
matches only the entry carrying the canonical block (follow-up: P15); none of the six added pairs
carries one.

### B.7 Cross-source disagreements (informational; each source simulated as defined)

Genesys 2 / Nexys 4 / Nexys 4 DDR: 6 buttons (Digilent XDC counts CPU reset) vs 5 (LiteX
`cpu_reset` is separate) · Cmod A7: 2 vs 1 (same reason) · DE2-115: LiteX 18L vs custom
27L/18S/4B · Versa ECP5: LiteX 8 DIP-as-buttons vs Amaranth 8 switches (D-2) · KC705 / KCU105:
LiteX 9 buttons vs Amaranth 0 (Amaranth declares none) · ButterStick: LiteX 8L vs Amaranth 1L ·
iCESugar Pro / QuickFeather / Tang Nano: LiteX aliases (D-1) vs Amaranth single RGB. *Added
2026-10-31:* DECA: LiteX 3 buttons vs Amaranth 2 · MachXO3: LiteX 4 DIP-as-buttons vs Amaranth 4
switches + 1 button (D-2) · Supercon 2019 badge: Amaranth 12L/8B vs LiteX two collapsed multi-pin
LEDs and no buttons (D-3) · iCE40UP5K EVN: LiteX 4L+1rgb vs Amaranth 3L+1rgb (D-1).

### B.8 Runtime generic ranges (`build_generics`), today vs projected at heads

| Generic | Today | Projected | New values |
|---|---|---|---|
| `NUM_LEDS` | 1..32 | 1..32 | 30 (`ztex213`) |
| `NUM_SWITCHES` | 1..18 | 1..18 | — |
| `NUM_BUTTONS` | 1..13 | 1..13 | — |
| `NUM_SEGS` | 1..8 | 1..8 | — |
| `CLK_HALF_NS_INIT` | 1..988142 | 1..988142 | 6; from the clock fixes, 240 (MachXO2 breakouts, 2.08 MHz) and 100 (QuickFeather, 5 MHz) |

(988142 ns is the Acorn baseboard's upstream 506 Hz clock — decision 2. The clock fixes of defects
13, 22 and 23 move 11 boards' `CLK_HALF_NS_INIT`, `max(1, round(5e8 / default_clock_hz))`; the
other new values — 5, 10, 20, 21 and 4 — already occur today. *2026-10-31.*)

## Appendix C — Code anchors (verified 2026-10-28; re-checked and extended 2026-10-31)

| Concern | Anchor |
|---|---|
| LiteX mocks | `scripts/litex_parser.py:21` `_Pins` · `:99` `_PLATFORM_VENDORS` (`:109` iCE40 key) · `:124` `_make_mock_platform` (`:146` `add_connectors`, `:149` `add_extension`) · `:166` `_make_litex_namespace` (`:203` real builtins) |
| LiteX classify/parse | `:226` `_classify_resource` (`:239` DIP · `:241` `"switch" in n`) · `:289` `_parse_io_as_component` (`:312` DIP name) · `:439` `_build_litex_convention` · `:467` `_prettify_filename` · `:474` `_make_class_name` · `:486` `parse_litex_board` (`:500` exec except · `:526-527` class-level default clock · `:536` instantiate except · `:541` `_io` fallback · `:641` 12 MHz no-clock fallback · `:649` one board) |
| Amaranth | `scripts/amaranth_parser.py:293` `_make_namespace` (`:345` real builtins) · `:375` `_find_default_clock_hz` (`:383` 12 MHz fallback) · `:422` `_classify` (`:431` `sw`) · `:436` `_to_component` · `:584` `_prettify_class_name` · `:599` `load_board_from_source` (`:614` except · `:662` `device` only) |
| Digilent | `scripts/digilent_parser.py:206` `_RE_LED_WORD` · `:213` RGB channel pattern · `:227` `_classify_section` · `:261` heading classification · `:278` `parse_xdc` · `:825` frequency only from `create_clock` · `:864` 100 MHz no-period fallback |
| Amaranth upstream clock rules | `amaranth/vendor/_lattice.py` (`OSCH`, `OSCG`, `OSCA`) · `_siliconblue.py` (`SB_HFOSC`, `SB_LFOSC`) · `_altera.py` (`cyclonev_oscillator`) · `_quicklogic.py` (`sys_clk0`) · `_gowin.py` (`OSC`) — each in `default_clk_constraint` (checked on Amaranth `main`, 2026-10-31) |
| Sync scripts | `scripts/sync_litex_boards.py:61` `generate_all_json` (`:80` silent skip, `:93` file name) · `scripts/sync_amaranth_boards.py:50` `generate_board_json` (`:67`, `:80`) · `scripts/sync_digilent_xdc.py:103,106` |
| Sync common | `scripts/sync_common.py:23` `sanitize_filename` · `:34` `unique_name` · `:64` token from the environment · `:160` `_fold_forward_unmanaged_keys` · `:223` polarity reconcile · `:240` `_carry_forward_sync_stamp` · `:268` `write_outputs` |
| Conventions | `scripts/framework_conventions.py:86` `build_bank` · `:99` primary-group rule · `:166` `build_convention` · `:225` `reconcile_framework_polarity` |
| Drift | `scripts/check_board_drift.py:64` `main` |
| Loader | `src/fpga_sim/board_loader.py:21` `_FALLBACK_CLOCK_HZ` · `:54` overrides · `:242` `is_rgb` · `:285` `BoardDef` · `:352` `num_led_channels` · `:366` `led_channel_targets` · `:473` `from_json` · `:543` silent skip of an unreadable file · `:566` `find_board` |
| Matcher/wrapper | `src/fpga_sim/conventions.py:105` `ConventionMatch` · `:478` `_convention_precedence` · `:521` `match_convention` · `src/fpga_sim/wrapper.py` `leds_rgb` packing (~`:171-218`) · `src/fpga_sim/vhdl_contract.py:306` pin-map path |
| Runtime | `src/fpga_sim/controller.py:130` `build_generics` · `src/fpga_sim/pinmap.py:112-145` pin index · `:430` `_same_silicon` (`:450` empty = match) · `:576` wrong-board hint · `src/fpga_sim/session_config.py:129` `push_recent` · `src/fpga_sim/ui/components.py:67` chip `device` label |
| CPU IO | `scripts/embedded_core/templates/cpu_io.vhd.tmpl:37` `LED_REG_WIDTH` · `:43-57` read mux and config registers |
| Exec sites (Phase 0 removes them) | `scripts/amaranth_parser.py:340-345` real `os`/`subprocess`/builtins · `:613` `exec` · `scripts/litex_parser.py:199-203` · `:499` `exec` · `:533` `platform_class()` |
| Docs | `CONTRIBUTING.md` "Syncs that run upstream code" (#466; Phase 0 rewrites it) |
| Tests | `tests/test_litex_parser.py` · `tests/test_digilent_parser.py` · `tests/test_sync_amaranth_boards.py` · `tests/test_sync_common.py` · `tests/test_check_board_drift.py` · `tests/test_board_schema.py` · `tests/test_serialization.py` · `tests/test_board_display_names.py` · `tests/test_docs_board_counts.py` · `tests/test_native_convention.py` · `tests/test_pinmap.py` · `tests/fixtures/pinmap/` · `tests/test_ui_map.py` (the pattern for the matrix test) · `tests/conftest.py:212` |
