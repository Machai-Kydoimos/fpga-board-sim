# Changelog

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **README / onboarding accuracy.** The "Try it" walkthrough now shows the correct
  order — **Load VHDL File** (pick the design) *then* **Start Simulation**, which is
  greyed until a file is loaded — instead of implying the reverse. Also names GTKWave /
  Surfer as the waveform viewers, notes that `fpga-sim` needs a graphical display (with
  the headless `pytest` / `--benchmark` alternatives), and corrects CONTRIBUTING's claim
  that `uv sync` installs runtime dependencies only (`uv` includes the `dev` group by
  default).

### Internal

- **Single-window simulation groundwork (U34, part 1).** Added the process-split
  IPC layer a later change will use to keep the launcher's window alive during
  simulation: a `sim_link` transport (messages between the UI host and a headless
  child over an authenticated localhost socket), a headless cocotb bridge
  (`sim/sim_testbench_bridge.py`, no pygame), and a `SimChild` process handle with
  `start_simulation()` / `finish_waveform()` in `sim_bridge.py` — sharing a new
  `_prepare_simulation()` helper with the unchanged `launch_simulation()`. Inert:
  nothing reaches it from the default launcher flow yet, so behavior is unchanged.
  See [`docs/experiments/single_window_sim.md`](docs/experiments/single_window_sim.md).

## [0.14.0] - 2026-07-16

### Added

- **Auto-derived board-native conventions for litex & amaranth boards (U32).**
  The litex and amaranth board syncs now emit a framework-derived
  `port_conventions` block for **241 of their 246 boards**, so a VHDL design
  written to a board's framework-native port names — litex `clk100` /
  `user_led` / `user_sw` / `user_btn`, amaranth `clk100` / `led` / `switch` /
  `button` — runs **board-native** on that board (unmodified, no `NUM_*`
  generics), extending the U21 experience previously limited to a few
  hand-authored Terasic boards to nearly the whole litex/amaranth fleet. The
  blocks are marked `framework-derived`; a vendor-authoritative convention
  added for a board later coexists with and takes precedence over the derived
  one. Boards whose LED bank is narrower than their full LED count (e.g. an Arty
  whose RGB LEDs sit alongside `user_led`) light the bank and leave the rest
  dark. A committed litex Arty example (`hdl/native/arty_litex.vhd`) simulates
  on both GHDL and NVC.
- **Board-native coverage for two more Digilent boards (U33).** The Digilent
  XDC parser now recognizes clock sections titled by frequency or `System` /
  `PL` (`100MHz Clock`, `12 MHz System Clock`, `PL System Clock`) and LED
  sections named `N LEDs`, not only the exact `Clock signal` / `LEDs` strings —
  while still rejecting a mezzanine/transceiver reference clock (an FMC card's
  GTP/MGT clock, not the FPGA fabric's). Regenerated from the same pinned
  upstream, this recovers the clock — and, for Cmod S7-25, four user LEDs the
  old parser silently dropped — that let **USB104 A7-100T** and **Cmod S7-25**
  run board-native. Three Zynq boards (Cora Z7-07S / Z7-10, Eclypse Z7) regain
  their clock but stay non-native pending RGB-LED-bank handling (#229).
- **Vendor-canonical board-native conventions for 4 more boards (U33 Wave 2).**
  Alchitry Au, Sipeed Tang Nano 9K, Icepi Zero, and Trellisboard gain
  vendor-canonical `port_conventions` — their real constraint-file port names
  (e.g. Tang Nano's Gowin `led` / `sys_clk` rather than the litex framework
  names) — so a design hand-written to a board's own names runs board-native on
  it. Populated from each board's official-repo constraint file via
  `scripts/sync_port_conventions.py`; Tang Nano 9K's active-low LEDs carry a
  cited polarity overlay, and the canonical blocks take precedence over the
  framework-derived ones (U32). Supporting fixes: the sync scripts'
  `resolve_commit_sha` now sends `GITHUB_TOKEN` / `GH_TOKEN` when set (the
  unauthenticated GitHub API rate limit was silently degrading pinned source
  URLs to branch URLs mid-wave), and two stale registry source URLs were
  repointed from a renamed `master` branch to `main` (#231).
- **Board-native partial conventions + Sipeed Tang Nano 20K (U33 Wave 3).** The
  port-convention generator's width cross-check now accepts a source bank
  *narrower* than the board — a board whose own constraint file wires up only
  some of its LEDs/buttons is a legitimate partial convention the native
  wrapper already adapts (zero-extending a short LED bank, feeding the low bits
  of a short input bank, exactly as it does for U32's framework banks); only a
  source *wider* than the board (claiming resources the board doesn't model)
  stays a mismatch. Populates **Sipeed Tang Nano 20K** — its source `leds[6]`
  covers the 6 plain LEDs and the board's 7th is an RGB — active-low via a
  cited overlay (#233).
- **OLED / 7-segment pins no longer counted as user LEDs (U33 Wave 4).** The litex
  and amaranth board parsers classified a resource as a user LED with a bare
  `"led" in name` substring test, which wrongly swept in `oled*` (OLED display
  buses) and `segled_*` (7-segment display lines) — both merely *contain* "led" —
  inflating the LED bank on seven boards. LED classification now requires "led" at a
  token boundary (start, or after `_`/`-`/a digit), so `m2led` (the M.2 status LED)
  and `led0` still count while `oled` and `segled` do not. Regenerated from the same
  pinned upstream, this corrects the user-LED count on **Genesys2** (amaranth +
  litex), **Kintex7-BaseC**, **Nexys Video**, and **ULX3S** (each had one phantom
  OLED "LED"), and on **Nexys4** (34→18) and **Numato Mimas A7** (20→8) — whose
  `segled_*` pins are now modeled as their real multiplexed 7-segment displays (8
  and 4 digits, common-anode active-low, matching the golden Nexys4-DDR model)
  rather than phantom LEDs. Buttons and switches are unaffected fleet-wide and no
  legitimate LED is dropped (#235).
- **Vendor-canonical conventions for Litefury & Nitefury II (U33 Wave 4).** The two RHS
  Research PCIe FPGA cards gain vendor-canonical `port_conventions` — `clk = pcie_clkin_p`,
  `leds = LED_A1`..`LED_A4` — a clk+LED *partial* interface (no switches/buttons, which the
  U31 native wrapper ties off) populated from their official sample-project XDC. Their LEDs
  are **active-low**, cited to the vendor's own sample HDL (`CodeBlinker.v`'s
  `localparam LED_ON = 1'b0`), which also revealed the amaranth-boards platform models these
  LEDs active-high — incorrect per the vendor's own blinker. ICEBreaker Bitsy, the other
  candidate considered, is intentionally left on its (correct) framework convention: its
  canonical bank would classify to the RGB breakout rather than the red+green primary (#237).
- **Port-convention source registry.** New maintainer-facing registry at
  `docs/port_convention_sources/` — one TOML per board family holding ranked,
  fetch-verified pointers to each board's canonical constraint/pin file (QSF,
  XDC, UCF, PCF, LPF, PDC, CST, CCF, …), with extracted port names, license
  notes, and honest `none-found` records. Covers the full board fleet across
  19 family files; `digilent.toml` is auto-generated from the existing sync
  pipeline's pinned upstream. Groundwork for **U21** (board-native VHDL): every
  future `port_conventions` block in `boards/*/*.json` traces to an
  authoritative source, and better sources later mean editing one registry row.
  The simulator does not read these files at runtime (#198)
- **U21 schema groundwork (Phase A0).** Extended `boards/schema/board.schema.json`
  ahead of the board-native VHDL convention matcher: `seg_port_mapping.style`
  gains `per_segment_scalars` / `scan` / `serial` alongside the existing
  `packed_vector` / `individual`; `scan` boards get a typed `digit_enable`
  strobe; `port_convention` gains a `source` provenance stamp
  (`url`/`retrieved`/`registry_board`) and a `naming`
  (`canonical`/`project-derived`) flag for data the upcoming A3 generator will
  populate from the port-convention registry; the already-used `leds_green`
  key (Terasic-style secondary LED bank) is now a typed `port_mapping` instead
  of an ad-hoc extra key. Schema-only — no board JSON changes; all 278 boards
  still validate (U21 arc, issue #200)
- **U21 re-sync preservation guard (Phase A1).** `scripts/sync_common.py`'s
  shared `write_outputs()` now folds `port_conventions` / `peripherals`
  forward from whatever board JSON is already on disk before writing, so
  re-running an upstream sync can never silently wipe hand-authored or
  U21-populated convention data. `port_conventions` merges per top-level
  sub-key (new overlays old): `sync_digilent_xdc.py`'s generated `digilent`
  key always wins, every other convention key survives untouched; a parser
  that generates no conventions at all (amaranth, litex) contributes an empty
  overlay, so existing data passes through unchanged. The merged result — not
  just the freshly generated content — is what gets schema-validated, so a
  corrupted on-disk block is caught rather than folded in silently. Boards
  with nothing to preserve are written byte-identical to today's output (no
  re-serialization), verified against a real amaranth-boards sync (79 boards,
  diff limited to the expected `sync_commit`/`sync_timestamp` refresh) and a
  real digilent-xdc sync with a hand-added sibling convention (survived
  intact). An existing board file that isn't valid JSON, or whose top level
  isn't an object, now fails with a clear error naming the file instead of a
  raw traceback (U21 arc, issue #201)
- **U21 constraint-dialect parsers (Phase A2).** New `scripts/port_convention_parsers/`
  package: one pure `parse(text) -> PortTable` module per constraint dialect
  (QSF, XDC, UCF, PCF, LPF, CST, CCF, BoardStore XML), plus a shared,
  dialect-agnostic `classify()` that buckets the parsed ports into a
  `port_convention`-shaped dict (clk/leds/switches/buttons/seven_seg) by
  name-shape alone — bracket-indexed vector widths, Digilent's
  compass-direction named buttons, and three 7-seg structures (per-digit,
  per-segment-scalars, shared-segment + digit-enable ⇒ scan) are all detected
  without any dialect-specific knowledge. Every gotcha the #198 registry
  research found in the wild is encoded as a fixture taken from a real,
  fetch-verified source: quoted vs. bare `PACKAGE_PIN` values in the same XDC
  file (Numato Mimas A7), Digilent's fully-commented master XDC convention,
  UCF's bracket/paren/angle-bracket vector syntax, PCF's `-nowarn` flag and
  `_N` active-low naming convention, LPF's `FREQUENCY PORT` clock statement,
  and BoardStore XML's valid-but-unusual `name ="X"` spacing. A golden test
  parses the real Digilent Basys3 master XDC and reproduces
  `boards/digilent-xdc/basys_3.json`'s existing clk/leds/switches/buttons
  convention — and, now that A0 added the `scan` style, correctly
  reclassifies its 7-segment display from the on-disk `packed_vector` to
  `scan` (a shared `seg` vector plus an `an` digit-enable, a distinction the
  pre-A0 `digilent_parser.py` had no schema support to express). Parsers are
  pure and network-free (U21 arc, issue #202)
- **U21 port_conventions generator + overlay (Phase A3).** New
  `scripts/sync_port_conventions.py`: turns a `docs/port_convention_sources/`
  registry row into a board JSON's `port_conventions.<maker-slug>` block —
  resolve the rank-1 source URL to a commit-pinned raw URL, fetch it (new
  `sync_common.fetch_url()`, with an on-disk cache), parse + classify it with
  A2's pipeline, layer any `overlay.toml` override on top, cross-check widths
  against that board's own already-known resource counts, and shallow-merge
  the result into every board JSON the row's `files` lists — independently
  per target file, since one registry row can point at more than one board
  JSON for the same physical board (discovered live: DE2-115's litex-derived
  file never captured its `LEDG` bank, so it now cleanly skips there while
  the hand-authored `custom/de2_115.json` still gets populated). A board only
  reaches a write if registry `status == "verified"`, its rank-1 source is
  `vendor-official`/`official-repo`, and it's listed in new
  `docs/port_convention_sources/waves.toml` (Wave 1's teaching-priority
  boards populated now; Wave 2 deliberately left for its own population
  phase rather than risk a mistranscribed name); `--board <name>` bypasses
  that trust gate for targeted testing/curation, never the width
  cross-check. New `docs/port_convention_sources/overlay.toml` holds cited
  facts no constraint file states (the canonical clock on a multi-clock
  board, signal polarity) — proven against two real, fetched Terasic
  sources: DE10-Standard and DE2-115 both reproduce Rick's existing
  hand-authored `boards/custom/` blocks field-for-field once overlaid, and a
  forced run against Digilent's Basys 3 reproduces `sync_digilent_xdc.py`'s
  output the same way A2's golden test already established.
  `classify()` gains `leds_green` detection (Terasic's secondary LED bank,
  e.g. DE2-115's `LEDG`), matched narrowly enough that it can never win the
  primary `leds` slot regardless of relative bank size (U21 arc, issue #203)
- **`port_mapping.names` (U21 schema follow-up).** `boards/schema/board.schema.json`'s
  `port_mapping` (used for `leds`/`switches`/`buttons`) gains an optional `names`
  array, symmetric with `seg_port_mapping`'s existing one. Closes a gap A2 found and
  deliberately left open (flagged in its PR body rather than reopening A0's
  already-merged schema unilaterally): boards whose LEDs/switches/buttons are
  distinct un-bracketed scalars sharing a common prefix (Nandland Go's
  `o_LED_1`..`o_LED_4`, a Wave-1 board) previously got no convention for that
  resource at all, since inventing a shared vector port name would describe
  something no real design declares. `classify()` now populates `names` for
  that shape instead of declining — real port names, not a fabrication —
  while two genuinely unrelated scalar names with no common prefix (GateMate's
  `FPGA_LED`/`JTAG_LED`) still correctly yield nothing (U21 arc)
- **`sync_port_conventions.py` trusts `boards/custom/` targets (U21 arc, pre-A4-Wave-1
  refinement).** The generator's row gate now skips its `kind` check (but not
  `status`/wave-membership) for any registry row whose `files[]` includes a
  `boards/custom/` target — that directory is where a human has already verified
  a board's port names against real vendor documentation, which is a stronger
  trust signal than the registry's `kind` field (a hosting-location fact, not an
  accuracy one). Confirmed empirically: DE10-Standard and DE2-115 now pass the
  real gate rather than needing `--board` to force them through, and A3's
  hand-authored regression test was updated to prove exactly that (U21 arc)
- **U21 `port_conventions` population — Wave 1 (Phase A4).** Three Terasic teaching boards —
  DE0-CV, DE1-SoC, DE0-Nano — gain generated `port_conventions.terasic` blocks (canonical
  `CLOCK_50` / `LEDR`|`LED` / `SW` / `KEY` / `HEX0..5` names, cited signal polarity, and
  commit-pinned source stamps). To reach them, `sync_port_conventions.py`'s row gate gains a
  second cited `kind` bypass alongside A3's `boards/custom/` one: a rank-1 registry source may
  be vouched `naming = "canonical"` with a `naming_cite`, because `kind` labels where a
  constraint file is *hosted*, not whether its port names are the vendor's canonical ones —
  Terasic's teaching-board QSFs in the wild are community-hosted course files that nonetheless
  use the manual's names. The vouch is per-source, requires a citation (uncited claims are
  ignored, fail-safe), and is still width-cross-checked against each board JSON. The remaining
  Wave-1 candidates (DE0, DE10-Lite, DE10-Nano, Nandland Go, RZ-EasyFPGA, Runber) stay listed
  but are held back with recorded reasons (see `docs/port_convention_sources/waves.toml` and the
  arc plan). Data-only for the runtime — conventions stay inert until Part B (U21 arc, issue #204)
- **U21 board-native conventions threaded into the runtime (Phase B1).** `BoardDef` now carries a
  `port_conventions` mapping: the runtime loader reads it from each board JSON (previously dropped
  as an unknown key), and `to_json`/`from_json` round-trip it, so a board's board-native VHDL port
  conventions ride along to the simulation subprocess via `FPGA_SIM_BOARD_JSON` (consumed
  launcher-side by the upcoming matcher/wrapper, so the subprocess carries them harmlessly).
  Threaded as the schema-shaped dict — a typed view is deferred to the matcher phase; a board with
  no conventions gets an empty mapping. Inert data until the convention matcher (B2) consumes it
  (U21 arc, issue #205)
- **U21 board-native convention matcher (Phase B2).** `check_vhdl_contract` now returns a frozen
  `ContractResult(ok, message, match)` instead of an `(ok, message)` tuple, and a new pure
  `match_convention()` recognizes a VHDL file that uses a board's *native* port names + fixed
  widths (e.g. DE10-Standard's `CLOCK_50` / `SW` / `KEY` / `LEDR` / `HEX0..5`) against the
  selected board's `port_conventions`. When a design fails the generic contract it is now checked
  against the board's conventions: a full match is reported with a precise message (naming the
  board and its native ports) and the `ConventionMatch` carried on the result, and a near-miss
  (≥2 roles matched) names the convention and lists what's missing/mis-sized. Detection only —
  `ok` stays False, because *running* a native design needs the B3 wrapper; accepting it before
  that exists would trade a clear contract rejection for a cryptic elaboration crash. Generic
  designs are entirely unaffected. Scope: the `individual` 7-seg style (the only one in canonical
  board data), optional secondary LED banks (`leds_green`), and scalar-port banks;
  `packed_vector` / `scan` / `serial` decline to the generic path / U22. Inert until the native
  wrapper (B3) turns it on (U21 arc, issue #206)
- **U21 DE10-Lite board-native rescue (A4 System-CD follow-up).** DE10-Lite now ships a canonical
  `port_conventions.terasic` block, so a board-native DE10-Lite design (`MAX10_CLK1_50` / `SW` /
  `KEY` / `LEDR` / `HEX0..5`) is recognized by the B2 matcher. Its verified community source uses
  vendor-canonical names for most ports but renames `LEDR`→`LED` and the clock→`Clk`;
  `scripts/sync_port_conventions.py`'s `apply_overlay` gains a cited resource-`name` override
  (alongside the existing `clk` / `active_low` overrides) that restores both to canonical, verified
  against the official Terasic DE10-Lite System CD v2.2.0 golden top (cite-not-copy: the fact plus a
  versioned file citation live in `overlay.toml`, never the copyrighted QSF). A third row-gate
  bypass, `_overlay_supplies_cited_canonical_names`, admits such a board — parallel to the
  `boards/custom/` and `naming = "canonical"` bypasses, all encoding that `kind` is a hosting-location
  label, not a port-name-accuracy one. Data-only for the board fleet; DE0 (needs an A2 `HEXn_D`/`_DP`
  classifier extension) and the candidate boards DE23-Lite / DE25-Standard / VEEK-MT2 remain for later
  System-CD-wave PRs (U21 arc)
- **U21 DE0 board-native rescue + split-DP 7-seg classifier (A4 System-CD follow-up).** DE0 (the
  original Cyclone III board, distinct from DE0-CV) now ships a canonical `port_conventions.terasic`
  block, so a board-native DE0 design (`CLOCK_50` / `SW` / `BUTTON` / `LEDG` / `HEX0_D`..`HEX3_D`) is
  recognized by the B2 matcher. Two additive `classify.py` fixes: (1) a split per-digit 7-seg branch
  reads `<prefix><n>_D[6:0]` segment vectors + companion `<prefix><n>_DP` scalars (an older Terasic
  style) as `individual` over the segment ports (the `_DP` decimal points are recognized but
  unmodeled — 7-bit, as on the bare-`HEXn` boards); (2) a green-only LED bank (DE0's `LEDG`, with no
  red `LEDR`) now populates the primary `leds` slot instead of `leds_green` (which stays reserved for
  a *secondary* green bank alongside a red one, e.g. DE2-115). DE0's names are vendor-canonical
  verbatim (golden-top-confirmed), so it takes the standard cited naming vouch plus a `clk` overlay
  (classify() otherwise mis-picks `GPIO0_CLKIN`). cite-not-copy. Data-only for the board fleet
  (U21 arc)
- **U21 board-native VHDL runs (Phase B3a — core).** A design written to a board's *own* port
  names and fixed widths (no `NUM_*` generics) now simulates unmodified: `check_vhdl_contract`
  returns `ok=True` for a full native match, and `_generate_wrapper` emits a *native* `sim_wrapper`
  that instantiates the design by its native names and adapts them to the simulator's
  `clk/sw/btn/led/seg` boundary — inverting active-low LEDs (`led <= not led_uut`) and buttons
  (`key_uut <= not btn`), and packing an `individual`-style 7-seg per digit into the display byte
  (decimal point off). The native wrapper carries the same entity/generics/top-ports/clock process
  as the generic one (so the run mechanics and the cocotb testbench are untouched) but bakes the
  board widths as its generic *defaults*, so the analysis-time default-generic elaboration lines up
  with the native fixed widths — no launch-path changes. The `ConventionMatch` from the contract
  check threads through `SessionState` → `analyze_vhdl` / `launch_simulation` → the wrapper, and a
  board-native run also exports `FPGA_SIM_NATIVE_CONVENTION` for the upcoming badge/session-log
  (B3b). Three example designs land under `hdl/native/` (DE10-Standard with active-high `LEDR`, DE0
  with split-DP `HEXn_D` + green `LEDG` + `BUTTON`, DE25-Standard with active-low `LEDR`), each
  analyzed end-to-end under **GHDL and NVC**; a standalone NVC run proves the active-low-LED
  inversion (`led == not ledr`). The auto-written GTKWave save file for a native run now preselects
  the design's *own* signals (`sim_wrapper.uut.<native>`) plus the board-logical `led`/`seg` so the
  inversion is visible, instead of the contract names. **Cross-board safety:** loading a native
  file against the wrong board either near-misses (different port names — e.g. a DE10-Standard file
  on a DE25 board differs on the clock name) or matches an electrically identical board; a
  data-invariant regression test asserts no cross-board full match ever silently flips polarity.
  Generic designs are entirely unaffected (U21 arc, issue #207)
- **U21 board-native run affordances (Phase B3b — UX).** When a board-native design runs, the
  simulator now says so. The top-left info strip tags the mode right after the filename —
  `(native: terasic)` in an accent color (a restrained visual "pop") for a native run, `(generic)`
  in the normal color otherwise — and the same tag appears in the window title. Pressing **S**
  (stats panel) shows a compact `board-native · active-low: LED, KEY, HEX` note in the INFO zone,
  spelling out which roles the board drives active-low (the detail behind the wrapper's polarity
  inversion); it's a single small-font line tucked below the existing rows, so the fixed-height
  panel doesn't grow and the board keeps its size. The analysis spinner reads "Analyzing
  board-native …" and the per-session log (`~/.fpga_simulator/sessions/`) gains `mode`
  (`generic`/`native`) and `convention` (the maker slug) fields. All of this is driven by the
  `FPGA_SIM_NATIVE_CONVENTION` metadata B3a already exports — no new detection logic (U21 arc,
  issue #207)
- **U21 board-native VHDL docs + arc closeout (Phase B4).** Documented the shipped feature and
  closed out the arc. `CLAUDE.md` gains a "Board-native designs" subsection — the
  simulates-the-*selected*-board / board-supplies-polarity / wrong-board-near-miss contract, plus
  the no-`COUNTER_BITS` "frozen-divider" gotcha (native designs tap mid counter bits so motion
  stays visible at sim speed) — and an `hdl/native/` file-table row. The roadmap U21 card is
  condensed to a shipped ✅ stub with the full record moved to `docs/roadmap_delivered.md`; the arc
  plan's status ledger and closeout checklist are completed and a lessons-learned section appended;
  and `docs/port_convention_sources/README.md` now documents how the A3 generator consumes the
  registry. Three follow-ups parked to the Icebox: global cross-board convention *ambiguity*
  detection (**P15**), Surfer waveform signal *preselection* (**P16**), and a board-native
  frozen-divider warning heuristic (**P17**). Docs only — no code change. Completes **U21** (U21
  arc, closes #207 and #208)
- **Board-native partial-interface support (U31).** A board-native design no longer has to declare
  the full clk + LEDs + switches + buttons interface — the matcher now requires only the roles the
  selected board's `port_conventions` block declares (clk + LEDs at minimum, switches/buttons
  matched only when the convention names them), generalizing the existing "7-seg required only when
  the board has a display" rule. So a design for a **switch-less** or **button-less** board (most
  FPGA boards have no switches) now simulates unmodified. The generated native wrapper ties off an
  absent input bank — the `sw`/`btn` boundary ports stay so the cocotb testbench is untouched, but
  are floored to one dummy bit and left unconnected to the design, mirroring the generic path's
  `NUM_* = max(1, count)` — and leaves absent output banks dark. A design that declares an *input*
  the convention lacks stays an honest near-miss (it would otherwise be an unbound port), while an
  extra *output* is left `open` (as the DE0 example already does for its decimal-point pins).
  Behavior on today's full-interface conventions is unchanged; this is the coverage lever that lets
  board-native mode reach the bulk of the fleet once the litex/amaranth conventions land (U32).
  `ConventionMatch.switches`/`.buttons` are now optional (#223, #226)

### Changed

- **Documentation restructure: three new focused guides under `docs/`.** Installation,
  day-to-day usage, and architecture now live in [`docs/install.md`](docs/install.md),
  [`docs/user_guide.md`](docs/user_guide.md), and [`docs/architecture.md`](docs/architecture.md)
  instead of one long README. `docs/install.md` collects the full GHDL/NVC install matrix
  (including from-source builds and the Windows/MSYS2 troubleshooting); `docs/user_guide.md`
  documents every screen and control plus the previously-undocumented board-native run cues
  (the "Board-native (maker)" analysis label, the stats-panel active-low note, and the
  session-log `mode`/`convention` fields), with the session/waveform settings broken into
  real subsections; `docs/architecture.md` absorbs the README's "How It Works" and
  CONTRIBUTING's "Architecture overview" and adds a "How board-native works" internals
  section. The README still carries its existing sections in this release (#242).
- **README rewritten around the new docs, plus a VHDL author's guide (`docs/writing_designs.md`).**
  The README is now a focused newcomer path — install one-liners, a step-by-step demo, a compilable
  entity snippet, a board-native example, and a features/docs index — that links the detailed guides
  rather than inlining everything. `docs/writing_designs.md` is the full design reference: the generic
  and 7-segment contracts, the `COUNTER_BITS` runtime override and clock semantics, the single-file
  embedded-CPU systems, and board-native designs documented properly (vendor-canonical vs
  framework-derived names, polarity, partial interfaces, and the near-miss message for a wrong-board
  file) (#243).
- **Boards whose only LEDs have no single declarable port no longer advertise a board-native
  convention (U32).** An RGB/RGBW LED exposes separate red/green/blue(/white) pins — there is no one
  `std_logic` port to drive — so a framework-derived `rgb_led` vector was fiction. Fifteen such boards
  (e.g. OrangeCrab, upduino_v3, quickfeather, the ECPIX-5 boards, Cora Z7, and a couple whose `led`
  resource is itself multi-pin) now ship no framework convention rather than a port that can't be
  wired. A board still runs board-native on its plain LEDs when it has any alongside the RGB ones;
  only boards with *nothing but* multi-pin LEDs are affected. Framework-derived board-native coverage
  is now **258/278** boards (#241).

### Fixed

- **Board-native mode accepts a one-LED board's natural scalar port (U21).** A design for a
  single-LED board (e.g. a TinyFPGA BX with just `led`) can now declare it as `led : out std_logic`
  — the natural spelling — instead of being forced to write `std_logic_vector(0 downto 0)`. A
  width-1 convention bank matches either form; the generated wrapper associates the scalar per
  element, and the `.gtkw` preselection uses the unranged signal path GHDL/NVC actually emit for a
  scalar. Previously the scalar spelling fell through to the misleading generic-contract "missing
  clk/sw/btn" error (#240).
- **Board-native mode allows extra input ports that carry a default (U21).** An input the board's
  convention doesn't map — e.g. `UART_RX : in std_logic := '1'` — no longer makes a design a
  near-miss when it has a default value, matching the generic contract's long-standing rule and the
  VHDL LRM (an unassociated `in` with a default is legal in both GHDL and NVC). A *default-less*
  unmapped input is still an honest near-miss, since it would otherwise be an unbound port (#240).
- **Clearer board-native near-miss message (U21).** A design that only partially matches a board's
  native interface now names the specific convention it is close to and points at `hdl/blinky.vhd`,
  dropping stale wording that implied the feature was unshipped. A `names[]` convention member
  declared as a vector (rather than a scalar) is now reported as a clean near-miss instead of failing
  later with a cryptic elaboration error (#240).
- **Board-native LED/switch/button polarity is now consistent between a board's vendor and
  framework conventions (U32).** For a board carrying both a cited vendor-canonical convention and
  an auto-derived framework one, the framework block's active-low/active-high polarity now defers to
  the canonical block when they describe the same bank — the physical truth wins, applied by the sync
  tooling so it survives re-syncs. This corrects four boards where they disagreed: DE0-CV (LEDR are
  active-high; the upstream amaranth `invert=True` is an apparent bug), Litefury and Nitefury II
  (LEDs active-low, per the vendor blinky), and Sipeed Tang Nano 9K (LEDs active-low) (#241).
- **OLED / 7-seg-backing pins are no longer miscounted as user LEDs in the constraint-file
  convention parser (U33).** The `classify` step used a bare `led` substring test, so `oled*` and
  `segled*` ports could inflate or hijack a board's LED bank; it now matches `led` only at a token
  boundary (`m2led` and `led0` still count), mirroring the hardening already in the litex/amaranth
  parsers. No shipped canonical block changes (#241).

## [0.13.0] - 2026-07-11

### Added

- **Waveform capture (U10).** The Settings dialog gains a **Waveform** row that
  cycles **off / VCD / FST**. When enabled, the simulation dumps a native
  waveform (GHDL `--vcd`/`--fst`; NVC `--wave` + `--format`) to a timestamped
  `~/.fpga_simulator/waveforms/<design>_<timestamp>.<ext>` — overridable with
  `FPGA_SIM_WAVEFORM_DIR` to keep captures in your own project tree — ready to
  open in GTKWave; successive runs accumulate so you can compare iterations. The file's path is printed when the
  run ends. Capture is a simulator run-command flag (independent of the cocotb
  interface) and is off by default, so the standard run and benchmarks are
  unaffected. Refines the reserved `waveform_enabled` session key into the
  tri-state `waveform` (#186, #187)
- **Auto GTKWave save file (U28).** When waveform capture is on, each run also
  writes a matching `<design>_<timestamp>.gtkw` beside the dump, so
  `gtkwave <file>.gtkw` opens preloaded with the top-level ports —
  clk / sw / btn / led (plus seg on 7-seg boards) — instead of an empty signal
  tree. The save file names its dump, so it loads the trace on its own; a
  crashed/empty run writes none (#189, #192)
- **Waveform env vars + auto-open (U29).** `FPGA_SIM_WAVEFORM=off|vcd|fst`
  enables capture without the Settings dialog (headless / CI). A new Settings
  **Auto-open** toggle — or `FPGA_SIM_WAVEFORM_OPEN=1` — launches a viewer on the
  dump after a run: the command comes from `FPGA_SIM_WAVEFORM_VIEWER`, a template
  with `{dump}` / `{gtkw}` placeholders (default `gtkwave {gtkw}`; `surfer {dump}`
  or a wrapper script work too), falling back to the OS default handler when the
  program isn't on `PATH`. The platform opener moved to a new
  `fpga_sim.platform_open` module, shared with the error dialog's [View Example]
  (#190, #193)
- **Waveform "include memories" depth (U30).** A new Settings **Memories** toggle
  — or `FPGA_SIM_WAVEFORM_MEMORIES=1` (env wins, for headless / CI) — captures
  nested arrays and memories in the waveform, so the embedded-core designs'
  RAM/ROM/registers appear in the trace instead of just the top-level ports. This
  drives NVC's `--dump-arrays`, which NVC needs because it omits nested arrays by
  default in every format (VCD and FST). GHDL's FST/GHW writers already include
  them, so the toggle is a no-op under GHDL — with the caveat that GHDL's VCD
  writer omits memories (with or without a flag), so choose FST to inspect one.
  Off by default, since arrays add significant dump size (#191, #196)

### Fixed

- **Settings gear icon.** The gear trigger in the board-preview header is now
  drawn as a proper cog — a body disc ringed by eight identical trapezoidal
  teeth with a see-through hub — instead of eight radial spokes whose diagonal
  tips rendered as jagged diamonds rather than teeth. The glyph is supersampled
  for clean anti-aliased edges and cached (#194)

## [0.12.0] - 2026-07-08

### Added

- **Component hover tooltips (U3).** Hovering an LED, switch, or button for
  ~400 ms shows a small tooltip with its net name, pin(s), and direction;
  moving the cursor away dismisses it. Works in both the board preview and the
  running simulation, and follows the active theme (#172, #184)
- **In-simulation navigation toolbar (U7).** The running simulation gains three
  buttons at the bottom-left — **[Back to Boards]**, **[Change VHDL]**, and
  **[Reload VHDL]** — so it is no longer a dead end reachable only by ESC.
  **[Reload VHDL]** re-validates and re-analyzes the current file (pick up edits
  you just made in your editor) and restarts the simulation without returning to
  the launcher; **[Change VHDL]** opens the file picker; **[Back to Boards]**
  returns to the selector. The buttons follow the active theme. Pressing
  **F1** or **?** during a simulation now opens the help overlay too (#175)
- **Error messages with contextual hints (U4).** The pre-simulation contract
  check now parses the design's toplevel entity and explains violations in
  terms of the selected board — e.g. *"Port 'led' is a fixed 16 bits wide,
  but DE10-Lite has 10 LEDs. The simulator sets NUM_LEDS=10 for this board —
  declare the port as `led : out std_logic_vector(NUM_LEDS - 1 downto 0)`"*.
  It also catches wrong port directions (which GHDL/NVC accept silently,
  yielding dead LEDs), missing required generics (previously a console-only
  warning followed by a cryptic `sim_wrapper.vhd` error), extra ports or
  generics without defaults, and `seg`-without-`NUM_SEGS` on 7-seg boards.
  GHDL/NVC analysis errors gain appended `Hint:` lines for the common
  failure modes, quoting the board's real resource counts. Error dialogs
  gain a **[View Example]** button (`V` key) that opens the
  board-appropriate bundled example design (#173, #181)
- **Theme system (U6).** Three selectable UI themes: the default **PCB Green**,
  **Dark** (graphite PCB, slate-blue accents), and **High Contrast** (pure
  black surfaces, white text and borders, yellow accents, saturated component
  states). The Settings dialog's Theme row — shipped disabled in 0.11.0 — is
  now enabled and applies the choice live; the persisted theme is restored at
  startup and carried into the simulation subprocess via `FPGA_SIM_THEME`.
  `generate-board-images` gains a `--theme` option. The default theme is
  pixel-identical to 0.11.0 (all 278 board PNGs byte-for-byte) (#174, #178)
- **Theme-aware board-image batch runs.** `generate-board-images --theme` now
  accepts a comma-separated list or `all` — a single theme keeps the flat
  output layout (byte-identical to before), several themes render into
  per-theme subdirectories with stable basenames — and a new `--list-themes`
  flag prints the selectable themes with their Settings-dialog labels (#179)

## [0.11.0] - 2026-07-06

### Added

- **Settings dialog + extended session persistence (U5).** A gear button in
  the board preview header opens a new Settings overlay (`ui/settings_dialog.py`)
  with three rows: the UI theme (cycles `THEME_NAMES`; disabled until U6 adds
  alternates), the remembered sim-speed with a [Reset], and the new
  recent-files list with a [Clear]. The session file now also persists the
  window size (restored at startup), the speed slider (seeded into the sim
  via `FPGA_SIM_SPEED` and written back at sim exit; benchmark/test runs
  never touch it), a `theme` name, reserved `metrics_enabled` /
  `waveform_enabled` toggles (for U19/U10), and `recent[]` — the last 10
  (board, VHDL) pairs for U18's picker section. All session writers now
  merge into the file instead of rewriting it, and the launcher saves on
  every board / simulator / VHDL change and at quit — not only at simulation
  launch — so a browsed-but-unrun file and its directory survive a restart
  (#124, #169)

### Changed

- **`main()`'s 264-line screen loop extracted into a `ScreenController` (D6b).**
  New `src/fpga_sim/controller.py` holds a `SessionState` dataclass (the VHDL /
  work-dir / simulator tuple plus the persisted selector preferences) and a
  `ScreenController` whose public transition methods (`on_board_selected`,
  `on_vhdl_loaded`, `on_simulate`, `on_back`) form an explicit state machine,
  dispatched by a `match` on the D6a `ScreenResult` enum; `__main__.main()` is
  now a thin driver and `_build_generics` moved to `controller.build_generics`.
  No behavior change; 33 new tests (#123, #168)

## [0.10.0] - 2026-07-03

### Added

- **README badge row + CI matrix note.** The README now shows a project-info
  badge trio (license, latest release, Python 3.10+) alongside the existing
  CI badge and a new tooling trio (ruff, mypy, uv), plus a one-line "tested
  on" summary of the CI matrix (Ubuntu + Windows × Python 3.10/3.12/3.13,
  plus GHDL/NVC simulator jobs) in place of per-OS badges, which GitHub
  Actions cannot express per-job (#159)
- **Embedded-core generated designs now carry their firmware source.** Above
  the ROM constant, every generated `hdl/*.vhd` embeds its firmware assembly
  listing verbatim as a `--` comment block, so the single file shows both the
  machine code and the program that produced it. `scripts/gen_embedded_core.py`
  also gains a `--prescaler-bits` generation-time override for the
  `PRESCALER_BITS` generic default (e.g. for a temporary faster-stepping
  capture build), and all 8 committed designs are regenerated (#161)
- **New capture scenarios + assets: `cpu_walk` and `dice`.** `sim/capture_frames.py`'s
  interactive-storyboard machinery is generalized into a `_Storyboard` base
  class shared by the snake, embedded-CPU walking-counter, and dice-roller
  demos. `scripts/capture_demo.py` gains `--prescaler-bits`, `--vhdl-label`,
  and `--png` (save a still frame instead of assembling a GIF). New assets:
  an interactive `mx65_walking_counter_demo.gif` for the README, an
  `mx65_dice_7seg.gif`, and an `mx65_hello_7seg.png`, all embedded in the
  guide/README (#162)
- **Annotated waveform for guide §15.** New `scripts/capture_waveform.py`
  simulates `mx65_hello_7seg` against an inline testbench, hand-parses the
  resulting VCD, and renders `docs/assets/mx65_hello_waveform.png` in a
  GTKWave-like visual idiom (black background, green traces, hexagonal bus
  lanes) with five annotations — POR release, reset-vector fetch, first
  opcode, the LED-on store, and the terminal spin loop — all located
  programmatically from the trace. Also (re)writes
  `docs/assets/mx65_hello_7seg.gtkw` so `gtkwave <vcd> <that file>` opens the
  identical view in real GTKWave (#163)

### Changed

- **README doc references are now links.** The `docs/embedded_core_system_guide.md`
  and `docs/embedded_core_improvement_plan.md` mentions in the README's
  embedded-CPU section are clickable relative links instead of plain
  backticked text (#159)
- **Embedded-core guide navigation.** `docs/embedded_core_system_guide.md` gains
  a table of contents, and all 61 `§N` cross-references and ~37 repo-file
  mentions are now clickable anchor/relative links; the misaligned §3 ASCII
  diagram is corrected (#160)
- **Fixed temporally-aliased embedded-CPU GIFs and the `demo.gif` loop seam.**
  The walking-counter GIFs were captured against a temporary
  `--prescaler-bits 14` variant build instead of the committed design's
  default, so the visible step rate is now readable (~6.4 steps/s) instead of
  aliased (~4 steps/frame). `demo.gif`'s storyboard now restores both `SW0`
  and `BTN0` at the end, so its loop seam is continuous in rate and
  direction. The three digit-count GIFs are renamed
  `cpu_walk_{2,4,6}digit.gif` → `mx65_walking_counter_{2,4,6}digit.gif` (#162)

## [0.9.0] - 2026-07-02

### Added

- **Embedded CPU core systems (6502 + Z80).** A design can now be a single
  self-contained `.vhd` that embeds a soft CPU core plus ROM, RAM, and a
  memory-mapped (or Z80 port-mapped) IO subsystem, with checked-in **firmware**
  producing the behavior instead of hand-written RTL. Six committed designs
  prove the skeleton is core-agnostic: the same walking counter runs on a 6502
  (vendored **mx65**) and a Z80 (vendored **T80**) across an interrupt ×
  IO-transport matrix — polled, fixed-vector IRQ, and Z80 IM 2 vectored;
  memory-mapped and Z80 port IO. The firmware reads the board's resource
  counts from IO config registers, so one design fits any board (proven across
  2/4/6-digit 7-seg boards). Each design is generated by
  `scripts/gen_embedded_core.py` from a vendored core + a `systems/*.toml`
  spec + an assembled firmware `.bin`; firmware sources are checked in as
  first-class docs (6502 `.s` for ca65/ld65, Z80 `.asm` for z88dk z80asm)
  alongside their binaries. All six pass a shared cocotb behavioral suite
  under both GHDL and NVC, and `docs/embedded_core_system_guide.md` documents
  the full architecture (#135)
- **Newcomer on-ramp: `hdl/mx65_hello_7seg.vhd`.** The smallest possible
  embedded-core design — a ~20-line 6502 firmware that lights LED 0, shows
  "0" on digit 0, and holds — committed as a runnable copy-and-start template
  (same memory map and generics as the walking counter). The README gains an
  "Embedded CPU systems" section and the guide a five-step "your first
  change" quickstart, so the feature is discoverable from the front door
  (#150)
- **Custom peripherals: `peripherals` spec axis + `hdl/mx65_dice_7seg.vhd`.**
  The generator's IO template gains four anchor points where a spec-selected
  peripheral splices in its own signals, read-mux arm, and clocked logic
  (empty by default — all pre-existing designs regenerate byte-identical).
  The worked example is a free-running 8-bit LFSR at `$E008`: each `btn(0)`
  press rolls a die, showing 1–6 on digit 0 and in binary on the LEDs. It is
  also the first design with deliberately different ROM (2 KB) and RAM (1 KB)
  sizes, proving the decoupled memory map at runtime (#152)
- **`hdl/stopwatch_7seg.vhd` — hand-written interactive stopwatch.** `btn(0)`
  starts/stops, `btn(1)` resets (without changing the running state), each
  active switch doubles the count rate, and `led(0)` shows the running state.
  Written in `counter_7seg.vhd`'s commented teaching style as the RTL half of
  the repo's "same behavior, hardware vs software" teaching pair with the
  embedded-core designs (#154)
- **Embedded-core maintainer tooling.** New `scripts/regen_embedded_cores.py`
  checks every committed generated design against its spec
  (`OK`/`DIFFERS`/`MISSING`, nonzero exit on drift), regenerates drifted files
  with `--write`, and reassembles every firmware with its pinned dev-time
  toolchain via `--assemble` — never writing a `.bin`; that stays a deliberate
  manual act. Reassembly-guard tests prove each checked-in binary reproduces
  from its source with both toolchains. `systems/*.toml` specs are now
  validated eagerly — memory-map rules (power-of-two sizes, base alignment,
  overlap, in-range placement), unknown-key rejection at every level, and a
  ROM-fit check — so a wrong spec fails at the generator with a clear message
  naming the offending region or key instead of a confusing late VHDL error.
  `gen_embedded_core.py`'s `--cpu`/`--rom`/`--out` are now inferred from
  `--system` (explicit flags still override) (#142, #144)
- Board-sync scripts now validate every generated board against
  `boards/schema/board.schema.json` before writing. Validation happens in the
  shared `write_outputs()` chokepoint, so all sources (and any future one) are
  covered; an invalid board aborts the sync with no partial output, and
  `--dry-run` doubles as a schema check. Catches parser regressions at
  generation time instead of later in the test suite.

### Changed

- Tightened the board JSON schema: the board object and the `clock_object`,
  `component`, `seven_seg`, and `source` definitions now set
  `additionalProperties: false`, so a misspelled field (e.g. `default_clk_hz`
  for `default_clock_hz`) is rejected instead of silently ignored. All 278
  boards already conform. The explicitly future-facing sections — `peripherals`
  (intentionally free-form) and the `port_conventions` subtree (shape still
  settling) — remain open.

### Fixed

- **Switch-driven speed-up in four bundled demo designs quadrupled the rate
  instead of doubling it.** `walking_counter_7seg.vhd`, `blinky_walking.vhd`,
  `blinky_counter.vhd`, and `snake_7seg.vhd` all computed the switch-driven
  step-index as `base - n * 2` (`n` = active-switch count), which halves the
  step period *twice* per switch — every header/inline comment in these files
  says "doubles" (#133). Changed to `base - n` so the code matches its own
  docs. `sim/capture_frames.py`, which mirrors `snake_7seg`'s timing in Python
  to pace the README demo-GIF capture, was updated to match or it would have
  desynced from the corrected hardware.

## [0.8.0] - 2026-06-26

### Added

- **Analysis spinner.** Loading a VHDL file (and re-checking it before a run)
  used to freeze the window for several seconds while the simulator analyzed
  and elaborated the design, with no feedback. There is now a centered
  "Analyzing &lt;file&gt;…" overlay with a rotating spinner that animates while
  the work runs on a background thread, so the app stays responsive and clearly
  shows it is busy. The overlay disappears when analysis succeeds or fails.

### Changed

- **Simulator backends now share one base class (internal refactor).**
  `_SimBackend` became an abstract base class instead of a `Protocol`: the four
  discovery helpers (`find` / `available` / `lib_dir` / `sim_bin_lib`) are
  defined once on the ABC as classmethods keyed on each backend's `NAME`, so
  `_GHDLBackend` / `_NVCBackend` now override only `NAME` plus the four
  per-simulator command builders. Removes ~19 lines of duplicated code in
  `sim_bridge.py` and clears the way for a future third backend. No behavior
  change.
- **Launcher screens return typed results instead of strings (internal
  refactor).** `FPGABoard.run()` and `ErrorDialog.run()` previously returned
  bare strings (`"simulate"` / `"load_vhdl"` / `"back"` / `"quit"`, and
  `"retry"` / `"back"`); they now return `ScreenResult` / `DialogResult` enums
  (new `fpga_sim/ui/results.py`), so the main loop dispatches on members that
  mypy type-checks rather than typo-prone literals. Groundwork for the
  forthcoming `ScreenController` extraction. No behavior change.

### Fixed

- **NVC no longer aborts on large designs with a cryptic out-of-memory error.**
  NVC's global heap defaults to 16 MB, which deep / many-instance designs
  exhausted mid-elaboration (`** Fatal: (init): out of memory … increase with
  the -H option`). The NVC backend now passes `-H 512m` on elaboration and run,
  raising the cap — it is a ceiling the heap grows into on demand, not an
  up-front reservation, so small designs are unaffected (measured peak RSS for
  a trivial design is within ~1 MB of the default). In testing this lifted the
  practical ceiling several-fold (a synthetic 64-hart multi-core that previously
  failed now elaborates cleanly); designs with hundreds of instances may
  additionally need NVC's `-M` design-unit-heap option.

## [0.7.0] - 2026-06-25

### Added

- **Board selector polish:** an always-visible scrollbar when the board list
  overflows the window, and each row now shows its definition **source**
  (litex-boards / amaranth-boards / digilent-xdc / custom) as a dim right-aligned
  tag — previously the source appeared only on names that collide across sources.
- **Visual README** — the project page now opens with two animated GIFs: an
  *interactive* live simulation (`hdl/snake_7seg.vhd` on the DE10-Lite — a faux
  cursor taps BTN0 / BTN1 / SW0 with cause→effect captions over a persistent
  "live VHDL simulation · board · running file" strip, driving the real DUT) and
  the board selector filtering its 278 boards down by component and vendor with a
  cursor clicking each chip. Both are reproducible
  via new maintainer tools `scripts/capture_demo.py` and
  `scripts/capture_selector.py` (shared helpers in `scripts/capture_common.py`;
  cocotb capture testbench in `sim/capture_frames.py`); Pillow was added to the
  `dev` group.
- **6 new boards** synced from upstream (272 → 278 loadable): amaranth Cora
  Z7-07S / Cora Z7-10; litex Adiuvo Forgix, Altera Agilex5e 065B Premium DevKit,
  Brisbanesilicon BRS-100, Trenz TEL0025. Each headless-spot-checked on NVC.
- **Parser unit tests** for litex and digilent (`tests/test_litex_parser.py`,
  `tests/test_digilent_parser.py`), closing the coverage gap on the two
  previously-untested parsers (~70% of the board catalog).

### Changed

- **Decoupled the amaranth-boards sync from the runtime board loader.** The
  mock-exec parser that turns upstream amaranth `.py` board files into
  `BoardDef`s moved out of `src/fpga_sim/board_loader.py` into a dedicated
  `scripts/amaranth_parser.py`, and `scripts/sync_boards.py` was renamed to
  `scripts/sync_amaranth_boards.py` (parallel to `sync_litex_boards.py` /
  `sync_digilent_xdc.py`). `board_loader.py` is now a pure JSON runtime loader
  (804 → 241 lines); generated board JSON is byte-for-byte unchanged.
- **Modularized the litex and digilent sync scripts** (parallel to the amaranth
  split): the parsers moved into dedicated `scripts/litex_parser.py` /
  `scripts/digilent_parser.py`; the `sync_*.py` scripts are now thin
  download/output/CLI wrappers. Generated board JSON is byte-for-byte unchanged.
- **Extracted shared sync scaffolding** into `scripts/sync_common.py` (download,
  ref resolution, filesystem-safe naming, JSON/metadata output) used by all three
  `sync_*.py` scripts; also gives the digilent script the filename-collision dedup
  it previously lacked. Output byte-for-byte unchanged.

### Removed

- Dead pre-JSON discovery fallbacks in `board_loader.py`
  (`_discover_boards_legacy` and the amaranth-boards submodule path),
  unreachable since board definitions moved to JSON.

## [0.6.0] - 2026-06-22

### Added

- **In-app help overlay** — a Help / About modal reachable from every
  launcher screen via **F1**, **?**, or a **(?)** button (board-selector
  header and preview corner). Shows a 4-step workflow, a keyboard-shortcut
  legend (rendered from a single source of truth), and the VHDL
  design-contract summary; dismiss with Esc / F1 / ?, the Close button, or a
  click outside. Resizing the window while it is open re-scales the screen
  beneath on close (U1)
- **Keyboard navigation** in the board selector and VHDL file picker —
  **↑ / ↓** and **Page Up / Page Down** move the highlight and **Enter**
  selects; on the selector, **Enter** also drives the sort dropdown when it is
  open (U13)
- **Board selector filtering & sort** — filter chips (Has LEDs / Switches /
  Buttons / 7-seg, plus per-vendor chips with an "Other" group) that compose
  with the text filter, a sort control with 7 modes (Name, Vendor, LEDs,
  Switches, Buttons, 7-seg, Total), an active-filter count ("N of 272 boards"),
  and session persistence of all filter/sort state (U0)
- **R key** resets all switches off and releases any held buttons; works
  in both the board preview screen and during live simulation. Inputs
  only — the design's internal state (counters, registers) is unaffected
  (U11)
- **Five new boards** in `boards/custom/`: **DE2-115** (Intel Cyclone IV E
  — 27 LEDs, 18 switches, 4 buttons, 8-digit 7-seg), **VEEK-MT2** (the
  DE2-115's EP4CE115 base on the VEEK-MT2 carrier), **DE23-Lite** (Intel
  Agilex 3 — 10 LEDs, 10 switches, 4 buttons, 6-digit 7-seg),
  **DE25-Standard** (Intel Agilex 5, same layout as DE23-Lite), and
  **VEEK-MT-SoCKit** (Intel Cyclone V SX — 4 LEDs, 4 switches, 4 buttons)
- Python 3.13 added to the CI test matrix

### Changed

- Unified the two VHDL wrapper templates (`sim_wrapper_template.vhd` and
  the deleted `sim_wrapper_7seg_template.vhd`) into a single template with
  conditional placeholders that `_generate_wrapper()` splices in when the
  board and design both use 7-seg. Removes ~73 lines and unblocks U21
  (board-native VHDL) and U22 (7-seg physical mux) (D1)
- **Board summary format** in the board selector is now compact:
  `"4 LEDs · 2 BTN · 4 SW · 4-digit 7-seg"` (middle-dot separator,
  abbreviated `BTN`/`SW`) instead of `"4 LEDs, 2 buttons, 4 switches,
  4-digit 7-seg"` (U12)
- Internal: simulator backend identifiers are now typed with a
  `Simulator = Literal["ghdl", "nvc"]` alias (threaded through `sim_bridge`,
  `session_config`, `__main__`, and `FPGABoard`) so mypy rejects typos like
  `_backend("gdhl")`; no behavior change (D9)
- Internal: extracted a shared `ui/widgets/button.py` (`ButtonStyle` +
  `draw_button`) and routed all four open-coded button sites through it — the
  board-preview footer, the error dialog, the simulation-speed panel's clock
  steppers, and the sim Stop/Pause overlay. Removes the per-site styling drift
  (each had hand-rolled hover/border/radius); the clock steppers now show hover
  feedback. No other visual change (D4)
- Tooling: added [rumdl](https://github.com/rvben/rumdl) as a Markdown linter —
  wired into the pre-commit hooks and the CI lint job, configured under
  `[tool.rumdl]` (MD013 line-length and MD036 emphasis-as-heading disabled), and
  applied a one-time `rumdl fmt` pass across the repo's Markdown
- Tooling: ruff and ruff-format now run as local pre-commit hooks (via
  `uv run`), like mypy and rumdl, so they use the `uv.lock`-pinned ruff rather
  than a separate `astral-sh/ruff-pre-commit` `rev:`. Removes silent drift
  between the pre-commit ruff and the version CI / `uv run` use
- Internal: documented `board_loader.py`'s exec-in-mock-namespace strategy
  and added docstrings to the eight mock classes and the resource helpers
  (D11)
- Tooling: the test suite now runs in randomized order via `pytest-randomly`
  to surface inter-test state leakage

### Fixed

- **litex-boards sync** selected the wrong platform class for non-Xilinx
  boards. The corrected re-sync updates ~148 board definitions and adds 16
  more litex boards (Colorlight, OrangeCrab, ButterStick, Logicbone,
  Machdyne, QMTech, etc.). Combined with the five new custom boards above,
  the catalog is now 275 definitions (272 loadable) across four sources
  (#67)

## [0.5.0] - 2026-05-25

### Added

- **litex-boards sync** — `scripts/sync_litex_boards.py` downloads and converts
  board definitions from [litex-hub/litex-boards](https://github.com/litex-hub/litex-boards),
  adding ~147 boards across Xilinx, Intel, Lattice, Gowin, Efinix, and CologneChip
- **Digilent XDC sync** — `scripts/sync_digilent_xdc.py` parses Digilent master XDC
  constraint files from [Digilent/digilent-xdc](https://github.com/Digilent/digilent-xdc),
  adding ~26 boards (Basys 3, Nexys A7, Arty, Zybo, etc.) with auto-generated
  `port_conventions` for future board-native VHDL mode (U21)
- 7-segment display detection in both new sources (multiplexed and non-multiplexed)
- Board count increased from ~80 to ~250 across four sources

### Changed

- Board selector now shows boards from all four sources: `amaranth-boards`,
  `litex-boards`, `digilent-xdc`, and `custom`
- Test `test_arty_a7_found` updated to allow multi-source board matches

## [0.4.0] - 2026-05-25

### Changed

- Migrated board definitions from amaranth-boards git submodule to self-contained
  JSON files in `boards/` — no submodule initialization required
- Board loader discovers JSON sources automatically; each subdirectory under
  `boards/` is an independent source (`amaranth-boards/`, `custom/`, etc.)
- Multiple sources may define the same board; all definitions are shown in the
  board selector with source annotations when names collide
- Session persistence now tracks board source for disambiguation

### Added

- `boards/schema/board.schema.json` — JSON Schema for board definition validation
- `boards/custom/de10_standard.json` — Terasic DE10-Standard (Cyclone V SX SoC,
  10 LEDs, 4 buttons, 10 switches, 6-digit 7-seg); includes `peripherals` and
  `port_conventions` sections for future use
- `scripts/sync_boards.py` — downloads and converts board definitions from the
  amaranth-boards GitHub repository without requiring a local clone
- Support for richer clock format in JSON (objects with name, Hz, pin, is_default)
- `jsonschema` added to dev dependencies for CI validation

### Removed

- `amaranth-boards/` git submodule (replaced by `boards/amaranth-boards/` JSON files)

### Security

- Hardened CI workflow: pinned actions to commit SHAs, added `permissions` blocks,
  restricted token scopes

## [0.3.1] - 2026-05-19

### Changed

- Unified `_NVCBackend.run_cmd` signature with `_GHDLBackend` (`generics` parameter
  added, ignored at runtime since NVC bakes them in at elaboration); introduced
  `_SimBackend` Protocol; removed the two remaining `# type: ignore[call-arg]`
  suppressions from `launch_simulation()` (closes #30)

## [0.3.0] - 2026-05-19

### Added

- 7-segment display support: 8 boards (DE0, DE0-CV, DE1-SoC, DE10-Lite, Nandland-Go,
  Nexys4-DDR, RZ-EasyFPGA-A2/2, StepMXO2); Mercury excluded (display behind extension
  resource list, not in `resources`)
- `SevenSegDef` dataclass: `num_digits`, `has_dp`, `is_multiplexed`, `inverted`,
  `select_inverted`; round-trips through `BoardDef` JSON
- `SevenSeg` pygame widget: amber polygon segments, scales from 24 px to any size
- `FPGABoard` horizontal split layout: FPGA chip (55 %) + 7-seg panel (45 %) in top section
- `FPGABoard.set_seg(index, bits8)` method for cocotb readback
- `sim_wrapper_7seg_template.vhd`: 7-seg wrapper with `NUM_SEGS` generic and `seg` port
- `counter_7seg.vhd`: hex digit counter, all 8 boards
- `snake_7seg.vhd`: single segment crawls figure-8 across all digits; bouncing LED + decimal point
- `walking_counter_7seg.vhd`: bouncing LED with decimal BCD counter on 7-seg digits
- SVG board previews include 7-seg digit outlines (all-OFF ghost segments)
- VHDL contract checker enforces `seg` port presence/absence based on board type

### Changed

- Upgraded ruff 0.15.12 → 0.15.13, mypy 1.20.2 → 2.1.0, pre-commit 4.5.1 → 4.6.0
- amaranth-boards submodule advanced to include Tang Mega 138k Pro Dock

## [0.2.0] - 2026-04-03

### Added

- Windows support: NVC simulator works via MSYS2; auto-detect Python DLL with `cocotb-config` (#52)
- CI: Windows test matrix (pure-Python + GHDL) (#54)
- CI: Linux GHDL and NVC full-suite jobs (#55)

### Changed

- Migrated to `src/` layout (`fpga_sim` package under `src/`) (#56)
- Improved README accuracy: board count, NVC install, VPI/VHPI details (#49)
- Corrected docs: NVC is available on Windows via MSYS2 (#53)

### Fixed

- Bumped Pygments 2.19.2 → 2.20.0 to resolve CVE-2026-4539 (#51)

## [0.1.0] - 2026-03-30

- Initial release

[Unreleased]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/Machai-Kydoimos/fpga-board-sim/releases/tag/v0.1.0
